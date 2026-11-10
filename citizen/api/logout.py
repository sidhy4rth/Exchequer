"""/api/logout: see _lib/routes.py (logout)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import routes, web  # noqa: E402

ENDPOINT = web.Endpoint(routes.logout, methods=("POST",), cap=4096)
handler = web.handler_for(ENDPOINT)
