us_code=500)

async def ui_api_logs(request):
    """Return log entries."""
    limit = int(request.query_params.get("limit", 100))
    entries = []

    log_path = os.path.join(LOG_DIR, LOG_FILE) if LOG_DIR else LOG_FILE
    if os.path.isfile(log_path):
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    line = line.strip()
                    if not line:
                        continue
                    # Parse log format: 2025-12-03 12:08:28,115 - stash-jellyfin-proxy - INFO - message
                    parts = line.split(" - ", 3)
                    if len(parts) >= 4:
                        entries.append({
                            "timestamp": parts[0],
                            "level": parts[2],
                            "message": parts[3]
                        })
                    else:
                        entries.append({
                            "timestamp": "",
                            "level": "INFO",
                            "message": line
                        })
        except Exception as e:
            pass

    return JSONResponse({
        "entries": entries,
        "logPath": log_path
    })

async def ui_api_streams(request):
    """Return active streams."""
    streams = []
    now = time.time()
    for scene_id, info in _active_streams.items():
        # Only include streams active in last 5 minutes
        if now - info.get("last_seen", 0) < 300:
            streams.append({
                "id": scene_id,
                "title": info.get("title", scene_id),
                "started": info.get("started", 0),
                "lastSeen": info.get("last_seen", 0),
                "user": info.get("user", SJS_USER),
                "clientIp": info.get("client_ip", "unknown"),
                "clientType": info.get("client_type", "unknown")
            })
    return JSONResponse({"streams": streams})

# Global reference for restart functionality
_shutdown_event = None
_restart_requested = False

async def ui_api_restart(request):
    """Restart the proxy server."""
    global _restart_requested
    
    if request.method != "POST":
        return JSONResponse({"error": "Method not allowed"}, status_code=405)
    
    logger.info("Restart requested via Web UI")
    _restart_requested = True
    
    # Schedule the shutdown after responding (restart happens after main loop exits)
    async def delayed_shutdown():
        await asyncio.sleep(1)  # Allow response to be sent
        logger.info("Shutting down for restart...")
        if _shutdown_event:
            _shutdown_event.set()
    
    asyncio.create_task(delayed_shutdown())
    return JSONResponse({"success": True, "message": "Restarting..."})

async def ui_api_auth_config(request):
    """Authenticate for config access."""
    if request.method != "POST":
        return JSONResponse({"error": "Method not allowed"}, status_code=405)
    
    try:
        data = await request.json()
        password = data.get("password", "")
        
        # Debug: log password lengths for troubleshooting
        logger.debug(f"Auth attempt: input len={len(password)}, expected len={len(SJS_PASSWORD)}")
        
        # Strip any whitespace from both passwords for comparison
        input_pw = password.strip()
        expected_pw = SJS_PASSWORD.strip()
        
        if input_pw == expected_pw:
            logger.info("Config authentication successful")
            return JSONResponse({"success": True})
        else:
            logger.warning(f"Config authentication failed - password mismatch (input: {len(input_pw)} chars, expected: {len(expected_pw)} chars)")
            return JSONResponse({"success": False, "error": "Invalid password"})
    except Exception as e:
        logger.error(f"Config authentication error: {e}")
        return JSONResponse({"success": False, "error": str(e)})

ui_routes = [
    Route("/", ui_index),
    Route("/api/status", ui_api_status),
    Route("/api/config", ui_api_config, methods=["GET", "POST"]),
    Route("/api/auth-config", ui_api_auth_config, methods=["POST"]),
    Route("/api/logs", ui_api_logs),
    Route("/api/streams", ui_api_streams),
    Route("/api/restart", ui_api_restart, methods=["POST"]),
]

ui_middleware = [
    Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
]

ui_app = Starlette(debug=False, routes=ui_routes, middleware=ui_middleware)

# --- Hypercorn Disconnect Error Filter ---
class SuppressDisconnectFilter(logging.Filter):
    """Filter to suppress expected socket disconnect errors from Hypercorn."""
    
    def filter(self, record):
        # Suppress "socket.send() raised exception" messages
        msg = record.getMessage()
        if "socket.send() raised exception" in msg:
            return False
        if "socket.recv() raised exception" in msg:
            return False
        
        # Also suppress common disconnect exception types
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type in (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                return False
        
        return True

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stash-Jellyfin Proxy Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging (overrides config)")
    parser.add_argument("--no-log-file", action="store_true", help="Disable file logging")
    parser.add_argument("--no-ui", action="store_true", help="Disable Web UI server")
    args = parser.parse_args()

    # Override logging if --debug flag is set
    if args.debug:
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers:
            handler.setLevel(logging.DEBUG)

    # Remove file handler if --no-log-file is set
    if args.no_log_file:
        logger.handlers = [h for h in logger.handlers if not isinstance(h, (RotatingFileHandler, logging.FileHandler))]

    # Suppress socket disconnect errors (expected during video seeking)
    # These come from both Hypercorn and asyncio when clients disconnect
    hypercorn_error_logger = logging.getLogger("hypercorn.error")
    hypercorn_error_logger.addFilter(SuppressDisconnectFilter())
    
    # The "socket.send() raised exception" messages come from asyncio, not Hypercorn
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.setLevel(logging.CRITICAL)  # Only show critical asyncio errors

    logger.info(f"--- Stash-Jellyfin Proxy v3.83 ---")
    logger.info(f"Binding: {PROXY_BIND}:{PROXY_PORT}")
    logger.info(f"Stash URL: {STASH_URL}")

    stash_ok = check_stash_connection()
    if not stash_ok:
        logger.warning("Could not connect to Stash. Proxy will start but streaming will not work until Stash is reachable.")
        logger.warning(f"Check STASH_URL ({STASH_URL}) and STASH_API_KEY settings.")
    
    PROXY_RUNNING = True
    PROXY_START_TIME = time.time()

    # Configure proxy server
    proxy_config = Config()
    proxy_config.bind = [f"{PROXY_BIND}:{PROXY_PORT}"]
    proxy_config.accesslog = logging.getLogger("hypercorn.access")
    proxy_config.access_log_format = "%(h)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s"
    proxy_config.errorlog = logging.getLogger("hypercorn.error")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    shutdown_event = asyncio.Event()
    
    # Update module-level reference for restart endpoint
    import __main__
    __main__._shutdown_event = shutdown_event
    
    def signal_handler():
        logger.info("Shutdown signal received...")
        shutdown_event.set()

    async def run_servers():
        """Run both proxy and UI servers with graceful shutdown."""
        # Set up signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        
        tasks = [serve(app, proxy_config, shutdown_trigger=shutdown_event.wait)]

        # Start UI server if enabled
        if UI_PORT > 0 and not args.no_ui:
            ui_config = Config()
            ui_config.bind = [f"{PROXY_BIND}:{UI_PORT}"]
            ui_config.accesslog = None  # Disable access logging for UI
            ui_config.errorlog = logging.getLogger("hypercorn.error")
            tasks.append(serve(ui_app, ui_config, shutdown_trigger=shutdown_event.wait))
            logger.info(f"Web UI: http://{PROXY_BIND}:{UI_PORT}")

        logger.info("Starting Hypercorn server...")
        await asyncio.gather(*tasks)
        logger.info("Servers stopped.")

    try:
        loop.run_until_complete(run_servers())
    except KeyboardInterrupt:
        pass
    except OSError as e:
        if e.errno == 98:  # Address already in use
            logger.error(f"ABORTING: Port already in use. Is another instance running?")
            logger.error(f"  Proxy port {PROXY_PORT} or UI port {UI_PORT} is already bound.")
            logger.error(f"  Try: lsof -i :{PROXY_PORT} or lsof -i :{UI_PORT}")
        else:
            logger.error(f"ABORTING: Network error: {e}")
        sys.exit(1)
    
    # Check if restart was requested (must happen after event loop exits)
    if _restart_requested:
        logger.info("Executing restart...")
        time.sleep(0.5)  # Brief pause before restart
        
        # Detect if running in Docker (/.dockerenv exists or CONFIG_FILE points to /config)
        in_docker = os.path.exists("/.dockerenv") or CONFIG_FILE.startswith("/config")
        
        if in_docker:
            # In Docker, exit cleanly and let Docker's restart policy handle it
            logger.info("Docker detected - exiting for container restart")
            sys.exit(0)
        else:
            # Outside Docker, use os.execv for in-place restart
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
