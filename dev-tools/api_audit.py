#!/usr/bin/env python3
"""Pre-Phase-4 API audit — drive every relevant Jellyfin endpoint against
the dev proxy and record what each returns. Focuses on scene-list
sort/filter permutations and Home-rail / detail coverage.

Output: dev-data/prephase4-audit/<timestamp>/
  probes.json   structured per-probe results
  report.md     human-readable summary
"""
import datetime
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "dev-data" / "stash_jellyfin_proxy.conf"

BASE = "http://localhost:18096"
USER_ID = "bed0fa2f-5a08-543a-96eb-ef0150360506"
# Swiftfin + Infuse + default — probe the same endpoint across clients
# to surface per-profile behaviour differences (CollectionType, performer
# typing, etc.).
PROFILES = {
    "default": None,
    "swiftfin": "Swiftfin/1.0",
    "infuse": "Infuse-Direct/8.4.3",
    "senplayer": "SenPlayer/6.0.1",
}


def _token() -> str:
    for line in CONF.read_text().splitlines():
        if line.startswith("ACCESS_TOKEN"):
            return line.split("=", 1)[1].strip()
    sys.exit("ACCESS_TOKEN not found in conf")


TOKEN = _token()


def _get(path: str, ua: Optional[str] = None, timeout: int = 30) -> Tuple[int, Any]:
    url = BASE + path
    headers = {"X-Emby-Token": TOKEN, "Accept": "application/json"}
    if ua:
        headers["User-Agent"] = ua
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return status, json.loads(raw.decode())
            return status, {"__content_type__": ct, "__bytes__": len(raw)}
    except urllib.error.HTTPError as e:
        return e.code, {"__error__": str(e)}
    except Exception as e:
        return 0, {"__error__": str(e)}


def _summarize_items_response(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        return {"shape": "non-dict", "type": type(body).__name__}
    items = body.get("Items") or []
    types_count: Dict[str, int] = {}
    for it in items:
        t = (it.get("Type") if isinstance(it, dict) else None) or "?"
        types_count[t] = types_count.get(t, 0) + 1
    # Skip the pinned FILTERS BoxSet folder — it appears at index 0 on
    # every list and masks real sort differences. Find the first real
    # scene/folder item.
    first = {}
    for it in items:
        if isinstance(it, dict) and it.get("Type") != "BoxSet":
            first = it
            break
        if isinstance(it, dict) and it.get("Id", "").startswith(("scene-", "studio-", "performer-", "group-", "series-", "tagitem-")):
            first = it
            break
    if not first and items and isinstance(items[0], dict):
        first = items[0]
    # Capture a small ordered sample so we can see sort signatures beyond item 0.
    sample = []
    for it in items[:5]:
        if isinstance(it, dict):
            sample.append(f"{it.get('Id')}|{(it.get('Name') or '')[:30]}")
    return {
        "trc": body.get("TotalRecordCount"),
        "count": len(items),
        "types": types_count,
        "first_id": first.get("Id"),
        "first_name": (first.get("Name") or "")[:60],
        "first_sortname": first.get("SortName"),
        "first_genres_len": len(first.get("Genres") or []) if first else 0,
        "first_tags_len": len(first.get("Tags") or []) if first else 0,
        "sample_ids": sample,
    }


# ---------- Probe bank ----------

probes: List[Dict[str, Any]] = []


def run_probe(name: str, path: str, *, ua: Optional[str] = None, expect: str = "items",
              notes: str = "") -> Dict[str, Any]:
    status, body = _get(path, ua=ua)
    entry: Dict[str, Any] = {
        "name": name,
        "path": path,
        "ua": ua or "default",
        "status": status,
        "notes": notes,
    }
    if expect == "items":
        entry["summary"] = _summarize_items_response(body)
    elif expect == "filters":
        if isinstance(body, dict):
            entry["summary"] = {
                "genres_len": len(body.get("Genres") or []),
                "tags_len": len(body.get("Tags") or []),
                "years_len": len(body.get("Years") or []),
                "rating_len": len(body.get("OfficialRatings") or []),
                "genres_sample": (body.get("Genres") or [])[:5],
            }
        else:
            entry["summary"] = {"shape": "non-dict"}
    elif expect == "detail":
        if isinstance(body, dict):
            entry["summary"] = {
                "type": body.get("Type"),
                "name": body.get("Name"),
                "sortname": body.get("SortName"),
                "official_rating": body.get("OfficialRating"),
                "has_overview": bool(body.get("Overview")),
                "backdrop_tags": body.get("BackdropImageTags"),
                "genres_len": len(body.get("Genres") or []),
                "tags_len": len(body.get("Tags") or []),
                "provider_ids": body.get("ProviderIds"),
                "studios": body.get("Studios"),
                "series_name": body.get("SeriesName"),
                "season_name": body.get("SeasonName"),
                "status_field": body.get("Status"),
                "rating": body.get("CommunityRating"),
            }
        else:
            entry["summary"] = {"shape": "non-dict"}
    else:
        entry["summary"] = {"raw": body if isinstance(body, dict) and len(str(body)) < 200 else "(truncated)"}
    probes.append(entry)
    return entry


def _items(parent: str, ua: str = "", **kwargs) -> str:
    qs = {
        "ParentId": parent,
        "Recursive": "true",
        "Limit": "5",
        "Fields": "PrimaryImageAspectRatio,SortName,Overview,Genres,Tags,ProviderIds",
    }
    qs.update(kwargs)
    return f"/Users/{USER_ID}/Items?" + urllib.parse.urlencode(qs)


# ---------- Library root cards ----------

print("=> library roots")
for profile, ua in PROFILES.items():
    run_probe(f"views.{profile}", f"/Users/{USER_ID}/Views", ua=ua, expect="items",
              notes="Root libraries + counts")

# ---------- Scene list sort permutations ----------

print("=> scene list sort permutations")
SCENE_SORTS = [
    "SortName", "Name", "PremiereDate", "DateCreated", "Random",
    "CommunityRating", "Runtime", "PlayCount", "DatePlayed",
    "ProductionYear", "DateLastContentAdded", "CriticRating",
]
for sort in SCENE_SORTS:
    for order in ("Ascending", "Descending"):
        run_probe(
            f"scenes.sort.{sort}.{order}",
            _items("root-scenes", SortBy=sort, SortOrder=order),
            notes=f"SortBy={sort}&SortOrder={order}",
        )

# ---------- Scene list filter permutations ----------

print("=> scene list filter permutations")
run_probe("scenes.filter.IsFavorite", _items("root-scenes", Filters="IsFavorite"),
          notes="Favorite scenes via IsFavorite filter")
run_probe("scenes.filter.IsPlayed", _items("root-scenes", Filters="IsPlayed"),
          notes="Played scenes")
run_probe("scenes.filter.IsUnplayed", _items("root-scenes", Filters="IsUnplayed"),
          notes="Unplayed scenes")
run_probe("scenes.filter.IsResumable", _items("root-scenes", Filters="IsResumable"),
          notes="Scenes with resume position")
run_probe("scenes.filter.HasSubtitles", _items("root-scenes", HasSubtitles="true"),
          notes="Scenes with subtitles")

# Year filter — pick one year and verify
run_probe("scenes.filter.Years", _items("root-scenes", Years="2025"),
          notes="Year filter (2025)")

# Genre filter — requires a known genre; probe with FAVORITE (should be empty per excludes)
run_probe("scenes.filter.Genres.FAVORITE", _items("root-scenes", Genres="FAVORITE"),
          notes="Should be empty — FAVORITE is system-excluded")
run_probe("scenes.filter.Genres.JOI", _items("root-scenes", Genres="JOI"),
          notes="Single-genre filter, real tag name")

# Multi-type filters
run_probe("scenes.types.Movie", _items("root-scenes", IncludeItemTypes="Movie"),
          notes="Movies only (excludes SERIES-studio Episode scenes)")
run_probe("scenes.types.Episode", _items("root-scenes", IncludeItemTypes="Episode"),
          notes="Episodes only (SERIES-studio scenes)")
run_probe("scenes.types.MovieEpisode", _items("root-scenes", IncludeItemTypes="Movie,Episode"),
          notes="Both Movies + Episodes")

# Pagination sanity
run_probe("scenes.page.0", _items("root-scenes", StartIndex="0", Limit="3"))
run_probe("scenes.page.1000", _items("root-scenes", StartIndex="1000", Limit="3"))
run_probe("scenes.page.boundary", _items("root-scenes", StartIndex="28000", Limit="3"))

# ---------- Folder-type libraries sort ----------

print("=> folder libraries")
FOLDER_SORTS = ["SortName", "Name", "DateCreated", "Random", "CommunityRating"]
for root in ("root-studios", "root-performers", "root-groups", "root-series"):
    for sort in FOLDER_SORTS:
        run_probe(f"{root}.sort.{sort}", _items(root, SortBy=sort),
                  notes=f"SortBy={sort}")

# ---------- Tags library ----------

print("=> tags library")
run_probe("root-tags.list", _items("root-tags"),
          notes="Top-level Tags navigation folder")
run_probe("root-tags.favorites", _items("tags-favorites"),
          notes="Stash's own favorite-tagged tags")

# ---------- TAG_GROUPS libraries ----------

print("=> TAG_GROUPS libraries")
tag_groups = ["Tit Worship", "JOI", "Gooning", "Cum Countdown", "Cock Hero"]
for tag_name in tag_groups:
    tag_slug = f"tag-{tag_name.lower().replace(' ', '-')}"
    for sort in ("PremiereDate", "Random", "CommunityRating"):
        run_probe(f"tag.{tag_slug}.sort.{sort}",
                  _items(tag_slug, SortBy=sort),
                  notes=f"{tag_name} tag library, SortBy={sort}")

# ---------- /Items/Filters per library ----------

print("=> filter panel")
for parent in ("root-scenes", "root-studios", "root-performers", "root-groups",
               "tag-joi", "tag-cum-countdown"):
    run_probe(f"filters.{parent}", f"/Items/Filters?ParentId={parent}", expect="filters",
              notes=f"Filter-drawer options for {parent}")

# ---------- Search ----------

print("=> search")
for query in ("cum", "joi", "busty", "nonexistentqueryxyz"):
    for profile, ua in (("swiftfin", "Swiftfin/1.0"), ("infuse", "Infuse-Direct/8.4.3")):
        run_probe(f"search.{query}.{profile}",
                  f"/Users/{USER_ID}/Items?SearchTerm={query}&Recursive=true&Limit=10",
                  ua=ua, notes=f"Search '{query}' as {profile}")
    # Search Hints endpoint
    run_probe(f"hints.{query}", f"/Search/Hints?SearchTerm={query}&Limit=10",
              notes=f"/Search/Hints for '{query}'")

# /Persons search
run_probe("persons.search.joi", f"/Persons?SearchTerm=joi&Limit=5",
          notes="/Persons search endpoint")
for profile, ua in (("swiftfin", "Swiftfin/1.0"), ("infuse", "Infuse-Direct/8.4.3")):
    run_probe(f"persons.search.lolly.{profile}",
              f"/Persons?SearchTerm=lolly&Limit=5", ua=ua,
              notes=f"/Persons search 'lolly' as {profile}")

# ---------- Home rails ----------

print("=> home rails")
run_probe("home.resume", f"/Users/{USER_ID}/Items/Resume?Limit=10",
          notes="Continue Watching")
run_probe("home.resume.infuse", f"/UserItems/Resume?userId={USER_ID}&limit=40&mediaTypes=Video&recursive=true",
          ua="Infuse-Direct/8.4.3", notes="Infuse-style Continue Watching")
run_probe("home.latest.scenes",
          f"/Users/{USER_ID}/Items/Latest?ParentId=root-scenes&Limit=12",
          notes="Latest Scenes rail")
run_probe("home.latest.studios",
          f"/Users/{USER_ID}/Items/Latest?ParentId=root-studios&Limit=12",
          notes="Latest Studios rail (zero-scene filter applies)")
run_probe("home.latest.performers",
          f"/Users/{USER_ID}/Items/Latest?ParentId=root-performers&Limit=12")
run_probe("home.latest.groups",
          f"/Users/{USER_ID}/Items/Latest?ParentId=root-groups&Limit=12")
run_probe("home.nextup", "/Shows/NextUp?Limit=20",
          notes="/Shows/NextUp — currently random, Phase 4 target")
run_probe("home.banner.movie.random",
          _items("root-scenes", IncludeItemTypes="Movie", SortBy="Random", Limit="6"),
          notes="Banner-row request (Infuse home top)")

# ---------- Favorites tab ----------

print("=> favorites tab")
for t in ("Movie", "Video", "Episode", "Series", "BoxSet", "Person", ""):
    qs = {"Filters": "IsFavorite", "Recursive": "true", "Limit": "10"}
    if t:
        qs["IncludeItemTypes"] = t
    run_probe(f"favorites.type.{t or 'NONE'}",
              f"/Users/{USER_ID}/Items?" + urllib.parse.urlencode(qs),
              notes=f"Favorites filter with IncludeItemTypes={t or '<none>'}")

run_probe("favorites.persons", f"/Users/{USER_ID}/FavoriteItems",
          notes="Legacy /FavoriteItems route")

# ---------- Series navigation ----------

print("=> series navigation")
run_probe("series.list", _items("root-series"), notes="Series library roots")
for sid in ("series-383", "series-462"):
    run_probe(f"{sid}.detail", f"/Items/{sid}", expect="detail",
              notes=f"Series detail — {sid}")
    run_probe(f"{sid}.seasons", f"/Shows/{sid}/Seasons",
              notes=f"Season list — {sid}")
    run_probe(f"{sid}.episodes.all", f"/Shows/{sid}/Episodes",
              notes="All episodes in series")
run_probe("season.383-7.episodes",
          "/Shows/season-383-7/Episodes",
          notes="Season 7 episodes via season-id path")
run_probe("season.383-0.episodes",
          "/Shows/season-383-0/Episodes",
          notes="Specials (Season 0) episodes")
run_probe("season.383-7.detail", "/Items/season-383-7", expect="detail")

# ---------- Detail pages ----------

print("=> detail pages")
for ua in (None, "Swiftfin/1.0", "Infuse-Direct/8.4.3"):
    run_probe(f"scene.detail.{ua or 'default'}",
              "/Items/scene-38676", ua=ua, expect="detail",
              notes="Non-SERIES scene (Movie)")
    run_probe(f"episode.detail.{ua or 'default'}",
              "/Items/scene-39097", ua=ua, expect="detail",
              notes="SERIES scene (Episode)")
    run_probe(f"studio.detail.{ua or 'default'}",
              "/Items/studio-367", ua=ua, expect="detail",
              notes="Studio with parent network")
    run_probe(f"performer.detail.{ua or 'default'}",
              "/Items/performer-3010", ua=ua, expect="detail",
              notes="Performer with rich attrs")

# ---------- Write outputs ----------

ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%SZ")
out_dir = ROOT / "dev-data" / "prephase4-audit" / ts
out_dir.mkdir(parents=True, exist_ok=True)

probes_path = out_dir / "probes.json"
probes_path.write_text(json.dumps(probes, indent=2))

# ---------- Markdown summary ----------

def _md_section(title: str) -> str:
    return f"\n## {title}\n\n"


errors = [p for p in probes if p["status"] >= 400 or p["status"] == 0]
empty = [p for p in probes if isinstance(p.get("summary"), dict) and p["summary"].get("trc") == 0]

lines: List[str] = []
lines.append(f"# Pre-Phase-4 API Audit — {ts}\n")
lines.append(f"Base: `{BASE}`  •  User: `{USER_ID}`  •  Probes: **{len(probes)}**")
lines.append(f"Errors (non-2xx): **{len(errors)}**  •  Zero-result probes: **{len(empty)}**")

# --- Summary table per section ---

def fmt_summary(p: Dict[str, Any]) -> str:
    s = p.get("summary") or {}
    if "trc" in s:
        return f"TRC={s.get('trc')} count={s.get('count')} types={s.get('types')}"
    if "type" in s:
        return f"Type={s.get('type')} name={s.get('name')!r}"
    if "genres_len" in s and "years_len" in s:
        return f"genres={s['genres_len']} tags={s['tags_len']} years={s['years_len']} ratings={s['rating_len']}"
    return str(s)[:120]


groups: Dict[str, List[Dict[str, Any]]] = {}
for p in probes:
    key = p["name"].split(".")[0]
    groups.setdefault(key, []).append(p)

for section, items in groups.items():
    lines.append(_md_section(section))
    lines.append(f"| probe | status | summary | notes |")
    lines.append(f"|---|---|---|---|")
    for p in items:
        lines.append(
            f"| `{p['name']}` | {p['status']} | {fmt_summary(p)} | {p.get('notes','')} |"
        )

# --- Interesting findings ---

lines.append(_md_section("Errors & anomalies"))
if errors:
    for p in errors:
        lines.append(f"- **{p['name']}** → HTTP {p['status']}  `{p['path']}`")
else:
    lines.append("_No errors._")

lines.append(_md_section("Zero-result probes"))
if empty:
    for p in empty[:30]:
        lines.append(f"- `{p['name']}`  ({p.get('notes','')})")
else:
    lines.append("_None._")

(out_dir / "report.md").write_text("\n".join(lines))
print(f"\nWrote {len(probes)} probes → {probes_path}")
print(f"Report          → {out_dir / 'report.md'}")
