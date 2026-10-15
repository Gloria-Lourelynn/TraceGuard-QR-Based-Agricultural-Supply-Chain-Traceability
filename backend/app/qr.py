"""QR image generation (qrcode). Signing lives in security.py."""
from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_Q



def qr_png(payload: str) -> bytes:
    """PNG for an exact issued payload; error correction Q helps with field labels."""
    img = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=10, border=4)
    img.add_data(payload)
    img.make(fit=True)
    buf = io.BytesIO()
    img.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()
