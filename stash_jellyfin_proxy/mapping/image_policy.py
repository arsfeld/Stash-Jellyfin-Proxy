"""Image format policy — per-client poster format and performer item type.

Phase 1: all clients receive landscape scene images and Person-typed
performers. The routing hooks are in place for Phase 2/3:
  - Phase 2: performer_item_type returns BoxSet for non-Swiftfin clients
  - Phase 3: scene_poster_format returns "portrait" for Swiftfin clients

User-Agent detection is a simple substring match. Full player-profile
resolution (config-driven, per §6.1) lands in Phase 2.
"""


def _is_swiftfin(request) -> bool:
    ua = request.headers.get("user-agent", "")
    return "Swiftfin" in ua


def scene_poster_format(request) -> str:
    """Return 'portrait' or 'landscape' for scene poster images.

    Phase 1 stub: always 'landscape' — no behavior change.
    Phase 3 will return 'portrait' for Swiftfin clients.
    """
    return "landscape"


def performer_item_type(request) -> str:
    """Return the Jellyfin Type string for performer items.

    Swiftfin uses native Person browsing (bio, filmography view).
    Other clients (Infuse, SenPlayer) use BoxSet for performer tiles.

    Phase 1: Swiftfin → 'Person', others → 'BoxSet'.
    Phase 2 will replace this with full player-profile resolution.
    """
    if _is_swiftfin(request):
        return "Person"
    return "BoxSet"
