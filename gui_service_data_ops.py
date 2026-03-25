from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from typing import Any

from gui_config_store import ACCOUNTS_TXT, save_config
from gui_http_utils import _http_post_json


def accounts_txt_path(service) -> str:
    """与 r_with_pwd 写入逻辑一致：有 TOKEN_OUTPUT_DIR 则用其下 accounts.txt。"""
    outdir = os.getenv("TOKEN_OUTPUT_DIR", "").strip()
    if outdir:
        return os.path.join(outdir, ACCOUNTS_TXT)
    return ACCOUNTS_TXT


def emails_from_accounts_json(fp: str) -> set[str]:
    """从导出 JSON 的 accounts 数组收集邮箱，用于删文件时同步 accounts.txt。"""
    emails: set[str] = set()
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        for acc in data.get("accounts", []):
            if not isinstance(acc, dict):
                continue
            e = (
                acc.get("name")
                or (acc.get("credentials") or {}).get("email")
                or (acc.get("extra") or {}).get("email")
            )
            if e and isinstance(e, str):
                emails.add(e.strip())
    except Exception:
        pass
    return emails


def email_from_account_entry(acc: dict[str, Any]) -> str:
    if not isinstance(acc, dict):
        return ""
    e = str(acc.get("name") or "").strip().lower()
    if e:
        return e
    creds = acc.get("credentials") or {}
    if isinstance(creds, dict):
        return str(creds.get("email") or "").strip().lower()
    return ""


def build_local_account_index(service) -> dict[str, dict[str, Any]]:
    """从本地 accounts_*.json 建立 email -> account 字典（新文件优先）。"""
    out: dict[str, dict[str, Any]] = {}
    files = sorted(glob.glob("accounts_*.json"), key=os.path.getmtime, reverse=True)
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                root = json.load(f)
            arr = root.get("accounts", [])
            if not isinstance(arr, list):
                continue
            for acc in arr:
                em = email_from_account_entry(acc)
                if em and em not in out and isinstance(acc, dict):
                    out[em] = acc
        except Exception:
            continue
    return out


def build_email_source_files_map(service) -> dict[str, list[str]]:
    """建立 email -> [来源文件名...] 映射（按文件时间倒序）。"""
    out: dict[str, list[str]] = {}
    files = sorted(glob.glob("accounts_*.json"), key=os.path.getmtime, reverse=True)
    for fp in files:
        name = os.path.basename(fp)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                root = json.load(f)
            arr = root.get("accounts", [])
            if not isinstance(arr, list):
                continue
            for acc in arr:
                if not isinstance(acc, dict):
                    continue
                em = email_from_account_entry(acc)
                if not em:
                    continue
                lst = out.setdefault(em, [])
                if name not in lst:
                    lst.append(name)
        except Exception:
            continue
    return out


def source_label(files: list[str]) -> str:
    if not files:
        return "-"
    if len(files) == 1:
        return files[0]
    return f"{files[0]} +{len(files) - 1}"


def save_json_file_note(service, path: str, note: str) -> dict[str, Any]:
    target = os.path.abspath(str(path or "").strip())
    if not target:
        raise ValueError("path 不能为空")

    allow = {os.path.abspath(p) for p in glob.glob("accounts_*.json")}
    if target not in allow or not os.path.isfile(target):
        raise ValueError("目标 JSON 文件不存在或不可编辑")

    name = os.path.basename(target)
    clean = str(note or "").strip()
    if len(clean) > 120:
        clean = clean[:120]

    with service._lock:
        notes = service._normalize_json_file_notes(service.cfg.get("json_file_notes") or {})
        if clean:
            notes[name] = clean
        else:
            notes.pop(name, None)
        service.cfg["json_file_notes"] = notes
        save_config(service.cfg)

    service.log(f"已保存备注: {name} -> {clean or '-'}")
    return {
        "path": target,
        "name": name,
        "note": clean,
    }


def list_json_files(service) -> dict[str, Any]:
    with service._lock:
        notes_map = service._normalize_json_file_notes(service.cfg.get("json_file_notes") or {})

    files = sorted(
        glob.glob("accounts_*.json"),
        key=os.path.getmtime,
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    total = 0
    for fp in files:
        fp_abs = os.path.abspath(fp)
        name = os.path.basename(fp_abs)
        try:
            with open(fp_abs, "r", encoding="utf-8") as f:
                data = json.load(f)
            cnt = len(data.get("accounts", []))
        except Exception:
            cnt = 0
        try:
            cdate = datetime.fromtimestamp(os.path.getctime(fp_abs)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            cdate = "-"
        total += cnt
        items.append(
            {
                "path": fp_abs,
                "name": name,
                "count": cnt,
                "created": cdate,
                "note": str(notes_map.get(name) or ""),
                "file_color_idx": service._file_color_index(name),
            }
        )
    return {"items": items, "file_count": len(items), "account_total": total}


def list_accounts(service) -> dict[str, Any]:
    lines: list[str] = []
    ap = accounts_txt_path(service)
    if os.path.exists(ap):
        try:
            with open(ap, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        except Exception:
            lines = []

    local_counts: dict[str, int] = {}
    for line in lines:
        ep = line.split("----", 1)[0].strip().lower()
        if ep:
            local_counts[ep] = local_counts.get(ep, 0) + 1

    email_files_map = build_email_source_files_map(service)
    file_options = [
        os.path.basename(p)
        for p in sorted(glob.glob("accounts_*.json"), key=os.path.getmtime, reverse=True)
    ]

    with service._lock:
        remote_ready = service._remote_sync_status_ready
        remote_counts = dict(service._remote_email_counts)

    items: list[dict[str, Any]] = []
    for i, line in enumerate(lines, start=1):
        parts = line.split("----", 1)
        email = parts[0]
        pwd = parts[1] if len(parts) > 1 else ""
        ep = email.strip().lower()
        status = "normal"
        src_files = list(email_files_map.get(ep, []))
        primary_source = str(src_files[0] if src_files else "")
        if remote_ready:
            remote_cnt = int(remote_counts.get(ep, 0))
            local_cnt = int(local_counts.get(ep, 0))
            if local_cnt > 1 or remote_cnt > 1:
                status = "dup"
            elif remote_cnt > 0:
                status = "ok"
            else:
                status = "pending"
        items.append(
            {
                "key": f"{i}:{email}",
                "index": i,
                "email": email,
                "password": pwd,
                "status": status,
                "source": source_label(src_files),
                "source_files": src_files,
                "source_primary": primary_source,
                "source_color_idx": service._file_color_index(primary_source),
            }
        )
    return {
        "path": ap,
        "total": len(items),
        "items": items,
        "file_options": file_options,
    }


def delete_json_files(service, paths: list[str]) -> dict[str, Any]:
    if not paths:
        raise ValueError("请先选择要删除的 JSON 文件")

    allow = {os.path.abspath(p) for p in glob.glob("accounts_*.json")}
    selected = [os.path.abspath(str(p)) for p in paths]

    removed_files = 0
    removed_lines = 0
    skipped: list[str] = []
    all_emails: set[str] = set()
    removed_names: set[str] = set()

    for fp in selected:
        if fp not in allow:
            skipped.append(fp)
            continue
        if not os.path.isfile(fp):
            skipped.append(fp)
            continue
        all_emails |= emails_from_accounts_json(fp)
        try:
            os.remove(fp)
            removed_files += 1
            removed_names.add(os.path.basename(fp))
        except Exception:
            skipped.append(fp)

    if removed_names:
        with service._lock:
            notes = service._normalize_json_file_notes(service.cfg.get("json_file_notes") or {})
            changed = False
            for name in removed_names:
                if name in notes:
                    notes.pop(name, None)
                    changed = True
            if changed:
                service.cfg["json_file_notes"] = notes
                save_config(service.cfg)

    acct_path = accounts_txt_path(service)
    if all_emails and os.path.isfile(acct_path):
        email_lower = {e.lower() for e in all_emails}
        try:
            with open(acct_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            kept: list[str] = []
            for raw in lines:
                line = raw.strip()
                if not line:
                    continue
                ep = line.split("----", 1)[0].strip().lower()
                if ep in email_lower:
                    removed_lines += 1
                    continue
                kept.append(raw if raw.endswith("\n") else raw + "\n")
            with open(acct_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
        except Exception as e:
            service.log(f"更新 {acct_path} 失败: {e}")

    service.log(
        f"已删除 {removed_files} 个 JSON；从账号列表移除 {removed_lines} 行（{acct_path}）"
    )
    return {
        "removed_files": removed_files,
        "removed_lines": removed_lines,
        "skipped": skipped,
    }


def sync_selected_accounts(service, emails: list[str]) -> dict[str, Any]:
    selected = [str(e).strip().lower() for e in emails if str(e).strip()]
    if not selected:
        raise ValueError("请先勾选要同步的账号")

    with service._lock:
        if service._sync_busy:
            raise RuntimeError("同步正在进行中，请稍候")
        service._sync_busy = True

    ok = 0
    fail = 0
    missing: list[str] = []
    try:
        url = str(service.cfg.get("accounts_sync_api_url") or "").strip()
        tok = str(service.cfg.get("accounts_sync_bearer_token") or "").strip()
        verify_ssl = bool(service.cfg.get("openai_ssl_verify", True))
        proxy_arg = str(service.cfg.get("proxy") or "").strip() or None

        if not url:
            raise ValueError("请先填写同步 API 地址")
        if not tok:
            raise ValueError("请先填写 Bearer Token")

        auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
        emails_uniq = list(dict.fromkeys(selected))
        local_map = build_local_account_index(service)

        found_accounts: list[dict[str, Any]] = []
        for em in emails_uniq:
            acc = local_map.get(em)
            if not acc:
                missing.append(em)
                continue
            found_accounts.append(acc)

        for em in missing:
            service.log(f"同步跳过 {em}: 本地 JSON 中未找到该账号详情")

        if not found_accounts:
            fail = len(emails_uniq)
            raise RuntimeError("本地 JSON 中未找到可同步账号")

        payload = {
            "data": {"accounts": found_accounts, "proxies": []},
            "skip_default_group_bind": True,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": auth,
        }
        code, text = _http_post_json(
            url,
            body,
            headers,
            verify_ssl=verify_ssl,
            proxy=proxy_arg,
        )
        if 200 <= code < 300:
            ok = len(found_accounts)
            fail = len(missing)
            service.log(f"批量同步成功 HTTP {code}，账号 {ok} 个")
        else:
            fail = len(found_accounts) + len(missing)
            snippet = (text or "")[:500].replace("\n", " ")
            raise RuntimeError(f"批量同步失败 HTTP {code} {snippet}")

        return {"ok": ok, "fail": fail, "missing": missing}
    finally:
        with service._lock:
            service._sync_busy = False
        service.log(f"同步结束：成功 {ok}，失败 {fail}")


__all__ = [
    "accounts_txt_path",
    "build_email_source_files_map",
    "build_local_account_index",
    "delete_json_files",
    "email_from_account_entry",
    "emails_from_accounts_json",
    "list_accounts",
    "list_json_files",
    "save_json_file_note",
    "source_label",
    "sync_selected_accounts",
]
