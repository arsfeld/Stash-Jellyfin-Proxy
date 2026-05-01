"""Unit tests for is_scene_favorite / is_group_favorite case-insensitive
match (issue #17 — Infuse favorites broken when configured FAVORITE_TAG
casing differed from the existing Stash tag)."""
import pytest

from stash_jellyfin_proxy import runtime
from stash_jellyfin_proxy.mapping.scene import is_group_favorite, is_scene_favorite


@pytest.fixture
def fav_tag():
    saved = runtime.FAVORITE_TAG
    runtime.FAVORITE_TAG = "FAVORITE"
    yield
    runtime.FAVORITE_TAG = saved


def test_scene_favorite_matches_when_casing_differs(fav_tag):
    # Stash returns the existing tag with its stored casing; config has uppercase.
    scene = {"tags": [{"name": "Favorite"}, {"name": "Other"}]}
    assert is_scene_favorite(scene) is True


def test_scene_favorite_matches_lowercase_in_stash(fav_tag):
    scene = {"tags": [{"name": "favorite"}]}
    assert is_scene_favorite(scene) is True


def test_scene_favorite_false_when_tag_absent(fav_tag):
    scene = {"tags": [{"name": "Other"}, {"name": "Random"}]}
    assert is_scene_favorite(scene) is False


def test_scene_favorite_false_when_no_fav_tag_configured():
    saved = runtime.FAVORITE_TAG
    runtime.FAVORITE_TAG = ""
    try:
        scene = {"tags": [{"name": "Favorite"}]}
        assert is_scene_favorite(scene) is False
    finally:
        runtime.FAVORITE_TAG = saved


def test_scene_favorite_handles_whitespace(fav_tag):
    scene = {"tags": [{"name": "  Favorite  "}]}
    assert is_scene_favorite(scene) is True


def test_group_favorite_matches_when_casing_differs(fav_tag):
    group = {"tags": [{"name": "Favorite"}]}
    assert is_group_favorite(group) is True


def test_group_favorite_false_when_tag_absent(fav_tag):
    group = {"tags": [{"name": "Other"}]}
    assert is_group_favorite(group) is False
