from __future__ import annotations

import os
from typing import Callable

from ..mail_services import LuckyousOpenApiService


def build_luckyous_service(
    *,
    base_url: str,
    verify_ssl: bool,
    logger: Callable[[str], None] | None = None,
):
    api_base = str(os.getenv("LUCKYOUS_API_BASE", base_url or "") or "").strip()
    api_key = str(os.getenv("LUCKYOUS_API_KEY", "") or "")
    project_code = str(os.getenv("LUCKYOUS_PROJECT_CODE", "") or "").strip()
    email_type = str(os.getenv("LUCKYOUS_EMAIL_TYPE", "") or "").strip()
    domain = str(os.getenv("LUCKYOUS_DOMAIN", "") or "").strip().lower()
    variant_mode = str(os.getenv("LUCKYOUS_VARIANT_MODE", "") or "").strip().lower()
    specified_email = str(os.getenv("LUCKYOUS_SPECIFIED_EMAIL", "") or "").strip().lower()
    return LuckyousOpenApiService(
        base_url=api_base,
        api_key=api_key,
        project_code=project_code,
        email_type=email_type,
        domain=domain,
        variant_mode=variant_mode,
        specified_email=specified_email,
        verify_ssl=verify_ssl,
        logger=logger,
    )
