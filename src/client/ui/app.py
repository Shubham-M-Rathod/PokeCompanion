"""PokeCompanion NetBridge - Desktop Companion UI (PySide6).

Live Gen 3 GBA sidecar multiplayer companion:
- Tab 1: Trainer Profile, Gym Badges with online badge icons, Live 6-Pokémon Party
  with sprite avatars from open-source PokeAPI CDN, and Online Relay Lobby.
- Tab 2: In-Game Bag & Shared Cloud Bank with smooth scrolling, search filtering,
  and 1-click quick deposit/withdraw buttons.
- High-contrast, eye-friendly layout compatible with both dark and light modes.
"""

import asyncio
import datetime
import logging
import struct
import sys
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QColor, QPixmap
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
    QGroupBox,
    QMessageBox,
    QInputDialog,
    QTabWidget,
    QLineEdit,
    QComboBox,
    QTextEdit,
    QGraphicsOpacityEffect,
)

from src.memory.gdb_client import GDBClient
from src.client.state import GameStateManager, BADGE_NAMES_KANTO
from src.client.net import NetworkEngine
from src.client.ui.assets import AsyncImageLoader, KANTO_BADGE_URLS, pokemon_front_urls
from src.client.ui.battle_arena import BattleArenaWindow
from src.core.items import get_item_name, get_item_pocket


class BridgeSignals(QObject):
    state_updated = Signal()
    players_updated = Signal(object)
    challenge_received = Signal(str, str, object)
    challenge_declined = Signal(str, str)
    battle_ready = Signal(str, bytes)
    battle_started = Signal(object)
    battle_turn_result = Signal(object)
    battle_status_changed = Signal(str, bool, int)  # text, is_armed, poll_interval_ms
    ledger_updated = Signal(object)
    connection_status = Signal(str, str)
    activity_logged = Signal(str, str)
    notification = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(
        self,
        gdb_host: str = "127.0.0.1",
        gdb_port: int = 2345,
        server_url: str = "ws://127.0.0.1:8000",
        player_id: Optional[str] = None,
    ):
        super().__init__()
        self.resize(1100, 780)
        self.setMinimumSize(960, 660)

        # Core Engines
        self.signals = BridgeSignals()
        self.gdb = GDBClient(host=gdb_host, port=gdb_port)
        self.state_mgr = GameStateManager(self.gdb)
        self.net = NetworkEngine(self.state_mgr, server_url=server_url, player_id=player_id)
        self.setWindowTitle(
            f"PokeCompanion NetBridge - [{self.net.player_id} | mGBA :{gdb_port}]"
        )

        # Armed Battle Injection State (FR-5)
        self._armed_opponent_bytes: Optional[bytes] = None
        self._armed_opponent_id: str = ""
        self._armed_expected_pid: int = 0
        self._armed_battle_active: bool = False

        # Async Asset Loader
        self.image_loader = AsyncImageLoader()
        self.image_loader.image_loaded.connect(self._on_image_loaded)
        self._slot_avatar_urls: Dict[int, str] = {}
        self._badge_urls: Dict[int, str] = {}

        # State Caches for intelligent table diffing (prevents scroll resetting)
        self._last_ledger: Dict[int, int] = {}
        self._last_rendered_bag_cache: Optional[Tuple] = None
        self._last_rendered_cloud_cache: Optional[Tuple] = None
        self._last_rendered_lobby_cache: Optional[Tuple] = None

        # Setup Asyncio Event Loop in Background Thread
        self.loop = asyncio.new_event_loop()
        self.bg_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.bg_thread.start()

        # Arena window (created lazily on BATTLE_START)
        self.arena_window: Optional[BattleArenaWindow] = None

        # Connect signals
        self.signals.state_updated.connect(self._render_state)
        self.signals.players_updated.connect(self._render_lobby)
        self.signals.challenge_received.connect(self._handle_incoming_challenge)
        self.signals.challenge_declined.connect(self._handle_challenge_declined)
        self.signals.battle_ready.connect(self._handle_battle_ready)
        self.signals.battle_started.connect(self._handle_battle_started)
        self.signals.battle_turn_result.connect(self._handle_battle_turn_result)
        self.signals.battle_status_changed.connect(self._update_battle_status_ui)
        self.signals.ledger_updated.connect(self._render_ledger)
        self.signals.connection_status.connect(self._update_status)
        self.signals.activity_logged.connect(self._append_activity_log)
        self.signals.notification.connect(self._show_notification)

        # Wire NetEngine callbacks
        self.net.on_player_list_changed = lambda pl: self.signals.players_updated.emit(pl)
        self.net.on_challenge_received = lambda cid, cname, p: self.signals.challenge_received.emit(cid, cname, p)
        self.net.on_challenge_declined = lambda did, dname: self.signals.challenge_declined.emit(did, dname)
        self.net.on_battle_ready = lambda cid, pbytes: self.signals.battle_ready.emit(cid, pbytes)
        self.net.on_battle_started = lambda payload: self.signals.battle_started.emit(payload)
        self.net.on_battle_turn_result = lambda payload: self.signals.battle_turn_result.emit(payload)
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
            await self._check_armed_battle()
            self.signals.connection_status.emit("GDB", f"Connected ({self.state_mgr.game_code or 'GBA'})")
            self.signals.state_updated.emit()
            if self.net.is_running:
                await self.net.sync_state()
        except Exception:
            self.signals.connection_status.emit("GDB", "Disconnected (Start GDB in mGBA)")
        finally:
            self._is_polling = False

    async def _check_armed_battle(self):
        """Auto-injects armed opponent party right as an in-game battle begins (gBattleTypeFlags != 0)."""
        armed_bytes = self._armed_opponent_bytes
        if not armed_bytes:
            return

        flags = self.state_mgr.battle_type_flags
        if flags != 0:
            if not self._armed_battle_active:
                self._armed_battle_active = True
                self.signals.battle_status_changed.emit(
                    f"🔥 LIVE BATTLE vs {self._armed_opponent_id} (Watching Enemy RAM)",
                    True,
                    120,
                )

            if self.state_mgr.opponent_first_pid != self._armed_expected_pid:
                ok = await self.state_mgr.inject_opponent_party(armed_bytes)
                if ok:
                    self.signals.activity_logged.emit(
                        f"⚔️ Battle init detected (flags=0x{flags:X}) -> Injected {self._armed_opponent_id}'s team!",
                        "success",
                    )
        else:
            if self._armed_battle_active:
                opp_id = self._armed_opponent_id
                self._armed_opponent_bytes = None
                self._armed_opponent_id = ""
                self._armed_expected_pid = 0
                self._armed_battle_active = False
                self.signals.activity_logged.emit(f"🏁 Battle vs {opp_id} finished.", "info")
                self.signals.battle_status_changed.emit("Idle (Challenge a trainer in the lobby)", False, 800)

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

        self.lbl_client_id = QLabel(f"🪪 Client ID: {self.net.player_id}")
        self.lbl_client_id.setFont(QFont("Segoe UI", 10, QFont.Bold))

        top_bar.addWidget(self.lbl_gdb_status)
        top_bar.addSpacing(20)
        top_bar.addWidget(self.lbl_relay_status)
        top_bar.addSpacing(20)
        top_bar.addWidget(self.lbl_client_id)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # Tabs Layout
        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Segoe UI", 10, QFont.Bold))
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
        info_row.addSpacing(20)
        info_row.addWidget(self.lbl_trainer_id)
        info_row.addSpacing(20)
        info_row.addWidget(self.lbl_game_code)
        info_row.addStretch()
        trainer_box_layout.addLayout(info_row)

        # Line 2: Badges Row with Visual Badge Icons
        badges_row = QHBoxLayout()
        badges_lbl = QLabel("Gym Badges (0/8):")
        badges_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        badges_row.addWidget(badges_lbl)
        self.lbl_badge_summary = badges_lbl
        badges_row.addSpacing(10)

        self.badge_widgets = []
        for i, name in enumerate(BADGE_NAMES_KANTO):
            badge_card = QWidget()
            b_layout = QHBoxLayout(badge_card)
            b_layout.setContentsMargins(3, 1, 3, 1)
            b_layout.setSpacing(4)

            # Badge Image Label
            lbl_icon = QLabel()
            lbl_icon.setFixedSize(26, 26)
            lbl_icon.setAlignment(Qt.AlignCenter)

            # Opacity effect for dimming unearned badges
            opacity = QGraphicsOpacityEffect(lbl_icon)
            opacity.setOpacity(0.25)
            lbl_icon.setGraphicsEffect(opacity)

            # Badge Name
            lbl_text = QLabel(f"○ {name}")
            lbl_text.setFont(QFont("Segoe UI", 9))
            lbl_text.setStyleSheet("color: #718096;")

            b_layout.addWidget(lbl_icon)
            b_layout.addWidget(lbl_text)
            badges_row.addWidget(badge_card)

            self.badge_widgets.append({
                "icon": lbl_icon,
                "text": lbl_text,
                "opacity": opacity,
            })

            # Pre-fetch badge icon URL
            self._badge_urls[i] = KANTO_BADGE_URLS[i]
            self.image_loader.fetch(KANTO_BADGE_URLS[i])

        badges_row.addStretch()
        trainer_box_layout.addLayout(badges_row)
        layout.addWidget(trainer_box)

        # Middle Split: Party (Left) and Online Lobby (Right)
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(8)

        # Left: Live Party 6-Slot Grid with Sprite Avatars
        party_box = QGroupBox("Live Player Party (Decrypted RAM: 0x02024284)")
        party_layout = QVBoxLayout(party_box)
        self.party_slot_widgets = []

        grid = QGridLayout()
        grid.setSpacing(6)
        for i in range(6):
            slot_card = QGroupBox(f"Party Slot {i+1}")
            slot_hbox = QHBoxLayout(slot_card)
            slot_hbox.setContentsMargins(6, 6, 6, 6)
            slot_hbox.setSpacing(8)

            # Pokémon Avatar Sprite on Left
            lbl_avatar = QLabel()
            lbl_avatar.setFixedSize(54, 54)
            lbl_avatar.setAlignment(Qt.AlignCenter)
            lbl_avatar.setStyleSheet("background-color: rgba(0,0,0,0.04); border-radius: 6px; font-size: 20px;")
            lbl_avatar.setText("⚪")
            slot_hbox.addWidget(lbl_avatar)

            # Info Details on Right
            slot_vbox = QVBoxLayout()
            slot_vbox.setSpacing(3)
            slot_vbox.setAlignment(Qt.AlignVCenter)

            lbl_name = QLabel("Empty Slot")
            lbl_name.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_name.setWordWrap(True)

            lbl_level = QLabel("Level: --")
            lbl_level.setFont(QFont("Segoe UI", 9))

            slot_vbox.addWidget(lbl_name)
            slot_vbox.addWidget(lbl_level)
            slot_hbox.addLayout(slot_vbox)

            self.party_slot_widgets.append({
                "avatar": lbl_avatar,
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

        # Active Battle Broker Status Bar
        battle_box = QGroupBox("⚔️ Active Battle Broker")
        battle_vbox = QVBoxLayout(battle_box)
        battle_vbox.setContentsMargins(6, 6, 6, 6)
        battle_vbox.setSpacing(4)

        self.lbl_battle_status = QLabel("Idle (Challenge a trainer in the lobby)")
        self.lbl_battle_status.setWordWrap(True)
        self.lbl_battle_status.setFont(QFont("Segoe UI", 9, QFont.Bold))
        battle_vbox.addWidget(self.lbl_battle_status)

        battle_btn_row = QHBoxLayout()
        self.btn_open_arena = QPushButton("🎮 Open Battle Arena")
        self.btn_open_arena.setEnabled(False)
        self.btn_open_arena.clicked.connect(self._focus_arena_window)
        battle_btn_row.addWidget(self.btn_open_arena)

        self.btn_reinject_team = QPushButton("💉 Inject to RAM")
        self.btn_reinject_team.setEnabled(False)
        self.btn_reinject_team.clicked.connect(self._reinject_armed_team)
        battle_btn_row.addWidget(self.btn_reinject_team)

        self.btn_disarm_battle = QPushButton("✖ Clear")
        self.btn_disarm_battle.setEnabled(False)
        self.btn_disarm_battle.clicked.connect(self._disarm_battle)
        battle_btn_row.addWidget(self.btn_disarm_battle)

        battle_vbox.addLayout(battle_btn_row)
        lobby_layout.addWidget(battle_box)

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

    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        """Asynchronously updates avatars and badge icons when images arrive."""
        # 1. Check Party Slots
        for slot_idx, slot_url in self._slot_avatar_urls.items():
            if slot_url == url and slot_idx < len(self.party_slot_widgets):
                scaled = pixmap.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.party_slot_widgets[slot_idx]["avatar"].setPixmap(scaled)

        # 2. Check Badge Icons
        for badge_idx, badge_url in self._badge_urls.items():
            if badge_url == url and badge_idx < len(self.badge_widgets):
                scaled = pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.badge_widgets[badge_idx]["icon"].setPixmap(scaled)

    def _on_bag_filter_changed(self):
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

        # Update 8 Badges (with Icon & Opacity Highlight)
        for i, has_badge in enumerate(self.state_mgr.badges):
            b_name = BADGE_NAMES_KANTO[i]
            widgets = self.badge_widgets[i]
            if has_badge:
                widgets["text"].setText(f"✓ {b_name}")
                widgets["text"].setStyleSheet("color: #10b981; font-weight: bold;")
                widgets["opacity"].setOpacity(1.0)
            else:
                widgets["text"].setText(f"○ {b_name}")
                widgets["text"].setStyleSheet("color: #a0aec0; font-weight: normal;")
                widgets["opacity"].setOpacity(0.25)

        # 2. Update 6 Party Slots (Avatar Sprite on Left, Nickname & Level on Right)
        for i in range(6):
            widgets = self.party_slot_widgets[i]
            if i < len(self.state_mgr.party):
                mon = self.state_mgr.party[i]
                widgets["name"].setText(f"{mon.nickname}\n({mon.species_name})")
                widgets["level"].setText(f"Level: {mon.level}")

                # Fetch official sprite avatar from PokeAPI CDN (FRLG with default fallback)
                if mon.species > 0:
                    urls = pokemon_front_urls(mon.species)
                    sprite_url = urls[0]
                    if self._slot_avatar_urls.get(i) != sprite_url:
                        self._slot_avatar_urls[i] = sprite_url
                        self.image_loader.fetch(sprite_url, urls[1:])
            else:
                widgets["name"].setText(f"Slot {i+1}\n(Empty)")
                widgets["level"].setText("Level: --")
                widgets["avatar"].clear()
                widgets["avatar"].setText("⚪")
                self._slot_avatar_urls.pop(i, None)

        # 3. Update Local Bag Table (Scroll Preserved!)
        self._render_local_bag()

    def _render_local_bag(self):
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

        current_cache = (search_query, pocket_choice, tuple(filtered_items))
        if current_cache == self._last_rendered_bag_cache:
            return

        self._last_rendered_bag_cache = current_cache

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

        v_bar.setValue(prev_scroll)

    def _render_ledger(self, ledger: dict):
        self._last_ledger = ledger
        self._render_cloud_bag()

    def _render_cloud_bag(self):
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

            trainer_label = f"{p.get('trainer_name', 'Trainer')} ({pid})"
            self.table_players.setItem(row, 0, QTableWidgetItem(trainer_label))
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
        self._update_battle_status_ui(f"⏳ Challenge sent to {target_id} — waiting for acceptance...", False, 800)

    def _handle_incoming_challenge(self, challenger_id: str, challenger_name: str, payload: dict):
        reply = QMessageBox.question(
            self,
            "Battle Challenge!",
            f"Trainer '{challenger_name}' ({challenger_id}) has challenged you to a battle!\n\nDo you accept?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if not self.state_mgr.party:
                QMessageBox.warning(
                    self,
                    "No Party",
                    "Cannot accept battle: your in-game party is empty or mGBA is disconnected.",
                )
                asyncio.run_coroutine_threadsafe(self.net.decline_challenge(challenger_id), self.loop)
                return
            opp_b64 = payload.get("party_b64", "")
            asyncio.run_coroutine_threadsafe(
                self.net.accept_challenge(challenger_id, opp_b64), self.loop
            )
            self.signals.activity_logged.emit(f"⚔️ Accepted battle challenge from {challenger_name} ({challenger_id})!", "success")
        else:
            asyncio.run_coroutine_threadsafe(self.net.decline_challenge(challenger_id), self.loop)
            self.signals.activity_logged.emit(f"Declined battle challenge from {challenger_name} ({challenger_id}).", "info")

    def _handle_challenge_declined(self, decliner_id: str, decliner_name: str):
        self.signals.activity_logged.emit(f"❌ {decliner_name} ({decliner_id}) declined your battle challenge.", "warning")
        self._update_battle_status_ui(f"❌ {decliner_name} ({decliner_id}) declined your challenge.", False, 800)

    def _handle_battle_ready(self, opponent_id: str, opponent_bytes: bytes):
        opp_count = 0
        for idx in range(6):
            pid = struct.unpack_from("<I", opponent_bytes, idx * 100)[0]
            if pid != 0:
                opp_count += 1

        self._armed_opponent_bytes = opponent_bytes
        self._armed_opponent_id = opponent_id
        self._armed_expected_pid = struct.unpack_from("<I", opponent_bytes, 0)[0]
        self._armed_battle_active = False

        status_txt = (
            f"⚔️ Live Battle vs {opponent_id} ({opp_count} Pokémon) — "
            f"GBA Arena active (mGBA RAM also armed!)"
        )
        self._update_battle_status_ui(status_txt, True, 200)
        self.signals.activity_logged.emit(
            f"⚔️ Battle Ready vs {opponent_id} ({opp_count} Pokémon).",
            "success",
        )

    def _ensure_arena_window(self) -> BattleArenaWindow:
        if self.arena_window is None:
            self.arena_window = BattleArenaWindow(self.image_loader, parent=self)
            self.arena_window.action_submitted.connect(self._send_arena_action)
        return self.arena_window

    def _handle_battle_started(self, battle_state: dict):
        arena = self._ensure_arena_window()
        self.btn_open_arena.setEnabled(True)
        arena.start_battle(battle_state)
        arena.show()
        arena.raise_()
        arena.activateWindow()

    def _handle_battle_turn_result(self, payload: dict):
        arena = self._ensure_arena_window()
        arena.apply_turn_result(payload)
        if payload.get("phase") == "FINISHED":
            self._update_battle_status_ui("🏁 Live Battle finished! Ready for next challenge.", False, 800)

    def _send_arena_action(self, battle_id: str, action_type: str, move_index: int, switch_index: int):
        asyncio.run_coroutine_threadsafe(
            self.net.send_battle_action(battle_id, action_type, move_index, switch_index),
            self.loop,
        )

    def _focus_arena_window(self):
        if self.arena_window:
            self.arena_window.show()
            self.arena_window.raise_()
            self.arena_window.activateWindow()

    def _update_battle_status_ui(self, status_text: str, is_armed: bool, poll_interval_ms: int):
        self.lbl_battle_status.setText(status_text)
        self.btn_reinject_team.setEnabled(is_armed)
        self.btn_disarm_battle.setEnabled(is_armed)
        if self.poll_timer.interval() != poll_interval_ms:
            self.poll_timer.setInterval(poll_interval_ms)

    def _reinject_armed_team(self):
        if not self._armed_opponent_bytes:
            return
        armed_bytes = self._armed_opponent_bytes
        opp_id = self._armed_opponent_id

        async def _do_inject():
            ok = await self.state_mgr.inject_opponent_party(armed_bytes)
            if ok:
                self.signals.activity_logged.emit(f"💉 Manually injected {opp_id}'s team into Enemy Party RAM!", "success")
            else:
                self.signals.activity_logged.emit("⚠️ Manual team injection failed (check mGBA GDB connection).", "error")

        asyncio.run_coroutine_threadsafe(_do_inject(), self.loop)

    def _disarm_battle(self):
        self._armed_opponent_bytes = None
        self._armed_opponent_id = ""
        self._armed_expected_pid = 0
        self._armed_battle_active = False
        self._update_battle_status_ui("Idle (Challenge a trainer in the lobby)", False, 800)
        self.signals.activity_logged.emit("Disarmed pending battle injection.", "info")

    def _show_notification(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def closeEvent(self, event):
        self.poll_timer.stop()
        if self.net.is_connected:
            asyncio.run_coroutine_threadsafe(self.net.disconnect(), self.loop)
        event.accept()


def main(
    gdb_host: str = "127.0.0.1",
    gdb_port: int = 2345,
    server_url: str = "ws://127.0.0.1:8000",
    player_id: Optional[str] = None,
):
    app = QApplication(sys.argv)
    window = MainWindow(
        gdb_host=gdb_host,
        gdb_port=gdb_port,
        server_url=server_url,
        player_id=player_id,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
