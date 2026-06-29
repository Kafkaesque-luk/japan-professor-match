"""Tiny IO helpers so data files can be shipped gzipped (`.jsonl.gz`) or plain (`.jsonl`)."""

from __future__ import annotations

import gzip
import io
import os


def resolve_data(path: str) -> str:
    """Return the existing variant of ``path`` (plain first, then ``.gz``)."""
    if os.path.exists(path):
        return path
    if os.path.exists(path + ".gz"):
        return path + ".gz"
    return path


def open_text(path: str):
    """Open a text file for reading, transparently handling gzip (.gz)."""
    real = resolve_data(path)
    if real.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(real, "rb"), encoding="utf-8")
    return open(real, "r", encoding="utf-8")
