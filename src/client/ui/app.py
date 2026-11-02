"""PokeCompanion NetBridge - Desktop Companion UI (PySide6).

Live Gen 3 GBA sidecar multiplayer companion:
- Tab 1: Trainer Profile, Gym Badges, Live 6-Pokémon Party, and Online Relay Lobby.
- Tab 2: In-Game Bag & Shared Cloud Bank with smooth scrolling, search filtering,
  and 1-click quick deposit/withdraw buttons.
- High-contrast, eye-friendly layout compatible with both dark and light modes.
"""

import asyncio
import datetime
import logging
import sys
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QGroupBox,
    QMessageBox,
    QInputDialog,
    QTabWidget,
    QLineEdit,
    QComboBox,
    QTextEdit,
    QFrame,
)

from src.memory.gdb_client import GDBClient
from src.client.state import GameStateManager, BADGE_NAMES_KANTO
from src.client.net import NetworkEngine
from src.core.items import get_item_name, get_item_pocket


class BridgeSignals(QObject):
    state_updated = Signal()
    players_updated = Signal(object)
    challenge_received = Signal(str, str, object)
    battle_ready = Signal(str, bytes)
    ledger_updated = Signal(object)
    connection_status = Signal(str, str)  # component, status
    activity_logged = Signal(str, str)    # message, level ('info', 'success', 'warning', 'error')
    notification = Signal(str, str)       # title, message (for modals)


class MainWindow(QMainWindow):
    def __init__(self, gdb_host: str = "127.0.0.1", gdb_port: int = 2345, server_url: str = "ws://127.0.0.1:8000"):
        super().__init__()
        self.setWindowTitle("PokeCompanion NetBridge - Gen 3 Sidecar (FireRed / Emerald)")
        self.resize(1080, 780)
        self.setMinimumSize(960, 660)

        # Core Engines
        self.signals = BridgeSignals()
        self.gdb = GDBClient(host=gdb_host, port=gdb_port)
        self.state_mgr = GameStateManager(self.gdb)
        self.net = NetworkEngine(self.state_mgr, server_url=server_url)

        # State Caches for intelligent table diffing (prevents scroll resetting)
        self._last_ledger: Dict[int, int] = {}
        self._last_rendered_bag_cache: Optional[Tuple] = None
        self._last_rendered_cloud_cache: Optional[Tuple] = None
        self._last_rendered_lobby_cache: Optional[Tuple] = None

        # Setup Asyncio Event Loop in Background Thread
        self.loop = asyncio.new_event_loop()
        self.bg_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.bg_thread.start()

        # Connect signals
        self.signals.state_updated.connect(self._render_state)
        self.signals.players_updated.connect(self._render_lobby)
        self.signals.challenge_received.connect(self._handle_incoming_challenge)
        self.signals.battle_ready.connect(self._handle_battle_ready)
        self.signals.ledger_updated.connect(self._render_ledger)
        self.signals.connection_status.connect(self._update_status)
        self.signals.activity_logged.connect(self._append_activity_log)
        self.signals.notification.connect(self._show_notification)

        # Wire NetEngine callbacks
        self.net.on_player_list_changed = lambda pl: self.signals.players_updated.emit(pl)
        self.net.on_challenge_received = lambda cid, cname, p: self.signals.challenge_received.emit(cid, cname, p)
        self.net.on_battle_ready = lambda cid, pbytes: self.signals.battle_ready.emit(cid, pbytes)
        self.net.on_ledger_updated = lambda ldg: self.signals.ledger_updated.emit(ldg)

        self.net.on_deposit_success = lambda iid, q: (
            self.signals.activity_logged.emit(f"📥 Deposited {get_item_name(iid)} x{q} into Cloud Bank.", "success"),
            self.signals.state_updated.emit(),
        )
        self.net.on_withdraw_success = lambda iid, q: (
            self.signals.activity_logged.emit(
                f"📤 Withdrew {get_item_name(iid)} x{q} into In-Game Bag! (Close & re-open bag in mGBA)",
                "success",
            ),
            self.signals.state_updated.emit(),
        )
        self.net.on_item_gift_received = lambda s_id, s_name, iid, q: (
            self.signals.activity_logged.emit(
                f"🎁 Received gift: {get_item_name(iid)} x{q} from Trainer '{s_name}'!",
                "success",
            ),
            self.signals.state_updated.emit(),
        )
        self.net.on_error = lambda err: self.signals.activity_logged.emit(f"⚠️ {err}", "error")

        # Build UI
        self._setup_ui()

        # Polling Guard & Timer for RAM Inspection
        self._is_polling = False
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._schedule_poll)
        self.poll_timer.start(800)

        # Connect to mGBA and Relay Server
        asyncio.run_coroutine_threadsafe(self._init_connections(), self.loop)

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _init_connections(self):
        try:
            await self.state_mgr.update_all()
            self.signals.connection_status.emit("GDB", f"Connected ({self.state_mgr.game_code or 'GBA'})")
            self.signals.state_updated.emit()
            self.signals.activity_logged.emit(f"Connected to mGBA RAM ({self.state_mgr.game_code}).", "info")
        except Exception:
            self.signals.connection_status.emit("GDB", "Disconnected (Start GDB in mGBA)")

        try:
            await self.net.connect()
            self.signals.connection_status.emit("RELAY", "Connected to Server")
            self.signals.activity_logged.emit("Connected to Central Relay Server.", "info")
        except Exception as e:
            self.signals.connection_status.emit("RELAY", f"Offline ({e})")

    def _schedule_poll(self):
        if not self._is_polling:
            self._is_polling = True
            asyncio.run_coroutine_threadsafe(self._do_poll(), self.loop)

    async def _do_poll(self):
        try:
            await self.state_mgr.update_all()
            self.signals.connection_status.emit("GDB", f"Connected ({self.state_mgr.game_code or 'GBA'})")
            self.signals.state_updated.emit()
            if self.net.is_running:
                await self.net.sync_state()
        except Exception:
            self.signals.connection_status.emit("GDB", "Disconnected (Start GDB in mGBA)")
        finally:
            self._is_polling = False

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(6)

        # Top Global Status Bar
        top_bar = QHBoxLayout()
        self.lbl_gdb_status = QLabel("🎮 mGBA GDB: Connecting...")
        self.lbl_gdb_status.setFont(QFont("Segoe UI", 10, QFont.Bold))

        self.lbl_relay_status = QLabel("🌐 Relay Server: Connecting...")
        self.lbl_relay_status.setFont(QFont("Segoe UI", 10, QFont.Bold))

        top_bar.addWidget(self.lbl_gdb_status)
        top_bar.addSpacing(20)
        top_bar.addWidget(self.lbl_relay_status)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # Tabs Layout
        self.tabs = QTabWidget()
        font_tab = QFont("Segoe UI", 10, QFont.Bold)
        self.tabs.setFont(font_tab)
        main_layout.addWidget(self.tabs, stretch=1)

        # Tab 1: 👤 Player & Pokémon Party
        self.tab_player = QWidget()
        self._setup_player_tab()
        self.tabs.addTab(self.tab_player, "👤 Trainer Profile & Pokémon Team")

        # Tab 2: 🎒 Bag & Cloud Bank
        self.tab_bag = QWidget()
        self._setup_bag_tab()
        self.tabs.addTab(self.tab_bag, "🎒 Bag Management & Cloud Bank")

    def _setup_player_tab(self):
        layout = QVBoxLayout(self.tab_player)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Trainer & Gym Badges Overview Card
        trainer_box = QGroupBox("Trainer Information & Kanto Gym Badges")
        trainer_box_layout = QVBoxLayout(trainer_box)
        trainer_box_layout.setSpacing(6)

        # Line 1: Trainer Name, TID, Game Code
        info_row = QHBoxLayout()
        self.lbl_trainer_name = QLabel("Trainer Name: --")
        self.lbl_trainer_name.setFont(QFont("Segoe UI", 11, QFont.Bold))

        self.lbl_trainer_id = QLabel("Trainer ID: --")
        self.lbl_trainer_id.setFont(QFont("Segoe UI", 11, QFont.Bold))

        self.lbl_game_code = QLabel("Game Code: --")
        self.lbl_game_code.setFont(QFont("Segoe UI", 11, QFont.Bold))

        info_row.addWidget(self.lbl_trainer_name)
        info_row.addSpacing(15)
        info_row.addWidget(self.lbl_trainer_id)
        info_row.addSpacing(15)
        info_row.addWidget(self.lbl_game_code)
        info_row.addStretch()
        trainer_box_layout.addLayout(info_row)

        # Line 2: Badges Row
        badges_row = QHBoxLayout()
        badges_lbl = QLabel("Gym Badges (0/8):")
        badges_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        badges_row.addWidget(badges_lbl)
        self.lbl_badge_summary = badges_lbl

        self.badge_labels = []
        for name in BADGE_NAMES_KANTO:
            b_lbl = QLabel(f"[ {name} ]")
            b_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            b_lbl.setStyleSheet("color: #718096; padding: 2px 4px;")
            badges_row.addWidget(b_lbl)
            self.badge_labels.append(b_lbl)

        badges_row.addStretch()
        trainer_box_layout.addLayout(badges_row)
        layout.addWidget(trainer_box)

        # Middle Split: Party (Left) and Online Lobby (Right)
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(8)

        # Left: Live Party 6-Slot Grid
        party_box = QGroupBox("Live Player Party (Decrypted RAM: 0x02024284)")
        party_layout = QVBoxLayout(party_box)
        self.party_slot_widgets = []

        grid = QGridLayout()
        grid.setSpacing(6)
        for i in range(6):
            slot_card = QGroupBox(f"Party Slot {i+1}")
            slot_vbox = QVBoxLayout(slot_card)
            slot_vbox.setContentsMargins(8, 8, 8, 8)
            slot_vbox.setSpacing(4)

            lbl_name = QLabel("Empty Slot")
            lbl_name.setFont(QFont("Segoe UI", 10, QFont.Bold))

            lbl_level = QLabel("Level: --")
            lbl_level.setFont(QFont("Segoe UI", 9))

            slot_vbox.addWidget(lbl_name)
            slot_vbox.addWidget(lbl_level)

            self.party_slot_widgets.append({
                "name": lbl_name,
                "level": lbl_level,
            })
            grid.addWidget(slot_card, i // 2, i % 2)

        party_layout.addLayout(grid)
        mid_layout.addWidget(party_box, stretch=3)

        # Right: Online Lobby & Battle Broker
        lobby_box = QGroupBox("Relay Server Lobby & Battles")
        lobby_layout = QVBoxLayout(lobby_box)
        lobby_layout.setContentsMargins(6, 8, 6, 6)

        self.table_players = QTableWidget(0, 4)
        self.table_players.setHorizontalHeaderLabels(["Trainer", "Game", "Badges", "Actions"])
        self.table_players.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_players.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_players.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_players.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_players.verticalHeader().setVisible(False)
        self.table_players.setAlternatingRowColors(True)
        lobby_layout.addWidget(self.table_players)

        mid_layout.addWidget(lobby_box, stretch=2)
        layout.addLayout(mid_layout, stretch=1)

    def _setup_bag_tab(self):
        layout = QVBoxLayout(self.tab_bag)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Filter & Search Controls
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        lbl_search = QLabel("🔍 Filter Items:")
        lbl_search.setFont(QFont("Segoe UI", 9, QFont.Bold))
        filter_bar.addWidget(lbl_search)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Search by item name...")
        self.input_search.setClearButtonEnabled(True)
        self.input_search.textChanged.connect(self._on_bag_filter_changed)
        filter_bar.addWidget(self.input_search, stretch=2)

        lbl_pocket = QLabel("Pocket:")
        lbl_pocket.setFont(QFont("Segoe UI", 9, QFont.Bold))
        filter_bar.addWidget(lbl_pocket)

        self.combo_pocket = QComboBox()
        self.combo_pocket.addItems(["All Pockets", "Items Pocket", "Poké Balls Pocket"])
        self.combo_pocket.currentIndexChanged.connect(self._on_bag_filter_changed)
        filter_bar.addWidget(self.combo_pocket, stretch=1)

        filter_bar.addSpacing(10)
        lbl_sync_tip = QLabel("💡 Changes write directly into mGBA RAM. Close & re-open your Bag in-game to refresh.")
        lbl_sync_tip.setStyleSheet("color: #4a5568; font-size: 11px; font-style: italic;")
        filter_bar.addWidget(lbl_sync_tip, stretch=2)
        layout.addLayout(filter_bar)

        # Notification Toast
        self.lbl_bag_toast = QLabel("")
        self.lbl_bag_toast.setStyleSheet(
            "background-color: #d1fae5; color: #065f46; border: 1px solid #6ee7b7; border-radius: 4px; padding: 4px 8px; font-weight: bold; font-size: 11px;"
        )
        self.lbl_bag_toast.setVisible(False)
        layout.addWidget(self.lbl_bag_toast)

        # Inventory Tables (Side-by-Side)
        tables_layout = QHBoxLayout()
        tables_layout.setSpacing(8)

        # Left: Local In-Game Bag
        local_box = QGroupBox("🎒 My In-Game Bag (SaveBlock1 RAM)")
        local_vbox = QVBoxLayout(local_box)
        local_vbox.setContentsMargins(6, 8, 6, 6)

        self.table_local_bag = QTableWidget(0, 4)
        self.table_local_bag.setHorizontalHeaderLabels(["Item Name", "Pocket", "Qty", "Quick Deposit"])
        self.table_local_bag.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_local_bag.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_local_bag.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_local_bag.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_local_bag.verticalHeader().setVisible(False)
        self.table_local_bag.setAlternatingRowColors(True)
        self.table_local_bag.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        local_vbox.addWidget(self.table_local_bag)
        tables_layout.addWidget(local_box, stretch=1)

        # Right: Shared Cloud Bank
        cloud_box = QGroupBox("☁️ Shared Cloud Bank (Relay Server Escrow)")
        cloud_vbox = QVBoxLayout(cloud_box)
        cloud_vbox.setContentsMargins(6, 8, 6, 6)

        self.table_ledger = QTableWidget(0, 4)
        self.table_ledger.setHorizontalHeaderLabels(["Item Name", "Pocket", "Available", "Quick Withdraw"])
        self.table_ledger.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_ledger.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_ledger.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_ledger.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_ledger.verticalHeader().setVisible(False)
        self.table_ledger.setAlternatingRowColors(True)
        self.table_ledger.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        cloud_vbox.addWidget(self.table_ledger)
        tables_layout.addWidget(cloud_box, stretch=1)

        layout.addLayout(tables_layout, stretch=3)

        # Bottom: Activity Log
        log_box = QGroupBox("📜 Live Inventory Activity Log")
        log_vbox = QVBoxLayout(log_box)
        log_vbox.setContentsMargins(6, 6, 6, 4)
        log_vbox.setSpacing(2)

        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setFixedHeight(95)
        self.activity_log.setFont(QFont("Consolas", 9))
        log_vbox.addWidget(self.activity_log)
        layout.addWidget(log_box, stretch=1)

    def _on_bag_filter_changed(self):
        """Forces an update of both bag tables when search or pocket filter changes."""
        self._last_rendered_bag_cache = None
        self._last_rendered_cloud_cache = None
        self._render_local_bag()
        self._render_cloud_bag()

    def _update_status(self, comp: str, status: str):
        if comp == "GDB":
            self.lbl_gdb_status.setText(f"🎮 mGBA GDB: {status}")
        elif comp == "RELAY":
            self.lbl_relay_status.setText(f"🌐 Relay Server: {status}")

    def _append_activity_log(self, message: str, level: str = "info"):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        self.activity_log.append(f"[{now_str}] {message}")

        # Show brief non-blocking toast
        self.lbl_bag_toast.setText(message)
        self.lbl_bag_toast.setVisible(True)
        QTimer.singleShot(4000, lambda: self.lbl_bag_toast.setVisible(False))

    def _render_state(self):
        # 1. Update Trainer Header
        badge_count = sum(self.state_mgr.badges)
        name = self.state_mgr.player_name or "ASH"
        tid = self.state_mgr.trainer_id
        game = self.state_mgr.game_code or "BPRE"

        self.lbl_trainer_name.setText(f"Trainer Name: {name}")
        self.lbl_trainer_id.setText(f"Trainer ID: {tid:05d}")
        self.lbl_game_code.setText(f"Game: {game}")
        self.lbl_badge_summary.setText(f"Gym Badges ({badge_count}/8):")

        # Update 8 Badges
        for i, has_badge in enumerate(self.state_mgr.badges):
            b_name = BADGE_NAMES_KANTO[i]
            lbl = self.badge_labels[i]
            if has_badge:
                lbl.setText(f"✓ {b_name}")
                lbl.setStyleSheet("color: #10b981; font-weight: bold; padding: 2px 4px;")
            else:
                lbl.setText(f"○ {b_name}")
                lbl.setStyleSheet("color: #a0aec0; font-weight: normal; padding: 2px 4px;")

        # 2. Update 6 Party Slots
        for i in range(6):
            widgets = self.party_slot_widgets[i]
            if i < len(self.state_mgr.party):
                mon = self.state_mgr.party[i]
                widgets["name"].setText(f"{mon.nickname} ({mon.species_name})")
                widgets["level"].setText(f"Level: {mon.level}")
            else:
                widgets["name"].setText(f"Slot {i+1} (Empty)")
                widgets["level"].setText("Level: --")

        # 3. Update Local Bag Table (Scroll Preserved!)
        self._render_local_bag()

    def _render_local_bag(self):
        """Renders local bag items with search filtering, pocket filter, and scroll preservation."""
        search_query = self.input_search.text().strip().lower()
        pocket_choice = self.combo_pocket.currentText()

        filtered_items = []
        for item_id, qty, item_name in self.state_mgr.bag_items:
            pocket = get_item_pocket(item_id)
            if pocket_choice == "Items Pocket" and pocket != "Items":
                continue
            if pocket_choice == "Poké Balls Pocket" and pocket != "Poké Balls":
                continue
            if search_query and search_query not in item_name.lower():
                continue
            filtered_items.append((item_id, qty, item_name, pocket))

        # Check if identical to last rendered cache
        current_cache = (search_query, pocket_choice, tuple(filtered_items))
        if current_cache == self._last_rendered_bag_cache:
            return  # DO NOT rebuild table if data didn't change! This keeps scrolling smooth.

        self._last_rendered_bag_cache = current_cache

        # Preserve scrollbar position
        v_bar = self.table_local_bag.verticalScrollBar()
        prev_scroll = v_bar.value()

        self.table_local_bag.setRowCount(0)
        for item_id, qty, item_name, pocket in filtered_items:
            row = self.table_local_bag.rowCount()
            self.table_local_bag.insertRow(row)

            # Item Name
            item_widget = QTableWidgetItem(item_name)
            item_widget.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_local_bag.setItem(row, 0, item_widget)

            # Pocket
            pocket_item = QTableWidgetItem(pocket)
            self.table_local_bag.setItem(row, 1, pocket_item)

            # Qty
            qty_item = QTableWidgetItem(f"x{qty}")
            qty_item.setTextAlignment(Qt.AlignCenter)
            self.table_local_bag.setItem(row, 2, qty_item)

            # Quick Action Buttons
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(4)

            btn_dep1 = QPushButton("Dep 1")
            btn_dep1.setToolTip(f"Deposit 1 {item_name} to Cloud Bank")
            btn_dep1.clicked.connect(lambda _, iid=item_id: self._execute_deposit(iid, 1))
            act_layout.addWidget(btn_dep1)

            if qty > 1:
                batch_amt = min(5, qty)
                label_batch = f"Dep {batch_amt}" if batch_amt < qty else "Dep All"
                btn_batch = QPushButton(label_batch)
                btn_batch.setToolTip(f"Deposit {batch_amt} {item_name} to Cloud Bank")
                btn_batch.clicked.connect(lambda _, iid=item_id, amt=batch_amt: self._execute_deposit(iid, amt))
                act_layout.addWidget(btn_batch)

                btn_custom = QPushButton("...")
                btn_custom.setToolTip("Deposit a custom quantity")
                btn_custom.setFixedWidth(24)
                btn_custom.clicked.connect(lambda _, iid=item_id: self._deposit_custom_dialog(iid))
                act_layout.addWidget(btn_custom)

            self.table_local_bag.setCellWidget(row, 3, act_widget)

        # Restore scroll position
        v_bar.setValue(prev_scroll)

    def _render_ledger(self, ledger: dict):
        self._last_ledger = ledger
        self._render_cloud_bag()

    def _render_cloud_bag(self):
        """Renders cloud bank items with search filtering, pocket filter, and scroll preservation."""
        search_query = self.input_search.text().strip().lower()
        pocket_choice = self.combo_pocket.currentText()

        filtered_items = []
        for item_id, qty in sorted(self._last_ledger.items()):
            if qty <= 0:
                continue
            item_name = get_item_name(item_id)
            pocket = get_item_pocket(item_id)
            if pocket_choice == "Items Pocket" and pocket != "Items":
                continue
            if pocket_choice == "Poké Balls Pocket" and pocket != "Poké Balls":
                continue
            if search_query and search_query not in item_name.lower():
                continue
            filtered_items.append((item_id, qty, item_name, pocket))

        current_cache = (search_query, pocket_choice, tuple(filtered_items))
        if current_cache == self._last_rendered_cloud_cache:
            return

        self._last_rendered_cloud_cache = current_cache

        v_bar = self.table_ledger.verticalScrollBar()
        prev_scroll = v_bar.value()

        self.table_ledger.setRowCount(0)
        for item_id, qty, item_name, pocket in filtered_items:
            row = self.table_ledger.rowCount()
            self.table_ledger.insertRow(row)

            # Item Name
            item_widget = QTableWidgetItem(item_name)
            item_widget.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_ledger.setItem(row, 0, item_widget)

            # Pocket
            pocket_item = QTableWidgetItem(pocket)
            self.table_ledger.setItem(row, 1, pocket_item)

            # Available Qty
            qty_item = QTableWidgetItem(f"x{qty}")
            qty_item.setTextAlignment(Qt.AlignCenter)
            self.table_ledger.setItem(row, 2, qty_item)

            # Quick Action Buttons
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(4)

            btn_take1 = QPushButton("Take 1")
            btn_take1.setToolTip(f"Withdraw 1 {item_name} into In-Game Bag")
            btn_take1.clicked.connect(lambda _, iid=item_id: self._execute_withdraw(iid, 1))
            act_layout.addWidget(btn_take1)

            if qty > 1:
                batch_amt = min(5, qty)
                label_batch = f"Take {batch_amt}" if batch_amt < qty else "Take All"
                btn_batch = QPushButton(label_batch)
                btn_batch.setToolTip(f"Withdraw {batch_amt} {item_name} into In-Game Bag")
                btn_batch.clicked.connect(lambda _, iid=item_id, amt=batch_amt: self._execute_withdraw(iid, amt))
                act_layout.addWidget(btn_batch)

                btn_custom = QPushButton("...")
                btn_custom.setToolTip("Withdraw a custom quantity")
                btn_custom.setFixedWidth(24)
                btn_custom.clicked.connect(lambda _, iid=item_id: self._withdraw_custom_dialog(iid))
                act_layout.addWidget(btn_custom)

            self.table_ledger.setCellWidget(row, 3, act_widget)

        v_bar.setValue(prev_scroll)

    def _render_lobby(self, players: list):
        lobby_items = tuple(
            (p.get("player_id"), p.get("trainer_name"), p.get("game_code"), p.get("badges_count"))
            for p in players
            if p.get("player_id") != self.net.player_id
        )
        if lobby_items == self._last_rendered_lobby_cache:
            return
        self._last_rendered_lobby_cache = lobby_items

        v_bar = self.table_players.verticalScrollBar()
        prev_scroll = v_bar.value()

        self.table_players.setRowCount(0)
        for p in players:
            pid = p.get("player_id", "")
            if pid == self.net.player_id:
                continue

            row = self.table_players.rowCount()
            self.table_players.insertRow(row)

            self.table_players.setItem(row, 0, QTableWidgetItem(p.get("trainer_name", "Trainer")))
            self.table_players.setItem(row, 1, QTableWidgetItem(p.get("game_code", "BPRE")))
            self.table_players.setItem(row, 2, QTableWidgetItem(f"{p.get('badges_count', 0)}/8"))

            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(4)

            btn_challenge = QPushButton("⚔️ Battle!")
            btn_challenge.clicked.connect(lambda _, target=pid: self._send_battle_challenge(target))
            act_layout.addWidget(btn_challenge)

            btn_gift = QPushButton("🎁 Send Item")
            btn_gift.clicked.connect(
                lambda _, t_id=pid, t_name=p.get("trainer_name", "Trainer"): self._send_item_to_trainer(t_id, t_name)
            )
            act_layout.addWidget(btn_gift)

            self.table_players.setCellWidget(row, 3, act_widget)

        v_bar.setValue(prev_scroll)

    def _execute_deposit(self, item_id: int, quantity: int):
        asyncio.run_coroutine_threadsafe(self.net.request_deposit(item_id, quantity), self.loop)

    def _deposit_custom_dialog(self, item_id: int):
        item_qty = 1
        item_name = get_item_name(item_id)
        for iid, qty, name in self.state_mgr.bag_items:
            if iid == item_id:
                item_qty = qty
                item_name = name
                break

        val, ok = QInputDialog.getInt(
            self,
            "Deposit Custom Quantity",
            f"How many {item_name} to deposit? (1 - {item_qty}):",
            1,
            1,
            item_qty,
        )
        if ok:
            self._execute_deposit(item_id, val)

    def _execute_withdraw(self, item_id: int, quantity: int):
        asyncio.run_coroutine_threadsafe(self.net.withdraw_item(item_id, quantity), self.loop)

    def _withdraw_custom_dialog(self, item_id: int):
        avail_qty = self._last_ledger.get(item_id, 1)
        item_name = get_item_name(item_id)
        val, ok = QInputDialog.getInt(
            self,
            "Withdraw Custom Quantity",
            f"How many {item_name} to withdraw? (1 - {avail_qty}):",
            1,
            1,
            avail_qty,
        )
        if ok:
            self._execute_withdraw(item_id, val)

    def _send_item_to_trainer(self, target_id: str, target_name: str):
        if not self.state_mgr.bag_items:
            QMessageBox.information(self, "Bag Empty", "Your in-game bag currently has no items to send.")
            return

        item_options = [f"{name} (x{qty})" for (iid, qty, name) in self.state_mgr.bag_items]
        chosen, ok = QInputDialog.getItem(
            self,
            "Send Item to Trainer",
            f"Select an item from your Bag to give to '{target_name}':",
            item_options,
            0,
            False,
        )
        if not (ok and chosen):
            return

        idx = item_options.index(chosen)
        item_id, item_qty, item_name = self.state_mgr.bag_items[idx]

        send_qty = 1
        if item_qty > 1:
            val, ok = QInputDialog.getInt(
                self,
                "Send Quantity",
                f"How many {item_name} to send to '{target_name}'? (1 - {item_qty}):",
                1,
                1,
                item_qty,
            )
            if not ok:
                return
            send_qty = val

        async def _do_send():
            ok = await self.net.send_item_gift(target_id, item_id, send_qty)
            if ok:
                self.signals.activity_logged.emit(
                    f"🎁 Successfully gifted {item_name} x{send_qty} to Trainer '{target_name}'!",
                    "success",
                )
                self.signals.state_updated.emit()

        asyncio.run_coroutine_threadsafe(_do_send(), self.loop)

    def _send_battle_challenge(self, target_id: str):
        if not self.state_mgr.party:
            QMessageBox.warning(self, "No Party", "You must have at least 1 Pokémon in your party to battle!")
            return
        asyncio.run_coroutine_threadsafe(self.net.send_challenge(target_id), self.loop)
        self.signals.activity_logged.emit(f"⚔️ Sent battle challenge to {target_id}. Waiting for response...", "info")
        QMessageBox.information(self, "Challenge Sent", f"Battle challenge sent to {target_id}! Waiting for acceptance...")

    def _handle_incoming_challenge(self, challenger_id: str, challenger_name: str, payload: dict):
        reply = QMessageBox.question(
            self,
            "Battle Challenge!",
            f"Trainer '{challenger_name}' ({challenger_id}) has challenged you to a battle!\n\nDo you accept?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            opp_b64 = payload.get("party_b64", "")
            asyncio.run_coroutine_threadsafe(
                self.net.accept_challenge(challenger_id, opp_b64), self.loop
            )
            self.signals.activity_logged.emit(f"⚔️ Accepted battle challenge from {challenger_name}!", "success")
        else:
            asyncio.run_coroutine_threadsafe(self.net.decline_challenge(challenger_id), self.loop)
            self.signals.activity_logged.emit(f"Declined battle challenge from {challenger_name}.", "info")

    def _handle_battle_ready(self, opponent_id: str, opponent_bytes: bytes):
        self.signals.activity_logged.emit(
            f"⚔️ Battle Ready! Opponent lineup ({len(opponent_bytes)} bytes) injected into Enemy Party RAM!",
            "success",
        )
        QMessageBox.information(
            self,
            "Battle Ready!",
            f"Opponent's 600-byte team injected into Opponent Party RAM (0x{self.state_mgr.offsets.OPPONENT_PARTY:08X})!\n\n"
            f"Talk to a trainer or enter a Link Battle in mGBA to fight their actual lineup!",
        )

    def _show_notification(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def closeEvent(self, event):
        self.poll_timer.stop()
        if self.net.is_connected:
            asyncio.run_coroutine_threadsafe(self.net.disconnect(), self.loop)
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
