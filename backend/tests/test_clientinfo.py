"""Prepoznavanje pregledača, OS-a i uređaja za audit prijava."""

from app.clientinfo import parse_user_agent, sanitize_client, summary

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


def test_browsers_and_os():
    assert parse_user_agent(CHROME_WIN) | {} == {
        "browser": "Chrome", "browser_version": "141.0.0.0", "os": "Windows", "os_version": "10 ili 11", "device": "računar"}
    edge = parse_user_agent(CHROME_WIN + " Edg/141.0.3537.57")
    assert edge["browser"] == "Edge" and edge["browser_version"] == "141.0.3537.57"
    iphone = parse_user_agent("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
                              "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1")
    assert (iphone["os"], iphone["os_version"], iphone["device"], iphone["browser"]) == ("iOS", "18.1", "telefon", "Safari")
    android = parse_user_agent("Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/141.0.0.0 Mobile Safari/537.36")
    assert (android["os"], android["device"]) == ("Android", "telefon")
    firefox = parse_user_agent("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    assert (firefox["browser"], firefox["os"]) == ("Firefox", "Linux")
    assert parse_user_agent("curl/8.5.0")["device"] == "program/skripta"


def test_sanitize_client_drops_unknown_and_trims():
    data = sanitize_client({"screen": "1920x1080", "cores": "8", "password": "tajna", "timezone": "x" * 500, "mobile": 0})
    assert data == {"screen": "1920x1080", "cores": 8, "timezone": "x" * 120, "mobile": False}
    assert sanitize_client(None) == {}


def test_summary():
    info = {"browser": "Chrome", "browser_version": "141.0.0.0", "os": "Windows", "os_version": "11",
            "device": "računar", "ip": "192.168.88.48", "hostname": "pc-zoran.lan"}
    assert summary(info) == "Chrome 141 · Windows 11 · računar · pc-zoran.lan (192.168.88.48)"
    assert summary({"ip": "10.0.0.1"}) == "10.0.0.1"
