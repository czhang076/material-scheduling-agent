"""Prevent historical exporters from overwriting evidence under a newer package."""

from material_scheduler import __version__


def require_stage(expected):
    if __version__ != expected:
        raise SystemExit(f"Historical stage script requires package {expected}; current package is {__version__}. Use the current docs/RUNBOOK.md. No evidence was rewritten.")
