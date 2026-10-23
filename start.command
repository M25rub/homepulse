#!/bin/sh
# Double-click (Mac) or run (Linux) to start HomePulse. Installs what it needs the first time.
cd "$(dirname "$0")"
python3 -m pip install --quiet -r requirements.txt
python3 run.py
