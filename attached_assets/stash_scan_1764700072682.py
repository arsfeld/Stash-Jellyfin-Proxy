#!/usr/bin/env python3
# Stash Metadata Scan Script
# Version: 1.0.0
# Changelog:
# 2025-05-08: Initial version with scan and metadata generation
# 2025-05-09: Reduced logging verbosity, added dependency checks, centralized config
# 2025-05-28: Added signal handling and increased api timeouts from 10 to 30
# Logs to /var/log/chris_services.log via rsyslog with programname 'stash_scan'
# Run as: ./stash_scan.py [--full] [--debug]
# For cron:
# */10 * * * * /usr/bin/python3 /home/chris/bin/stash_scan.py
# 0 */6 * * * /usr/bin/python3 /home/chris/bin/stash_scan.py --full

import sys
import json
import requests
import logging
from logging.handlers import SysLogHandler
import urllib3
import argparse
import os
import shutil
import signal

def handle_termination(signum, frame):
    logger.info(f"Received signal {signum}, exiting cleanly")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_termination)
signal.signal(signal.SIGINT, handle_termination)

# Suppress InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

##########################################################
# --- Load Config ---
##########################################################
CONFIG_FILE = "/home/chris/.scripts.conf"
if not os.path.isfile(CONFIG_FILE):
    print(f"stash_scan[ERROR]: Configuration file {CONFIG_FILE} not found", file=sys.stderr)
    sys.exit(1)
with open(CONFIG_FILE, 'r') as f:
    exec(f.read())

##########################################################
# --- Configuration Items ---
##########################################################
STASH_API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJGZWxkb3JuIiwiaWF0IjoxNjgyNDUyMDQ0LCJzdWIiOiJBUElLZXkifQ.aOUDW-mpev6E1OHlQYZmmN7s4qRjz-oeTvpnKeByS68'
SERVER = 'stash.feldorn.com'
PORT = 443
PROTO = 'https'
DEFAULT_SCAN_PATH = '/data/Video-B/--NEW'
# DEFAULT_SCAN_PATH = '/data2/Video-B/Miscellaneous - JOI'

##########################################################
# GraphQL endpoint
##########################################################
GRAPHQL_URL = f"{PROTO}://{SERVER}:{PORT}/graphql-local"
HEADERS = {
    "ApiKey": STASH_API_KEY,
    "Content-Type": "application/json"
}

##########################################################
# --- Setup Logger ---
##########################################################
def setup_logger(level: int = logging.INFO) -> logging.Logger:
    """Configure and return a logger writing to rsyslog with tag 'stash_scan'."""
    logger = logging.getLogger("stash_scan")
    logger.setLevel(level)
    try:
        if not logger.handlers:
            syslog_handler = SysLogHandler(address='/dev/log')
            syslog_handler.setLevel(level)
            formatter = logging.Formatter("%(name)s[%(levelname)s]: %(message)s")
            syslog_handler.setFormatter(formatter)
            logger.addHandler(syslog_handler)
        logger.debug("Logger setup successful")
    except Exception as e:
        logger.error(f"Failed to setup logger: {e}")
        raise
    return logger

##########################################################
# --- Run Scan ---
##########################################################
def run_scan(paths, scan_type, logger):
    """Initiates a metadata scan for the specified paths via the Stash GraphQL API."""
    logger.debug(f"Entering run_scan for {scan_type} scan")
    scan_query = {
        "query": """
        mutation MetadataScan($input: ScanMetadataInput!) {
            metadataScan(input: $input)
        }
        """,
        "variables": {
            "input": {
                "paths": paths,
                "rescan": False,
                "scanGenerateCovers": True,
                "scanGeneratePreviews": True,
                "scanGenerateImagePreviews": False,
                "scanGenerateSprites": True,
                "scanGeneratePhashes": True,
                "scanGenerateThumbnails": False,
                "scanGenerateClipPreviews": False
            }
        }
    }
    try:
        if scan_type == "DIRECTORY":
            logger.info(f"Starting metadata scan for directory: {paths[0]}")
        else:
            logger.info(f"Starting {scan_type} metadata scan")
        response = requests.post(
            GRAPHQL_URL,
            json=scan_query,
            headers=HEADERS,
#            verify=False,
            timeout=30  # 30-second timeout
        )
        response.raise_for_status()
        scan_response = response.json()
        logger.debug(f"GraphQL response: {json.dumps(scan_response, indent=2)}")
        if "errors" in scan_response:
            logger.error(f"Failed to initiate {scan_type} scan. GraphQL errors: {scan_response['errors']}")
            return False
        scan_task_id = scan_response.get("data", {}).get("metadataScan")
        if scan_task_id:
            logger.info(f"{scan_type} metadata scan started successfully — Task ID: {scan_task_id}")
            return True
        else:
            logger.error(f"Failed to initiate {scan_type} scan. GraphQL response: {scan_response}")
            return False
    except requests.exceptions.Timeout:
        logger.error(f"Timeout initiating {scan_type} scan")
        return False
    except Exception as e:
        logger.error(f"Failed to initiate {scan_type} scan: {e}")
        return False
    finally:
        logger.debug(f"Exiting run_scan for {scan_type} scan")

##########################################################
# --- Run Metadata Generator ---
##########################################################
def run_metadata_generate(logger):
    """Initiates global metadata generation via the Stash GraphQL API."""
    logger.debug("Entering run_metadata_generate")
    gen_query = {
        "query": """
        mutation MetadataGenerate($input: GenerateMetadataInput!) {
            metadataGenerate(input: $input)
        }
        """,
        "variables": {
            "input": {
                "sprites": True,
                "previews": True,
                "imagePreviews": False,
                "markers": False,
                "transcodes": False
            }
        }
    }
    try:
        logger.info("Starting global metadata generation")
        response = requests.post(
            GRAPHQL_URL,
            json=gen_query,
            headers=HEADERS,
#            verify=False,
            timeout=30  # 30-second timeout
        )
        response.raise_for_status()
        gen_response = response.json()
        logger.debug(f"GraphQL response: {json.dumps(gen_response, indent=2)}")
        if "errors" in gen_response:
            logger.error(f"Failed to initiate metadata generation. GraphQL errors: {gen_response['errors']}")
            return False
        gen_task_id = gen_response.get("data", {}).get("metadataGenerate")
        if gen_task_id:
            logger.info(f"Metadata generation task started successfully — Task ID: {gen_task_id}")
            return True
        else:
            logger.error(f"Failed to initiate metadata generation. GraphQL response: {gen_response}")
            return False
    except requests.exceptions.Timeout:
        logger.error("Timeout initiating metadata generation")
        return False
    except Exception as e:
        logger.error(f"Failed to initiate metadata generation: {e}")
        return False
    finally:
        logger.debug("Exiting run_metadata_generate")

##########################################################
# --- MAIN ---
##########################################################
def main():
    """Main entry point."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Stash Metadata Scan Script")
    parser.add_argument("--full", action="store_true", help="Perform full-library scan")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Set logging level based on --debug
    log_level = logging.DEBUG if args.debug else logging.INFO

    # Early logging to confirm script start
    try:
        logger = setup_logger(log_level)
        if "CRON" in os.environ:
            logger.debug("Running in cron environment")
    except Exception as e:
        print(f"stash_scan[ERROR]: Failed to setup logger: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Determine scan type based on command-line switch
        if args.full:
            scan_type = "FULL-LIBRARY"
            paths = []
        else:
            scan_type = "DIRECTORY"
            paths = [DEFAULT_SCAN_PATH]

        if not run_scan(paths, scan_type, logger):
            logger.error(f"{scan_type} scan failed, exiting")
            os.system(f"{PUSHOVER_SCRIPT} -b 'Stash {scan_type} Scan Failed'")
            sys.exit(1)

        if args.full:
            if not run_metadata_generate(logger):
                logger.error("Metadata generation failed, exiting")
                os.system(f"{PUSHOVER_SCRIPT} -b 'Stash Metadata Generation Failed'")
                sys.exit(1)

        logger.info("Script completed successfully")
    except Exception as e:
        logger.error(f"Script failed: {e}")
        os.system(f"{PUSHOVER_SCRIPT} -b 'Stash Script Failed: {e}'")
        sys.exit(1)

if __name__ == "__main__":
    main()
