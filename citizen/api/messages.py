"""/api/messages: see _lib/routes.py (messages)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import routes, web  # noqa: E402

ENDPOINT = web.Endpoint(routes.messages, methods=("POST",), cap=4096)


class handler(web.handler_for(ENDPOINT)):  # Vercel finds a function by a top-level handler class
    pass
