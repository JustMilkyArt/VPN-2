"""
Главное окно VPN клиента.
PyQt6 — тёмная тема, список подключений, Connect/Disconnect.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame,
    QMessageBox, QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QCursor

import logging
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Воркер — connect/disconnect в отдельном потоке чтобы не вешать UI
# ─────────────────────────────────────────────────────────────────────────────

class _Worker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, vpn_manager, conn, action):
        super().__init__()
        self.vpn_manager = vpn_manager
        self.conn = conn
        self.action = action   # "connect" | "disconnect"

    def run(self):
        if self.action == "connect":
            ok, msg = self.vpn_manager.connect(self.conn)
            self.done.emit(ok, msg)
        else:
            self.vpn_manager.disconnect()
            self.done.emit(True, "Отключено")


# ─────────────────────────────────────────────────────────────────────────────
# Карточка одного подключения
# ─────────────────────────────────────────────────────────────────────────────

PROTO_COLOR = {
    "vless_reality": "#6C63FF",
    "amnezia_wg":    "#00BFA5",
    "naive_proxy":   "#FF8C42",
}
PROTO_LABEL = {
    "vless_reality": "VLESS Reality",
    "amnezia_wg":    "AmneziaWG",
    "naive_proxy":   "NaiveProxy",
}
TYPE_LABEL = {
    "direct":  "Direct",
    "cascade": "Cascade",
}


class ConnectionCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, conn: dict, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.selected = False
        self._build()
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def _build(self):
        self.setFixedHeight(72)
        self._apply_style(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(12)

        # цветная точка протокола
        proto = self.conn.get("protocol", "")
        color = PROTO_COLOR.get(proto, "#888")
        dot = QLabel("●")
        dot.setFixedWidth(18)
        dot.setFont(QFont("Segoe UI", 16))
        dot.setStyleSheet(f"color: {color}; background: transparent;")
        row.addWidget(dot)

        # текст
        col = QVBoxLayout()
        col.setSpacing(3)

        name = self.conn.get("client_name", "Unknown")
        lbl_name = QLabel(name)
        lbl_name.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        lbl_name.setStyleSheet("color: #EAEAEA; background: transparent;")
        col.addWidget(lbl_name)

        proto_txt = PROTO_LABEL.get(proto, proto)
        type_txt  = TYPE_LABEL.get(self.conn.get("connection_type", ""), "")
        port_txt  = str(self.conn.get("port", ""))
        sub = QLabel(f"{proto_txt}  ·  {type_txt}  ·  :{port_txt}")
        sub.setFont(QFont("Segoe UI", 8))
        sub.setStyleSheet("color: #666; background: transparent;")
        col.addWidget(sub)

        row.addLayout(col)
        row.addStretch()

        # маршрут для cascade: флаги RU→EU
        if self.conn.get("connection_type") == "cascade" and self.conn.get("ru_server"):
            ru_flag = self.conn["ru_server"].get("flag_emoji", "🇷🇺")
            eu_flag = self.conn["server"].get("flag_emoji", "🌐")
            lbl_route = QLabel(f"{ru_flag}→{eu_flag}")
            lbl_route.setFont(QFont("Segoe UI", 12))
            lbl_route.setStyleSheet("background: transparent; color: #888;")
            row.addWidget(lbl_route)

        # зелёная точка — активно
        self.dot_active = QLabel("⬤")
        self.dot_active.setFont(QFont("Segoe UI", 10))
        self.dot_active.setStyleSheet("color: #00E676; background: transparent;")
        self.dot_active.setVisible(False)
        row.addWidget(self.dot_active)

    def _apply_style(self, selected: bool):
        if selected:
            self.setStyleSheet("""
                QFrame {
                    background: #1B2640;
                    border: 1.5px solid #6C63FF;
                    border-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background: #181D2B;
                    border: 1px solid #252B3B;
                    border-radius: 10px;
                }
                QFrame:hover { background: #1E2438; border-color: #353D5A; }
            """)

    def set_selected(self, v: bool):
        self.selected = v
        self._apply_style(v)
        self.dot_active.setVisible(v and False)   # скрыто пока не подключены

    def set_active(self, v: bool):
        self.dot_active.setVisible(v)

    def mousePressEvent(self, _event):
        self.clicked.emit(self.conn)


# ─────────────────────────────────────────────────────────────────────────────
# Заголовок группы серверов
# ─────────────────────────────────────────────────────────────────────────────

class GroupHeader(QLabel):
    def __init__(self, flag: str, name: str):
        super().__init__(f"  {flag}  {name.upper()}")
        self.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.setStyleSheet("color: #555; padding: 12px 6px 4px 4px; letter-spacing: 1.5px;")


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, vpn_manager, api_client):
        super().__init__()
        self.vpn = vpn_manager
        self.api = api_client
        self.cards: dict[int, ConnectionCard] = {}
        self.selected_conn: dict | None = None
        self._worker: _Worker | None = None

        self.setWindowTitle("VPN Client")
        self.setMinimumSize(440, 680)
        self.setMaximumWidth(540)
        self._apply_theme()
        self._build_ui()
        self._load()

        # Периодическая проверка соединения
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_alive)
        self._timer.start(4000)

    # ── тема ─────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #10131E; color: #EAEAEA;
                font-family: 'Segoe UI', Arial, sans-serif; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: #181D2B; width: 5px; border-radius: 2px; }
            QScrollBar::handle:vertical { background: #353D5A; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    # ── построение UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(16, 16, 16, 14)
        vbox.setSpacing(0)

        # ── шапка ─────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(4, 0, 4, 14)

        ico = QLabel("🔒")
        ico.setFont(QFont("Segoe UI", 22))
        hdr.addWidget(ico)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        t1 = QLabel("VPN Client")
        t1.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        t1.setStyleSheet("color: #FFF;")
        t2 = QLabel("Secure connections")
        t2.setFont(QFont("Segoe UI", 8))
        t2.setStyleSheet("color: #555;")
        titles.addWidget(t1)
        titles.addWidget(t2)
        hdr.addLayout(titles)
        hdr.addStretch()

        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedSize(34, 34)
        btn_refresh.setToolTip("Обновить список")
        btn_refresh.setStyleSheet("""
            QPushButton { background:#181D2B; color:#777; border:1px solid #252B3B;
                border-radius:8px; font-size:17px; }
            QPushButton:hover { color:#FFF; background:#1E2438; }
        """)
        btn_refresh.clicked.connect(self._load)
        hdr.addWidget(btn_refresh)
        vbox.addLayout(hdr)

        # ── статус-карточка ───────────────────────────────────────────────
        self.status_card = QFrame()
        self.status_card.setFixedHeight(82)
        self._status_style("idle")
        sc_row = QHBoxLayout(self.status_card)
        sc_row.setContentsMargins(18, 0, 18, 0)
        sc_row.setSpacing(14)

        self.lbl_dot = QLabel("⬤")
        self.lbl_dot.setFont(QFont("Segoe UI", 20))
        self.lbl_dot.setStyleSheet("color: #333;")
        sc_row.addWidget(self.lbl_dot)

        sc_col = QVBoxLayout()
        sc_col.setSpacing(2)
        self.lbl_status = QLabel("Не подключено")
        self.lbl_status.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet("color: #888;")
        self.lbl_detail = QLabel("Выберите подключение ниже")
        self.lbl_detail.setFont(QFont("Segoe UI", 8))
        self.lbl_detail.setStyleSheet("color: #555;")
        sc_col.addWidget(self.lbl_status)
        sc_col.addWidget(self.lbl_detail)
        sc_row.addLayout(sc_col)
        sc_row.addStretch()
        vbox.addWidget(self.status_card)
        vbox.addSpacing(14)

        # ── кнопки ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_connect = QPushButton("  Подключиться")
        self.btn_connect.setFixedHeight(48)
        self.btn_connect.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.btn_connect.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #6C63FF, stop:1 #8B5CF6);
                color:#FFF; border:none; border-radius:10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #7D75FF, stop:1 #9C6DF7);
            }
            QPushButton:disabled { background:#1E2438; color:#444; }
            QPushButton:pressed  { background:#5A52EF; }
        """)
        self.btn_connect.setEnabled(False)
        self.btn_connect.clicked.connect(self._on_connect)

        self.btn_disconnect = QPushButton("  Отключиться")
        self.btn_disconnect.setFixedHeight(48)
        self.btn_disconnect.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.btn_disconnect.setStyleSheet("""
            QPushButton {
                background:#181D2B; color:#FF5252;
                border:1.5px solid #FF5252; border-radius:10px;
            }
            QPushButton:hover { background:#2A0808; }
            QPushButton:disabled { color:#333; border-color:#252B3B; }
            QPushButton:pressed  { background:#3A0A0A; }
        """)
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._on_disconnect)

        btn_row.addWidget(self.btn_connect)
        btn_row.addWidget(self.btn_disconnect)
        vbox.addLayout(btn_row)
        vbox.addSpacing(18)

        # ── список подключений ────────────────────────────────────────────
        sec_lbl = QLabel("ПОДКЛЮЧЕНИЯ")
        sec_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        sec_lbl.setStyleSheet("color: #3A3A4A; letter-spacing:2px; padding-left:4px;")
        vbox.addWidget(sec_lbl)
        vbox.addSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_w = QWidget()
        self.list_lay = QVBoxLayout(self.list_w)
        self.list_lay.setSpacing(6)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.addStretch()
        scroll.setWidget(self.list_w)
        vbox.addWidget(scroll)

        # ── футер ─────────────────────────────────────────────────────────
        footer = QLabel("VLESS Reality  ·  AmneziaWG  ·  NaiveProxy")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(QFont("Segoe UI", 7))
        footer.setStyleSheet("color: #2A2A3A; padding-top:8px;")
        vbox.addWidget(footer)

    # ── загрузка подключений ──────────────────────────────────────────────────

    def _load(self):
        self.lbl_detail.setText("Загрузка…")
        conns = self.api.get_connections()
        self._rebuild_list(conns)
        n = len(conns)
        self.lbl_detail.setText(f"{n} подключений доступно" if n else "Нет подключений")

    def _rebuild_list(self, conns: list):
        # чистим список
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.cards.clear()

        if not conns:
            empty = QLabel("Не удалось загрузить подключения.\nПроверьте соединение с сервером.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color:#444; padding:40px;")
            self.list_lay.insertWidget(0, empty)
            return

        # группируем по EU серверу
        groups: dict[int, dict] = {}
        order: list[int] = []
        for c in conns:
            sid = c["server"]["id"]
            if sid not in groups:
                groups[sid] = {"server": c["server"], "conns": []}
                order.append(sid)
            groups[sid]["conns"].append(c)

        idx = 0
        for sid in order:
            srv = groups[sid]["server"]
            flag = srv.get("flag_emoji", "🌐")
            name = srv.get("display_name") or srv.get("name", "?")

            hdr = GroupHeader(flag, name)
            self.list_lay.insertWidget(idx, hdr); idx += 1

            for c in groups[sid]["conns"]:
                card = ConnectionCard(c)
                card.clicked.connect(self._on_card)
                self.cards[c["id"]] = card
                self.list_lay.insertWidget(idx, card); idx += 1

    # ── события ───────────────────────────────────────────────────────────────

    def _on_card(self, conn: dict):
        # снимаем выделение с предыдущей
        if self.selected_conn:
            old = self.cards.get(self.selected_conn["id"])
            if old:
                old.set_selected(False)

        self.selected_conn = conn
        card = self.cards.get(conn["id"])
        if card:
            card.set_selected(True)

        if not self.vpn.is_connected():
            self.btn_connect.setEnabled(True)

    def _on_connect(self):
        if not self.selected_conn:
            return
        self._set_busy(True)
        self._status("connecting")
        self.lbl_detail.setText(self.selected_conn.get("client_name", ""))

        self._worker = _Worker(self.vpn, self.selected_conn, "connect")
        self._worker.done.connect(self._on_connect_done)
        self._worker.start()

    def _on_disconnect(self):
        self._set_busy(True)
        self._status("connecting")
        self.lbl_status.setText("Отключение…")

        self._worker = _Worker(self.vpn, None, "disconnect")
        self._worker.done.connect(self._on_disconnect_done)
        self._worker.start()

    def _on_connect_done(self, ok: bool, msg: str):
        self._set_busy(False)
        if ok:
            self._status("connected")
            self.lbl_status.setText("Подключено")
            self.lbl_detail.setText(self.selected_conn.get("client_name", ""))
            self.btn_disconnect.setEnabled(True)
            self.btn_connect.setEnabled(False)
            # подсветить активную карточку
            card = self.cards.get(self.selected_conn["id"])
            if card:
                card.set_active(True)
            QMessageBox.information(self, "Подключено", msg)
        else:
            self._status("error")
            self.lbl_status.setText("Ошибка подключения")
            self.lbl_detail.setText("Попробуйте другое подключение")
            self.btn_connect.setEnabled(True)
            QMessageBox.critical(self, "Ошибка", msg)

    def _on_disconnect_done(self, _ok: bool, _msg: str):
        self._set_busy(False)
        self._status("idle")
        self.lbl_status.setText("Не подключено")
        self.lbl_detail.setText("Выберите подключение ниже")
        self.btn_disconnect.setEnabled(False)
        self.btn_connect.setEnabled(bool(self.selected_conn))
        # убираем активную точку со всех карточек
        for c in self.cards.values():
            c.set_active(False)

    def _check_alive(self):
        """Если соединение упало само — обновить UI."""
        if self.vpn.active_conn and not self.vpn.is_connected():
            self.vpn.active_conn  = None
            self.vpn.active_proto = None
            self._status("error")
            self.lbl_status.setText("Соединение потеряно")
            self.lbl_detail.setText("Переподключитесь")
            self.btn_disconnect.setEnabled(False)
            self.btn_connect.setEnabled(bool(self.selected_conn))
            for c in self.cards.values():
                c.set_active(False)

    # ── вспомогательные ───────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        self.btn_connect.setEnabled(not busy)
        self.btn_disconnect.setEnabled(not busy)
        for c in self.cards.values():
            c.setEnabled(not busy)

    def _status(self, state: str):
        """state: idle | connecting | connected | error"""
        if state == "idle":
            self.lbl_dot.setStyleSheet("color:#333;")
            self._status_style("idle")
            self.lbl_status.setStyleSheet("color:#888;")
        elif state == "connecting":
            self.lbl_dot.setStyleSheet("color:#FFA726;")
            self._status_style("connecting")
            self.lbl_status.setStyleSheet("color:#FFA726;")
            self.lbl_status.setText("Подключение…")
        elif state == "connected":
            self.lbl_dot.setStyleSheet("color:#00E676;")
            self._status_style("connected")
            self.lbl_status.setStyleSheet("color:#00E676;")
        elif state == "error":
            self.lbl_dot.setStyleSheet("color:#FF5252;")
            self._status_style("error")
            self.lbl_status.setStyleSheet("color:#FF5252;")

    def _status_style(self, state: str):
        borders = {
            "idle":       "#252B3B",
            "connecting": "#FFA726",
            "connected":  "#00E676",
            "error":      "#FF5252",
        }
        bgs = {
            "idle":       "stop:0 #181D2B, stop:1 #10131E",
            "connecting": "stop:0 #1A1500, stop:1 #10131E",
            "connected":  "stop:0 #0A2010, stop:1 #10131E",
            "error":      "stop:0 #200808, stop:1 #10131E",
        }
        border = borders.get(state, "#252B3B")
        bg     = bgs.get(state, "stop:0 #181D2B, stop:1 #10131E")
        self.status_card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, {bg});
                border: 1.5px solid {border};
                border-radius: 12px;
            }}
        """)

    def closeEvent(self, event):
        self.vpn.disconnect()
        event.accept()
