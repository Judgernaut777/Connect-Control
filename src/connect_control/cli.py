"""Console entry point. Serves the scaffold app with uvicorn."""

from __future__ import annotations

import uvicorn

from connect_control.app import create_app


def main() -> None:
    uvicorn.run(create_app(), host="127.0.0.1", port=8800)
