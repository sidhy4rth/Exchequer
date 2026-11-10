"""/api/my-case: see _lib/routes.py (my_case)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import routes, web  # noqa: E402

ENDPOINT = web.Endpoint(routes.my_case, methods=("GET",), cap=4096)
handler = web.handler_for(ENDPOINT)
