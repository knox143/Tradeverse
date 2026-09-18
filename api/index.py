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
        matched_path = environ.get("HTTP_X_MATCHED_PATH") or environ.get("HTTP_X_FORWARDED_URI")
        if matched_path:
            for prefix in ("/api/index.py", "/api/index", "/api/app.py", "/api/app"):
                if matched_path == prefix:
                    matched_path = "/"
                    break
                elif matched_path.startswith(prefix + "/"):
                    matched_path = matched_path[len(prefix):] or "/"
                    break
            environ["PATH_INFO"] = matched_path
        else:
            path_info = environ.get("PATH_INFO", "")
            for prefix in ("/api/index.py", "/api/index", "/api/app.py", "/api/app"):
                if path_info == prefix:
                    environ["PATH_INFO"] = "/"
                    break
                elif path_info.startswith(prefix + "/"):
                    environ["PATH_INFO"] = path_info[len(prefix):] or "/"
                    break
        return self.wsgi_app(environ, start_response)

app.wsgi_app = StripPrefixMiddleware(app.wsgi_app)

