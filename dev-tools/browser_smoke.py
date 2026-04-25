#!/usr/bin/env python3
"""Drive the dev Jellyfin web client in headless Chromium and report what breaks.

Pre-seeds localStorage with a working access token so we skip the login screen,
then walks a set of named routes. For each route it waits for network-idle,
takes a screenshot, and captures console errors + failed network requests.

Run with the venv that has Playwright installed:

    ~/bin/download_epubs/bin/python dev-tools/browser_smoke.py

Output: ./dev-data/browser-session/<timestamp>/
    report.json     structured per-route results
    summary.txt     human-readable overview
    <route>.png     screenshot per route
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, Error as PlaywrightError


WEB_BASE = "http://192.168.0.200:18098"
API_BASE = "http://192.168.0.200:18096"
SERVER_ID = "5884545f-0192-45e3-ae35-70061e0dba57"
USER_ID = "bed0fa2f-5a08-543a-96eb-ef0150360506"
ACCESS_TOKEN = "a89fc0ca-e371-4023-b85f-afcf1fc7d44b"


def _api_get(path):
    req = urllib.request.Request(
        API_BASE + path,
        headers={"X-Emby-Authorization": f'MediaBrowser Token="{ACCESS_TOKEN}"'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _first_id(path, prefix):
    """Pull the first Items[].Id starting with `prefix` from a paginated endpoint."""
    try:
        data = _api_get(path)
    except Exception:
        return None
    for it in data.get("Items", []):
        iid = str(it.get("Id", ""))
        if iid.startswith(prefix):
            return iid
    return None


def discover_routes():
    """Build the route list at runtime using real IDs so the harness
    doesn't rot when Stash data changes."""
    scene = _first_id(
        f"/Users/{USER_ID}/Items?ParentId=root-scenes&Limit=20&IncludeItemTypes=Movie",
        "scene-",
    )
    studio = _first_id(
        f"/Users/{USER_ID}/Items?ParentId=root-studios&Limit=10",
        "studio-",
    )
    performer = _first_id(
        f"/Users/{USER_ID}/Items?ParentId=root-performers&Limit=10",
        "performer-",
    )
    tag_group = "tag-cock-hero"  # stable name from TAG_GROUPS

    routes = [
        ("home",           "/#/home.html"),
        ("favorites",      "/#/home.html?tab=1"),
        ("lib-scenes",     f"/#/list.html?parentId=root-scenes&serverId={SERVER_ID}"),
        ("lib-studios",    f"/#/list.html?parentId=root-studios&serverId={SERVER_ID}"),
        ("lib-performers", f"/#/list.html?parentId=root-performers&serverId={SERVER_ID}"),
        ("lib-groups",     f"/#/list.html?parentId=root-groups&serverId={SERVER_ID}"),
        ("lib-tags",       f"/#/list.html?parentId=root-tags&serverId={SERVER_ID}"),
        ("tag-group",      f"/#/list.html?parentId={tag_group}&serverId={SERVER_ID}"),
        ("search",         "/#/search.html?query=cum"),
    ]
    if scene:
        routes.append(("scene-detail", f"/#/details?id={scene}&serverId={SERVER_ID}"))
    if studio:
        routes.append(("studio-detail", f"/#/details?id={studio}&serverId={SERVER_ID}"))
    if performer:
        routes.append(("performer-detail", f"/#/details?id={performer}&serverId={SERVER_ID}"))
    return routes

SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def walk(out_dir: Path, headless: bool = True, timeout_ms: int = 15000):
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"base": WEB_BASE, "routes": [], "started": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1440, "height": 900})

        # Prime localStorage via init script so every page in this context
        # starts logged in.
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

        def on_console(msg):
            if msg.type in ("error", "warning"):
                console_events.append({
                    "type": msg.type,
                    "text": msg.text[:500],
                })

        def on_pageerror(err):
            page_errors.append(str(err)[:500])

        def on_response(resp):
            if resp.status >= 400:
                network_failures.append({
                    "status": resp.status,
                    "method": resp.request.method,
                    "url": resp.url,
                })

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

        # The web client is a SPA with a hash router. Going to #/home first
        # gives every subsequent route a stable base for in-app navigation
        # and loads the React bundle once.
        page.goto(WEB_BASE + "/#/home.html", wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightError:
            pass
        time.sleep(1.0)

        for name, route in discover_routes():
            console_events.clear()
            network_failures.clear()
            page_errors.clear()
            url = WEB_BASE + route
            entry = {"name": name, "url": url, "status": "ok"}
            try:
                # Hash-route change doesn't trigger a full nav, so goto()
                # followed by waiting for the route-specific spinner to
                # disappear is the reliable way to know content has rendered.
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except PlaywrightError:
                    pass
                # Wait for the route's main spinner (.docspinner / .mdl-spinner)
                # to be detached, bounded.
                try:
                    page.wait_for_function(
                        "() => !document.querySelector('.mdl-spinner.is-active, .docspinner.mdl-spinner--active')",
                        timeout=8000,
                    )
                except PlaywrightError:
                    pass
                time.sleep(2.0)  # buffer for late state-driven re-renders
                entry["title"] = page.title()
                # Skip the left nav drawer text so snippets show actual content.
                main_text = page.evaluate(
                    "() => { const m = document.querySelector('.mainAnimatedPage, .page:not(.hide), .view:not(.hide)');"
                    "       return (m && m.innerText) || ((document.body && document.body.innerText) || ''); }"
                )
                entry["body_snippet"] = (main_text or "").strip().replace("\n", " | ")[:300]
            except PlaywrightError as e:
                entry["status"] = "nav-error"
                entry["error"] = str(e)[:500]

            shot_path = out_dir / f"{SAFE_RE.sub('_', name)}.png"
            try:
                # Viewport screenshot, not full-page: one of the carousels
                # contains off-screen tiles that balloon full_page captures
                # to 8000+ px wide.
                page.screenshot(path=str(shot_path), full_page=False)
                entry["screenshot"] = shot_path.name
            except PlaywrightError as e:
                entry["screenshot_error"] = str(e)[:200]

            entry["console"] = list(console_events)
            entry["network_failures"] = list(network_failures)
            entry["page_errors"] = list(page_errors)
            report["routes"].append(entry)

        browser.close()

    report["finished"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "summary.txt").write_text(render_summary(report))
    return report


def render_summary(report):
    lines = [f"browser_smoke @ {report['started']}", f"base: {report['base']}", ""]
    for r in report["routes"]:
        lines.append(f"[{r['status']:<9}] {r['name']:<15} {r['url']}")
        if r.get("title"):
            lines.append(f"    title: {r['title']}")
        if r.get("body_snippet"):
            lines.append(f"    body:  {r['body_snippet'][:120].strip()}")
        if r.get("page_errors"):
            for e in r["page_errors"]:
                lines.append(f"    PAGE ERROR: {e[:180]}")
        for f in r.get("network_failures", []):
            lines.append(f"    NET {f['status']} {f['method']} {f['url'][:180]}")
        errs = [c for c in r.get("console", []) if c["type"] == "error"]
        for c in errs[:8]:
            lines.append(f"    CONSOLE ERROR: {c['text'][:180]}")
        warns = [c for c in r.get("console", []) if c["type"] == "warning"]
        if warns:
            lines.append(f"    (+{len(warns)} console warnings)")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="Output dir (default: ./dev-data/browser-session/<ts>)")
    ap.add_argument("--headed", action="store_true", help="Run non-headless for local debugging")
    args = ap.parse_args()

    out = Path(args.out) if args.out else Path("dev-data/browser-session") / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report = walk(out, headless=not args.headed)

    # Print summary to stdout
    sys.stdout.write((out / "summary.txt").read_text())
    total = len(report["routes"])
    broken = sum(
        1 for r in report["routes"]
        if r["status"] != "ok" or r.get("page_errors") or any(c["type"] == "error" for c in r.get("console", []))
    )
    print(f"\nCaptured {total} routes → {out}. Clean: {total - broken}. Problems: {broken}.")


if __name__ == "__main__":
    main()
