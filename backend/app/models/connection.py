from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.db.database import Base


class Protocol(str, enum.Enum):
    VLESS_REALITY = "vless_reality"
    AMNEZIA_WG    = "amnezia_wg"
    NAIVE_PROXY   = "naive_proxy"
    TROJAN        = "trojan"


class ConnectionType(str, enum.Enum):
    DIRECT  = "direct"   # клиент → EU
    CASCADE = "cascade"  # клиент → RU → EU


class ConnectionStatus(str, enum.Enum):
    ACTIVE    = "active"
    INACTIVE  = "inactive"
    DEPLOYING = "deploying"
    ERROR     = "error"


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = {"extend_existing": True}

    id         = Column(Integer, primary_key=True, index=True)
    server_id  = Column(Integer, ForeignKey("servers.id"), nullable=False)   # EU сервер (выходной)
    ru_server_id = Column(Integer, ForeignKey("servers.id"), nullable=True)  # RU сервер (только для cascade)

    # тип и протокол
    connection_type = Column(String(10), nullable=False, default=ConnectionType.DIRECT)  # direct|cascade
    protocol        = Column(String(30), nullable=False)
    port            = Column(Integer, nullable=False)

    # VLESS + Reality
    uuid                 = Column(String(36),  nullable=True)
    reality_public_key   = Column(String(255), nullable=True)
    reality_private_key  = Column(String(255), nullable=True)
    reality_short_id     = Column(String(32),  nullable=True)
    reality_server_name  = Column(String(255), nullable=True, default="www.microsoft.com")
    reality_fingerprint  = Column(String(32),  nullable=True, default="chrome")

    # AmneziaWG
    wg_private_key        = Column(String(255), nullable=True)
    wg_public_key         = Column(String(255), nullable=True)
    wg_preshared_key      = Column(String(255), nullable=True)
    wg_client_private_key = Column(String(255), nullable=True)
    wg_client_public_key  = Column(String(255), nullable=True)
    wg_client_ip          = Column(String(20),  nullable=True)
    awg_junk_packet_count    = Column(Integer, nullable=True, default=4)
    awg_junk_packet_min_size = Column(Integer, nullable=True, default=40)
    awg_junk_packet_max_size = Column(Integer, nullable=True, default=70)
    awg_s1   = Column(Integer, nullable=True, default=50)
    awg_s2   = Column(Integer, nullable=True, default=100)
    awg_h1   = Column(Integer, nullable=True, default=1)
    awg_h2   = Column(Integer, nullable=True, default=2)
    awg_h3   = Column(Integer, nullable=True, default=3)
    awg_h4   = Column(Integer, nullable=True, default=4)

    # NaiveProxy / Trojan
    password   = Column(String(255), nullable=True)
    np_domain  = Column(String(255), nullable=True)  # домен для NaiveProxy
    np_user    = Column(String(64),  nullable=True, default="vpnuser")

    # готовые конфиги для клиента
    client_link  = Column(Text, nullable=True)  # URI ссылка (vless://, naive+https://, awg://)
    config_text  = Column(Text, nullable=True)  # текстовый конфиг (.conf для AWG, JSON для NaiveProxy)
    config_qr    = Column(Text, nullable=True)  # base64 PNG QR-кода

    # сплит-тоннелинг
    split_tunnel_enabled = Column(Boolean, nullable=False, default=True)

    # WARP fallback
    warp_enabled = Column(Boolean, nullable=False, default=False)

    # статус и флаги
    status    = Column(String(20), nullable=False, default=ConnectionStatus.INACTIVE)
    is_active = Column(Boolean,   nullable=False, default=True)

    # прогресс создания
    setup_status = Column(String(20), nullable=True)   # pending|in_progress|done|failed
    setup_step   = Column(String(50), nullable=True)
    setup_log    = Column(Text, nullable=True)
    setup_error  = Column(Text, nullable=True)

    # ── Health monitoring (runtime) ─────────────────────────────────────────
    # Итоговый статус последнего health-check: HEALTHY|DEGRADED|BROKEN
    health_status        = Column(String(20),  nullable=True)
    # Время последней проверки
    last_check_at        = Column(DateTime(timezone=True), nullable=True)
    # Результат последней проверки (True=прошла без BROKEN)
    last_check_ok        = Column(Boolean, nullable=True)
    # Outbound IP с сервера (что видит ipify.org)
    last_outbound_ip     = Column(String(64),  nullable=True)
    # Геолокация outbound (страна/код)
    last_outbound_geo    = Column(String(64),  nullable=True)
    # TLS handshake статус: CONNECTED|REFUSED|TIMEOUT|UNAVAILABLE|UNKNOWN
    last_tls_status      = Column(String(32),  nullable=True)

    # ── Latency / jitter / packet loss ─────────────────────────────────────
    latency_ms           = Column(Float,   nullable=True)   # средняя задержка ping (мс)
    jitter_ms            = Column(Float,   nullable=True)   # jitter (мс)
    packet_loss_pct      = Column(Float,   nullable=True)   # потери пакетов (%)

    # ── Auto-recovery ──────────────────────────────────────────────────────
    # Статус последнего авто-рекавери: idle|recovering|recovered|failed
    recovery_status      = Column(String(20),  nullable=True)
    # Время последнего авто-рекавери
    last_recovery_at     = Column(DateTime(timezone=True), nullable=True)
    # Лог авто-рекавери (последние события)
    recovery_log         = Column(Text,        nullable=True)
    # Счётчик авто-рекавери за последние 24ч (anti-flap)
    recovery_count_24h   = Column(Integer, nullable=True, default=0)

    # ── Uptime tracking ────────────────────────────────────────────────────
    # Когда последний раз статус стал ACTIVE
    last_active_at       = Column(DateTime(timezone=True), nullable=True)
    # Суммарное время аптайма (секунды, накапливается)
    total_uptime_seconds = Column(Integer, nullable=True, default=0)

    # meta
    notes      = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    server    = relationship("Server", foreign_keys=[server_id],    back_populates="connections")
    ru_server = relationship("Server", foreign_keys=[ru_server_id])

    # legacy compat
    @property
    def name(self):
        proto_label = {
            "vless_reality": "VLESS+Reality",
            "amnezia_wg":    "AmneziaWG",
            "naive_proxy":   "NaiveProxy",
            "trojan":        "Trojan",
        }.get(self.protocol, self.protocol)
        t = "Каскад" if self.connection_type == "cascade" else "Прямое"
        return f"{proto_label} ({t})"

    @property
    def exit_server_id(self):
        return self.server_id

    def __repr__(self):
        return f"<Connection [{self.protocol}] {self.connection_type} port={self.port} {self.status}>"
