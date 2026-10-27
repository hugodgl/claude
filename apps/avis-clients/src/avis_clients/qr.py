"""Génération de QR codes (PNG et SVG) pointant vers la page publique d'avis."""
from __future__ import annotations

import io

import qrcode
from qrcode.image.svg import SvgPathImage


def _qr(data: str, box_size: int = 10, border: int = 2) -> qrcode.QRCode:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    return qr


def qr_png(data: str, box_size: int = 10, border: int = 2) -> bytes:
    img = _qr(data, box_size, border).make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_svg(data: str, border: int = 2) -> bytes:
    img = _qr(data, box_size=10, border=border).make_image(image_factory=SvgPathImage)
    return img.to_string()
