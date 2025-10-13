#!/usr/bin/env python3
"""Development runner for Gmail bookmark service."""

import asyncio
import os
import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gmail_bookmark_service.main import main

if __name__ == "__main__":
    # Set development defaults
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("LOG_LEVEL", "INFO")
    os.environ.setdefault("JSON_LOGS", "false")

    # Run the service
    asyncio.run(main())