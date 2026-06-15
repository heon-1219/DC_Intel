"""Impact-level assignment in strict precedence order (economic-calendar.md §5)."""

_PROVIDER_SCALE = {3: "high", 2: "medium", 1: "low"}


def assign_impact(entry: dict | None, provider_importance: int | None) -> tuple[str, str]:
    """Returns (impact_level, impact_source). override > provider > default(low)."""
    if entry and entry.get("impact_override"):
        return entry["impact_override"], "override"
    if provider_importance in _PROVIDER_SCALE:
        return _PROVIDER_SCALE[provider_importance], "provider"
    return "low", "default"
