"""Faza 5: tačnost vremena, zakazani izveštaji, kanali (bez mreže)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app import schedules
from app.health import merge_thresholds, system_conditions
from app.notify import channels

TH = merge_thresholds(None)
TZ = ZoneInfo("Europe/Belgrade")


def rules(conds):
    return {c.rule: c for c in conds}


def test_time_ok_and_offsets():
    assert system_conditions({"offset_ms": 120.0, "host_synchronized": True, "ntp_server": "pool.ntp.org"}, TH) == []
    warn = rules(system_conditions({"offset_ms": -3500.0, "ntp_server": "pool.ntp.org"}, TH))["time_offset"]
    assert warn.severity == "warning" and warn.device_id is None and "-3500" in warn.message
    crit = rules(system_conditions({"offset_ms": 45000.0, "ntp_server": "x"}, TH))["time_offset"]
    assert crit.severity == "critical"


def test_time_unreachable_and_unsynced():
    r = rules(system_conditions({"error": "NTP server x nije odgovorio: timed out", "host_synchronized": False}, TH))
    assert r["ntp_unreachable"].severity == "warning" and r["time_unsynced"].severity == "warning"


def test_schedule_due():
    base = {"enabled": True, "period": "weekly", "hour": 7, "weekday": 1}
    monday7 = datetime(2026, 10, 26, 7, 5, tzinfo=TZ)
    assert schedules.due(base, monday7)
    assert not schedules.due(base, datetime(2026, 10, 27, 7, 5, tzinfo=TZ))  # utorak
    assert not schedules.due(base, datetime(2026, 10, 26, 8, 5, tzinfo=TZ))  # drugi sat
    assert not schedules.due({**base, "enabled": False}, monday7)
    assert not schedules.due({**base, "last_sent_at": datetime(2026, 10, 26, 7, 0, tzinfo=TZ).isoformat()}, monday7)
    assert schedules.due({"enabled": True, "period": "daily", "hour": 7}, monday7)
    assert schedules.due({"enabled": True, "period": "monthly", "hour": 7}, datetime(2026, 11, 1, 7, 5, tzinfo=TZ))
    assert not schedules.due({"enabled": True, "period": "monthly", "hour": 7}, monday7)


def test_channels_public_hides_secrets():
    cfg = channels.merged({"telegram": {"enabled": True, "bot_token_enc": "gAAAA-sifrovano", "chat_id": "123"}})
    pub = channels.public(cfg)
    assert pub["telegram"]["has_bot_token"] is True and "bot_token_enc" not in pub["telegram"]
    assert pub["pushover"]["has_app_token"] is False and pub["webhook"]["enabled"] is False


def test_channel_validation_without_network():
    import pytest

    with pytest.raises(channels.ChannelError):
        channels._send_sync("telegram", channels.DEFAULTS["telegram"], "t", "b", None, "info", None)
    with pytest.raises(channels.ChannelError):
        channels._send_sync("webhook", {"url": "ftp://x"}, "t", "b", None, "info", None)
