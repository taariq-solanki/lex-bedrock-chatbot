"""
Root conftest.py - applies workarounds needed before pytest plugins load.

Fixes a broken pydantic 1.x entry point that references a non-existent
hypothesis plugin module, which prevents hypothesis from importing.
"""

import importlib.metadata

_original_entry_points = importlib.metadata.entry_points


def _patched_entry_points(**kwargs):
    eps = _original_entry_points(**kwargs)
    if kwargs.get("group") == "hypothesis":
        return [ep for ep in eps if "pydantic" not in ep.value]
    return eps


importlib.metadata.entry_points = _patched_entry_points
