#!/usr/bin/env python3
"""Galileo data toolkit. Run `python tools/galileo.py --help`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from galileo_data.cli import main  # noqa: E402

sys.exit(main())
