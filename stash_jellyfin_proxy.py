import os
import sys
import json
import logging
import asyncio
import signal
import uuid
import argparse
import mimetypes
from typing import Optional, List, Dict, Any
from logging.handlers import SysLogHandler
from urllib.parse import quote

# Third-party dependencies (install with: pip install hypercorn starlette requests aiofiles)
try:
    from hypercorn.config import Config
    from hypercorn.asyncio import serve
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response, RedirectResponse, PlainTextResponse
    from starlette.routing import Route, Mount
    from starlette.requests import Request
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    import requests
except ImportError as e:
    print(f"Missing dependency: {e}. Please run: pip install hypercorn starlette requests aiofiles")
    sys.exit(1)

# --- Configuration Loading ---
CONFIG_FILE = "/home/chris/.scripts.conf"

# Default Configuration (will be overridden by config file)
STASH_URL = "http://localhost:9999"
STASH_API_KEY = ""
MEDIA_ROOTS = []
PROXY_BIND = "0.0.0.0"
PROXY_PORT = 8096
PROXY_API_KEY = "infuse12345"

# Load Config
if os.path.isfile(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            exec(f.read())
    except Exception as e:
        print(f"Error loading config file {CONFIG_FILE}: {e}", file=sys.stderr)
        sys.exit(1)
else:
    # Fallback for testing/development if file doesn't exist
    print(f"Warning: Config file {CONFIG_FILE} not found. Using defaults/env vars if available.")
    STASH_URL = os.getenv("STASH_URL", STASH_URL)
    STASH_API_KEY = os.getenv("STASH_API_KEY", STASH_API_KEY)

# --- Logging Setup ---
logger = logging.getLogger("stash-jellyfin-proxy")
logger.setLevel(logging.INFO)

def setup_logging(debug: bool):
    if debug:
        logger.setLevel(logging.DEBUG)
    
    # Syslog handler
    try:
        syslog = SysLogHandler(address='/dev/log')
        syslog.setFormatter(logging.Formatter('%(name)s: [%(levelname)s] %(message)s'))
        logger.addHandler(syslog)
    except Exception:
        pass # Fallback if syslog not available (e.g. non-Linux)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console)

# --- Stash GraphQL Client ---
GRAPHQL_URL = f"{STASH_URL}/graphql-local" if not STASH_URL.endswith("/graphql-local") else STASH_URL
STASH_HEADERS = {
    "ApiKey": STASH_API_KEY,
    "Content-Type": "application/json"
}

def stash_query(query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
    try:
        resp = requests.post(GRAPHQL_URL, json={"query": query, "variables": variables or {}}, headers=STASH_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Stash API error: {e}")
        return {"errors": [str(e)]}

# --- Jellyfin Models & Helpers ---
SERVER_ID = "stash-proxy-v1"
USER_ID = "user-1"
ACCESS_TOKEN = str(uuid.uuid4()) # Generated at startup

def format_jellyfin_item(scene: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Stash Scene to a Jellyfin Item."""
    item_id = scene.get("id")
    title = scene.get("title") or scene.get("code") or f"Scene {item_id}"
    date = scene.get("date")
    
    # Map paths
    files = scene.get("files", [])
    path = files[0].get("path") if files else ""
    
    # Map Studio
    studio = scene.get("studio", {}).get("name") if scene.get("studio") else None
    
    # Map Tags to Genres/Tags
    tags = [t.get("name") for t in scene.get("tags", [])]
    
    # Map Performers
    people = []
    for p in scene.get("performers", []):
        people.append({
            "Name": p.get("name"),
            "Id": p.get("id"),
            "Type": "Actor",
            "Role": "Performer"
        })

    return {
        "Name": title,
        "Id": item_id,
        "ServerId": SERVER_ID,
        "Type": "Movie", # Treat scenes as Movies for simplicity
        "MediaType": "Video",
        "ProductionYear": int(date[:4]) if date else None,
        "PremiereDate": f"{date}T00:00:00.0000000Z" if date else None,
        "DateCreated": f"{date}T00:00:00.0000000Z" if date else None,
        "Path": path,
        "Studios": [{"Name": studio}] if studio else [],
        "Genres": tags,
        "Tags": tags,
        "People": people,
        "ImageTags": {
            "Primary": item_id, # Use ID as fake tag to trigger image fetch
            "Thumb": item_id 
        },
        "Container": "mp4", # simplified
        "SupportsSync": True,
        "RunTimeTicks": int(scene.get("files", [{}])[0].get("duration", 0) * 10000000) if files else 0
    }

# --- API Endpoints ---

async def endpoint_system_info(request):
    return JSONResponse({
        "ServerName": "Stash Proxy",
        "Version": "10.8.0", # Fake Jellyfin version
        "Id": SERVER_ID,
        "OperatingSystem": "Linux",
        "SupportsLibraryMonitor": False,
        "WebSocketPortNumber": PROXY_PORT,
        "CompletedInstallations": [
            {"Guid": SERVER_ID, "Name": "Stash Proxy"}
        ]
    })

async def endpoint_public_info(request):
    return JSONResponse({
        "LocalAddress": f"http://{PROXY_BIND}:{PROXY_PORT}",
        "ServerName": "Stash Proxy",
        "Version": "10.8.0",
        "Id": SERVER_ID
    })

async def endpoint_authenticate_by_name(request):
    data = await request.json()
    username = data.get("Username")
    pw = data.get("Pw")
    
    # Simple Auth
    if pw == PROXY_API_KEY:
        return JSONResponse({
            "User": {
                "Name": username,
                "Id": USER_ID,
                "Policy": {"IsAdministrator": True}
            },
            "SessionInfo": {
                "UserId": USER_ID,
                "IsActive": True
            },
            "AccessToken": ACCESS_TOKEN,
            "ServerId": SERVER_ID
        })
    else:
        return JSONResponse({"error": "Invalid Token"}, status_code=401)

async def endpoint_users(request):
    # List users (only one fake user)
    return JSONResponse([{
        "Name": "Infuse User",
        "Id": USER_ID,
        "HasPassword": True,
        "Policy": {"IsAdministrator": True}
    }])

async def endpoint_user_views(request):
    # Top level library folders
    # We can map Stash "Studios" or just a root "All Scenes"
    return JSONResponse({
        "Items": [
            {
                "Name": "All Scenes",
                "Id": "root-scenes",
                "ServerId": SERVER_ID,
                "Type": "CollectionFolder",
                "CollectionType": "movies"
            },
            {
                "Name": "Studios",
                "Id": "root-studios",
                "ServerId": SERVER_ID,
                "Type": "CollectionFolder",
                "CollectionType": "movies"
            }
        ],
        "TotalRecordCount": 2
    })

async def endpoint_items(request):
    # This is the complex search/browse endpoint
    user_id = request.path_params.get("user_id")
    parent_id = request.query_params.get("ParentId")
    
    items = []
    
    if parent_id == "root-scenes":
        # Fetch recent scenes
        q = """
        query FindScenes {
            findScenes(scene_filter: {sort: date, direction: DESC}, filter: {per_page: 50}) {
                scenes { id title code date files { path duration } studio { name } tags { name } performers { name id } }
            }
        }
        """
        res = stash_query(q)
        for s in res.get("data", {}).get("findScenes", {}).get("scenes", []):
            items.append(format_jellyfin_item(s))

    elif parent_id == "root-studios":
        # List studios as folders
        q = """
        query FindStudios {
            findStudios(filter: {per_page: 50, sort: name, direction: ASC}) {
                studios { id name }
            }
        }
        """
        res = stash_query(q)
        for s in res.get("data", {}).get("findStudios", {}).get("studios", []):
            items.append({
                "Name": s["name"],
                "Id": f"studio-{s['id']}",
                "ServerId": SERVER_ID,
                "Type": "Folder",
                "ImageTags": {}
            })
            
    elif parent_id and parent_id.startswith("studio-"):
        # List scenes for a studio
        studio_id = parent_id.replace("studio-", "")
        q = """
        query FindScenes($sid: ID!) {
            findScenes(scene_filter: {studios: {value: $sid, modifier: EQUALS}, sort: date, direction: DESC}, filter: {per_page: 50}) {
                scenes { id title code date files { path duration } studio { name } tags { name } performers { name id } }
            }
        }
        """
        res = stash_query(q, {"sid": studio_id})
        for s in res.get("data", {}).get("findScenes", {}).get("scenes", []):
            items.append(format_jellyfin_item(s))
            
    # Detail view for a single item
    ids = request.query_params.get("Ids")
    if ids:
        # Fetch specific item
        q = """
        query FindScene($id: ID!) {
            findScene(id: $id) { id title code date files { path duration } studio { name } tags { name } performers { name id } }
        }
        """
        res = stash_query(q, {"id": ids})
        scene = res.get("data", {}).get("findScene")
        if scene:
            items.append(format_jellyfin_item(scene))

    return JSONResponse({
        "Items": items,
        "TotalRecordCount": len(items)
    })

async def endpoint_item_details(request):
    item_id = request.path_params.get("item_id")
    q = """
    query FindScene($id: ID!) {
        findScene(id: $id) { id title code date files { path duration } studio { name } tags { name } performers { name id } }
    }
    """
    res = stash_query(q, {"id": item_id})
    scene = res.get("data", {}).get("findScene")
    if not scene:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(format_jellyfin_item(scene))

async def endpoint_playback_info(request):
    # Always direct play
    return JSONResponse({
        "MediaSources": [{
            "Id": "src1",
            "Protocol": "Http",
            "MediaStreams": [],
            "SupportsDirectPlay": True,
            "SupportsTranscoding": False
        }],
        "PlaySessionId": "session-1"
    })

async def endpoint_stream(request):
    item_id = request.path_params.get("item_id")
    # Get file path from Stash
    q = """query FindScene($id: ID!) { findScene(id: $id) { files { path } } }"""
    res = stash_query(q, {"id": item_id})
    files = res.get("data", {}).get("findScene", {}).get("files", [])
    if not files:
        return Response("File not found", status_code=404)
    
    file_path = files[0]["path"]
    
    # PREFERRED: X-Accel-Redirect (requires Nginx frontend)
    # return Response(headers={"X-Accel-Redirect": f"/protected_files/{file_path}"})

    # FALLBACK: Redirect to Stash direct stream (if Stash exposes it)
    # OR Direct file serve (Not efficient in Python, but requested as fallback)
    # For this implementation, we'll try to redirect to Stash's stream endpoint if we can guess it,
    # otherwise we'll just return a 404 saying "Setup Nginx" as serving video via python is risky for single thread.
    # Actually, let's implement a basic Redirect to the file path assuming local access or a simple file server.
    
    # Since this is running on the same host as Stash and files, we can just serve it?
    # No, Starlette isn't great at serving large files.
    # Let's assume we redirect to a static file server or use the stash stream url.
    
    stash_stream_url = f"{STASH_URL}/scene/{item_id}/stream" # This usually requires auth.
    # We can proxy the request to Stash with our API key?
    
    # Simpler: Just 302 redirect to Stash stream URL if accessible
    return RedirectResponse(url=stash_stream_url)

async def endpoint_image(request):
    item_id = request.path_params.get("item_id")
    # Redirect to Stash thumbnail
    stash_img_url = f"{STASH_URL}/scene/{item_id}/screenshot"
    return RedirectResponse(url=stash_img_url)


# --- App Construction ---
routes = [
    Route("/System/Info", endpoint_system_info),
    Route("/System/Info/Public", endpoint_public_info),
    Route("/Users/AuthenticateByName", endpoint_authenticate_by_name, methods=["POST"]),
    Route("/Users/{user_id}/Views", endpoint_user_views),
    Route("/Users/{user_id}/Items", endpoint_items),
    Route("/Users/{user_id}/Items/{item_id}", endpoint_item_details),
    Route("/Items", endpoint_items), # Root items
    Route("/Videos/{item_id}/stream", endpoint_stream),
    Route("/Videos/{item_id}/stream.mp4", endpoint_stream), # Infuse likes extensions
    Route("/Items/{item_id}/Images/Primary", endpoint_image),
    Route("/Items/{item_id}/Images/Thumb", endpoint_image),
    Route("/PlaybackInfo", endpoint_playback_info, methods=["POST", "GET"]),
]

app = Starlette(debug=True, routes=routes)

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.debug)
    
    logger.info(f"Starting Stash-Jellyfin Proxy on {PROXY_BIND}:{PROXY_PORT}")
    logger.info(f"Target Stash: {STASH_URL}")

    config = Config()
    config.bind = [f"{PROXY_BIND}:{PROXY_PORT}"]
    
    # Handle signals
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(serve(app, config))
    except KeyboardInterrupt:
        logger.info("Stopping...")
