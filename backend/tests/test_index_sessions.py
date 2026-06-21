"""M8f — JP/DE index sessions + index_state(region) mapping (backend-design §6.8)."""
from datetime import datetime, timezone

from app.market.hours import index_state

# 2026-06-15 is a Monday (June -> JST=UTC+9 always, CEST=UTC+2, EDT=UTC-4).
def _utc(h, m=0, day=15):
    return datetime(2026, 6, day, h, m, tzinfo=timezone.utc)


def test_jp_index_open_morning_and_afternoon():
    assert index_state("JP", _utc(1)) == "open"     # 10:00 JST
    assert index_state("JP", _utc(5)) == "open"     # 14:00 JST


def test_jp_index_closed_during_lunch_and_after():
    assert index_state("JP", _utc(3)) == "closed"   # 12:00 JST (lunch)
    assert index_state("JP", _utc(7)) == "closed"   # 16:00 JST (after close)


def test_de_index_open_and_closed():
    assert index_state("DE", _utc(8)) == "open"     # 10:00 CEST
    assert index_state("DE", _utc(16)) == "closed"  # 18:00 CEST (after 17:30)


def test_kr_and_us_index_map_to_their_sessions():
    assert index_state("KR", _utc(1)) == "open"     # 10:00 KST
    assert index_state("US", _utc(14)) == "open"    # 10:00 EDT


def test_weekend_all_closed():
    sat = datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)   # Saturday
    for region in ("KR", "US", "JP", "DE"):
        assert index_state(region, sat) == "closed"


def test_unknown_region_closed():
    assert index_state("XX", _utc(8)) == "closed"
