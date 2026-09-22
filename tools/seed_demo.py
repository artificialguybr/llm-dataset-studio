"""Load the sample corpus into a running Studio instance.

Usage: uv run python tools/seed_demo.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("IDS_API_URL", "http://127.0.0.1:8766").rstrip("/")

req = urllib.request.Request(f"{BASE}/api/seed-demo", method="POST",
                           headers={"content-type": "application/json"}, data=b"{}")
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print(json.loads(resp.read()))
except urllib.error.HTTPError as exc:
    print(f"seed failed ({exc.code}): {exc.read().decode()[:200]}", file=sys.stderr)
    raise SystemExit(1)
