from __future__ import annotations

import json
import os
import random
import re
import string
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from curl_cffi import requests

from .gui_config_store import save_config
from .mail_services import (
    MailServiceError,
    available_mail_providers,
    build_mail_service,
    normalize_mail_provider,
)


def mail_proxy(service) -> dict[str, str] | None:
    raw = str(service.cfg.get("proxy") or "").strip()
    if not raw:
        return None
    return {"http": raw, "https": raw}


def mail_client_signature(service) -> tuple[Any, ...]:
    provider = normalize_mail_provider(service.cfg.get("mail_service_provider") or "mailfree")
    worker_domain = str(service.cfg.get("worker_domain") or "").strip()
    cf_temp_base_url = str(service.cfg.get("cf_temp_base_url") or "").strip()
    cf_temp_mail_domains = str(service.cfg.get("cf_temp_mail_domains") or "").strip()
    if provider == "cloudflare_temp_email" and cf_temp_base_url:
        domain = cf_temp_base_url
    else:
        domain = worker_domain
    if domain and not domain.startswith("http"):
        domain = f"https://{domain}"
    if provider == "cloudflare_temp_email" and cf_temp_mail_domains:
        mail_domains = cf_temp_mail_domains
    else:
        mail_domains = str(service.cfg.get("mail_domains") or "").strip()
    graph_accounts_file = str(service.cfg.get("graph_accounts_file") or "").strip()
    graph_accounts_mode = str(service.cfg.get("graph_accounts_mode") or "file").strip().lower()
    if graph_accounts_mode not in {"file", "api"}:
        graph_accounts_mode = "file"
    graph_api_base_url = str(service.cfg.get("graph_api_base_url") or "").strip()
    graph_api_token = str(service.cfg.get("graph_api_token") or "").strip()
    graph_tenant = str(service.cfg.get("graph_tenant") or "common").strip()
    graph_fetch_mode = str(service.cfg.get("graph_fetch_mode") or "graph_api").strip()
    cf_temp_admin_auth = str(service.cfg.get("cf_temp_admin_auth") or "")
    cloudmail_api_url = str(service.cfg.get("cloudmail_api_url") or "").strip()
    cloudmail_admin_email = str(service.cfg.get("cloudmail_admin_email") or "").strip()
    cloudmail_admin_password = str(service.cfg.get("cloudmail_admin_password") or "")
    mail_curl_api_base = str(service.cfg.get("mail_curl_api_base") or "").strip()
    mail_curl_key = str(service.cfg.get("mail_curl_key") or "")
    luckyous_api_base = str(service.cfg.get("luckyous_api_base") or "https://mails.luckyous.com").strip()
    luckyous_api_key = str(service.cfg.get("luckyous_api_key") or "").strip()
    luckyous_project_code = str(service.cfg.get("luckyous_project_code") or "").strip()
    luckyous_email_type = str(service.cfg.get("luckyous_email_type") or "ms_graph").strip().lower()
    luckyous_domain = str(service.cfg.get("luckyous_domain") or "").strip().lower()
    luckyous_variant_mode = str(service.cfg.get("luckyous_variant_mode") or "").strip().lower()
    luckyous_specified_email = str(service.cfg.get("luckyous_specified_email") or "").strip().lower()
    gmail_imap_user = str(service.cfg.get("gmail_imap_user") or "").strip()
    gmail_imap_pass = str(service.cfg.get("gmail_imap_pass") or "")
    gmail_alias_emails = str(service.cfg.get("gmail_alias_emails") or "").strip()
    gmail_imap_server = str(service.cfg.get("gmail_imap_server") or "imap.gmail.com").strip()
    gmail_imap_port = service._to_int(service.cfg.get("gmail_imap_port"), 993, 1, 65535)
    gmail_alias_tag_len = service._to_int(service.cfg.get("gmail_alias_tag_len"), 8, 1, 64)
    gmail_alias_mix_googlemail = bool(service.cfg.get("gmail_alias_mix_googlemail", True))
    return (
        provider,
        domain.rstrip("/"),
        str(service.cfg.get("freemail_username") or "").strip(),
        str(service.cfg.get("freemail_password") or ""),
        bool(service.cfg.get("openai_ssl_verify", True)),
        mail_domains,
        cf_temp_admin_auth,
        cloudmail_api_url,
        cloudmail_admin_email,
        cloudmail_admin_password,
        mail_curl_api_base,
        mail_curl_key,
        luckyous_api_base,
        luckyous_api_key,
        luckyous_project_code,
        luckyous_email_type,
        luckyous_domain,
        luckyous_variant_mode,
        luckyous_specified_email,
        graph_accounts_file,
        graph_accounts_mode,
        graph_api_base_url,
        graph_api_token,
        graph_tenant,
        graph_fetch_mode,
        gmail_imap_user,
        gmail_imap_pass,
        gmail_alias_emails,
        gmail_imap_server,
        gmail_imap_port,
        gmail_alias_tag_len,
        gmail_alias_mix_googlemail,
    )


def get_mail_client(service):
    sig = mail_client_signature(service)
    with service._lock:
        cached = service._mail_client
        cached_sig = service._mail_client_sig
    if cached is not None and cached_sig == sig:
        return cached

    (
        provider,
        base_url,
        username,
        password,
        verify_ssl,
        mail_domains,
        cf_temp_admin_auth,
        cloudmail_api_url,
        cloudmail_admin_email,
        cloudmail_admin_password,
        mail_curl_api_base,
        mail_curl_key,
        luckyous_api_base,
        luckyous_api_key,
        luckyous_project_code,
        luckyous_email_type,
        luckyous_domain,
        luckyous_variant_mode,
        luckyous_specified_email,
        graph_accounts_file,
        graph_accounts_mode,
        graph_api_base_url,
        graph_api_token,
        graph_tenant,
        graph_fetch_mode,
        gmail_imap_user,
        gmail_imap_pass,
        gmail_alias_emails,
        gmail_imap_server,
        gmail_imap_port,
        gmail_alias_tag_len,
        gmail_alias_mix_googlemail,
    ) = sig
    os.environ["MAIL_DOMAINS"] = mail_domains
    os.environ["CF_TEMP_ADMIN_AUTH"] = cf_temp_admin_auth
    os.environ["ADMIN_AUTH"] = cf_temp_admin_auth
    os.environ["CLOUDMAIL_API_URL"] = cloudmail_api_url
    os.environ["CLOUDMAIL_ADMIN_EMAIL"] = cloudmail_admin_email
    os.environ["CLOUDMAIL_ADMIN_PASSWORD"] = cloudmail_admin_password
    os.environ["MAIL_CURL_API_BASE"] = mail_curl_api_base
    os.environ["MAIL_CURL_KEY"] = mail_curl_key
    os.environ["LUCKYOUS_API_BASE"] = luckyous_api_base
    os.environ["LUCKYOUS_API_KEY"] = luckyous_api_key
    os.environ["LUCKYOUS_PROJECT_CODE"] = luckyous_project_code
    os.environ["LUCKYOUS_EMAIL_TYPE"] = luckyous_email_type
    os.environ["LUCKYOUS_DOMAIN"] = luckyous_domain
    os.environ["LUCKYOUS_VARIANT_MODE"] = luckyous_variant_mode
    os.environ["LUCKYOUS_SPECIFIED_EMAIL"] = luckyous_specified_email
    os.environ["GRAPH_ACCOUNTS_FILE"] = graph_accounts_file
    os.environ["GRAPH_ACCOUNTS_MODE"] = graph_accounts_mode
    os.environ["GRAPH_API_BASE_URL"] = graph_api_base_url
    os.environ["GRAPH_API_TOKEN"] = graph_api_token
    os.environ["GRAPH_API_URL"] = graph_api_base_url
    os.environ["MAIL_API_TOKEN"] = graph_api_token
    os.environ["GRAPH_TENANT"] = graph_tenant
    os.environ["GRAPH_FETCH_MODE"] = graph_fetch_mode
    os.environ["GMAIL_IMAP_USER"] = gmail_imap_user
    os.environ["GMAIL_IMAP_PASS"] = gmail_imap_pass
    os.environ["GMAIL_ALIAS_EMAILS"] = gmail_alias_emails
    os.environ["GMAIL_IMAP_SERVER"] = gmail_imap_server
    os.environ["GMAIL_IMAP_PORT"] = str(gmail_imap_port)
    os.environ["GMAIL_ALIAS_TAG_LEN"] = str(gmail_alias_tag_len)
    os.environ["GMAIL_ALIAS_MIX_GOOGLEMAIL"] = "1" if gmail_alias_mix_googlemail else "0"
    try:
        client = build_mail_service(
            provider,
            base_url=base_url,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            logger=None,
        )
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e

    with service._lock:
        service._mail_client = client
        service._mail_client_sig = sig
    return client


def mail_content_preview(text: str, limit: int = 200) -> str:
    s = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def mail_sender_text(raw_sender: Any) -> str:
    if isinstance(raw_sender, dict):
        name = str(raw_sender.get("name") or "").strip()
        addr = str(raw_sender.get("address") or raw_sender.get("email") or "").strip()
        if name and addr:
            return f"{name} <{addr}>"
        return name or addr
    if isinstance(raw_sender, list):
        vals = [mail_sender_text(x) for x in raw_sender]
        vals = [v for v in vals if v]
        return ", ".join(vals)
    return str(raw_sender or "").strip()


def _cf_safe_text(raw: Any, limit: int = 260) -> str:
    text = str(raw or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _cf_extract_error(payload: Any) -> str:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                code = str(first.get("code") or "").strip()
                msg = str(first.get("message") or first.get("error") or "").strip()
                if code and msg:
                    return f"{code}: {msg}"
                if msg:
                    return msg
        msg = str(payload.get("message") or payload.get("msg") or "").strip()
        if msg:
            return msg
    return "请求失败"


def _cf_has_error_code(payload: Any, code: int) -> bool:
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    for it in errors:
        if not isinstance(it, dict):
            continue
        try:
            c = int(it.get("code"))
        except Exception:
            continue
        if c == int(code):
            return True
    return False


def _cf_token(service) -> str:
    token = str(service.cfg.get("cf_api_token") or "").strip()
    if not token:
        raise ValueError("请先填写 Cloudflare API Token（cf_api_token）")
    return token


def _cf_clean_domain(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = text.strip("/")
    if ":" in text:
        text = text.split(":", 1)[0].strip()
    if "@" in text:
        text = text.split("@", 1)[1].strip()
    text = text.strip(".")
    return text


def _cf_clean_label(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    text = text.split(".", 1)[0]
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")
    if len(text) > 63:
        text = text[:63].rstrip("-")
    return text


def _cf_render_fqdn(label: str, zone_name: str) -> str:
    lb = _cf_clean_label(label)
    zone = _cf_clean_domain(zone_name)
    if not lb or not zone:
        return ""
    return f"{lb}.{zone}"


def _cf_relative_label(full_name: str, zone_name: str) -> str:
    name = _cf_clean_domain(full_name)
    zone = _cf_clean_domain(zone_name)
    if not name:
        return ""
    if zone and name.endswith("." + zone):
        return name[: -(len(zone) + 1)]
    return name


def _cf_suffix_label(base: str, idx: int) -> str:
    base_label = _cf_clean_label(base)
    if not base_label:
        return ""
    if idx <= 1:
        return base_label
    suffix = f"-{idx}"
    max_len = 63 - len(suffix)
    if max_len <= 0:
        return ""
    return f"{base_label[:max_len].rstrip('-')}{suffix}"


def _cf_random_label(prefix: str, random_len: int) -> str:
    plen = max(3, min(32, int(random_len)))
    pfx = _cf_clean_label(prefix)
    tail = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(plen))
    if pfx:
        room = 63 - (len(pfx) + 1)
        if room <= 0:
            return pfx[:63]
        return f"{pfx}-{tail[:room]}"
    return tail[:63]


def _cf_headers(service) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_cf_token(service)}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _cf_request(
    service,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 35,
) -> dict[str, Any]:
    url = f"https://api.cloudflare.com/client/v4{path}"
    proxy = mail_proxy(service)
    verify_ssl = bool(service.cfg.get("openai_ssl_verify", True))
    try:
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            json=json_body,
            headers=_cf_headers(service),
            proxies=proxy,
            impersonate="safari",
            verify=verify_ssl,
            timeout=timeout,
        )
    except Exception as e:
        raise RuntimeError(f"Cloudflare API 请求失败: {e}") from e

    status = int(resp.status_code or 0)
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if not (200 <= status < 300):
        detail = _cf_extract_error(payload)
        raw = _cf_safe_text(getattr(resp, "text", ""))
        hint = ""
        if status == 403 and _cf_has_error_code(payload, 10000):
            hint = (
                "。请检查 Token 是否包含对应资源与权限："
                "账户->Workers 脚本(读取/编辑)；区域->DNS(读取/编辑)"
            )
        raise RuntimeError(f"Cloudflare API {method} {path} HTTP {status}: {detail or raw}{hint}")

    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"Cloudflare API {method} {path} 失败: {_cf_extract_error(payload)}")

    if not isinstance(payload, dict):
        raise RuntimeError("Cloudflare API 返回格式异常")
    return payload


def _cf_list_zones_internal(service) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while page <= 20:
        payload = _cf_request(
            service,
            "GET",
            "/zones",
            params={"page": str(page), "per_page": "50", "status": "active"},
            timeout=25,
        )
        result = payload.get("result") if isinstance(payload, dict) else []
        if not isinstance(result, list):
            break
        if not result:
            break
        rows.extend([x for x in result if isinstance(x, dict)])
        info = payload.get("result_info") if isinstance(payload, dict) else {}
        if not isinstance(info, dict):
            break
        total_pages = int(info.get("total_pages") or page)
        if page >= total_pages:
            break
        page += 1
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in rows:
        zid = str(it.get("id") or "").strip()
        zname = _cf_clean_domain(it.get("name") or "")
        if not zid or not zname or zid in seen:
            continue
        seen.add(zid)
        account = it.get("account") if isinstance(it.get("account"), dict) else {}
        out.append(
            {
                "id": zid,
                "name": zname,
                "status": str(it.get("status") or "").strip() or "active",
                "account_id": str(account.get("id") or "").strip(),
                "account_name": str(account.get("name") or "").strip(),
            }
        )
    out.sort(key=lambda x: (str(x.get("name") or ""), str(x.get("id") or "")))
    return out


def _cf_get_zone(service, zone_id: str) -> dict[str, Any]:
    zid = str(zone_id or "").strip()
    if not zid:
        raise ValueError("zone_id 不能为空")
    payload = _cf_request(service, "GET", f"/zones/{zid}", timeout=25)
    result = payload.get("result") if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        raise RuntimeError("读取 Zone 信息失败")
    return result


def mail_cf_zones(service) -> dict[str, Any]:
    zones = _cf_list_zones_internal(service)
    selected_zone_id = ""
    with service._lock:
        selected_zone_id = str(service.cfg.get("cf_zone_id") or "").strip()
        cfg_account_id = str(service.cfg.get("cf_account_id") or "").strip()
        worker_script = str(service.cfg.get("cf_worker_script") or "mailfree").strip() or "mailfree"
        worker_binding = str(service.cfg.get("cf_worker_mail_domain_binding") or "MAIL_DOMAIN").strip() or "MAIL_DOMAIN"
        target_domain = _cf_clean_domain(service.cfg.get("cf_dns_target_domain") or "")

    zone_ids = {str(x.get("id") or "").strip() for x in zones}
    if selected_zone_id not in zone_ids:
        selected_zone_id = str((zones[0] or {}).get("id") or "") if zones else ""

    zone_name_map = {str(x.get("id") or ""): str(x.get("name") or "") for x in zones}
    if not target_domain:
        target_domain = _cf_clean_domain(zone_name_map.get(selected_zone_id) or "")

    account_id = cfg_account_id
    if not account_id:
        for z in zones:
            aid = str(z.get("account_id") or "").strip()
            if aid:
                account_id = aid
                break

    return {
        "zones": zones,
        "total": len(zones),
        "selected_zone_id": selected_zone_id,
        "target_domain": target_domain,
        "account_id": account_id,
        "worker_script": worker_script,
        "worker_binding": worker_binding,
    }


def mail_cf_dns_list(service, zone_id: str) -> dict[str, Any]:
    zid = str(zone_id or "").strip()
    if not zid:
        raise ValueError("请先选择要查看的域名")
    zone = _cf_get_zone(service, zid)
    zone_name = _cf_clean_domain(zone.get("name") or "")
    if not zone_name:
        raise RuntimeError("Zone 名称为空，无法读取 DNS")

    rows: list[dict[str, Any]] = []
    page = 1
    while page <= 30:
        payload = _cf_request(
            service,
            "GET",
            f"/zones/{zid}/dns_records",
            params={"type": "CNAME", "page": str(page), "per_page": "200"},
            timeout=30,
        )
        result = payload.get("result") if isinstance(payload, dict) else []
        if not isinstance(result, list) or not result:
            break
        for item in result:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or "").strip()
            name = _cf_clean_domain(item.get("name") or "")
            content = _cf_clean_domain(item.get("content") or "")
            if not rid or not name:
                continue
            rows.append(
                {
                    "key": rid,
                    "id": rid,
                    "type": "CNAME",
                    "name": name,
                    "label": _cf_relative_label(name, zone_name),
                    "zone_id": zid,
                    "zone_name": zone_name,
                    "target": content,
                    "ttl": int(item.get("ttl") or 1),
                    "proxied": bool(item.get("proxied", False)),
                }
            )
        info = payload.get("result_info") if isinstance(payload, dict) else {}
        total_pages = int((info or {}).get("total_pages") or page)
        if page >= total_pages:
            break
        page += 1

    rows.sort(key=lambda x: (str(x.get("label") or ""), str(x.get("id") or "")))
    return {
        "zone_id": zid,
        "zone_name": zone_name,
        "records": rows,
        "total": len(rows),
    }


def mail_cf_dns_create_batch(service, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload or {}
    zid = str(data.get("zone_id") or "").strip()
    if not zid:
        raise ValueError("请先选择域名")

    zone = _cf_get_zone(service, zid)
    zone_name = _cf_clean_domain(zone.get("name") or "")
    if not zone_name:
        raise RuntimeError("目标 Zone 无效")

    target_domain = _cf_clean_domain(data.get("target_domain") or "")
    if not target_domain:
        target_domain = zone_name

    count = service._to_int(data.get("count"), 1, 1, 200)
    mode = str(data.get("mode") or "random").strip().lower()
    if mode not in {"random", "manual"}:
        mode = "random"
    random_len = service._to_int(data.get("random_length"), 8, 3, 32)
    random_prefix = _cf_clean_label(data.get("random_prefix") or "")
    manual_name = _cf_clean_label(data.get("manual_name") or "")
    proxied = service._to_bool(data.get("proxied"), False)
    ttl = service._to_int(data.get("ttl"), 1, 1, 86400)

    existing_rows = mail_cf_dns_list(service, zid).get("records") or []
    existing = {str((x or {}).get("label") or "").strip().lower() for x in existing_rows if isinstance(x, dict)}
    generated: list[str] = []

    if mode == "manual":
        if not manual_name:
            raise ValueError("手动模式下请先填写二级域名前缀")
        idx = 1
        max_rounds = max(300, count * 20)
        while len(generated) < count and idx <= max_rounds:
            label = _cf_suffix_label(manual_name, 1 if idx == 1 else (idx - 1))
            idx += 1
            if not label:
                continue
            low = label.lower()
            if low in existing or low in generated:
                continue
            generated.append(low)
    else:
        max_rounds = max(300, count * 40)
        attempts = 0
        while len(generated) < count and attempts < max_rounds:
            attempts += 1
            label = _cf_random_label(random_prefix, random_len)
            low = str(label or "").strip().lower()
            if not low or low in existing or low in generated:
                continue
            generated.append(low)

    if len(generated) < count:
        raise RuntimeError("可用二级域名不足，请调整前缀或长度后重试")

    ok = 0
    fail = 0
    errors: list[dict[str, str]] = []
    created: list[dict[str, Any]] = []
    for lb in generated:
        fqdn = _cf_render_fqdn(lb, zone_name)
        if not fqdn:
            fail += 1
            errors.append({"name": lb, "error": "域名生成失败"})
            continue
        try:
            res = _cf_request(
                service,
                "POST",
                f"/zones/{zid}/dns_records",
                json_body={
                    "type": "CNAME",
                    "name": fqdn,
                    "content": target_domain,
                    "ttl": ttl,
                    "proxied": proxied,
                },
                timeout=30,
            )
            item = res.get("result") if isinstance(res, dict) else {}
            ok += 1
            created.append(
                {
                    "id": str((item or {}).get("id") or "").strip(),
                    "name": _cf_clean_domain((item or {}).get("name") or fqdn),
                    "label": lb,
                    "target": _cf_clean_domain((item or {}).get("content") or target_domain),
                    "ttl": int((item or {}).get("ttl") or ttl),
                    "proxied": bool((item or {}).get("proxied", proxied)),
                    "zone_name": zone_name,
                    "zone_id": zid,
                }
            )
        except Exception as e:
            fail += 1
            errors.append({"name": fqdn, "error": str(e)})

    service.log(f"[MailFree][Cloudflare] DNS 批量新增: zone={zone_name} 成功 {ok} 失败 {fail}")
    return {
        "zone_id": zid,
        "zone_name": zone_name,
        "target_domain": target_domain,
        "ok": ok,
        "fail": fail,
        "total": len(generated),
        "records": created,
        "errors": errors,
    }


def mail_cf_dns_update(service, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload or {}
    zid = str(data.get("zone_id") or "").strip()
    rid = str(data.get("record_id") or "").strip()
    if not zid or not rid:
        raise ValueError("zone_id 与 record_id 不能为空")

    zone = _cf_get_zone(service, zid)
    zone_name = _cf_clean_domain(zone.get("name") or "")
    if not zone_name:
        raise RuntimeError("Zone 无效")

    label = _cf_clean_label(data.get("label") or "")
    if not label:
        raise ValueError("请填写二级域名前缀")
    fqdn = _cf_render_fqdn(label, zone_name)
    if not fqdn:
        raise RuntimeError("域名生成失败")

    target_domain = _cf_clean_domain(data.get("target_domain") or "")
    if not target_domain:
        target_domain = zone_name

    proxied = service._to_bool(data.get("proxied"), False)
    ttl = service._to_int(data.get("ttl"), 1, 1, 86400)

    res = _cf_request(
        service,
        "PATCH",
        f"/zones/{zid}/dns_records/{rid}",
        json_body={
            "type": "CNAME",
            "name": fqdn,
            "content": target_domain,
            "ttl": ttl,
            "proxied": proxied,
        },
        timeout=30,
    )
    item = res.get("result") if isinstance(res, dict) else {}
    service.log(f"[MailFree][Cloudflare] DNS 已更新: {fqdn} -> {target_domain}")
    return {
        "record": {
            "id": str((item or {}).get("id") or rid).strip(),
            "name": _cf_clean_domain((item or {}).get("name") or fqdn),
            "label": label,
            "target": _cf_clean_domain((item or {}).get("content") or target_domain),
            "ttl": int((item or {}).get("ttl") or ttl),
            "proxied": bool((item or {}).get("proxied", proxied)),
            "zone_name": zone_name,
            "zone_id": zid,
        }
    }


def mail_cf_dns_delete_batch(service, zone_id: str, record_ids: list[Any]) -> dict[str, Any]:
    zid = str(zone_id or "").strip()
    if not zid:
        raise ValueError("请先选择域名")

    ordered: list[str] = []
    seen: set[str] = set()
    for raw in record_ids or []:
        rid = str(raw or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        ordered.append(rid)
    if not ordered:
        raise ValueError("请先勾选要删除的 DNS 记录")

    ok = 0
    fail = 0
    errors: list[dict[str, str]] = []
    for rid in ordered:
        try:
            _cf_request(service, "DELETE", f"/zones/{zid}/dns_records/{rid}", timeout=20)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append({"id": rid, "error": str(e)})

    service.log(f"[MailFree][Cloudflare] DNS 批量删除: zone={zid} 成功 {ok} 失败 {fail}")
    return {
        "zone_id": zid,
        "ok": ok,
        "fail": fail,
        "total": len(ordered),
        "errors": errors,
    }


def mail_cf_worker_set_mail_domain(service, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload or {}
    mail_domain = _cf_clean_domain(data.get("mail_domain") or "")
    if not mail_domain:
        raise ValueError("mail_domain 不能为空")

    with service._lock:
        provider = normalize_mail_provider(service.cfg.get("mail_service_provider") or "mailfree")
    if provider != "mailfree":
        raise ValueError("请先将邮箱服务切换为 MailFree，再执行域名同步")

    client = get_mail_client(service)
    if not hasattr(client, "add_domain"):
        raise RuntimeError("当前 MailFree 客户端不支持域名同步，请更新程序")

    proxy = mail_proxy(service)
    try:
        res = client.add_domain(mail_domain, proxies=proxy)
    except MailServiceError as e:
        msg = str(e)
        low = msg.lower()
        if "403" in msg or "forbidden" in low:
            raise RuntimeError(
                "同步到 MailFree 失败：当前账号无权管理域名，请使用严格管理员账号登录 MailFree。"
            ) from e
        raise RuntimeError(f"同步到 MailFree 失败：{msg}") from e

    existed = bool((res or {}).get("existed"))
    service.log(
        f"[MailFree][Cloudflare] 已同步域名到 MailFree: {mail_domain}"
        + ("（已存在）" if existed else "")
    )
    return {
        "ok": True,
        "mail_domain": mail_domain,
        "synced": True,
        "existed": existed,
    }


def record_mail_domain_error(service, domain: str) -> int:
    d = str(domain or "").strip().lower()
    if not d:
        return 0
    with service._lock:
        counts = service._normalize_domain_error_counts(service.cfg.get("mail_domain_error_counts") or {})
        now = int(counts.get(d, 0)) + 1
        counts[d] = now
        service.cfg["mail_domain_error_counts"] = counts
        save_config(service.cfg)
    return now


def record_mail_domain_registered(service, domain: str) -> int:
    d = str(domain or "").strip().lower()
    if not d:
        return 0
    with service._lock:
        counts = service._normalize_domain_registered_counts(
            service.cfg.get("mail_domain_registered_counts") or {}
        )
        now = int(counts.get(d, 0)) + 1
        counts[d] = now
        service.cfg["mail_domain_registered_counts"] = counts
        save_config(service.cfg)
    return now


def mail_domain_stats(service) -> dict[str, Any]:
    with service._lock:
        provider = normalize_mail_provider(service.cfg.get("mail_service_provider") or "mailfree")
        selected = service._normalize_domain_list(service.cfg.get("mail_domain_allowlist") or [])
        counts = service._normalize_domain_error_counts(service.cfg.get("mail_domain_error_counts") or {})
        registered = service._normalize_domain_registered_counts(
            service.cfg.get("mail_domain_registered_counts") or {}
        )
    return {
        "provider": provider,
        "selected": selected,
        "error_counts": counts,
        "registered_counts": registered,
    }


def mail_providers(service) -> dict[str, Any]:
    with service._lock:
        current = normalize_mail_provider(service.cfg.get("mail_service_provider") or "mailfree")
    return {
        "items": available_mail_providers(),
        "current": current,
    }


def mail_graph_account_files(service) -> dict[str, Any]:
    current = str(service.cfg.get("graph_accounts_file") or "").strip()
    items = [{"label": current, "value": current}] if current else []
    return {"items": items, "current": current}


def mail_import_graph_account_file(service, filename: str, content: str) -> dict[str, Any]:
    name = os.path.basename(str(filename or "").strip())
    if not name:
        raise ValueError("请选择 txt 文件")
    if not name.lower().endswith(".txt"):
        raise ValueError("仅支持 .txt 文件")
    if len(name) > 128:
        raise ValueError("文件名过长")

    raw = str(content or "")
    lines = [str(x).strip() for x in raw.replace("\r\n", "\n").split("\n")]
    valid_rows: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if not line or line.startswith("#"):
            continue
        line = line.lstrip("\ufeff")
        parts = line.split("----", 3)
        if len(parts) < 4:
            raise ValueError(f"第 {idx} 行格式错误：必须是 邮箱----密码----client_id----令牌")
        email = str(parts[0] or "").strip().lstrip("\ufeff").lower()
        password = str(parts[1] or "").strip()
        client_id = str(parts[2] or "").strip()
        token = str(parts[3] or "").strip()
        if not email or "@" not in email:
            raise ValueError(f"第 {idx} 行邮箱无效")
        if not password:
            raise ValueError(f"第 {idx} 行密码不能为空")
        if not client_id:
            raise ValueError(f"第 {idx} 行 client_id 不能为空")
        if not token:
            raise ValueError(f"第 {idx} 行令牌不能为空")
        valid_rows.append(f"{email}----{password}----{client_id}----{token}")

    if not valid_rows:
        raise ValueError("文件没有可用账号行")

    target_path = os.path.abspath(name)
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("\n".join(valid_rows) + "\n")
    except Exception as e:
        raise RuntimeError(f"保存文件失败: {e}") from e

    with service._lock:
        service.cfg["graph_accounts_file"] = name
        service._mail_client = None
        service._mail_client_sig = None
        save_config(service.cfg)

    return {
        "filename": name,
        "path": target_path,
        "count": len(valid_rows),
    }


def mail_delete_graph_account_file(service, filename: str) -> dict[str, Any]:
    name = os.path.basename(str(filename or "").strip())
    if not name:
        raise ValueError("请先选择要删除的 Graph 账号文件")
    if not name.lower().endswith(".txt"):
        raise ValueError("仅支持删除 .txt 文件")

    target_path = os.path.abspath(name)
    if not os.path.isfile(target_path):
        raise ValueError("文件不存在")

    try:
        os.remove(target_path)
    except Exception as e:
        raise RuntimeError(f"删除文件失败: {e}") from e

    with service._lock:
        current = str(service.cfg.get("graph_accounts_file") or "").strip()
        if current == name:
            service.cfg["graph_accounts_file"] = ""
            service._mail_client = None
            service._mail_client_sig = None
            save_config(service.cfg)

    return {"filename": name, "deleted": True}


def mail_overview(service, limit: Any = 120, offset: Any = 0) -> dict[str, Any]:
    lim = service._to_int(limit, 120, 1, 500)
    off = service._to_int(offset, 0, 0, 100000)
    providers = available_mail_providers()
    current = normalize_mail_provider(service.cfg.get("mail_service_provider") or "mailfree")
    selected = service._normalize_domain_list(service.cfg.get("mail_domain_allowlist") or [])
    err_counts = service._normalize_domain_error_counts(service.cfg.get("mail_domain_error_counts") or {})
    registered_counts = service._normalize_domain_registered_counts(
        service.cfg.get("mail_domain_registered_counts") or {}
    )
    proxy = mail_proxy(service)

    try:
        client = get_mail_client(service)
        domains = client.list_domains(proxies=proxy)
        mailboxes = client.list_mailboxes(limit=lim, offset=off, proxies=proxy)
    except RuntimeError as e:
        # Graph 模式下，账号文件为空或被删除时不阻断页面，返回空列表等待用户重新选择。
        if current == "graph":
            msg = str(e)
            if ("Graph 账号文件不存在" in msg) or ("Graph 账号文件为空或格式无效" in msg):
                domains = []
                mailboxes = []
            else:
                raise
        else:
            raise
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e

    rows: list[dict[str, Any]] = []
    for idx, it in enumerate(mailboxes):
        if not isinstance(it, dict):
            continue
        addr = str(it.get("address") or it.get("mailbox") or it.get("email") or "").strip()
        if not addr:
            continue
        created = str(it.get("created_at") or it.get("created") or "-")
        expires = str(it.get("expires_at") or it.get("expires") or "-")
        try:
            count = int(it.get("count") or 0)
        except Exception:
            count = 0
        rows.append(
            {
                "key": f"{addr}:{idx}",
                "address": addr,
                "created_at": created,
                "expires_at": expires,
                "count": max(0, count),
            }
        )

    domains_out = [str(x).strip().lower() for x in domains if str(x).strip()]
    domains_out = list(dict.fromkeys(domains_out))

    # 与邮件服务返回的最新域名集合对齐，清理 gui_config.json 中的历史脏域名与统计。
    if domains_out:
        domain_set = set(domains_out)
        selected_clean = [d for d in selected if d in domain_set]
        if not selected_clean:
            selected_clean = list(domains_out)
        err_counts_clean = {k: int(v) for k, v in err_counts.items() if k in domain_set and int(v) > 0}
        registered_counts_clean = {
            k: int(v) for k, v in registered_counts.items() if k in domain_set and int(v) > 0
        }

        changed = (
            selected_clean != selected
            or err_counts_clean != err_counts
            or registered_counts_clean != registered_counts
        )
        if changed:
            with service._lock:
                service.cfg["mail_domain_allowlist"] = selected_clean
                service.cfg["mail_domain_error_counts"] = err_counts_clean
                service.cfg["mail_domain_registered_counts"] = registered_counts_clean
                save_config(service.cfg)
            selected = selected_clean
            err_counts = err_counts_clean
            registered_counts = registered_counts_clean
    domain_stats = {
        dm: {
            "selected": (dm in selected) if selected else True,
            "errors": int(err_counts.get(dm, 0)),
            "registered": int(registered_counts.get(dm, 0)),
        }
        for dm in domains_out
    }

    return {
        "providers": providers,
        "current": current,
        "domains": domains_out,
        "selected_domains": selected,
        "domain_error_counts": err_counts,
        "domain_registered_counts": registered_counts,
        "domain_stats": domain_stats,
        "mailboxes": rows,
        "mailbox_total": len(rows),
    }


def mail_generate_mailbox(service) -> dict[str, Any]:
    client = get_mail_client(service)
    proxy = mail_proxy(service)
    random_domain = bool(service.cfg.get("mailfree_random_domain", True))
    selected_domains = service._normalize_domain_list(service.cfg.get("mail_domain_allowlist") or [])
    mailbox_custom_enabled = bool(service.cfg.get("mailbox_custom_enabled", False))
    mailbox_prefix = str(service.cfg.get("mailbox_prefix") or "").strip() if mailbox_custom_enabled else ""
    mailbox_random_len = (
        service._to_int(service.cfg.get("mailbox_random_len"), 0, 0, 32)
        if mailbox_custom_enabled
        else 0
    )
    try:
        email = client.generate_mailbox(
            random_domain=random_domain,
            allowed_domains=selected_domains,
            local_prefix=mailbox_prefix,
            random_length=mailbox_random_len,
            proxies=proxy,
        )
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e
    service.log(f"[邮箱] 已生成临时邮箱: {email}")
    return {
        "email": email,
        "mailbox_custom_enabled": mailbox_custom_enabled,
        "random_domain": random_domain,
        "mailbox_prefix": mailbox_prefix,
        "mailbox_random_len": mailbox_random_len,
    }


def mail_list_emails(service, mailbox: str) -> dict[str, Any]:
    target = str(mailbox or "").strip()
    if not target:
        raise ValueError("请先选择邮箱账号")
    client = get_mail_client(service)
    proxy = mail_proxy(service)
    try:
        mails = client.list_emails(target, proxies=proxy)
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e

    rows: list[dict[str, Any]] = []
    for idx, it in enumerate(mails):
        if not isinstance(it, dict):
            continue
        mid = str(it.get("id") or f"mail-{idx}").strip()
        sender = mail_sender_text(it.get("from") or it.get("sender"))
        subject = str(it.get("subject") or "(无主题)").strip() or "(无主题)"
        received = str(it.get("date") or it.get("created_at") or "-")
        preview = mail_content_preview(it.get("preview") or it.get("intro") or it.get("text") or "")
        rows.append(
            {
                "key": f"{mid}:{idx}",
                "id": mid,
                "from": sender,
                "subject": subject,
                "date": received,
                "preview": preview,
                "mailbox": target,
            }
        )

    return {"mailbox": target, "total": len(rows), "items": rows}


def mail_get_email_detail(service, email_id: str) -> dict[str, Any]:
    target = str(email_id or "").strip()
    if not target:
        raise ValueError("邮件 ID 不能为空")
    client = get_mail_client(service)
    proxy = mail_proxy(service)
    try:
        detail = client.get_email_detail(target, proxies=proxy)
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e

    content = str(detail.get("content") or "").strip()
    if not content:
        try:
            content = json.dumps(detail, ensure_ascii=False, indent=2)
        except Exception:
            content = mail_content_preview(str(detail), limit=1000)
    return {
        "id": str(detail.get("id") or target),
        "from": str(detail.get("from") or "-"),
        "subject": str(detail.get("subject") or "(无主题)"),
        "date": str(detail.get("date") or "-"),
        "text": str(detail.get("text") or ""),
        "html": str(detail.get("html") or ""),
        "raw": str(detail.get("raw") or ""),
        "content": content,
    }


def mail_delete_email(service, email_id: str) -> dict[str, Any]:
    target = str(email_id or "").strip()
    if not target:
        raise ValueError("邮件 ID 不能为空")
    client = get_mail_client(service)
    proxy = mail_proxy(service)
    try:
        res = client.delete_email(target, proxies=proxy)
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e
    service.log(f"[邮箱] 已删除邮件: id={target}")
    return {
        "id": target,
        "success": bool(res.get("success", True)) if isinstance(res, dict) else True,
    }


def mail_delete_emails(service, ids: list[Any]) -> dict[str, Any]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        ordered.append(mid)
    if not ordered:
        raise ValueError("请先选择要删除的邮件")

    ok = 0
    fail = 0
    errors: list[dict[str, str]] = []
    for mid in ordered:
        try:
            mail_delete_email(service, mid)
            ok += 1
        except Exception as e:
            fail += 1
            err_text = str(e)
            service.log(f"[邮箱] 删除邮件失败: id={mid} -> {err_text}")
            errors.append({"id": mid, "error": err_text})

    return {
        "ok": ok,
        "fail": fail,
        "total": len(ordered),
        "errors": errors,
    }


def mail_clear_emails(service, mailbox: str) -> dict[str, Any]:
    target = str(mailbox or "").strip()
    if not target:
        raise ValueError("请先选择邮箱账号")
    client = get_mail_client(service)
    proxy = mail_proxy(service)
    try:
        res = client.clear_emails(target, proxies=proxy)
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e
    deleted = 0
    if isinstance(res, dict):
        try:
            deleted = int(res.get("deleted") or 0)
        except Exception:
            deleted = 0
    service.log(f"[邮箱] 已清空邮箱 {target}，删除 {deleted} 封")
    return {"mailbox": target, "deleted": max(0, deleted)}


def mail_delete_mailbox(service, address: str) -> dict[str, Any]:
    target = str(address or "").strip()
    if not target:
        raise ValueError("请先选择邮箱账号")
    client = get_mail_client(service)
    proxy = mail_proxy(service)
    try:
        res = client.delete_mailbox(target, proxies=proxy)
    except MailServiceError as e:
        raise RuntimeError(str(e)) from e
    method = str(res.get("api_method") or "") if isinstance(res, dict) else ""
    path = str(res.get("api_path") or "") if isinstance(res, dict) else ""
    api_text = f"{method} {path}".strip()
    if api_text:
        service.log(f"[邮箱] 已删除邮箱账号: {target} · 接口 {api_text}")
    else:
        service.log(f"[邮箱] 已删除邮箱账号: {target}")
    return {
        "address": target,
        "success": True,
        "api_method": method,
        "api_path": path,
    }


def mail_delete_mailboxes(service, addresses: list[Any]) -> dict[str, Any]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in addresses:
        addr = str(raw or "").strip()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        ordered.append(addr)
    if not ordered:
        raise ValueError("请先选择要删除的邮箱")

    total = len(ordered)
    worker_count = min(
        total,
        service._to_int(service.cfg.get("mail_delete_concurrency"), 4, 1, 12),
    )
    service.log(f"[邮箱] 批量删除启动: 总数 {total}，并发 {worker_count}")

    ok = 0
    fail = 0
    errors: list[dict[str, str]] = []
    api_used: dict[str, int] = {}
    state_lock = threading.Lock()

    def _run_one(idx_addr: tuple[int, str]) -> tuple[int, dict[str, Any]]:
        idx, addr = idx_addr
        try:
            res = mail_delete_mailbox(service, addr)
            method = str((res or {}).get("api_method") or "")
            path = str((res or {}).get("api_path") or "")
            api = f"{method} {path}".strip()
            with state_lock:
                nonlocal ok
                ok += 1
                if api:
                    api_used[api] = int(api_used.get(api, 0)) + 1
            return idx, {"address": addr, "success": True, "api": api}
        except Exception as e:
            err_text = str(e)
            service.log(f"[邮箱] 删除失败: {addr} -> {err_text}")
            with state_lock:
                nonlocal fail
                fail += 1
            return idx, {"address": addr, "success": False, "error": err_text}

    ordered_pairs = list(enumerate(ordered))
    results_by_idx: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_run_one, it) for it in ordered_pairs]
        for fut in as_completed(futures):
            try:
                idx, item = fut.result()
            except Exception as e:
                idx = -1
                item = {"address": "-", "success": False, "error": str(e)}
            results_by_idx[idx] = item

    ordered_results: list[dict[str, Any]] = []
    for i in range(total):
        item = results_by_idx.get(i) or {
            "address": ordered[i],
            "success": False,
            "error": "未知错误",
        }
        ordered_results.append(item)
        if not item.get("success"):
            errors.append(
                {
                    "address": str(item.get("address") or ""),
                    "error": str(item.get("error") or "未知错误"),
                }
            )

    api_summary = [
        {"api": k, "count": int(v)}
        for k, v in sorted(api_used.items(), key=lambda x: (-int(x[1]), str(x[0])))
    ]
    if api_summary:
        apis = "；".join([f"{it['api']} ×{it['count']}" for it in api_summary[:4]])
        service.log(f"[邮箱] 批量删除接口统计: {apis}")

    service.log(f"[邮箱] 批量删除结束: 成功 {ok}，失败 {fail}")
    return {
        "ok": ok,
        "fail": fail,
        "total": total,
        "errors": errors,
        "api_summary": api_summary,
        "concurrency": worker_count,
        "results": ordered_results,
    }


__all__ = [
    "get_mail_client",
    "mail_cf_dns_create_batch",
    "mail_cf_dns_delete_batch",
    "mail_cf_dns_list",
    "mail_cf_dns_update",
    "mail_cf_worker_set_mail_domain",
    "mail_cf_zones",
    "mail_graph_account_files",
    "mail_import_graph_account_file",
    "mail_delete_graph_account_file",
    "mail_clear_emails",
    "mail_client_signature",
    "mail_content_preview",
    "mail_delete_email",
    "mail_delete_emails",
    "mail_delete_mailbox",
    "mail_delete_mailboxes",
    "mail_domain_stats",
    "mail_generate_mailbox",
    "mail_get_email_detail",
    "mail_list_emails",
    "mail_overview",
    "mail_providers",
    "mail_proxy",
    "mail_sender_text",
    "record_mail_domain_error",
    "record_mail_domain_registered",
]
