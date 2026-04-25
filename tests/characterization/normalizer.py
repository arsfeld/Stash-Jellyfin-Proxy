"""Normalize volatile fields in proxy responses so diffs are stable.

The characterization tests care about structure and deterministic content —
not timestamps, session tokens, or per-request random selections. Strip
those before comparison.
"""
import copy
import re
from typing import Any, Optional

# Patterns for fields whose *values* are volatile but whose *presence* matters.
VOLATILE_KEYS = {
    "PlaySessionId",          # session-<ts>
    "DateLastAccessed",
    "LastLoginDate",
    "LastActivityDate",
    "DateCreated",            # stash-reported creation time
    "PremiereDate",           # varies if Stash rescans
    "StartDate",
    "EndDate",
    "PlaybackPositionTicks",  # varies with live resume state
    "UserData",               # contains position/watch state
    "RunTimeTicks",            # can shift when Stash refreshes file_info
    "Bitrate",
    "BitRate",
    "Size",
    "RealFrameRate",
    "AverageFrameRate",
    "Width",
    "Height",
    "AspectRatio",
    "DateModified",
    "Etag",
    "ImageTags",              # tag-hash changes when Stash re-derives
    "BackdropImageTags",
    "ImageBlurHashes",
    "PrimaryImageAspectRatio",
    "Path",                   # absolute paths may shift if Stash remounts
    "Version",                # stash version / proxy version strings
}

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?")


def _sort_key_for_item(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("Id") or item.get("Name") or "")
    return str(item)


def _normalize(value: Any, key: Optional[str] = None) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in VOLATILE_KEYS:
                out[k] = f"<{k.upper()}>"
            else:
                out[k] = _normalize(v, k)
        return out
    if isinstance(value, list):
        normalized = [_normalize(x) for x in value]
        # For "Items" arrays (and other list-of-identifiable-dicts), sort by
        # Id so characterization isn't sensitive to random/order-dependent
        # endpoints like NextUp, Resume, Latest. Structure + membership are
        # what we care about at this level.
        if key in ("Items", "SearchHints") and normalized and isinstance(normalized[0], dict):
            normalized = sorted(normalized, key=_sort_key_for_item)
        return normalized
    if isinstance(value, str) and ISO_DATE.search(value):
        return ISO_DATE.sub("<DATE>", value)
    return value


def normalize(payload: Any) -> Any:
    """Return a deep-copied, normalized version of payload."""
    return _normalize(copy.deepcopy(payload))
