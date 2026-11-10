"""/api/session: see _lib/routes.py (session)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import routes, web  # noqa: E402

ENDPOINT = web.Endpoint(routes.session, methods=("POST",), cap=4096)
handler = web.handler_for(ENDPOINT)
