"""Shared FalconX rate schedule loader.

Single source of truth for loan notice rates. Both the updater and
the xlsx importer read from config/falconx_rates.json via this module.
"""

import json
import os
from datetime import datetime, timezone

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'config', 'falconx_rates.json')

_SCHEDULE = None
_FEE_MULTIPLIER = None


def _load():
    """Load and cache the rate schedule from config."""
    global _SCHEDULE, _FEE_MULTIPLIER
    if _SCHEDULE is not None:
        return

    with open(_CONFIG_PATH) as f:
        cfg = json.load(f)

    fee_pct = float(cfg["performance_fee_pct"])
    _FEE_MULTIPLIER = 1.0 - fee_pct

    _SCHEDULE = []
    for entry in cfg["rate_schedule"]:
        start = datetime.fromisoformat(entry["start"].replace("Z", "+00:00"))
        gross = float(entry["gross_rate"])
        _SCHEDULE.append((start, gross))


def get_net_rate(ts):
    """Get net rate for a given UTC timestamp from the loan notice schedule.

    Net rate = gross_rate × (1 - performance_fee_pct).
    """
    _load()
    rate = _SCHEDULE[0][1]
    for start, r in _SCHEDULE:
        if ts >= start:
            rate = r
    return rate * _FEE_MULTIPLIER


def get_rate_schedule():
    """Return the full rate schedule as list of (start_datetime, gross_rate)."""
    _load()
    return list(_SCHEDULE)


def reload():
    """Force reload from config (used after config changes)."""
    global _SCHEDULE, _FEE_MULTIPLIER
    _SCHEDULE = None
    _FEE_MULTIPLIER = None
    _load()
