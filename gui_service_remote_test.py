from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from queue import Empty, Queue
from typing import Any

from gui_http_utils import (
    _hint_connect_error,
    _http_get,
    _http_post_json,
    _merge_http_headers,
    _urlopen_request,
)


def consume_test_event_stream(resp) -> tuple[bool, str, str]:
    """解析测试接口 SSE 流，返回 (是否成功, 摘要文本, 错误信息)。"""
    pending = ""
    content_parts: list[str] = []
    complete_success: bool | None = None
    err_msg = ""

    def _feed_line(line: str) -> None:
        nonlocal complete_success, err_msg
        s = line.strip()
        if not s or s.startswith(":"):
            return
        if not s.startswith("data:"):
            return
        raw = s[5:].strip()
        if not raw or raw == "[DONE]":
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        typ = str(payload.get("type") or "")
        if typ == "content":
            text = str(payload.get("text") or "")
            if text:
                content_parts.append(text)
            return
        if typ == "test_complete":
            if "success" in payload:
                complete_success = bool(payload.get("success"))
            m = str(payload.get("message") or payload.get("error") or "").strip()
            if m:
                err_msg = m
            return
        if typ in {"error", "failed"}:
            m = str(payload.get("message") or payload.get("error") or "").strip()
            if m:
                err_msg = m

    while True:
        chunk = resp.read(1024)
        if not chunk:
            break
        pending += chunk.decode("utf-8", "replace")
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            _feed_line(line)
    if pending:
        _feed_line(pending)

    summary = "".join(content_parts).strip()
    if not summary:
        summary = err_msg or "无有效返回"
    if len(summary) > 220:
        summary = summary[:220] + "…"

    if complete_success is None:
        ok = bool(content_parts) and not err_msg
    else:
        ok = bool(complete_success) and not err_msg
    return ok, summary, err_msg


def is_ssl_retryable_error(msg: str) -> bool:
    """判断错误是否属于可重试的 SSL/TLS 握手类异常。"""
    low = str(msg or "").lower()
    keys = [
        "ssl",
        "tls",
        "handshake",
        "wrong version number",
        "certificate verify",
        "sslv3",
        "unexpected eof",
        "decryption failed",
        "bad record mac",
        "eof occurred",
    ]
    return any(k in low for k in keys)


def is_token_invalidated_error(msg: str) -> bool:
    """判断错误是否属于 access token 失效。"""
    low = str(msg or "").strip().lower()
    if not low:
        return False
    keys = [
        "token_invalidated",
        "token_revoked",
        "invalidated oauth token",
        "encountered invalidated oauth token",
        "authentication token has been invalidated",
        "invalid authentication token",
        "token invalid",
        "token expired",
        "access token expired",
        "jwt expired",
        "身份验证令牌已失效",
        "令牌已失效",
        "token 已失效",
    ]
    return any(k in low for k in keys)


def is_account_deactivated_error(msg: str) -> bool:
    low = str(msg or "").strip().lower()
    if not low:
        return False
    keys = [
        "account has been deactivated",
        "access deactivated",
        "账号已被封禁",
        "账户已被封禁",
        "deactivated",
    ]
    return any(k in low for k in keys)


def is_rate_limited_error(msg: str) -> bool:
    low = str(msg or "").strip().lower()
    if not low:
        return False
    if "429" in low:
        return True
    keys = ["rate limit", "too many requests", "请求过于频繁", "限流"]
    return any(k in low for k in keys)


def refresh_api_success(code: int, text: str) -> tuple[bool, str]:
    """解析 token 刷新接口响应。"""
    raw = str(text or "")
    snippet = raw.replace("\n", " ").strip()[:220]

    if not (200 <= int(code or 0) < 300):
        return False, f"HTTP {code}: {snippet}"

    if not raw.strip():
        return True, f"HTTP {code}"

    try:
        payload = json.loads(raw)
    except Exception:
        low = raw.lower()
        if (
            "success" in low
            or "refreshed" in low
            or "ok" == low.strip()
            or "刷新成功" in raw
            or "已刷新" in raw
        ):
            return True, snippet or f"HTTP {code}"
        return False, snippet or f"HTTP {code}"

    if isinstance(payload, dict):
        if "code" in payload:
            try:
                cval = int(payload.get("code") or 0)
            except Exception:
                cval = -1
            msg = str(payload.get("message") or payload.get("error") or "").strip()
            if cval == 0:
                return True, msg or "code=0"
            msg_low = msg.lower()
            if msg and (
                "already valid" in msg_low
                or "token valid" in msg_low
                or "already refreshed" in msg_low
                or "已是最新" in msg
                or "无需刷新" in msg
            ):
                return True, msg
            return False, f"code={cval} {msg}".strip()

        if payload.get("success") is True or payload.get("ok") is True:
            msg = str(payload.get("message") or payload.get("msg") or "").strip()
            return True, msg or "success=true"

        data = payload.get("data")
        if isinstance(data, dict):
            if data.get("success") is True or data.get("ok") is True:
                msg = str(data.get("message") or data.get("msg") or "").strip()
                return True, msg or "data.success=true"

        msg = str(payload.get("message") or payload.get("error") or "").strip()
        msg_low = msg.lower()
        if msg and (
            "refreshed" in msg_low
            or "refresh success" in msg_low
            or "already valid" in msg_low
            or "已刷新" in msg
            or "刷新成功" in msg
        ):
            return True, msg
        if msg:
            return False, msg

    return False, snippet or f"HTTP {code}"


def try_refresh_remote_token(
    service,
    aid: str,
    *,
    base: str,
    auth: str,
    verify_ssl: bool,
    proxy_arg: str | None,
) -> tuple[bool, str, str]:
    """尝试调用管理端刷新指定账号 token，返回 (是否成功, 详情, 命中接口)。"""
    aid_clean = str(aid or "").strip()
    if not aid_clean:
        return False, "账号 ID 为空", ""

    aid_enc = urllib.parse.quote(aid_clean)
    root = str(base or "").rstrip("/")
    body_empty = json.dumps({}, ensure_ascii=False).encode("utf-8")
    body_id = json.dumps({"id": aid_clean}, ensure_ascii=False).encode("utf-8")

    post_candidates: list[tuple[str, bytes]] = [
        (f"{root}/{aid_enc}/refresh", body_empty),
        (f"{root}/{aid_enc}/refresh-token", body_empty),
        (f"{root}/{aid_enc}/refresh_token", body_empty),
        (f"{root}/{aid_enc}/token/refresh", body_empty),
        (f"{root}/{aid_enc}/relogin", body_empty),
        (f"{root}/refresh", body_id),
        (f"{root}/refresh-token", body_id),
        (f"{root}/refresh_token", body_id),
        (f"{root}/token/refresh", body_id),
    ]
    get_candidates: list[str] = [
        f"{root}/{aid_enc}/refresh",
        f"{root}/{aid_enc}/refresh-token",
        f"{root}/{aid_enc}/refresh_token",
    ]

    last_detail = ""

    for url, body in post_candidates:
        code, text = _http_post_json(
            url,
            body,
            {
                "Accept": "application/json",
                "Authorization": auth,
                "Content-Type": "application/json",
            },
            verify_ssl=verify_ssl,
            timeout=90,
            proxy=proxy_arg,
        )
        ok_refresh, detail = refresh_api_success(code, text)
        if ok_refresh:
            return True, detail or f"POST {url} HTTP {code}", f"POST {url}"
        if code not in {404, 405} and detail:
            last_detail = detail

    for url in get_candidates:
        code, text = _http_get(
            url,
            {
                "Accept": "application/json",
                "Authorization": auth,
            },
            verify_ssl=verify_ssl,
            timeout=90,
            proxy=proxy_arg,
        )
        ok_refresh, detail = refresh_api_success(code, text)
        if ok_refresh:
            return True, detail or f"GET {url} HTTP {code}", f"GET {url}"
        if code not in {404, 405} and detail:
            last_detail = detail

    if last_detail:
        return False, last_detail, ""
    return False, "未找到可用的 token 刷新接口", ""


def set_remote_test_state(
    service,
    account_id: str,
    *,
    status_text: str,
    summary: str,
    duration_ms: int,
) -> None:
    """更新测试状态缓存并回填到远端列表行。"""
    aid = str(account_id).strip()
    if not aid:
        return
    status = str(status_text or "").strip() or "失败"
    text = (summary or "-").strip()
    if len(text) > 220:
        text = text[:220] + "…"
    at = datetime.now().strftime("%H:%M:%S")
    state = {
        "status": status,
        "result": text,
        "at": at,
        "duration_ms": str(max(0, int(duration_ms))),
    }

    with service._lock:
        service._remote_test_state[aid] = state
        for row in service._remote_rows:
            if str(row.get("id") or "").strip() != aid:
                continue
            row["test_status"] = state["status"]
            row["test_result"] = state["result"]
            row["test_at"] = state["at"]


def batch_test_remote_accounts(service, ids: list[Any]) -> dict[str, Any]:
    """批量测试远端账号（按给定 id 列表顺序）。"""
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        aid = str(raw).strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        ordered_ids.append(aid)
    if not ordered_ids:
        raise ValueError("请先选择要测试的账号")

    with service._lock:
        if service._remote_busy:
            raise RuntimeError("服务端列表拉取中，请稍后再测")
        if service._remote_test_busy:
            raise RuntimeError("批量测试进行中，请稍候")
        service._remote_test_busy = True
        service._remote_test_stats = {
            "total": len(ordered_ids),
            "done": 0,
            "ok": 0,
            "fail": 0,
        }

    ok = 0
    fail = 0
    results: list[dict[str, Any]] = []

    try:
        tok = str(service.cfg.get("accounts_sync_bearer_token") or "").strip()
        base = str(service.cfg.get("accounts_list_api_base") or "").strip()
        if not tok:
            raise ValueError("请先填写 Bearer Token")
        if not base:
            raise ValueError("请先填写账号列表 API")

        verify_ssl = bool(service.cfg.get("openai_ssl_verify", True))
        proxy_arg = str(service.cfg.get("proxy") or "").strip() or None
        auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
        total = len(ordered_ids)
        worker_count = min(
            total,
            service._to_int(service.cfg.get("remote_test_concurrency"), 4, 1, 12),
        )
        ssl_retry_limit = service._to_int(service.cfg.get("remote_test_ssl_retry"), 2, 0, 5)

        service.log(
            f"[批量测试] 启动：总数 {total}，并发 {worker_count}，"
            f"SSL 重试 {ssl_retry_limit}"
        )

        q: Queue[str] = Queue()
        for aid in ordered_ids:
            q.put(aid)

        state_lock = threading.Lock()

        def _run_one(aid: str) -> tuple[bool, str, int, str]:
            t0 = time.time()
            success = False
            summary = ""
            status_text = "失败"

            ssl_retry_done = 0

            while True:
                success = False
                summary = ""
                try:
                    test_url = f"{base.rstrip('/')}/{urllib.parse.quote(aid)}/test"
                    body = json.dumps(
                        {
                            "model_id": "gpt-5.4",
                            "prompt": "",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    req = urllib.request.Request(
                        test_url,
                        data=body,
                        method="POST",
                        headers=_merge_http_headers(
                            {
                                "Authorization": auth,
                                "Accept": "text/event-stream",
                                "Cache-Control": "no-cache",
                                "Content-Type": "application/json",
                            }
                        ),
                    )
                    with _urlopen_request(
                        req,
                        verify_ssl=verify_ssl,
                        timeout=240,
                        proxy=proxy_arg,
                    ) as resp:
                        code = int(resp.getcode() or 0)
                        if not (200 <= code < 300):
                            raise RuntimeError(f"HTTP {code}")
                        success, summary, err_msg = consume_test_event_stream(resp)
                        if err_msg and not summary:
                            summary = err_msg
                except urllib.error.HTTPError as e:
                    raw = e.read().decode("utf-8", "replace")
                    summary = f"HTTP {e.code}: {(raw or '')[:220]}"
                    success = False
                except Exception as e:
                    summary = _hint_connect_error(str(e)).replace("\n", " ")[:220]
                    success = False

                if success:
                    summary = "测试通过"
                    status_text = "成功"
                    break

                if is_account_deactivated_error(summary):
                    status_text = "封禁"
                    summary = "账号封禁(deactivated)"
                    break

                if is_rate_limited_error(summary):
                    status_text = "429限流"
                    summary = "429 限流"
                    break

                if is_token_invalidated_error(summary):
                    status_text = "Token过期"
                    summary = "Token 过期/失效"
                    break

                if ssl_retry_done >= ssl_retry_limit:
                    break
                if not is_ssl_retryable_error(summary):
                    break

                ssl_retry_done += 1
                wait = round(0.8 * ssl_retry_done, 2)
                service.log(
                    f"[批量测试] id={aid} SSL/TLS 异常，"
                    f"{wait}s 后重试 ({ssl_retry_done}/{ssl_retry_limit})"
                )
                time.sleep(wait)

            cost_ms = int((time.time() - t0) * 1000)
            return success, summary, cost_ms, status_text

        def _worker(worker_no: int) -> None:
            nonlocal ok, fail
            while True:
                try:
                    aid = q.get_nowait()
                except Empty:
                    return

                service.log(f"[批量测试-W{worker_no}] 开始 id={aid}")
                success, summary, cost_ms, status_text = _run_one(aid)
                set_remote_test_state(
                    service,
                    aid,
                    status_text=status_text,
                    summary=summary,
                    duration_ms=cost_ms,
                )

                with state_lock:
                    if success:
                        ok += 1
                    else:
                        fail += 1
                    done = ok + fail
                    ok_now = ok
                    fail_now = fail
                    results.append(
                        {
                            "id": aid,
                            "success": success,
                            "summary": summary,
                            "duration_ms": cost_ms,
                        }
                    )

                with service._lock:
                    service._remote_test_stats = {
                        "total": total,
                        "done": done,
                        "ok": ok_now,
                        "fail": fail_now,
                    }

                if success:
                    service.log(f"[批量测试-W{worker_no}] id={aid} 成功 ({cost_ms}ms)")
                else:
                    service.log(f"[批量测试-W{worker_no}] id={aid} 失败 ({cost_ms}ms): {summary}")
                service.log(f"[批量测试] 进度 {done}/{total} · 成功 {ok_now} · 失败 {fail_now}")
                q.task_done()

        workers: list[threading.Thread] = []
        for i in range(1, worker_count + 1):
            t = threading.Thread(target=_worker, args=(i,), daemon=True)
            workers.append(t)
            t.start()

        for t in workers:
            t.join()

        order_map = {aid: idx for idx, aid in enumerate(ordered_ids)}
        results.sort(key=lambda x: order_map.get(str(x.get("id") or ""), 10**9))

        service.log(f"[批量测试] 结束：成功 {ok}，失败 {fail}")
        return {
            "ok": ok,
            "fail": fail,
            "total": len(ordered_ids),
            "results": results,
        }
    finally:
        with service._lock:
            service._remote_test_busy = False


def revive_remote_tokens(service, ids: list[Any]) -> dict[str, Any]:
    """批量刷新所选账号 token（用于 Token 过期复活）。"""
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        aid = str(raw).strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        ordered_ids.append(aid)
    if not ordered_ids:
        raise ValueError("请先选择要复活的账号")

    with service._lock:
        if service._remote_busy:
            raise RuntimeError("服务端列表拉取中，请稍后再试")
        if service._remote_test_busy:
            raise RuntimeError("批量测试进行中，请稍后再试")
        state_by_id = {
            str(r.get("id") or "").strip(): str(r.get("test_status") or "").strip()
            for r in service._remote_rows
        }

    candidates = [aid for aid in ordered_ids if state_by_id.get(aid) == "Token过期"]
    skipped = [aid for aid in ordered_ids if aid not in set(candidates)]
    if not candidates:
        raise ValueError("所选账号中没有“Token过期”状态")

    tok = str(service.cfg.get("accounts_sync_bearer_token") or "").strip()
    base = str(service.cfg.get("accounts_list_api_base") or "").strip()
    if not tok:
        raise ValueError("请先填写 Bearer Token")
    if not base:
        raise ValueError("请先填写账号列表 API")

    verify_ssl = bool(service.cfg.get("openai_ssl_verify", True))
    proxy_arg = str(service.cfg.get("proxy") or "").strip() or None
    auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    worker_count = min(
        len(candidates),
        service._to_int(service.cfg.get("remote_revive_concurrency"), 4, 1, 12),
    )

    service.log(
        f"[复活] 启动：候选 {len(candidates)}，并发 {worker_count}"
        + (f"，跳过 {len(skipped)}" if skipped else "")
    )

    ok = 0
    fail = 0
    state_lock = threading.Lock()
    api_used: dict[str, int] = {}
    results: list[dict[str, Any]] = []

    def _run_one(aid: str) -> dict[str, Any]:
        refreshed, detail, api = try_refresh_remote_token(
            service,
            aid,
            base=base,
            auth=auth,
            verify_ssl=verify_ssl,
            proxy_arg=proxy_arg,
        )
        if refreshed:
            set_remote_test_state(
                service,
                aid,
                status_text="已复活",
                summary="Token已刷新",
                duration_ms=0,
            )
            service.log(
                f"[复活] id={aid} 成功"
                + (f" · 接口 {api}" if api else "")
                + (f" · {detail}" if detail else "")
            )
            return {"id": aid, "success": True, "detail": detail, "api": api}

        service.log(f"[复活] id={aid} 失败: {detail}")
        return {"id": aid, "success": False, "detail": detail, "api": api}

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {executor.submit(_run_one, aid): aid for aid in candidates}
        for fut in as_completed(future_map):
            aid = future_map[fut]
            try:
                item = fut.result()
            except Exception as e:
                item = {"id": aid, "success": False, "detail": str(e), "api": ""}

            with state_lock:
                results.append(item)
                if item.get("success"):
                    ok += 1
                    api = str(item.get("api") or "").strip()
                    if api:
                        api_used[api] = int(api_used.get(api, 0)) + 1
                else:
                    fail += 1

    results.sort(key=lambda x: ordered_ids.index(str(x.get("id") or "")))
    api_summary = [
        {"api": k, "count": int(v)}
        for k, v in sorted(api_used.items(), key=lambda x: (-int(x[1]), str(x[0])))
    ]
    service.log(f"[复活] 结束：成功 {ok}，失败 {fail}")
    return {
        "ok": ok,
        "fail": fail,
        "total": len(candidates),
        "skipped": skipped,
        "api_summary": api_summary,
        "concurrency": worker_count,
        "results": results,
    }


__all__ = [
    "batch_test_remote_accounts",
    "consume_test_event_stream",
    "is_account_deactivated_error",
    "is_rate_limited_error",
    "is_ssl_retryable_error",
    "is_token_invalidated_error",
    "refresh_api_success",
    "revive_remote_tokens",
    "set_remote_test_state",
    "try_refresh_remote_token",
]
