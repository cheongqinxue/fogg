"""Alternate Uvicorn entrypoint for the FastAPI service."""

from api.app import app

__all__ = ["app"]
