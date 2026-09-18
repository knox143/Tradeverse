import sys
from pathlib import Path

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app

class StripPrefixMiddleware:
    """WSGI middleware to normalize PATH_INFO for Vercel serverless functions."""
    def __init__(self, wsgi_app, prefix="/api/index"):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "")
        if path_info.startswith(self.prefix + ".py"):
            environ["PATH_INFO"] = path_info[len(self.prefix + ".py"):] or "/"
        elif path_info.startswith(self.prefix):
            environ["PATH_INFO"] = path_info[len(self.prefix):] or "/"
        return self.wsgi_app(environ, start_response)

app.wsgi_app = StripPrefixMiddleware(app.wsgi_app)

