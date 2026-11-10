"""GBA FireRed-Styled Turn-Based PvP Battle Arena UI (PySide6).

Renders an authentic Game Boy Advance battle stage using:
- FireRed outdoor sky & grassy battle platforms with painted HUD frames.
- Back sprite for the player's Pokémon and front sprite for the opponent's Pokémon.
- Status condition badges (PAR/BRN/PSN/TOX/SLP/FRZ), stat stages, and party Pokéballs.
- Classic 2x2 GBA Command Menu -> colored Move Grid (Type, PHY/SPC/STA, Power, PP)
  & Party Switcher + step-by-step GBA battle text playback.
"""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.battle.items_data import get_battle_item_effect
from src.battle.type_chart import TYPE_COLORS
from src.client.ui.assets import AsyncImageLoader, pokemon_back_urls, pokemon_front_urls

STATUS_COLORS: Dict[str, str] = {
    "PAR": "#eab308",
    "BRN": "#ef4444",
    "PSN": "#a855f7",
    "TOX": "#7e22ce",
    "SLP": "#64748b",
    "FRZ": "#06b6d4",
}


def _hp_bar_color(ratio: float) -> QColor:
    if ratio > 0.5:
        return QColor("#22c55e")
    if ratio > 0.2:
        return QColor("#eab308")
    return QColor("#ef4444")


class BattleStageWidget(QWidget):
    """Custom-painted FireRed-style battle scene with platforms, sprites, and GBA HUD cards."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(340)
        self.you_view: Dict[str, Any] = {}
        self.opp_view: Dict[str, Any] = {}
        self.player_pixmap: Optional[QPixmap] = None
        self.opp_pixmap: Optional[QPixmap] = None
        self.flash_side: Optional[str] = None  # "you" or "opponent"
        self.shake_offset: int = 0

    def update_state(self, you_view: Dict[str, Any], opp_view: Dict[str, Any]) -> None:
        self.you_view = you_view
        self.opp_view = opp_view
        self.update()

    def set_player_sprite(self, pixmap: QPixmap) -> None:
        self.player_pixmap = pixmap
        self.update()

    def set_opponent_sprite(self, pixmap: QPixmap) -> None:
        self.opp_pixmap = pixmap
        self.update()

    def trigger_hit_flash(self, side: str) -> None:
        self.flash_side = side
        self.shake_offset = 6
        self.update()
        QTimer.singleShot(90, lambda: self._step_flash(-6))
        QTimer.singleShot(180, lambda: self._step_flash(4))
        QTimer.singleShot(260, self._clear_flash)

    def _step_flash(self, offset: int) -> None:
        self.shake_offset = offset
        self.update()

    def _clear_flash(self) -> None:
        self.flash_side = None
        self.shake_offset = 0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()

        # 1. Sky & Grassy Horizon Background (FireRed outdoor field palette)
        horizon_y = int(h * 0.56)
        sky_grad = QLinearGradient(0, 0, 0, horizon_y)
        sky_grad.setColorAt(0.0, QColor("#a5d8ff"))
        sky_grad.setColorAt(0.7, QColor("#d0ebff"))
        sky_grad.setColorAt(1.0, QColor("#e9fac8"))
        painter.fillRect(0, 0, w, horizon_y, sky_grad)

        field_grad = QLinearGradient(0, horizon_y, 0, h)
        field_grad.setColorAt(0.0, QColor("#a9e34b"))
        field_grad.setColorAt(0.35, QColor("#82c91e"))
        field_grad.setColorAt(1.0, QColor("#5c940d"))
        painter.fillRect(0, horizon_y, w, h - horizon_y, field_grad)

        # Distant treeline silhouette along horizon
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#74b816"))
        painter.drawRect(0, horizon_y - 6, w, 10)

        # 2. Grassy Battle Platforms
        opp_plat = QRectF(w * 0.56, h * 0.38, w * 0.34, h * 0.17)
        you_plat = QRectF(w * 0.08, h * 0.77, w * 0.38, h * 0.19)
        self._draw_platform(painter, opp_plat)
        self._draw_platform(painter, you_plat)

        # 3. Opponent Sprite (Top-Right)
        opp_active = self.opp_view.get("active", {})
        opp_fainted = opp_active.get("fainted", False)
        if self.opp_pixmap and not self.opp_pixmap.isNull() and not opp_fainted:
            if self.flash_side != "opponent" or self.shake_offset > 0:
                dx = self.shake_offset if self.flash_side == "opponent" else 0
                sprite_sz = min(136, int(h * 0.38))
                scaled = self.opp_pixmap.scaled(sprite_sz, sprite_sz, Qt.KeepAspectRatio, Qt.FastTransformation)
                sx = int(opp_plat.center().x() - scaled.width() / 2) + dx
                sy = int(opp_plat.center().y() - scaled.height() + 14)
                painter.drawPixmap(sx, sy, scaled)

        # 4. Player Back Sprite (Bottom-Left)
        you_active = self.you_view.get("active", {})
        you_fainted = you_active.get("fainted", False)
        if self.player_pixmap and not self.player_pixmap.isNull() and not you_fainted:
            if self.flash_side != "you" or self.shake_offset > 0:
                dx = self.shake_offset if self.flash_side == "you" else 0
                sprite_sz = min(156, int(h * 0.44))
                scaled = self.player_pixmap.scaled(sprite_sz, sprite_sz, Qt.KeepAspectRatio, Qt.FastTransformation)
                sx = int(you_plat.center().x() - scaled.width() / 2) + dx
                sy = int(you_plat.center().y() - scaled.height() + 26)
                painter.drawPixmap(sx, sy, scaled)

        # 5. GBA HUD Cards
        if opp_active:
            opp_hud = QRectF(18, 16, min(330, w * 0.44), 92)
            self._draw_hud_card(
                painter,
                opp_hud,
                trainer_name=self.opp_view.get("trainer_name", "Opponent"),
                mon=opp_active,
                party_status=self.opp_view.get("party_status", []),
                show_numeric_hp=False,
            )

        if you_active:
            hud_w = min(350, w * 0.47)
            you_hud = QRectF(w - hud_w - 18, h - 116, hud_w, 102)
            team = self.you_view.get("team", [])
            you_party_status = [{"fainted": m.get("fainted", False), "status": m.get("status")} for m in team]
            self._draw_hud_card(
                painter,
                you_hud,
                trainer_name=self.you_view.get("trainer_name", "You"),
                mon=you_active,
                party_status=you_party_status,
                show_numeric_hp=True,
            )

    def _draw_platform(self, painter: QPainter, rect: QRectF) -> None:
        # Earthy outer rim
        painter.setPen(QPen(QColor("#5c7cfa").darker(200), 1.5))
        painter.setBrush(QColor("#b2966d"))
        painter.drawEllipse(rect.adjusted(0, 5, 0, 5))
        # Grassy top surface
        painter.setPen(QPen(QColor("#74b816"), 2))
        painter.setBrush(QColor("#94d82d"))
        painter.drawEllipse(rect)
        # Inner darker shadow under sprite
        shadow = rect.adjusted(rect.width() * 0.22, rect.height() * 0.30, -rect.width() * 0.22, -rect.height() * 0.26)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawEllipse(shadow)

    def _draw_hud_card(
        self,
        painter: QPainter,
        rect: QRectF,
        trainer_name: str,
        mon: Dict[str, Any],
        party_status: List[Dict[str, Any]],
        show_numeric_hp: bool,
    ) -> None:
        # Drop shadow
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 65))
        painter.drawRoundedRect(rect.adjusted(4, 4, 4, 4), 10, 10)

        # Classic FireRed cream card with dark forest border
        painter.setPen(QPen(QColor("#3b4252"), 2.5))
        painter.setBrush(QColor("#f8f9e6"))
        painter.drawRoundedRect(rect, 10, 10)

        x = rect.x() + 12
        y = rect.y() + 18

        # Row 1: Nickname + Level
        painter.setPen(QColor("#1e293b"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        nick = str(mon.get("nickname") or mon.get("species_name") or "---")
        lvl = mon.get("level", 1)
        painter.drawText(int(x), int(y), nick)

        lvl_text = f"Lv{lvl}"
        painter.drawText(int(rect.right() - 54), int(y), lvl_text)

        # Status Pill or Stat Stages
        status = mon.get("status")
        if status:
            pill_rect = QRectF(x, y + 6, 38, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(STATUS_COLORS.get(status, "#64748b")))
            painter.drawRoundedRect(pill_rect, 4, 4)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(pill_rect, Qt.AlignCenter, status)

        # Row 2: GBA HP Bar
        hp = int(mon.get("hp", 0))
        max_hp = max(1, int(mon.get("max_hp", 1)))
        ratio = max(0.0, min(1.0, hp / max_hp))

        bar_y = y + 12
        bar_left = x + (46 if status else 0)
        bar_w = rect.right() - 14 - bar_left

        # Dark pill track containing "HP" + bar
        track_rect = QRectF(bar_left, bar_y, bar_w, 14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#334155"))
        painter.drawRoundedRect(track_rect, 7, 7)

        painter.setPen(QColor("#facc15"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.drawText(int(bar_left + 5), int(bar_y + 11), "HP")

        inner_left = bar_left + 24
        inner_w = max(10.0, bar_w - 28)
        inner_bg = QRectF(inner_left, bar_y + 3, inner_w, 8)
        painter.setBrush(QColor("#1e293b"))
        painter.drawRoundedRect(inner_bg, 4, 4)

        if ratio > 0:
            fill_rect = QRectF(inner_left, bar_y + 3, max(4.0, inner_w * ratio), 8)
            painter.setBrush(_hp_bar_color(ratio))
            painter.drawRoundedRect(fill_rect, 4, 4)

        # Row 3: Numeric HP (player only) + Pokeball party indicators + Stat stages
        row3_y = y + 40
        if show_numeric_hp:
            painter.setPen(QColor("#1e293b"))
            painter.setFont(QFont("Consolas", 10, QFont.Bold))
            painter.drawText(int(rect.right() - 96), int(row3_y), f"{hp:3d} / {max_hp:3d}")

        # Pokéballs row on bottom-left of HUD
        ball_x = x
        ball_y = row3_y - 10
        for idx in range(6):
            r = QRectF(ball_x + idx * 14, ball_y, 10, 10)
            if idx < len(party_status):
                p_info = party_status[idx]
                if p_info.get("fainted"):
                    painter.setPen(QPen(QColor("#64748b"), 1))
                    painter.setBrush(QColor("#cbd5e1"))
                elif p_info.get("status"):
                    painter.setPen(QPen(QColor("#92400e"), 1))
                    painter.setBrush(QColor("#f59e0b"))
                else:
                    painter.setPen(QPen(QColor("#991b1b"), 1))
                    painter.setBrush(QColor("#ef4444"))
            else:
                painter.setPen(QPen(QColor("#cbd5e1"), 1))
                painter.setBrush(Qt.transparent)
            painter.drawEllipse(r)

        # Trainer tag + active stat boosts
        stages = mon.get("stages", {})
        stage_parts = [f"{'+' if v > 0 else ''}{v}{k.upper()}" for k, v in stages.items()]
        tag_text = trainer_name
        if stage_parts:
            tag_text += "  |  " + " ".join(stage_parts[:3])
        painter.setPen(QColor("#475569"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(int(x), int(rect.bottom() - 6), tag_text)


class BattleArenaWindow(QDialog):
    """Complete GBA-styled Live PvP Battle Arena synced with RelayManager."""

    # battle_id, action_type, move_idx, switch_idx, item_id, target_idx
    action_submitted = Signal(str, str, int, int, int, int)

    def __init__(self, image_loader: AsyncImageLoader, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("⚔️ PokeCompanion GBA Battle Arena")
        self.resize(820, 620)
        self.setMinimumSize(720, 560)

        self.image_loader = image_loader
        self.image_loader.image_loaded.connect(self._on_sprite_loaded)

        self.battle_id: str = ""
        self.current_state: Dict[str, Any] = {}
        self._bag_items: List[Tuple[int, int, str]] = []
        self._selected_item_id: int = 0
        self.player_sprite_url: str = ""
        self.opp_sprite_url: str = ""
        self.party_thumb_urls: Dict[int, str] = {}
        self.party_thumb_labels: Dict[int, QLabel] = {}

        self._event_queue: List[Dict[str, Any]] = []
        self._playback_timer = QTimer(self)
        self._playback_timer.timeout.connect(self._advance_event_playback)
        self._pending_state_after_playback: Optional[Dict[str, Any]] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Top Battle Stage Canvas
        self.stage = BattleStageWidget()
        root.addWidget(self.stage, stretch=3)

        # Bottom GBA Command Deck (Message Box Left + Action Menu Right)
        deck_frame = QFrame()
        deck_frame.setStyleSheet("QFrame#gbaDeck { background-color: #1e293b; border: 3px solid #475569; border-radius: 8px; }")
        deck_frame.setObjectName("gbaDeck")
        deck_layout = QHBoxLayout(deck_frame)
        deck_layout.setContentsMargins(8, 8, 8, 8)
        deck_layout.setSpacing(8)

        # Left: Classic FireRed Teal Dialog Box + Collapsible History
        msg_container = QWidget()
        msg_vbox = QVBoxLayout(msg_container)
        msg_vbox.setContentsMargins(0, 0, 0, 0)
        msg_vbox.setSpacing(4)

        self.lbl_dialog = QLabel("Battle starting...")
        self.lbl_dialog.setWordWrap(True)
        self.lbl_dialog.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_dialog.setMinimumHeight(115)
        self.lbl_dialog.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_dialog.setStyleSheet(
            "background-color: #28527a; color: #f8fafc; border: 3px solid #e2e8f0; "
            "border-radius: 8px; padding: 12px;"
        )
        msg_vbox.addWidget(self.lbl_dialog, stretch=1)

        self.txt_history = QTextEdit()
        self.txt_history.setReadOnly(True)
        self.txt_history.setVisible(False)
        self.txt_history.setMinimumHeight(115)
        self.txt_history.setFont(QFont("Consolas", 9))
        self.txt_history.setStyleSheet(
            "background-color: #0f172a; color: #e2e8f0; border: 2px solid #94a3b8; border-radius: 6px; padding: 6px;"
        )
        msg_vbox.addWidget(self.txt_history, stretch=1)

        self.btn_log = QPushButton("📜 View Battle Log")
        self.btn_log.setFixedHeight(22)
        self.btn_log.setStyleSheet(
            "background-color: #334155; color: #e2e8f0; border: 1px solid #64748b; "
            "border-radius: 4px; font-size: 10px; font-weight: bold;"
        )
        self.btn_log.clicked.connect(self._toggle_history_view)
        msg_vbox.addWidget(self.btn_log)

        deck_layout.addWidget(msg_container, stretch=3)

        # Right: Stacked Action Menu
        self.menu_stack = QStackedWidget()
        self.menu_stack.setStyleSheet(
            "QStackedWidget { background-color: #f8fafc; border: 3px solid #94a3b8; border-radius: 8px; }"
        )

        # Page 0: Classic 2x2 GBA Menu (FIGHT | BAG / POKEMON | RUN)
        self.page_main = QWidget()
        main_grid = QGridLayout(self.page_main)
        main_grid.setContentsMargins(8, 8, 8, 8)
        main_grid.setSpacing(6)

        self.btn_fight = self._menu_btn("⚔️ FIGHT", "#dc2626")
        self.btn_bag = self._menu_btn("🎒 BAG", "#d97706")
        self.btn_pokemon = self._menu_btn("🔄 POKéMON", "#16a34a")
        self.btn_run = self._menu_btn("🏳️ RUN", "#2563eb")

        self.btn_fight.clicked.connect(lambda: self.menu_stack.setCurrentIndex(1))
        self.btn_bag.clicked.connect(self._open_bag_menu)
        self.btn_pokemon.clicked.connect(self._open_switch_menu)
        self.btn_run.clicked.connect(self._confirm_forfeit)

        main_grid.addWidget(self.btn_fight, 0, 0)
        main_grid.addWidget(self.btn_bag, 0, 1)
        main_grid.addWidget(self.btn_pokemon, 1, 0)
        main_grid.addWidget(self.btn_run, 1, 1)
        self.menu_stack.addWidget(self.page_main)

        # Page 1: 4-Move Grid
        self.page_moves = QWidget()
        moves_vbox = QVBoxLayout(self.page_moves)
        moves_vbox.setContentsMargins(6, 6, 6, 6)
        moves_vbox.setSpacing(4)

        self.moves_grid = QGridLayout()
        self.moves_grid.setSpacing(4)
        self.move_buttons: List[QPushButton] = []
        for idx in range(4):
            btn = QPushButton("--")
            btn.setMinimumHeight(46)
            btn.clicked.connect(lambda _, m_idx=idx: self._submit_fight(m_idx))
            self.move_buttons.append(btn)
            self.moves_grid.addWidget(btn, idx // 2, idx % 2)
        moves_vbox.addLayout(self.moves_grid)

        btn_moves_back = QPushButton("← Back")
        btn_moves_back.setFixedHeight(26)
        btn_moves_back.setStyleSheet("background-color: #e2e8f0; color: #1e293b; font-weight: bold;")
        btn_moves_back.clicked.connect(lambda: self.menu_stack.setCurrentIndex(0))
        moves_vbox.addWidget(btn_moves_back)
        self.menu_stack.addWidget(self.page_moves)

        # Page 2: Party Switcher
        self.page_switch = QWidget()
        sw_vbox = QVBoxLayout(self.page_switch)
        sw_vbox.setContentsMargins(6, 6, 6, 6)
        sw_vbox.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.switch_list_widget = QWidget()
        self.switch_list_layout = QVBoxLayout(self.switch_list_widget)
        self.switch_list_layout.setContentsMargins(2, 2, 2, 2)
        self.switch_list_layout.setSpacing(4)
        scroll.setWidget(self.switch_list_widget)
        sw_vbox.addWidget(scroll)

        self.btn_switch_back = QPushButton("← Back")
        self.btn_switch_back.setFixedHeight(26)
        self.btn_switch_back.setStyleSheet("background-color: #e2e8f0; color: #1e293b; font-weight: bold;")
        self.btn_switch_back.clicked.connect(lambda: self.menu_stack.setCurrentIndex(0))
        sw_vbox.addWidget(self.btn_switch_back)
        self.menu_stack.addWidget(self.page_switch)

        # Page 3: Waiting for Opponent
        self.page_waiting = QWidget()
        wait_vbox = QVBoxLayout(self.page_waiting)
        wait_vbox.setAlignment(Qt.AlignCenter)
        self.lbl_waiting = QLabel("⏳ Waiting for opponent...")
        self.lbl_waiting.setAlignment(Qt.AlignCenter)
        self.lbl_waiting.setWordWrap(True)
        self.lbl_waiting.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_waiting.setStyleSheet("color: #1e293b;")
        wait_vbox.addWidget(self.lbl_waiting)
        self.menu_stack.addWidget(self.page_waiting)

        # Page 4: Battle Finished
        self.page_finished = QWidget()
        fin_vbox = QVBoxLayout(self.page_finished)
        fin_vbox.setAlignment(Qt.AlignCenter)
        fin_vbox.setSpacing(8)
        self.lbl_result = QLabel("Battle Complete!")
        self.lbl_result.setAlignment(Qt.AlignCenter)
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_result.setStyleSheet("color: #1e293b;")
        fin_vbox.addWidget(self.lbl_result)

        btn_close = QPushButton("Close Arena")
        btn_close.setMinimumHeight(34)
        btn_close.setStyleSheet("background-color: #2563eb; color: #ffffff; font-weight: bold; border-radius: 6px; padding: 6px 14px;")
        btn_close.clicked.connect(self.close)
        fin_vbox.addWidget(btn_close)
        self.menu_stack.addWidget(self.page_finished)

        # Page 5: Battle Bag Items
        self.page_bag = QWidget()
        bag_vbox = QVBoxLayout(self.page_bag)
        bag_vbox.setContentsMargins(6, 6, 6, 6)
        bag_vbox.setSpacing(4)

        bag_scroll = QScrollArea()
        bag_scroll.setWidgetResizable(True)
        self.bag_list_widget = QWidget()
        self.bag_list_layout = QVBoxLayout(self.bag_list_widget)
        self.bag_list_layout.setContentsMargins(2, 2, 2, 2)
        self.bag_list_layout.setSpacing(4)
        bag_scroll.setWidget(self.bag_list_widget)
        bag_vbox.addWidget(bag_scroll)

        btn_bag_back = QPushButton("← Back")
        btn_bag_back.setFixedHeight(26)
        btn_bag_back.setStyleSheet("background-color: #e2e8f0; color: #1e293b; font-weight: bold;")
        btn_bag_back.clicked.connect(lambda: self.menu_stack.setCurrentIndex(0))
        bag_vbox.addWidget(btn_bag_back)
        self.menu_stack.addWidget(self.page_bag)

        # Page 6: Bag Item Target Pokemon Picker
        self.page_bag_target = QWidget()
        bt_vbox = QVBoxLayout(self.page_bag_target)
        bt_vbox.setContentsMargins(6, 6, 6, 6)
        bt_vbox.setSpacing(4)

        self.lbl_bag_target_hdr = QLabel("Use item on:")
        self.lbl_bag_target_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_bag_target_hdr.setStyleSheet("color: #1e293b;")
        bt_vbox.addWidget(self.lbl_bag_target_hdr)

        bt_scroll = QScrollArea()
        bt_scroll.setWidgetResizable(True)
        self.bag_target_widget = QWidget()
        self.bag_target_layout = QVBoxLayout(self.bag_target_widget)
        self.bag_target_layout.setContentsMargins(2, 2, 2, 2)
        self.bag_target_layout.setSpacing(4)
        bt_scroll.setWidget(self.bag_target_widget)
        bt_vbox.addWidget(bt_scroll)

        btn_bt_back = QPushButton("← Back to Bag")
        btn_bt_back.setFixedHeight(26)
        btn_bt_back.setStyleSheet("background-color: #e2e8f0; color: #1e293b; font-weight: bold;")
        btn_bt_back.clicked.connect(self._open_bag_menu)
        bt_vbox.addWidget(btn_bt_back)
        self.menu_stack.addWidget(self.page_bag_target)

        deck_layout.addWidget(self.menu_stack, stretch=2)
        root.addWidget(deck_frame, stretch=1)

    def _menu_btn(self, label: str, hex_bg: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setMinimumHeight(52)
        btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_bg}; color: #ffffff; border: 2px solid #0f172a; border-radius: 6px; }}"
            f"QPushButton:hover {{ opacity: 0.9; border: 2px solid #facc15; }}"
        )
        return btn

    def start_battle(self, battle_state: Dict[str, Any]) -> None:
        self.txt_history.clear()
        self._event_queue.clear()
        self._playback_timer.stop()
        self._pending_state_after_playback = None

        opp_name = battle_state.get("opponent", {}).get("trainer_name", "Opponent")
        opp_mon = battle_state.get("opponent", {}).get("active", {}).get("nickname", "Pokemon")
        you_mon = battle_state.get("you", {}).get("active", {}).get("nickname", "Pokemon")

        self.setWindowTitle(f"⚔️ GBA Battle Arena — vs {opp_name}")
        self._apply_battle_state(battle_state)
        intro = f"{opp_name} sent out {opp_mon}!\nGo! {you_mon}! What will {you_mon} do?"
        self.lbl_dialog.setText(intro)
        self.txt_history.append(f"--- Battle Started vs {opp_name} ---")
        self.txt_history.append(f"{opp_name} sent out {opp_mon}! Go! {you_mon}!")

    def apply_turn_result(self, payload: Dict[str, Any]) -> None:
        events = payload.get("events", [])
        self._pending_state_after_playback = payload
        if not events:
            self._apply_battle_state(payload)
            return

        self._event_queue = list(events)
        self.menu_stack.setCurrentIndex(3)
        self.lbl_waiting.setText("🎬 Resolving turn...")
        self._advance_event_playback()
        self._playback_timer.start(650)

    def _advance_event_playback(self) -> None:
        if not self._event_queue:
            self._playback_timer.stop()
            if self._pending_state_after_playback:
                final_state = self._pending_state_after_playback
                self._pending_state_after_playback = None
                self._apply_battle_state(final_state)
            return

        ev = self._event_queue.pop(0)
        text = ev.get("text", "")
        if text:
            self.lbl_dialog.setText(text)
            self.txt_history.append(text)

        # Visual hit flash on damage event
        if ev.get("kind") == "damage" and ev.get("player_id"):
            you_id = self.current_state.get("you", {}).get("player_id")
            hit_side = "you" if ev["player_id"] == you_id else "opponent"
            self.stage.trigger_hit_flash(hit_side)

    def _apply_battle_state(self, state: Dict[str, Any]) -> None:
        self.current_state = state
        self.battle_id = state.get("battle_id", "")
        you_view = state.get("you", {})
        opp_view = state.get("opponent", {})

        self.stage.update_state(you_view, opp_view)

        # Fetch player back sprite & opponent front sprite
        you_species = int(you_view.get("active", {}).get("species", 0))
        opp_species = int(opp_view.get("active", {}).get("species", 0))
        if you_species > 0:
            urls = pokemon_back_urls(you_species)
            if self.player_sprite_url != urls[0]:
                self.player_sprite_url = urls[0]
                self.stage.set_player_sprite(QPixmap())
                self.image_loader.fetch(urls[0], urls[1:])
        if opp_species > 0:
            urls = pokemon_front_urls(opp_species)
            if self.opp_sprite_url != urls[0]:
                self.opp_sprite_url = urls[0]
                self.stage.set_opponent_sprite(QPixmap())
                self.image_loader.fetch(urls[0], urls[1:])

        self._refresh_move_buttons(you_view.get("active", {}))
        self._refresh_party_switcher(you_view)

        phase = state.get("phase", "CHOOSE_ACTION")
        you_id = you_view.get("player_id")
        active_nick = you_view.get("active", {}).get("nickname", "Pokémon")

        if phase == "FINISHED":
            winner_id = state.get("winner_id")
            if winner_id == you_id:
                self.lbl_result.setText("🏆 VICTORY!\nYou won the battle!")
            elif winner_id == "DRAW":
                self.lbl_result.setText("🤝 DRAW!\nBoth teams fainted.")
            else:
                self.lbl_result.setText("💀 DEFEAT!\nYour team fainted.")
            self.menu_stack.setCurrentIndex(4)
            return

        if phase == "FORCE_SWITCH":
            if state.get("must_switch"):
                self.lbl_dialog.setText("Choose your next Pokémon to send out!")
                self.btn_switch_back.setVisible(False)
                self.menu_stack.setCurrentIndex(2)
            else:
                opp_name = opp_view.get("trainer_name", "Opponent")
                self.lbl_waiting.setText(f"⏳ Waiting for {opp_name} to choose their next Pokémon...")
                self.menu_stack.setCurrentIndex(3)
            return

        self.btn_switch_back.setVisible(True)
        waiting_for = state.get("waiting_for_players", [])
        if waiting_for and you_id not in waiting_for:
            opp_name = opp_view.get("trainer_name", "Opponent")
            self.lbl_waiting.setText(f"⏳ Move locked! Waiting for {opp_name}...")
            self.menu_stack.setCurrentIndex(3)
        else:
            self.lbl_dialog.setText(f"What will {active_nick} do?")
            self.menu_stack.setCurrentIndex(0)

    def _refresh_move_buttons(self, active_mon: Dict[str, Any]) -> None:
        moves = active_mon.get("moves", [])
        for idx, btn in enumerate(self.move_buttons):
            if idx < len(moves):
                m = moves[idx]
                mtype = m.get("type", "Normal")
                cat = m.get("category", "Physical")[:3].upper()
                pwr = m.get("power", 0)
                pp = m.get("pp", 0)
                max_pp = m.get("max_pp", 1)
                color = TYPE_COLORS.get(mtype, "#64748b")

                pwr_str = f"Pwr {pwr}" if pwr > 0 else "Status"
                btn.setText(f"{m['name']}\n{mtype} ({cat}) | {pwr_str} | PP {pp}/{max_pp}")
                btn.setEnabled(pp > 0)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {color}; color: #111827; font-weight: bold; "
                    f"font-size: 10px; border: 2px solid #1e293b; border-radius: 6px; padding: 4px; }}"
                    f"QPushButton:hover {{ border: 2px solid #ffffff; }}"
                    f"QPushButton:disabled {{ background-color: #cbd5e1; color: #64748b; }}"
                )
            else:
                btn.setText("--")
                btn.setEnabled(False)
                btn.setStyleSheet("background-color: #e2e8f0; color: #94a3b8; border-radius: 6px;")

    def _refresh_party_switcher(self, you_view: Dict[str, Any]) -> None:
        while self.switch_list_layout.count():
            item = self.switch_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.party_thumb_urls.clear()
        self.party_thumb_labels.clear()

        active_idx = you_view.get("active_index", 0)
        team = you_view.get("team", [])

        for idx, mon in enumerate(team):
            row_frame = QFrame()
            row_frame.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px;")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(6, 4, 6, 4)
            row_layout.setSpacing(6)

            lbl_thumb = QLabel("⚪")
            lbl_thumb.setFixedSize(34, 34)
            lbl_thumb.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(lbl_thumb)

            species = int(mon.get("species", 0))
            if species > 0:
                urls = pokemon_front_urls(species)
                self.party_thumb_urls[idx] = urls[0]
                self.party_thumb_labels[idx] = lbl_thumb
                self.image_loader.fetch(urls[0], urls[1:])

            info_col = QVBoxLayout()
            info_col.setSpacing(2)
            status_tag = f" [{mon['status']}]" if mon.get("status") else ""
            lbl_title = QLabel(f"{mon['nickname']} Lv{mon['level']}{status_tag}")
            lbl_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_title.setStyleSheet("color: #1e293b; border: none;")
            info_col.addWidget(lbl_title)

            hp_bar = QProgressBar()
            hp_bar.setRange(0, max(1, int(mon.get("max_hp", 1))))
            hp_bar.setValue(int(mon.get("hp", 0)))
            hp_bar.setFixedHeight(10)
            hp_bar.setFormat(f"{mon.get('hp', 0)}/{mon.get('max_hp', 1)}")
            info_col.addWidget(hp_bar)
            row_layout.addLayout(info_col, stretch=1)

            btn_send = QPushButton("Active" if idx == active_idx else ("Fainted" if mon.get("fainted") else "Switch"))
            btn_send.setFixedWidth(68)
            can_switch = (idx != active_idx) and not mon.get("fainted", False)
            btn_send.setEnabled(can_switch)
            btn_send.setStyleSheet(
                "background-color: #16a34a; color: #ffffff; font-weight: bold; border-radius: 4px; padding: 4px;"
                if can_switch else
                "background-color: #cbd5e1; color: #475569; border-radius: 4px; padding: 4px;"
            )
            btn_send.clicked.connect(lambda _, s_idx=idx: self._submit_switch(s_idx))
            row_layout.addWidget(btn_send)

            self.switch_list_layout.addWidget(row_frame)

    def _on_sprite_loaded(self, url: str, pixmap: QPixmap) -> None:
        if url == self.player_sprite_url:
            self.stage.set_player_sprite(pixmap)
        if url == self.opp_sprite_url:
            self.stage.set_opponent_sprite(pixmap)
        for idx, thumb_url in self.party_thumb_urls.items():
            if thumb_url == url and idx in self.party_thumb_labels:
                scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.FastTransformation)
                self.party_thumb_labels[idx].setPixmap(scaled)

    def set_bag_items(self, bag_items: List[Tuple[int, int, str]]) -> None:
        self._bag_items = list(bag_items)
        if self.menu_stack.currentIndex() == 5:
            self._populate_bag_items_list()

    def _open_bag_menu(self) -> None:
        self._populate_bag_items_list()
        self.menu_stack.setCurrentIndex(5)

    def _populate_bag_items_list(self) -> None:
        while self.bag_list_layout.count():
            item = self.bag_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        usable = []
        for item_id, qty, name in self._bag_items:
            eff = get_battle_item_effect(item_id)
            if eff and qty > 0:
                usable.append((item_id, qty, eff))

        if not usable:
            lbl_empty = QLabel("No usable battle items in your in-game Bag\n(Potions, Status Heals, Revives, X-Items).")
            lbl_empty.setWordWrap(True)
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setStyleSheet("color: #64748b; padding: 12px;")
            self.bag_list_layout.addWidget(lbl_empty)
            return

        for item_id, qty, eff in usable:
            btn = QPushButton(f"{eff.name}  x{qty}\n{eff.description}")
            btn.setStyleSheet(
                "QPushButton { background-color: #ffffff; color: #1e293b; text-align: left; "
                "border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; font-size: 10px; font-weight: bold; }"
                "QPushButton:hover { border: 2px solid #d97706; background-color: #fffbeb; }"
            )
            btn.clicked.connect(lambda _, iid=item_id: self._open_item_target_picker(iid))
            self.bag_list_layout.addWidget(btn)

    def _is_item_applicable(self, eff, mon: Dict[str, Any], is_active: bool) -> bool:
        fainted = mon.get("fainted", False)
        if eff.revive_ratio > 0:
            return fainted
        if fainted:
            return False
        if eff.stat_boosts:
            return is_active
        needs_hp = (eff.full_hp or eff.heal_hp > 0) and mon.get("hp", 0) < mon.get("max_hp", 1)
        needs_status = bool(mon.get("status")) and mon.get("status") in eff.cures_statuses
        needs_pp = eff.restore_pp > 0 and any(m.get("pp", 0) < m.get("max_pp", 1) for m in mon.get("moves", []))
        return needs_hp or needs_status or needs_pp or eff.cures_confusion

    def _open_item_target_picker(self, item_id: int) -> None:
        eff = get_battle_item_effect(item_id)
        if not eff:
            return
        self._selected_item_id = item_id
        self.lbl_bag_target_hdr.setText(f"Use {eff.name} on which Pokémon?")

        while self.bag_target_layout.count():
            item = self.bag_target_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        you_view = self.current_state.get("you", {})
        active_idx = you_view.get("active_index", 0)
        team = you_view.get("team", [])

        for idx, mon in enumerate(team):
            can_use = self._is_item_applicable(eff, mon, idx == active_idx)
            status_tag = f" [{mon['status']}]" if mon.get("status") else (" [FNT]" if mon.get("fainted") else "")
            btn = QPushButton(f"{mon['nickname']} Lv{mon['level']}{status_tag} — {mon['hp']}/{mon['max_hp']} HP")
            btn.setEnabled(can_use)
            btn.setStyleSheet(
                "QPushButton { background-color: #ffffff; color: #1e293b; text-align: left; font-weight: bold; "
                "border: 1px solid #cbd5e1; border-radius: 5px; padding: 6px; font-size: 10px; }"
                "QPushButton:hover { border: 2px solid #16a34a; background-color: #f0fdf4; }"
                "QPushButton:disabled { background-color: #e2e8f0; color: #94a3b8; }"
            )
            btn.clicked.connect(lambda _, t_idx=idx, iid=item_id: self._submit_item(iid, t_idx))
            self.bag_target_layout.addWidget(btn)

        self.menu_stack.setCurrentIndex(6)

    def _open_switch_menu(self) -> None:
        self.btn_switch_back.setVisible(True)
        self.menu_stack.setCurrentIndex(2)

    def _toggle_history_view(self) -> None:
        show_hist = not self.txt_history.isVisible()
        self.txt_history.setVisible(show_hist)
        self.lbl_dialog.setVisible(not show_hist)
        self.btn_log.setText("💬 Back to Battle Dialog" if show_hist else "📜 View Battle Log")

    def _submit_fight(self, move_index: int) -> None:
        if not self.battle_id:
            return
        self.menu_stack.setCurrentIndex(3)
        opp_name = self.current_state.get("opponent", {}).get("trainer_name", "Opponent")
        self.lbl_waiting.setText(f"⏳ Move chosen! Waiting for {opp_name}...")
        self.action_submitted.emit(self.battle_id, "FIGHT", move_index, 0, 0, 0)

    def _submit_switch(self, switch_index: int) -> None:
        if not self.battle_id:
            return
        self.menu_stack.setCurrentIndex(3)
        opp_name = self.current_state.get("opponent", {}).get("trainer_name", "Opponent")
        self.lbl_waiting.setText(f"⏳ Switch chosen! Waiting for {opp_name}...")
        self.action_submitted.emit(self.battle_id, "SWITCH", 0, switch_index, 0, 0)

    def _submit_item(self, item_id: int, target_index: int) -> None:
        if not self.battle_id:
            return
        self.menu_stack.setCurrentIndex(3)
        opp_name = self.current_state.get("opponent", {}).get("trainer_name", "Opponent")
        self.lbl_waiting.setText(f"⏳ Using item... Waiting for {opp_name}...")
        self.action_submitted.emit(self.battle_id, "ITEM", 0, 0, item_id, target_index)

    def _confirm_forfeit(self) -> None:
        reply = QMessageBox.question(
            self,
            "Forfeit Battle?",
            "Are you sure you want to forfeit this PvP battle?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes and self.battle_id:
            self.action_submitted.emit(self.battle_id, "FORFEIT", 0, 0, 0, 0)

