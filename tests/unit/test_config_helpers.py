"""Unit tests for the pure config-value helpers."""
import uuid

import pytest

from stash_jellyfin_proxy.config.helpers import (
    parse_bool,
    normalize_path,
    normalize_server_id,
    generate_server_id,
    save_config_value,
)
from stash_jellyfin_proxy.config.loader import load_config


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("TRUE", True), ("True", True),
    ("yes", True), ("1", True), ("on", True),
    ("false", False), ("no", False), ("0", False), ("off", False),
    ("", False), ("garbage", False),
])
def test_parse_bool_string_inputs(value, expected):
    assert parse_bool(value) is expected


def test_parse_bool_passes_bool_through():
    assert parse_bool(True) is True
    assert parse_bool(False) is False


def test_parse_bool_other_types_return_default():
    assert parse_bool(None) is True          # default
    assert parse_bool(None, default=False) is False
    assert parse_bool(123, default=True) is True


@pytest.mark.parametrize("value,expected", [
    ("/graphql", "/graphql"),
    ("graphql", "/graphql"),
    ("/graphql/", "/graphql"),
    ("/graphql-local/", "/graphql-local"),
    ("", "/graphql"),
    ("   ", "/graphql"),
])
def test_normalize_path(value, expected):
    assert normalize_path(value) == expected


def test_normalize_path_custom_default():
    assert normalize_path("", default="/custom") == "/custom"


def test_normalize_server_id_converts_dashless_hex_to_uuid():
    dashless = "efbf7f031234567890abcdef12345678"
    assert normalize_server_id(dashless) == "efbf7f03-1234-5678-90ab-cdef12345678"


def test_normalize_server_id_passes_valid_uuid_through():
    valid = "efbf7f03-1234-5678-90ab-cdef12345678"
    assert normalize_server_id(valid) == valid


def test_normalize_server_id_passes_non_hex_through():
    """Bad input should not raise — Web UI surfaces the issue instead."""
    assert normalize_server_id("not-a-uuid") == "not-a-uuid"


def test_generate_server_id_returns_valid_uuid_string():
    out = generate_server_id()
    # Parses as UUID round-trip
    assert str(uuid.UUID(out)) == out


def test_save_config_value_inserts_above_section_header(tmp_path):
    """Regression: post-migration files end with [player.default]; appending
    a new key at EOF would scope it into that section, so the loader can't
    see SERVER_ID/ACCESS_TOKEN on the next boot and bootstrap regenerates
    them every restart (Infuse re-add loop, GH issue #16)."""
    cfg_path = tmp_path / "test.conf"
    cfg_path.write_text(
        "CONFIG_VERSION = 2\n"
        "SJS_USER = Gyvari\n"
        "\n"
        "[player.default]\n"
        "performer_type = BoxSet\n"
    )
    save_config_value(str(cfg_path), "SERVER_ID", "abc-uuid", "auto-generated")
    save_config_value(str(cfg_path), "ACCESS_TOKEN", "tok", "auto-generated")

    cfg, _, sections = load_config(str(cfg_path))
    assert cfg.get("SERVER_ID") == "abc-uuid"
    assert cfg.get("ACCESS_TOKEN") == "tok"
    assert "SERVER_ID" not in sections.get("player.default", {})
    assert "ACCESS_TOKEN" not in sections.get("player.default", {})


def test_save_config_value_self_heals_trapped_key(tmp_path):
    """Affected users have SERVER_ID trapped in [player.default] from the
    buggy save path. On the next save we should pull it out, not leave a
    duplicate behind."""
    cfg_path = tmp_path / "test.conf"
    cfg_path.write_text(
        "CONFIG_VERSION = 2\n"
        "\n"
        "[player.default]\n"
        "performer_type = BoxSet\n"
        "SERVER_ID = stale-trapped\n"
    )
    save_config_value(str(cfg_path), "SERVER_ID", "fresh", "auto-generated")

    cfg, _, sections = load_config(str(cfg_path))
    assert cfg.get("SERVER_ID") == "fresh"
    assert "SERVER_ID" not in sections["player.default"]
    # No leftover/duplicate SERVER_ID line in the file
    assert cfg_path.read_text().count("SERVER_ID =") == 1


def test_save_config_value_updates_in_place_at_global_scope(tmp_path):
    """A SERVER_ID line already at global scope should be updated in place,
    not duplicated."""
    cfg_path = tmp_path / "test.conf"
    cfg_path.write_text(
        "CONFIG_VERSION = 2\n"
        "SERVER_ID = old\n"
        "SJS_USER = Gyvari\n"
        "\n"
        "[player.default]\n"
        "performer_type = BoxSet\n"
    )
    save_config_value(str(cfg_path), "SERVER_ID", "new", "auto-generated")

    cfg, _, sections = load_config(str(cfg_path))
    assert cfg["SERVER_ID"] == "new"
    assert cfg["SJS_USER"] == "Gyvari"
    assert sections["player.default"]["performer_type"] == "BoxSet"


def test_save_config_value_no_sections_appends_at_end(tmp_path):
    """When the file has no [section] blocks, the value is appended at EOF."""
    cfg_path = tmp_path / "test.conf"
    cfg_path.write_text("STASH_URL = http://x\n")
    save_config_value(str(cfg_path), "SERVER_ID", "uuid", "auto-generated")

    cfg, _, _ = load_config(str(cfg_path))
    assert cfg["SERVER_ID"] == "uuid"
    assert cfg["STASH_URL"] == "http://x"


def test_save_config_value_exact_key_match(tmp_path):
    """SERVER_ID must not match SERVER_ID_FOO (loose prefix match would
    overwrite unrelated keys)."""
    cfg_path = tmp_path / "test.conf"
    cfg_path.write_text(
        "SERVER_ID_FOO = keep-me\n"
        "STASH_URL = http://x\n"
        "\n"
        "[player.default]\n"
        "performer_type = BoxSet\n"
    )
    save_config_value(str(cfg_path), "SERVER_ID", "new", "auto-generated")

    cfg, _, _ = load_config(str(cfg_path))
    assert cfg["SERVER_ID"] == "new"
    assert cfg["SERVER_ID_FOO"] == "keep-me"
