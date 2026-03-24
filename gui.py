#!/usr/bin/env python3
"""CodeX Register Web 控制台（Naive UI）入口。"""

from __future__ import annotations

from gui_frontend import INDEX_HTML
from gui_server_runtime import main_entry
from gui_service import RegisterService


def main() -> None:
    main_entry(service_factory=RegisterService, index_html=INDEX_HTML)


if __name__ == "__main__":
    main()
