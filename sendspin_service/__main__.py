"""Command-line entry point for the Sendspin service."""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
