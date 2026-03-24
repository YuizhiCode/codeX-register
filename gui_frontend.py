from __future__ import annotations

from pathlib import Path

_FRONTEND_HTML_PATH = Path(__file__).resolve().with_name("gui_frontend.html")


def _load_index_html() -> str:
    return _FRONTEND_HTML_PATH.read_text(encoding="utf-8")


INDEX_HTML = _load_index_html()

__all__ = ["INDEX_HTML"]
