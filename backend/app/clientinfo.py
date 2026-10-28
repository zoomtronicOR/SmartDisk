"""Podaci o računaru i pregledaču sa kog se korisnik prijavljuje (za audit log).

Server vidi samo IP adresu i User-Agent; ime računara se pokušava dobiti obrnutim DNS upitom (radi samo ako
lokalni DNS/ruter zna imena uređaja). Ostalo (ekran, jezik, zona, broj jezgara, verzija OS-a preko Client Hints)
šalje sam pregledač pri prijavi. MAC adresa i korisničko ime na računaru nisu dostupni web aplikaciji.
"""

import asyncio
import re
import socket
from typing import Any

from fastapi import Request

from .audit import client_ip

# Polja koja pregledač sme da pošalje (sve ostalo se odbacuje); vrednosti se skraćuju.
CLIENT_FIELDS = {
    "platform": str, "platform_version": str, "architecture": str, "bitness": str, "model": str, "mobile": bool,
    "browser_full": str, "screen": str, "pixel_ratio": float, "viewport": str, "color_depth": int, "timezone": str,
    "language": str, "languages": str, "cores": int, "memory_gb": float, "touch_points": int, "color_scheme": str,
    "cookies": bool, "online": bool,
}


def sanitize_client(raw: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, kind in CLIENT_FIELDS.items():
        value = (raw or {}).get(key)
        if value is None:
            continue
        try:
            if kind is str:
                out[key] = str(value)[:120]
            elif kind is bool:
                out[key] = bool(value)
            elif kind is int:
                out[key] = int(value)
            else:
                out[key] = round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return out


_BROWSERS = [  # redosled je bitan: Edge i Opera sadrže i „Chrome”
    ("Edge", r"Edg(?:e|A|iOS)?/([\d.]+)"),
    ("Opera", r"(?:OPR|Opera)/([\d.]+)"),
    ("Vivaldi", r"Vivaldi/([\d.]+)"),
    ("Samsung Internet", r"SamsungBrowser/([\d.]+)"),
    ("Firefox", r"(?:Firefox|FxiOS)/([\d.]+)"),
    ("Chrome", r"(?:Chrome|CriOS)/([\d.]+)"),
    ("Safari", r"Version/([\d.]+).*Safari/"),
]
_WINDOWS = {"10.0": "10 ili 11", "6.3": "8.1", "6.2": "8", "6.1": "7"}


def parse_user_agent(ua: str) -> dict[str, Any]:
    info: dict[str, Any] = {"browser": None, "browser_version": None, "os": None, "os_version": None, "device": "računar"}
    for name, pattern in _BROWSERS:
        m = re.search(pattern, ua)
        if m:
            info["browser"], info["browser_version"] = name, m.group(1)
            break
    if m := re.search(r"Windows NT ([\d.]+)", ua):
        info["os"], info["os_version"] = "Windows", _WINDOWS.get(m.group(1), m.group(1))
    elif m := re.search(r"Android ([\d.]+)", ua):
        info["os"], info["os_version"] = "Android", m.group(1)
        info["device"] = "telefon" if "Mobile" in ua else "tablet"
    elif m := re.search(r"(iPhone|iPad).*OS ([\d_]+)", ua):
        info["os"], info["os_version"] = "iOS" if m.group(1) == "iPhone" else "iPadOS", m.group(2).replace("_", ".")
        info["device"] = "telefon" if m.group(1) == "iPhone" else "tablet"
    elif m := re.search(r"Mac OS X ([\d_]+)", ua):
        info["os"], info["os_version"] = "macOS", m.group(1).replace("_", ".")
    elif "CrOS" in ua:
        info["os"] = "ChromeOS"
    elif "Linux" in ua:
        info["os"] = "Linux"
    if re.search(r"bot|crawler|spider|curl|wget|python-requests|httpx", ua, re.I):
        info["device"] = "program/skripta"
    return info


async def _reverse_dns(ip: str) -> str | None:
    try:
        host, _ = await asyncio.wait_for(asyncio.get_running_loop().getnameinfo((ip, 0), socket.NI_NAMEREQD), 1.5)
        return host
    except (OSError, TimeoutError, socket.gaierror):
        return None


async def collect(request: Request, client: dict[str, Any] | None) -> dict[str, Any]:
    """Sve što se zna o računaru: IP, ime (ako ga DNS zna), pregledač, OS, uređaj i podaci koje je poslao pregledač."""
    ip = client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:400]
    info = parse_user_agent(ua)
    extra = sanitize_client(client)
    # Client Hints (Chromium) daju tačnu verziju OS-a: Windows platformVersion ≥ 13 je Windows 11.
    if extra.get("platform") == "Windows" and extra.get("platform_version"):
        major = int((extra["platform_version"].split(".") or ["0"])[0] or 0)
        info["os_version"] = "11" if major >= 13 else "10" if major > 0 else info["os_version"]
    elif extra.get("platform") == "macOS" and extra.get("platform_version"):
        info["os_version"] = extra["platform_version"]
    if extra.get("browser_full"):
        info["browser_version"] = extra["browser_full"].split(" ")[-1] if " " in extra["browser_full"] else info["browser_version"]
    if extra.get("mobile") is True and info["device"] == "računar":
        info["device"] = "telefon"
    return {
        "ip": ip,
        "hostname": await _reverse_dns(ip) if ip else None,
        **info,
        "user_agent": ua,
        "client": extra or None,
        "proxy": request.headers.get("x-forwarded-for"),
    }


def summary(info: dict[str, Any]) -> str:
    """Kratak opis za listu: „Chrome 141 · Windows 11 · računar · PC-ZORAN (192.168.88.48)”."""
    parts = []
    if info.get("browser"):
        parts.append(f"{info['browser']} {str(info.get('browser_version') or '').split('.')[0]}".strip())
    if info.get("os"):
        parts.append(f"{info['os']} {info.get('os_version') or ''}".strip())
    if info.get("device"):
        parts.append(info["device"])
    where = info.get("ip") or "?"
    parts.append(f"{info['hostname']} ({where})" if info.get("hostname") else where)
    return " · ".join(parts)
