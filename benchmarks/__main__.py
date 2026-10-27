"""Run gmaps benchmarks: ``uv run python -m benchmarks``."""

from __future__ import annotations


from benchmarks.timing import run_cli


def main() -> None:
    """Execute the timing CLI."""
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
