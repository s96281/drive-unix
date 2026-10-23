"""Entrypoint for running the web server directly with `python -m web`."""

from __future__ import annotations

import argparse
import sys
import uvicorn


def main() -> None:
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="drive-unix Web Interface Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind socket to this host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind socket to this port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code change")
    args = parser.parse_args()

    print(f"🚀 drive-unix Web UI: http://{args.host}:{args.port}")
    print(f"📖 API Documentation: http://{args.host}:{args.port}/docs")
    uvicorn.run("web.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
