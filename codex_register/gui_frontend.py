from __future__ import annotations

from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
_FRONTEND_TEMPLATE_PATH = _BASE_DIR / "gui_frontend.html"
_FRONTEND_STYLE_PATH = _BASE_DIR / "gui_frontend_style.css"
_FRONTEND_BOOTSTRAP_PATH = _BASE_DIR / "gui_frontend_bootstrap.js"
_FRONTEND_APP_PATH = _BASE_DIR / "gui_frontend_app.js"
_FRONTEND_APP_SETUP_PATH = _BASE_DIR / "gui_frontend_app_setup.js"
_FRONTEND_APP_TEMPLATE_PATH = _BASE_DIR / "gui_frontend_app_template.html"

_PLACEHOLDER_STYLE = "__GUI_FRONTEND_STYLE__"
_PLACEHOLDER_BOOTSTRAP = "__GUI_FRONTEND_BOOTSTRAP__"
_PLACEHOLDER_APP = "__GUI_FRONTEND_APP__"
_PLACEHOLDER_APP_SETUP = "__GUI_FRONTEND_APP_SETUP__"
_PLACEHOLDER_APP_TEMPLATE = "__GUI_FRONTEND_APP_TEMPLATE__"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_app_script() -> str:
    """加载并组装前端主脚本（含 setup/template 子片段）。"""
    app_template = _read_text(_FRONTEND_APP_PATH)
    setup_part = _read_text(_FRONTEND_APP_SETUP_PATH)
    template_part = _read_text(_FRONTEND_APP_TEMPLATE_PATH)
    app_script = app_template
    app_script = app_script.replace(_PLACEHOLDER_APP_SETUP, setup_part.rstrip())
    app_script = app_script.replace(_PLACEHOLDER_APP_TEMPLATE, template_part.rstrip())
    return app_script


def _load_index_html() -> str:
    template = _read_text(_FRONTEND_TEMPLATE_PATH)
    style = _read_text(_FRONTEND_STYLE_PATH)
    bootstrap = _read_text(_FRONTEND_BOOTSTRAP_PATH)
    app = _load_app_script()

    html = template
    html = html.replace(_PLACEHOLDER_STYLE, style.rstrip())
    html = html.replace(_PLACEHOLDER_BOOTSTRAP, bootstrap.rstrip())
    html = html.replace(_PLACEHOLDER_APP, app.rstrip())
    return html


INDEX_HTML = _load_index_html()

__all__ = ["INDEX_HTML"]
