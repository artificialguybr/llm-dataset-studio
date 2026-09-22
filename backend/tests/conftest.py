"""Isolate tests from the user's real data directory.

app.db reads IDS_DATA_DIR at import time, so this must run before any test
module imports the app. Point everything at a throwaway temp dir.
"""
import atexit
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="lds-test-data-")
os.environ["IDS_DATA_DIR"] = _tmp
os.environ.pop("IDS_DB_URL", None)
atexit.register(lambda: __import__("shutil").rmtree(_tmp, ignore_errors=True))
