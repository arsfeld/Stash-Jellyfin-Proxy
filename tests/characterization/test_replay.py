"""Replay recorded fixtures against the current proxy and diff responses.

Volatile fields (timestamps, session IDs, image blur hashes, bitrates that
can shift on Stash rescan) are stripped via normalizer.normalize before
comparison. A fixture JSON file in fixtures/ is a self-contained test case:
request + expected response.

Run against a live dev proxy:

    ~/bin/download_epubs/bin/python -m pytest tests/characterization -x -v

To update expectations after an intentional behavior change, re-run
capture.py (which clears and rewrites fixtures) and commit the diff.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from tests.characterization.normalizer import normalize

FIXTURE_DIR = Path(__file__).parent / "fixtures"

BASE = os.environ.get("SJP_TEST_BASE", "http://192.168.0.200:18096")
ACCESS_TOKEN = os.environ.get("SJP_TEST_TOKEN", "a89fc0ca-e371-4023-b85f-afcf1fc7d44b")
AUTH = f'MediaBrowser Client="char-replay", Device="dev", DeviceId="char-001", Version="6.02", Token="{ACCESS_TOKEN}"'


def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any, str]:
    data = None
    headers = {"Accept": "application/json", "X-Emby-Authorization": AUTH}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            status = resp.status
            ct = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        status = e.code
        ct = e.headers.get("Content-Type", "") if e.headers else ""
    if ct.startswith("application/json") and raw:
        try:
            return status, json.loads(raw), ct
        except ValueError:
            pass
    return status, {"__content_type__": ct, "__bytes__": len(raw)}, ct


def _load_fixtures():
    return sorted(FIXTURE_DIR.glob("*.json"))


def _shape(value: Any) -> Any:
    """Reduce a response body to a structural skeleton. Used for endpoints
    whose content is non-deterministic (random/recency driven) but whose
    shape must not regress.

    Top level: dict keys + types. Items[] reduced to (type-of-list,
    count-present bool, union-of-top-level-keys-across-items) — individual
    items often have optional fields (Overview, Tags, People) so union is
    the only stable aggregate."""
    if isinstance(value, dict):
        out = {}
        for k, v in sorted(value.items()):
            if k == "Items" and isinstance(v, list):
                keys = set()
                for item in v:
                    if isinstance(item, dict):
                        keys.update(item.keys())
                out[k] = {
                    "__list__": "list",
                    "__nonempty__": len(v) > 0,
                    "__item_keys_union__": sorted(keys),
                }
            else:
                out[k] = _shape(v)
        return out
    if isinstance(value, list):
        return {"__list_len__": len(value)}
    return type(value).__name__


@pytest.mark.parametrize("fixture_path", _load_fixtures(), ids=lambda p: p.stem)
def test_fixture_matches(fixture_path: Path):
    spec = json.loads(fixture_path.read_text())
    req = spec["request"]
    expected = spec["response"]
    mode = spec.get("compare_mode", "full")

    status, body, ct = _request(req["method"], req["path"], req.get("body"))

    assert status == expected["status"], (
        f"{fixture_path.name}: status {status} != expected {expected['status']}"
    )

    norm_actual = normalize(body)
    norm_expected = normalize(expected["body"])

    # Binary endpoints — content-type + byte-range check only.
    if isinstance(norm_expected, dict) and "__bytes__" in norm_expected:
        assert norm_actual.get("__content_type__") == norm_expected.get("__content_type__"), (
            f"{fixture_path.name}: content-type mismatch"
        )
        exp_bytes = norm_expected.get("__bytes__", 0)
        act_bytes = norm_actual.get("__bytes__", 0)
        if exp_bytes > 0:
            assert abs(act_bytes - exp_bytes) / exp_bytes < 0.20, (
                f"{fixture_path.name}: bytes {act_bytes} vs expected {exp_bytes}"
            )
        return

    if mode == "shape":
        assert _shape(norm_actual) == _shape(norm_expected), (
            f"{fixture_path.name}: shape mismatch"
        )
        return

    assert norm_actual == norm_expected, (
        f"{fixture_path.name}: body mismatch"
    )
