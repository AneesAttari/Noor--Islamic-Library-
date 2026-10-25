"""Entry point: runs the library with a production-grade WSGI server (waitress).

Usage:
    python run.py                # serves on 0.0.0.0:8000
    IDL_PORT=8080 python run.py  # custom port
"""
from __future__ import annotations

import os

from waitress import serve

from idl import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("IDL_HOST", "0.0.0.0")
    port = int(os.environ.get("IDL_PORT", "8000"))
    print(f"Maktaba — Islamic Digital Library listening on http://{host}:{port}")
    serve(app, host=host, port=port, threads=8)
