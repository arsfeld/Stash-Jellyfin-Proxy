#!/usr/bin/env python3
"""Pre-Phase-4 browser audit — walk the dev Jellyfin Web client across
every library root under multiple sort/filter URL-param combinations and
snapshot what renders. Complements dev-tools/api_audit.py (server shape);
this one captures what an end-user actually sees.

Output: dev-data/browser-session/prephase4-<timestamp>/
  report.json     per-route results (title, body snippet, console, net-fails)
  summary.txt     tabular overview
  <slug>.png      screenshot per route
"""
import datetime
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Error as PlaywrightError

WEB_BASE = "http://192.168.0.200:18098"
API_BASE = "http://192.168.0.200:18096"
SERVER_ID = "5884545f-0192-45e3-ae35-70061e0dba57"
USER_ID = "bed0fa2f-5a08-543a-96eb-ef0150360506"
ACCESS_TOKEN = "a89fc0ca-e371-4023-b85f-afcf1fc7d44b"


def build_routes():
    """The list.html hash route honours sortBy / sortOrder / filters /
    genres / years as URL params — no DOM clicking needed, the SPA
    re-renders from the hash state.
    """
    r = [
        # Home / favorites / root cards
        ("home",                   "/#/home.html"),
        ("home-favorites-tab",     "/#/home.html?tab=1"),
    ]

    # Each library root, default render
    for slug in ("root-scenes", "root-studios", "root-performers",
                 "root-groups", "root-series", "root-tags",
                 "tag-tit-worship", "tag-joi", "tag-gooning",
                 "tag-cum-countdown", "tag-cock-hero"):
        r.append((f"lib-{slug}",
                  f"/#/list.html?parentId={slug}&serverId={SERVER_ID}"))

    # Scene library under every sort option
    scene_sorts = [
        "SortName", "DateCreated", "PremiereDate", "Random",
        "CommunityRating", "Runtime", "PlayCount", "DatePlayed",
    ]
    for sort in scene_sorts:
        for order in ("Ascending", "Descending"):
            slug = f"scenes-sort-{sort}-{order[:3]}"
            r.append((slug,
                      f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}"
                      f"&sortBy={sort}&sortOrder={order}"))

    # Scene library under each filter dimension
    r.extend([
        ("scenes-favorites",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&filters=IsFavorite"),
        ("scenes-played",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&filters=IsPlayed"),
        ("scenes-unplayed",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&filters=IsUnplayed"),
        ("scenes-resumable",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&filters=IsResumable"),
        ("scenes-year-2025",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&years=2025"),
        ("scenes-genre-joi",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&genres=JOI"),
        ("scenes-movies-only",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&includeItemTypes=Movie"),
        ("scenes-episodes-only",
         f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}&includeItemTypes=Episode"),
    ])

    # Folder libraries under different sorts
    for sort in ("SortName", "DateCreated", "Random", "CommunityRating"):
        r.append((f"studios-sort-{sort}",
                  f"/#/list.html?parentId=root-studios&serverId={SERVER_ID}"
                  f"&sortBy={sort}&sortOrder=Ascending"))
        r.append((f"performers-sort-{sort}",
                  f"/#/list.html?parentId=root-performers&serverId={SERVER_ID}"
                  f"&sortBy={sort}&sortOrder=Ascending"))

    # Search — multiple queries
    for q in ("cum", "joi", "busty", "lolly", "nonexistentxyz"):
        r.append((f"search-{q}", f"/#/search.html?query={q}"))

    # Detail pages — one of each type
    r.extend([
        ("detail-scene",   f"/#/details?id=scene-38676&serverId={SERVER_ID}"),
        ("detail-episode", f"/#/details?id=scene-39097&serverId={SERVER_ID}"),
        ("detail-series",  f"/#/details?id=series-383&serverId={SERVER_ID}"),
        ("detail-season",  f"/#/details?id=season-383-7&serverId={SERVER_ID}"),
        ("detail-studio",  f"/#/details?id=studio-367&serverId={SERVER_ID}"),
        ("detail-performer", f"/#/details?id=performer-3010&serverId={SERVER_ID}"),
        ("detail-group",   f"/#/details?id=group-10&serverId={SERVER_ID}"),
    ])

    return r


SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def walk(out_dir: Path, headless: bool = True, timeout_ms: int = 15000):
    out_dir.mkdir(parents=True, exist_ok=True)
    routes = build_routes()
    report = {
        "base": WEB_BASE,
        "started": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "route_count": len(routes),
        "routes": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1440, "height": 900})

        console_events = []
        network_failures = []
        page_errors = []

        context.add_init_script(
            "window.localStorage.setItem('jellyfin_credentials', "
            + json.dumps(json.dumps({
                "Servers": [{
                    "ManualAddress": API_BASE,
                    "LastConnectionMode": 2,
                    "Name": "Stash Dev",
                    "Id": SERVER_ID,
                    "LocalAddress": API_BASE,
                    "DateLastAccessed": int(time.time() * 1000),
                    "AccessToken": ACCESS_TOKEN,
                    "UserId": USER_ID,
                    "manualAddressOnly": True,
                }]
            })) + ");"
        )

        page = context.new_page()
        page.on("console", lambda m: console_events.append(
            {"type": m.type, "text": m.text[:400]}
        ) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)[:400]))
        page.on("response", lambda r: network_failures.append(
            {"status": r.status, "method": r.request.method, "url": r.url}
        ) if r.status >= 400 else None)

        # Seed route
        page.goto(WEB_BASE + "/#/home.html", wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightError:
            pass
        time.sleep(1.0)

        for i, (name, route) in enumerate(routes, 1):
            print(f"  [{i:>3}/{len(routes)}] {name}")
            console_events.clear()
            network_failures.clear()
            page_errors.clear()
            url = WEB_BASE + route
            entry = {"name": name, "url": url, "status": "ok"}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except PlaywrightError:
                    pass
                try:
                    page.wait_for_function(
                        "() => !document.querySelector('.mdl-spinner.is-active, .docspinner.mdl-spinner--active')",
                        timeout=6000,
                    )
                except PlaywrightError:
                    pass
                time.sleep(1.2)
                entry["title"] = page.title()
                main_text = page.evaluate(
                    "() => { const m = document.querySelector('.mainAnimatedPage, .page:not(.hide), .view:not(.hide)');"
                    "       return (m && m.innerText) || ((document.body && document.body.innerText) || ''); }"
                )
                entry["body_snippet"] = (main_text or "").strip().replace("\n", " | ")[:400]
                # Extract the item count from the "1-100 of 28,974" blurb that
                # list.html always renders.
                cnt_match = re.search(r"\b1-\d+ of ([0-9,]+)\b", main_text or "")
                entry["visible_total"] = cnt_match.group(1) if cnt_match else None
            except PlaywrightError as e:
                entry["status"] = "nav-error"
                entry["error"] = str(e)[:400]

            shot_path = out_dir / f"{SAFE_RE.sub('_', name)}.png"
            try:
                page.screenshot(path=str(shot_path), full_page=False)
                entry["screenshot"] = shot_path.name
            except PlaywrightError:
                pass

            entry["console"] = list(console_events)
            entry["network_failures"] = list(network_failures)
            entry["page_errors"] = list(page_errors)
            report["routes"].append(entry)

        browser.close()

    report["ended"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))

    summary = [f"prephase4-browser-audit @ {report['started']}  base: {WEB_BASE}\n"]
    for r in report["routes"]:
        tag = r["status"]
        extras = []
        if r.get("visible_total"):
            extras.append(f"total={r['visible_total']}")
        if r.get("network_failures"):
            extras.append(f"netfail={len(r['network_failures'])}")
        if r.get("page_errors"):
            extras.append(f"pageerror={len(r['page_errors'])}")
        summary.append(
            f"[{tag:<10}] {r['name']:<35} {r.get('url','')[len(WEB_BASE):]}"
        )
        if extras:
            summary.append(f"             {' '.join(extras)}")
        body = r.get("body_snippet", "")
        if body:
            summary.append(f"             body: {body[:180]}")
        if r.get("console"):
            for c in r["console"][:2]:
                summary.append(f"             {c['type']}: {c['text'][:140]}")
    (out_dir / "summary.txt").write_text("\n".join(summary))
    print(f"\nWrote {len(report['routes'])} routes → {out_dir}")


if __name__ == "__main__":
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%SZ")
    out = Path(__file__).resolve().parent.parent / "dev-data" / "browser-session" / f"prephase4-{ts}"
    walk(out)
