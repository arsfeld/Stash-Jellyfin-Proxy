#!/usr/bin/env python3
"""
Stash-Jellyfin Proxy v6.02
Enables Infuse and other Jellyfin clients to connect to Stash by emulating the Jellyfin API.

# =============================================================================
# TODO / KNOWN ISSUES
# =============================================================================
#
# Dashboard Freezing During Stream Start
# --------------------------------------
# The Web UI dashboard can briefly freeze when Infuse starts a new stream.
# Cause: Synchronous Stash API calls block the async event loop during metadata
#        and image fetching, delaying UI polling requests.
# Possible fixes:
#   - Replace `requests` with async `httpx` client
#   - Cache Stash connection status in background instead of live checks
#   - Run Stash queries in thread pool via asyncio.to_thread()
#
# Infuse Image Caching
# --------------------
# Infuse aggressively caches images and may not refresh when Stash artwork changes.
# This is Infuse behavior, not a proxy issue. Users can clear Infuse metadata cache.
#
# =============================================================================
"""
import os
import sys
import logging
import asyncio
import signal
import argparse
import time
from logging.handlers import RotatingFileHandler

# Force UTF-8 on Windows consoles (cp1252 would crash on emoji log messages).
# Must run before any print() or logger output.
if sys.platform == "win32":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                pass

# Early CLI pre-scan: --config and --local-config need to land in env vars
# before the module-level config load runs. The full argparse (with --help,
# --debug, etc.) still happens later in main().
def _prescan_config_args(argv):
    """Consume --config and --local-config from argv and promote to env vars."""
    for flag, env_var in (("--config", "CONFIG_FILE"), ("--local-config", "LOCAL_CONFIG_FILE")):
        for i, arg in enumerate(argv):
            if arg == flag and i + 1 < len(argv):
                os.environ[env_var] = argv[i + 1]
                break
            if arg.startswith(flag + "="):
                os.environ[env_var] = arg.split("=", 1)[1]
                break

_prescan_config_args(sys.argv[1:])

# Third-party dependencies
try:
    from hypercorn.config import Config
    from hypercorn.asyncio import serve
except ImportError as e:
    print(f"Missing dependency: {e}. Please run: pip install hypercorn starlette requests")
    sys.exit(1)

# Optional setproctitle so `ps` / `top` / `pgrep` show "stash-jellyfin-proxy"
# instead of a bare "python". Not required — skip silently if unavailable.
try:
    import setproctitle
    setproctitle.setproctitle("stash-jellyfin-proxy")
except ImportError:
    pass


# --- Configuration Loading ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(SCRIPT_DIR, "stash_jellyfin_proxy.conf"))
_base, _ext = os.path.splitext(CONFIG_FILE)
LOCAL_CONFIG_FILE = os.getenv("LOCAL_CONFIG_FILE", f"{_base}.local{_ext}" if _ext else f"{CONFIG_FILE}.local")

import proxy.runtime as _runtime
from proxy.config.bootstrap import run_bootstrap
run_bootstrap(CONFIG_FILE, LOCAL_CONFIG_FILE)


# --- Logging Setup ---
from proxy.logging_setup import setup_logging
logger = setup_logging(
    log_level=_runtime.LOG_LEVEL,
    log_file=_runtime.LOG_FILE,
    log_dir=_runtime.LOG_DIR,
    log_max_size_mb=_runtime.LOG_MAX_SIZE_MB,
    log_backup_count=_runtime.LOG_BACKUP_COUNT,
)


# Proxy state + stash client needed by __main__
from proxy.state.stats import load_proxy_stats, save_proxy_stats
from proxy.stash.client import check_stash_connection

# --- App construction, routes, error handlers, and UI server ---
# All of these live in proxy/app.py now.
from proxy.app import app, ui_app, SuppressDisconnectFilter

# Global reference for restart functionality
_shutdown_event = None
_restart_requested = False


# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="stash-jellyfin-proxy",
        description="Stash-Jellyfin Proxy Server — serve Stash over the Jellyfin API.",
    )
    parser.add_argument("--config", metavar="PATH", help="Path to base config file (default: stash_jellyfin_proxy.conf beside the script, or $CONFIG_FILE)")
    parser.add_argument("--local-config", metavar="PATH", help="Path to local override config merged on top of --config (default: <base>.local.conf, or $LOCAL_CONFIG_FILE)")
    parser.add_argument("--host", metavar="HOST", help="Override PROXY_BIND from config (e.g. 127.0.0.1)")
    parser.add_argument("--port", type=int, metavar="PORT", help="Override PROXY_PORT from config")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Override LOG_LEVEL from config")
    parser.add_argument("--debug", action="store_true", help="Shortcut for --log-level DEBUG")
    parser.add_argument("--no-log-file", action="store_true", help="Disable file logging")
    parser.add_argument("--no-ui", action="store_true", help="Disable Web UI server")
    args = parser.parse_args()

    # Apply CLI overrides that take effect after config load.
    if args.host:
        _runtime.PROXY_BIND = args.host
    if args.port:
        _runtime.PROXY_PORT = args.port
    if args.log_level:
        level = getattr(logging, args.log_level)
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)

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

    logger.info(f"--- Stash-Jellyfin Proxy v6.02 ---")

    stash_ok = check_stash_connection()
    if not stash_ok:
        logger.warning("Could not connect to Stash. Proxy will start but streaming will not work until Stash is reachable.")
        logger.warning(f"Check STASH_URL ({_runtime.STASH_URL}) and STASH_API_KEY settings.")

    _runtime.PROXY_RUNNING = True
    _runtime.PROXY_START_TIME = time.time()

    # Load stats from file
    load_proxy_stats()

    # Configure proxy server
    proxy_config = Config()
    proxy_config.bind = [f"{_runtime.PROXY_BIND}:{_runtime.PROXY_PORT}"]
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
        # Save stats before shutting down
        save_proxy_stats()
        shutdown_event.set()

    async def run_servers():
        """Run both proxy and UI servers with graceful shutdown."""
        # Set up signal handlers (add_signal_handler not supported on Windows)
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, signal_handler)

        tasks = [serve(app, proxy_config, shutdown_trigger=shutdown_event.wait)]

        # Start UI server if enabled
        if _runtime.UI_PORT > 0 and not args.no_ui:
            ui_config = Config()
            ui_config.bind = [f"{_runtime.PROXY_BIND}:{_runtime.UI_PORT}"]
            ui_config.accesslog = None  # Disable access logging for UI
            ui_config.errorlog = logging.getLogger("hypercorn.error")
            tasks.append(serve(ui_app, ui_config, shutdown_trigger=shutdown_event.wait))
            logger.info(f"Web UI: http://{_runtime.PROXY_BIND}:{_runtime.UI_PORT}")

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
            logger.error(f"  Proxy port {_runtime.PROXY_PORT} or UI port {_runtime.UI_PORT} is already bound.")
            logger.error(f"  Try: lsof -i :{_runtime.PROXY_PORT} or lsof -i :{_runtime.UI_PORT}")
        else:
            logger.error(f"ABORTING: Network error: {e}")
        sys.exit(1)

    # Check if restart was requested (must happen after event loop exits)
    if _restart_requested:
        logger.info("Executing restart...")
        time.sleep(0.5)  # Brief pause before restart

        # Detect if running in Docker (/.dockerenv exists or CONFIG_FILE points to /config)
        in_docker = os.path.exists("/.dockerenv") or _runtime.CONFIG_FILE.startswith("/config")

        if in_docker:
            # In Docker, exit cleanly and let Docker's restart policy handle it
            logger.info("Docker detected - exiting for container restart")
            sys.exit(0)
        else:
            # Outside Docker, use os.execv for in-place restart
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
