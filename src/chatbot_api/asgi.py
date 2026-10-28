"""ASGI app at module level, for platforms that import `module:app` (Vercel)."""

from chatbot_api.main import create_app

app = create_app()
