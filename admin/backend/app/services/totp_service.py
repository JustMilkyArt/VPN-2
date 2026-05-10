"""
TOTP service — generate, validate, bind, reset.
Uses pyotp + qrcode.
No security logic lives in the frontend.
"""
import io
import base64
import logging

import pyotp
import qrcode

logger = logging.getLogger(__name__)

APP_NAME = "VPN Admin"


def generate_totp_secret() -> str:
    """Generate a new random base32 TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str) -> str:
    """Build otpauth:// URI for QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=APP_NAME)


def generate_qr_base64(secret: str, username: str) -> str:
    """
    Generate QR code PNG as base64 data URI.
    Returns string: 'data:image/png;base64,<...>'.
    """
    uri = get_totp_uri(secret, username)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str) -> bool:
    """
    Verify a 6-digit TOTP code against a secret.
    Allows ±1 window (30-second drift tolerance).
    """
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
