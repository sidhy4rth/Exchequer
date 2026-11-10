"""/api/complaints: see _lib/routes.py (complaints)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import routes, web  # noqa: E402

ENDPOINT = web.Endpoint(routes.complaints, methods=("POST",), cap=24576)
handler = web.handler_for(ENDPOINT)
