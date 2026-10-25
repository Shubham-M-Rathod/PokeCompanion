"""PokeCompanion NetBridge - Desktop Companion UI (PySide6).

Live Gen 3 GBA sidecar multiplayer companion:
- Monitors live party, badges, and bag in mGBA via GDB remote protocol.
- Connects to Central Relay Server for online discovery.
- Challenges other trainers and injects remote 600-byte parties for live battles.
- Provides atomic shared bag item transfers.
"""

import asyncio
import sys
import threading
from typing import Dict, List, Optional
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
)

from src.memory.gdb_client import GDBClient
from src.client.state import GameStateManager, BADGE_NAMES_KANTO
from src.client.net import NetworkEngine
from src.core.items import get_item_name


class BridgeSignals(QObject):
    state_updated = Signal()
    players_updated = Signal(object)
    challenge_received = Signal(str, str, object)
    battle_ready = Signal(str, bytes)
    ledger_updated = Signal(object)
    connection_status = Signal(str, str)  # component, status


class MainWindow(QMainWindow):
    def __init__(self, gdb_host: str = "127.0.0.1", gdb_port: int = 2345, server_url: str = "ws://127.0.0.1:8000"):
        super().__init__()
        self.setWindowTitle("PokeCompanion NetBridge - Gen 3 Sidecar (FireRed / Emerald)")
        self.resize(1000, 750)

        # Core Engines
        self.signals = BridgeSignals()
        self.gdb = GDBClient(host=gdb_host, port=gdb_port)
        self.state_mgr = GameStateManager(self.gdb)
        self.net = NetworkEngine(self.state_mgr, server_url=server_url)

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

        # Wire NetEngine callbacks to Qt signals
        self.net.on_player_list_changed = lambda pl: self.signals.players_updated.emit(pl)
        self.net.on_challenge_received = lambda cid, cname, p: self.signals.challenge_received.emit(cid, cname, p)
        self.net.on_battle_ready = lambda cid, pbytes: self.signals.battle_ready.emit(cid, pbytes)
        self.net.on_ledger_updated = lambda ldg: self.signals.ledger_updated.emit(ldg)

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
        # 1. Connect to mGBA
        connected_gdb = await self.gdb.connect()
        if connected_gdb:
            await self.state_mgr.detect_game_version()
            self.signals.connection_status.emit("GDB", f"Connected ({self.state_mgr.game_code or 'GBA'})")
        else:
            self.signals.connection_status.emit("GDB", "Disconnected (Start GDB in mGBA)")

        # 2. Connect to Relay Server
        try:
            await self.net.connect()
            self.signals.connection_status.emit("RELAY", "Connected to Server")
        except Exception as e:
            self.signals.connection_status.emit("RELAY", f"Offline ({e})")

    def _schedule_poll(self):
        if self.gdb.is_connected and not self._is_polling:
            self._is_polling = True
            asyncio.run_coroutine_threadsafe(self._do_poll(), self.loop)

    async def _do_poll(self):
        try:
            await self.state_mgr.update_all()
            self.signals.state_updated.emit()
            if self.net.is_running:
                await self.net.sync_state()
        except Exception as e:
            pass
        finally:
            self._is_polling = False

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top Status Bar
        status_box = QGroupBox("System Status & Trainer Info")
        status_layout = QHBoxLayout(status_box)

        self.lbl_gdb_status = QLabel("mGBA GDB: Connecting...")
        self.lbl_relay_status = QLabel("Relay Server: Connecting...")
        self.lbl_trainer_info = QLabel("Trainer: -- | ID: -- | Badges: 0/8")

        for lbl in (self.lbl_gdb_status, self.lbl_relay_status, self.lbl_trainer_info):
            lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            status_layout.addWidget(lbl)

        main_layout.addWidget(status_box)

        # Middle Content: Party (Left) & Lobby (Right)
        mid_layout = QHBoxLayout()

        # Left: Live Party View
        party_box = QGroupBox("Live Player Party (Decrypted RAM: 0x02024284)")
        party_layout = QVBoxLayout(party_box)
        self.party_slot_widgets = []

        grid = QGridLayout()
        for i in range(6):
            slot_card = QGroupBox(f"Slot {i+1}")
            slot_vbox = QVBoxLayout(slot_card)
            
            lbl_name = QLabel("Empty Slot")
            lbl_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            bar_hp = QProgressBar()
            bar_hp.setRange(0, 100)
            bar_hp.setValue(0)
            lbl_stats = QLabel("Lv: -- | HP: --/--")
            lbl_moves = QLabel("Moves: --")
            lbl_ivs = QLabel("IVs: --")

            for w in (lbl_name, bar_hp, lbl_stats, lbl_moves, lbl_ivs):
                slot_vbox.addWidget(w)

            self.party_slot_widgets.append({
                "name": lbl_name,
                "hp_bar": bar_hp,
                "stats": lbl_stats,
                "moves": lbl_moves,
                "ivs": lbl_ivs,
            })
            grid.addWidget(slot_card, i // 2, i % 2)

        party_layout.addLayout(grid)
        mid_layout.addWidget(party_box, stretch=3)

        # Right: Online Lobby & Challenge Panel
        lobby_box = QGroupBox("Relay Lobby & Battle Broker")
        lobby_layout = QVBoxLayout(lobby_box)

        self.table_players = QTableWidget(0, 4)
        self.table_players.setHorizontalHeaderLabels(["Trainer", "Game", "Badges", "Action"])
        self.table_players.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lobby_layout.addWidget(self.table_players)

        mid_layout.addWidget(lobby_box, stretch=2)
        main_layout.addLayout(mid_layout, stretch=3)

        # Bottom: Cloud Shared Bag
        bag_box = QGroupBox("Shared Cloud Bag (Atomic Escrow Ledger)")
        bag_layout = QHBoxLayout(bag_box)

        self.table_ledger = QTableWidget(0, 3)
        self.table_ledger.setHorizontalHeaderLabels(["Item Name", "Available", "Claim"])
        self.table_ledger.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        bag_layout.addWidget(self.table_ledger)

        # Deposit Controls
        dep_vbox = QVBoxLayout()
        self.btn_deposit = QPushButton("Deposit Item to Cloud")
        self.btn_deposit.clicked.connect(self._handle_deposit_clicked)
        dep_vbox.addWidget(self.btn_deposit)
        bag_layout.addLayout(dep_vbox)

        main_layout.addWidget(bag_box, stretch=1)

    def _update_status(self, comp: str, status: str):
        if comp == "GDB":
            self.lbl_gdb_status.setText(f"mGBA GDB: {status}")
        elif comp == "RELAY":
            self.lbl_relay_status.setText(f"Relay Server: {status}")

    def _render_state(self):
        # Update Trainer Header
        badge_count = sum(self.state_mgr.badges)
        if self.state_mgr.trainer_id == 0 and not self.state_mgr.party:
            trainer_text = "Trainer: [Waiting for Save to Load in mGBA] | Badges: 0/8"
        else:
            trainer_text = f"Trainer: {self.state_mgr.player_name} | ID: {self.state_mgr.trainer_id:05d} | Badges: {badge_count}/8"
        self.lbl_trainer_info.setText(trainer_text)

        # Update 6 Party Slots
        for i in range(6):
            widgets = self.party_slot_widgets[i]
            if i < len(self.state_mgr.party):
                mon = self.state_mgr.party[i]
                widgets["name"].setText(f"{mon.nickname} ({mon.species_name})")
                max_hp = max(mon.max_hp, 1)
                hp_pct = int((mon.current_hp / max_hp) * 100)
                widgets["hp_bar"].setValue(hp_pct)
                widgets["stats"].setText(f"Lv: {mon.level} | HP: {mon.current_hp}/{mon.max_hp}")
                widgets["moves"].setText(f"Moves: {mon.moves}")
                widgets["ivs"].setText(f"IVs: H{mon.hp_iv} A{mon.atk_iv} D{mon.def_iv} S{mon.spd_iv}")
            else:
                widgets["name"].setText(f"Slot {i+1} (Empty)")
                widgets["hp_bar"].setValue(0)
                widgets["stats"].setText("Lv: -- | HP: --/--")
                widgets["moves"].setText("Moves: --")
                widgets["ivs"].setText("IVs: --")

    def _render_lobby(self, players: list):
        self.table_players.setRowCount(0)
        for p in players:
            pid = p.get("player_id", "")
            if pid == self.net.player_id:
                continue  # Don't challenge oneself
            
            row = self.table_players.rowCount()
            self.table_players.insertRow(row)

            self.table_players.setItem(row, 0, QTableWidgetItem(p.get("trainer_name", "Trainer")))
            self.table_players.setItem(row, 1, QTableWidgetItem(p.get("game_code", "BPRE")))
            self.table_players.setItem(row, 2, QTableWidgetItem(f"{p.get('badges_count', 0)}/8"))

            btn_challenge = QPushButton("Battle!")
            btn_challenge.clicked.connect(lambda _, target=pid: self._send_battle_challenge(target))
            self.table_players.setCellWidget(row, 3, btn_challenge)

    def _send_battle_challenge(self, target_id: str):
        if not self.state_mgr.party:
            QMessageBox.warning(self, "No Party", "You must have at least 1 Pokémon in your party to battle!")
            return
        asyncio.run_coroutine_threadsafe(self.net.send_challenge(target_id), self.loop)
        QMessageBox.information(self, "Challenge Sent", f"Battle challenge sent to {target_id}! Waiting for acceptance...")

    def _handle_incoming_challenge(self, challenger_id: str, challenger_name: str, payload: dict):
        reply = QMessageBox.question(
            self,
            "Battle Challenge!",
            f"Trainer '{challenger_name}' ({challenger_id}) has challenged you to a battle!\nDo you accept?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            opp_b64 = payload.get("party_b64", "")
            asyncio.run_coroutine_threadsafe(
                self.net.accept_challenge(challenger_id, opp_b64), self.loop
            )
        else:
            asyncio.run_coroutine_threadsafe(self.net.decline_challenge(challenger_id), self.loop)

    def _handle_battle_ready(self, opponent_id: str, opponent_bytes: bytes):
        QMessageBox.information(
            self,
            "Battle Ready!",
            f"Opponent's 600-byte team injected into Opponent Party RAM (0x{self.state_mgr.offsets.OPPONENT_PARTY:08X})!\n\n"
            f"Talk to a trainer or enter a Link Battle in mGBA to fight their actual lineup!",
        )

    def _render_ledger(self, ledger: dict):
        self.table_ledger.setRowCount(0)
        for item_id, qty in ledger.items():
            row = self.table_ledger.rowCount()
            self.table_ledger.insertRow(row)

            item_name = get_item_name(item_id)
            self.table_ledger.setItem(row, 0, QTableWidgetItem(item_name))
            self.table_ledger.setItem(row, 1, QTableWidgetItem(str(qty)))

            btn_withdraw = QPushButton("Withdraw")
            btn_withdraw.clicked.connect(lambda _, iid=item_id: self._handle_withdraw_clicked(iid))
            self.table_ledger.setCellWidget(row, 2, btn_withdraw)

    def _handle_withdraw_clicked(self, item_id: int):
        asyncio.run_coroutine_threadsafe(self.net.withdraw_item(item_id, 1), self.loop)

    def _handle_deposit_clicked(self):
        if not self.state_mgr.bag_items:
            QMessageBox.information(self, "Bag Empty", "Your bag currently has no items to deposit.")
            return

        item_names = [f"{name} (x{qty})" for (iid, qty, name) in self.state_mgr.bag_items]
        chosen, ok = QInputDialog.getItem(self, "Deposit Item", "Select item to deposit to Cloud Bank:", item_names, 0, False)
        if ok and chosen:
            idx = item_names.index(chosen)
            item_id, qty, _ = self.state_mgr.bag_items[idx]
            asyncio.run_coroutine_threadsafe(self.net.deposit_item(item_id, 1), self.loop)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

