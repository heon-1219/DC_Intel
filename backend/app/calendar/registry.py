"""Load + query the economic-event registry and sector map (economic-calendar.md §4, §6.3)."""
import functools
import re
from pathlib import Path

import yaml


@functools.lru_cache
def _load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_registry(path: str) -> dict:
    """{event_type: entry}."""
    return _load_yaml(path).get("events", {}) or {}


def load_mega_caps(path: str) -> list[str]:
    return [str(t) for t in (_load_yaml(path).get("mega_cap_high", []) or [])]


def load_sectors(path: str) -> dict:
    return _load_yaml(path).get("sectors", {}) or {}


def match_event_type(registry: dict, provider: str, raw_name: str) -> str | None:
    """Case-insensitive match of a provider's raw event name to a canonical event_type."""
    name = raw_name.strip().lower()
    for etype, entry in registry.items():
        for alias in (entry.get("provider_match", {}) or {}).get(provider, []) or []:
            if alias.strip().lower() == name:
                return etype
    return None


def auto_slug(country: str, raw_name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
    return f"{country.lower()}_{s}"


def sector_codes_for(sectors: dict, symbol: str, exchange: str) -> list[str]:
    """Sector codes whose members include this stock (matches bare 'NVDA' or '005930:KRX')."""
    needle = {symbol, f"{symbol}:{exchange}"}
    return [code for code, s in sectors.items()
            if needle & set(str(m) for m in (s.get("members", []) or []))]
