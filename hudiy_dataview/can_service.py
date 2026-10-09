#!/usr/bin/env python3
"""Installed entry point retained for hudiy_status_service.service."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vehicle_data.service import main

if __name__ == '__main__':
    main()
