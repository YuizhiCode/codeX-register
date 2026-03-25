#!/usr/bin/env python3
"""
CodeX Register Web 控制台（Naive UI）。

职责：
- 提供本地 HTTP 服务，使用 Vue3 + Naive UI 构建 Web UI；
- 默认用 pywebview 打包为独立应用窗口显示（可切换浏览器模式）；
- 读写 gui_config.json，并将核心配置同步到环境变量；
- 在后台线程执行 r_with_pwd.run，实时采集日志；
- 管理 accounts_*.json、accounts.txt、本地同步与管理端拉取。
"""

from __future__ import annotations

import glob
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from queue import Empty, Queue
from typing import Any

from gui_config_store import ACCOUNTS_TXT, DEFAULT_CONFIG, load_config, save_config
from gui_http_utils import (
    _hint_connect_error,
    _http_delete,
    _http_get,
    _http_post_json,
    _merge_http_headers,
    _urlopen_request,
)
from gui_service_data_ops import (
    accounts_txt_path as _data_accounts_txt_path,
    build_email_source_files_map as _data_build_email_source_files_map,
    build_local_account_index as _data_build_local_account_index,
    delete_json_files as _data_delete_json_files,
    email_from_account_entry as _data_email_from_account_entry,
    emails_from_accounts_json as _data_emails_from_accounts_json,
    list_accounts as _data_list_accounts,
    list_json_files as _data_list_json_files,
    save_json_file_note as _data_save_json_file_note,
    source_label as _data_source_label,
    sync_selected_accounts as _data_sync_selected_accounts,
)
from gui_service_mail_ops import (
    get_mail_client as _mail_get_mail_client,
    mail_clear_emails as _mail_mail_clear_emails,
    mail_client_signature as _mail_mail_client_signature,
    mail_content_preview as _mail_mail_content_preview,
    mail_delete_email as _mail_mail_delete_email,
    mail_delete_emails as _mail_mail_delete_emails,
    mail_delete_mailbox as _mail_mail_delete_mailbox,
    mail_delete_mailboxes as _mail_mail_delete_mailboxes,
    mail_domain_stats as _mail_mail_domain_stats,
    mail_generate_mailbox as _mail_mail_generate_mailbox,
    mail_get_email_detail as _mail_mail_get_email_detail,
    mail_list_emails as _mail_mail_list_emails,
    mail_overview as _mail_mail_overview,
    mail_providers as _mail_mail_providers,
    mail_proxy as _mail_mail_proxy,
    mail_sender_text as _mail_mail_sender_text,
    record_mail_domain_error as _mail_record_mail_domain_error,
    record_mail_domain_registered as _mail_record_mail_domain_registered,
)
from gui_service_remote_test import (
    batch_test_remote_accounts as _remote_batch_test_remote_accounts,
    consume_test_event_stream as _remote_consume_test_event_stream,
    is_account_deactivated_error as _remote_is_account_deactivated_error,
    is_rate_limited_error as _remote_is_rate_limited_error,
    is_ssl_retryable_error as _remote_is_ssl_retryable_error,
    is_token_invalidated_error as _remote_is_token_invalidated_error,
    refresh_api_success as _remote_refresh_api_success,
    revive_remote_tokens as _remote_revive_remote_tokens,
    set_remote_test_state as _remote_set_remote_test_state,
    try_refresh_remote_token as _remote_try_refresh_remote_token,
)
from mail_services import (
    MailServiceError,
    available_mail_providers,
    build_mail_service,
    normalize_mail_provider,
)

class StdoutCapture:
    """按行把 print 输出交给回调，供后台线程日志上屏。"""

    def __init__(self, cb):
        self._cb = cb
        self._buf = ""

    def write(self, text: str) -> None:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._cb(line)

    def flush(self) -> None:
        if self._buf:
            self._cb(self._buf)
            self._buf = ""


class RegisterService:
    """应用业务层：配置、运行控制、数据管理、日志缓存。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._log_ctx = threading.local()
        self.cfg: dict[str, Any] = load_config()
        self._running = False
        self._status_text = "就绪"
        self._progress = 0.0
        self._stop = threading.Event()
        self._worker_thread: threading.Thread | None = None

        self._logs: deque[dict[str, Any]] = deque(maxlen=5000)
        self._log_seq = 0

        self._sync_busy = False
        self._remote_busy = False
        self._remote_test_busy = False
        self._remote_rows: list[dict[str, Any]] = []
        self._remote_total = 0
        self._remote_pages = 1
        self._remote_email_counts: dict[str, int] = {}
        self._remote_sync_status_ready = False
        self._remote_test_state: dict[str, dict[str, str]] = {}
        self._remote_test_stats: dict[str, int] = {
            "total": 0,
            "done": 0,
            "ok": 0,
            "fail": 0,
        }
        self._run_stats: dict[str, Any] = {
            "planned_total": 0,
            "success_count": 0,
            "retry_total": 0,
            "success_rate": 100.0,
            "last_retry_reason": "",
            "retry_reasons": {},
            "started_at": 0.0,
            "ended_at": 0.0,
            "elapsed_sec": 0.0,
            "success_cost_total_ms": 0,
            "success_cost_count": 0,
            "avg_success_sec": 0.0,
        }
        self._mail_client: Any | None = None
        self._mail_client_sig: tuple[str, str, str, str, bool] | None = None

        self._apply_to_env()
        self.log("Web 控制台已就绪")

    @staticmethod
    def _to_int(v: Any, default: int, lo: int = 1, hi: int | None = None) -> int:
        try:
            out = int(v)
        except (TypeError, ValueError):
            out = default
        out = max(lo, out)
        if hi is not None:
            out = min(hi, out)
        return out

    @staticmethod
    def _to_float(v: Any, default: float, lo: float = 0.0, hi: float | None = None) -> float:
        try:
            out = float(v)
        except (TypeError, ValueError):
            out = default
        out = max(lo, out)
        if hi is not None:
            out = min(hi, out)
        return out

    @staticmethod
    def _to_bool(v: Any, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            sv = v.strip().lower()
            if sv in {"1", "true", "yes", "on"}:
                return True
            if sv in {"0", "false", "no", "off"}:
                return False
        return default

    @staticmethod
    def _normalize_domain_list(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            d = str(raw or "").strip().lower()
            if not d or "@" in d:
                continue
            if d in seen:
                continue
            seen.add(d)
            out.append(d)
        return out

    @staticmethod
    def _normalize_domain_error_counts(values: Any) -> dict[str, int]:
        if not isinstance(values, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in values.items():
            domain = str(k or "").strip().lower()
            if not domain or "@" in domain:
                continue
            try:
                count = int(v)
            except Exception:
                continue
            if count > 0:
                out[domain] = count
        return out

    @staticmethod
    def _normalize_domain_registered_counts(values: Any) -> dict[str, int]:
        if not isinstance(values, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in values.items():
            domain = str(k or "").strip().lower()
            if not domain or "@" in domain:
                continue
            try:
                count = int(v)
            except Exception:
                continue
            if count > 0:
                out[domain] = count
        return out

    @staticmethod
    def _email_domain(value: str) -> str:
        email = str(value or "").strip().lower()
        if not email or "@" not in email:
            return ""
        return email.split("@", 1)[1].strip().lower()

    @staticmethod
    def _normalize_json_file_notes(values: Any) -> dict[str, str]:
        if not isinstance(values, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in values.items():
            name = os.path.basename(str(k or "").strip())
            if not name or not name.startswith("accounts_") or not name.endswith(".json"):
                continue
            note = str(v or "").strip()
            if len(note) > 120:
                note = note[:120]
            if note:
                out[name] = note
        return out

    @staticmethod
    def _file_color_index(file_name: str, palette_size: int = 12) -> int:
        name = str(file_name or "").strip().lower()
        if not name:
            return -1
        h = 0
        for ch in name:
            h = (h * 131 + ord(ch)) & 0x7FFFFFFF
        size = max(1, int(palette_size or 1))
        return int(h % size)

    def _calc_run_success_rate_locked(self) -> float:
        planned = max(0, int(self._run_stats.get("planned_total") or 0))
        retry_total = max(0, int(self._run_stats.get("retry_total") or 0))
        if planned <= 0:
            return 100.0
        return round((planned / (planned + retry_total)) * 100.0, 2)

    def _reset_run_stats(self, planned_total: int = 0) -> None:
        now = time.time()
        with self._lock:
            self._run_stats = {
                "planned_total": max(0, int(planned_total or 0)),
                "success_count": 0,
                "retry_total": 0,
                "success_rate": 100.0,
                "last_retry_reason": "",
                "retry_reasons": {},
                "started_at": now,
                "ended_at": 0.0,
                "elapsed_sec": 0.0,
                "success_cost_total_ms": 0,
                "success_cost_count": 0,
                "avg_success_sec": 0.0,
            }
            self._run_stats["success_rate"] = self._calc_run_success_rate_locked()

    def _refresh_run_elapsed_locked(self) -> None:
        started = float(self._run_stats.get("started_at") or 0.0)
        ended = float(self._run_stats.get("ended_at") or 0.0)
        if started <= 0:
            self._run_stats["elapsed_sec"] = 0.0
            return
        tail = ended if ended > 0 else time.time()
        self._run_stats["elapsed_sec"] = round(max(0.0, tail - started), 2)

    def _mark_run_finished(self) -> None:
        with self._lock:
            self._run_stats["ended_at"] = time.time()
            self._refresh_run_elapsed_locked()

    def _record_run_success(self, delta: int = 1, duration_ms: int = 0) -> None:
        inc = max(0, int(delta or 0))
        dur = max(0, int(duration_ms or 0))
        if inc <= 0 and dur <= 0:
            return
        with self._lock:
            if inc > 0:
                self._run_stats["success_count"] = max(
                    0,
                    int(self._run_stats.get("success_count") or 0) + inc,
                )
            if dur > 0:
                total_ms = max(0, int(self._run_stats.get("success_cost_total_ms") or 0)) + dur
                cnt = max(0, int(self._run_stats.get("success_cost_count") or 0)) + 1
                self._run_stats["success_cost_total_ms"] = total_ms
                self._run_stats["success_cost_count"] = cnt
                self._run_stats["avg_success_sec"] = round((total_ms / cnt) / 1000.0, 2)

    def _record_run_retry(self, reason: str) -> tuple[int, float]:
        why = str(reason or "").strip() or "未知失败"
        with self._lock:
            retry_total = max(0, int(self._run_stats.get("retry_total") or 0)) + 1
            reasons = dict(self._run_stats.get("retry_reasons") or {})
            reasons[why] = max(0, int(reasons.get(why) or 0)) + 1

            self._run_stats["retry_total"] = retry_total
            self._run_stats["retry_reasons"] = reasons
            self._run_stats["last_retry_reason"] = why
            self._run_stats["success_rate"] = self._calc_run_success_rate_locked()
            rate = float(self._run_stats.get("success_rate") or 0.0)
        return retry_total, rate

    @staticmethod
    def _top_retry_reasons(reason_counts: dict[str, int], limit: int = 3) -> list[dict[str, Any]]:
        rows = [
            {"reason": str(k), "count": int(v)}
            for k, v in (reason_counts or {}).items()
            if int(v or 0) > 0
        ]
        rows.sort(key=lambda x: (-int(x.get("count") or 0), str(x.get("reason") or "")))
        return rows[: max(1, int(limit or 1))]

    @staticmethod
    def _retry_reason_from_meta(meta: dict[str, Any]) -> str:
        code = str(meta.get("error_code") or "").strip().lower()
        msg = str(meta.get("error_message") or "").strip()
        mapping = {
            "otp_timeout": "未收到验证码(OTP超时)",
            "otp_validate_failed": "验证码校验失败",
            "mailbox_init_failed": "临时邮箱初始化失败",
            "net_check_failed": "网络地区检测失败",
            "auth_continue_failed": "注册前置接口失败(authorize/continue)",
            "register_password_failed": "密码提交失败(user/register)",
            "create_account_failed": "创建账号失败(create_account)",
            "registration_disallowed": "registration_disallowed 风控",
            "tls_error": "SSL/TLS 异常",
            "runtime_exception": "运行异常",
        }
        base = mapping.get(code, "")
        if not base and code:
            base = f"接口错误: {code}"
        if base and msg:
            return f"{base}: {msg}"
        if base:
            return base
        if msg:
            return msg
        return ""

    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        text = str(msg)
        prefix = str(getattr(self._log_ctx, "prefix", "") or "").strip()
        if prefix and not text.startswith(f"[{prefix}]"):
            text = f"[{prefix}] {text}"
        with self._lock:
            self._log_seq += 1
            line = f"[{ts}] {text}"
            self._logs.append(
                {
                    "id": self._log_seq,
                    "ts": ts,
                    "msg": text,
                    "line": line,
                }
            )

    def clear_logs(self) -> None:
        with self._lock:
            self._logs.clear()
            self._log_seq = 0
        self.log("日志已清空")

    def fetch_logs(self, since: int) -> dict[str, Any]:
        with self._lock:
            items = [x for x in self._logs if int(x.get("id", 0)) > since]
            last = self._log_seq
        return {"items": items, "last_id": last}

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_run_elapsed_locked()
            reasons = dict(self._run_stats.get("retry_reasons") or {})
            return {
                "running": self._running,
                "status_text": self._status_text,
                "progress": self._progress,
                "sync_busy": self._sync_busy,
                "remote_busy": self._remote_busy,
                "remote_test_busy": self._remote_test_busy,
                "remote_test_total": int(self._remote_test_stats.get("total", 0)),
                "remote_test_done": int(self._remote_test_stats.get("done", 0)),
                "remote_test_ok": int(self._remote_test_stats.get("ok", 0)),
                "remote_test_fail": int(self._remote_test_stats.get("fail", 0)),
                "run_planned_total": int(self._run_stats.get("planned_total", 0)),
                "run_success_count": int(self._run_stats.get("success_count", 0)),
                "run_retry_total": int(self._run_stats.get("retry_total", 0)),
                "run_success_rate": float(self._run_stats.get("success_rate", 100.0)),
                "run_last_retry_reason": str(self._run_stats.get("last_retry_reason") or ""),
                "run_retry_reasons": reasons,
                "run_retry_reasons_top": self._top_retry_reasons(reasons, limit=3),
                "run_elapsed_sec": float(self._run_stats.get("elapsed_sec") or 0.0),
                "run_avg_success_sec": float(self._run_stats.get("avg_success_sec") or 0.0),
            }

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.cfg)

    def update_config(self, data: dict[str, Any], emit_log: bool = True) -> dict[str, Any]:
        with self._lock:
            cfg = dict(self.cfg)

        if not isinstance(data, dict):
            data = {}

        if "num_accounts" in data:
            cfg["num_accounts"] = self._to_int(data.get("num_accounts"), cfg.get("num_accounts", 1), 1)
        if "num_files" in data:
            cfg["num_files"] = self._to_int(data.get("num_files"), cfg.get("num_files", 1), 1, 200)
        if "concurrency" in data:
            cfg["concurrency"] = self._to_int(data.get("concurrency"), cfg.get("concurrency", 1), 1, 6)
        if "sleep_min" in data:
            cfg["sleep_min"] = self._to_int(data.get("sleep_min"), cfg.get("sleep_min", 5), 1)
        if "sleep_max" in data:
            cfg["sleep_max"] = self._to_int(data.get("sleep_max"), cfg.get("sleep_max", 30), 1)
        if "retry_403_wait_sec" in data:
            cfg["retry_403_wait_sec"] = self._to_int(
                data.get("retry_403_wait_sec"),
                cfg.get("retry_403_wait_sec", 10),
                3,
                30,
            )
        if "remote_test_concurrency" in data:
            cfg["remote_test_concurrency"] = self._to_int(
                data.get("remote_test_concurrency"),
                cfg.get("remote_test_concurrency", 4),
                1,
                12,
            )
        if "remote_test_ssl_retry" in data:
            cfg["remote_test_ssl_retry"] = self._to_int(
                data.get("remote_test_ssl_retry"),
                cfg.get("remote_test_ssl_retry", 2),
                0,
                5,
            )
        if "remote_revive_concurrency" in data:
            cfg["remote_revive_concurrency"] = self._to_int(
                data.get("remote_revive_concurrency"),
                cfg.get("remote_revive_concurrency", 4),
                1,
                12,
            )
        if "mail_delete_concurrency" in data:
            cfg["mail_delete_concurrency"] = self._to_int(
                data.get("mail_delete_concurrency"),
                cfg.get("mail_delete_concurrency", 4),
                1,
                12,
            )
        if "accounts_list_ssl_retry" in data:
            cfg["accounts_list_ssl_retry"] = self._to_int(
                data.get("accounts_list_ssl_retry"),
                cfg.get("accounts_list_ssl_retry", 3),
                0,
                8,
            )
        if "accounts_list_ssl_retry_wait_sec" in data:
            cfg["accounts_list_ssl_retry_wait_sec"] = self._to_float(
                data.get("accounts_list_ssl_retry_wait_sec"),
                float(cfg.get("accounts_list_ssl_retry_wait_sec", 0.8)),
                0.1,
                5.0,
            )
        if "flclash_delay_timeout_ms" in data:
            cfg["flclash_delay_timeout_ms"] = self._to_int(
                data.get("flclash_delay_timeout_ms"),
                cfg.get("flclash_delay_timeout_ms", 4000),
                500,
                20000,
            )
        if "flclash_delay_max_ms" in data:
            cfg["flclash_delay_max_ms"] = self._to_int(
                data.get("flclash_delay_max_ms"),
                cfg.get("flclash_delay_max_ms", 1800),
                100,
                30000,
            )
        if "flclash_delay_retry" in data:
            cfg["flclash_delay_retry"] = self._to_int(
                data.get("flclash_delay_retry"),
                cfg.get("flclash_delay_retry", 1),
                0,
                5,
            )

        if cfg["sleep_max"] < cfg["sleep_min"]:
            cfg["sleep_max"] = cfg["sleep_min"]

        str_keys = [
            "proxy",
            "mail_service_provider",
            "flclash_controller",
            "flclash_secret",
            "flclash_group",
            "flclash_switch_policy",
            "flclash_delay_test_url",
            "worker_domain",
            "freemail_username",
            "freemail_password",
            "accounts_sync_api_url",
            "accounts_sync_bearer_token",
            "accounts_list_api_base",
            "accounts_list_timezone",
        ]
        for key in str_keys:
            if key in data:
                cfg[key] = str(data.get(key) or "").strip()

        if "openai_ssl_verify" in data:
            cfg["openai_ssl_verify"] = self._to_bool(
                data.get("openai_ssl_verify"),
                bool(cfg.get("openai_ssl_verify", True)),
            )
        if "skip_net_check" in data:
            cfg["skip_net_check"] = self._to_bool(
                data.get("skip_net_check"),
                bool(cfg.get("skip_net_check", False)),
            )
        if "mailfree_random_domain" in data:
            cfg["mailfree_random_domain"] = self._to_bool(
                data.get("mailfree_random_domain"),
                bool(cfg.get("mailfree_random_domain", True)),
            )
        if "mail_domain_allowlist" in data:
            cfg["mail_domain_allowlist"] = self._normalize_domain_list(
                data.get("mail_domain_allowlist")
            )
        if "mail_domain_error_counts" in data:
            cfg["mail_domain_error_counts"] = self._normalize_domain_error_counts(
                data.get("mail_domain_error_counts")
            )
        if "mail_domain_registered_counts" in data:
            cfg["mail_domain_registered_counts"] = self._normalize_domain_registered_counts(
                data.get("mail_domain_registered_counts")
            )
        if "fast_mode" in data:
            cfg["fast_mode"] = self._to_bool(
                data.get("fast_mode"),
                bool(cfg.get("fast_mode", False)),
            )
        if "flclash_enable_switch" in data:
            cfg["flclash_enable_switch"] = self._to_bool(
                data.get("flclash_enable_switch"),
                bool(cfg.get("flclash_enable_switch", False)),
            )
        if "flclash_switch_wait_sec" in data:
            cfg["flclash_switch_wait_sec"] = self._to_float(
                data.get("flclash_switch_wait_sec"),
                float(cfg.get("flclash_switch_wait_sec", 1.2)),
                0.0,
                10.0,
            )

        policy = str(cfg.get("flclash_switch_policy") or "round_robin").strip().lower()
        if policy not in {"round_robin", "random"}:
            policy = "round_robin"
        cfg["flclash_switch_policy"] = policy

        cfg["mail_service_provider"] = normalize_mail_provider(
            cfg.get("mail_service_provider") or "mailfree"
        )
        cfg["mail_domain_allowlist"] = self._normalize_domain_list(
            cfg.get("mail_domain_allowlist") or []
        )
        cfg["mail_domain_error_counts"] = self._normalize_domain_error_counts(
            cfg.get("mail_domain_error_counts") or {}
        )
        cfg["mail_domain_registered_counts"] = self._normalize_domain_registered_counts(
            cfg.get("mail_domain_registered_counts") or {}
        )
        cfg["json_file_notes"] = self._normalize_json_file_notes(
            cfg.get("json_file_notes") or {}
        )

        cfg["accounts_list_page_size"] = 10

        with self._lock:
            self.cfg = cfg
            self._mail_client = None
            self._mail_client_sig = None
            save_config(self.cfg)
            self._apply_to_env()

        if emit_log:
            self.log("配置已保存到 gui_config.json")
        return self.get_config()

    def _set_status(self, text: str) -> None:
        with self._lock:
            self._status_text = text

    def _set_progress(self, val: float) -> None:
        with self._lock:
            self._progress = max(0.0, min(1.0, float(val)))

    def _set_running(self, running: bool) -> None:
        with self._lock:
            self._running = running

    def _apply_to_env(self) -> None:
        domain = str(self.cfg.get("worker_domain") or "").strip()
        if domain and not domain.startswith("http"):
            domain = f"https://{domain}"
        os.environ["WORKER_DOMAIN"] = domain.rstrip("/")
        os.environ["FREEMAIL_USERNAME"] = str(self.cfg.get("freemail_username") or "")
        os.environ["FREEMAIL_PASSWORD"] = str(self.cfg.get("freemail_password") or "")
        os.environ["MAIL_SERVICE_PROVIDER"] = normalize_mail_provider(
            self.cfg.get("mail_service_provider") or "mailfree"
        )
        os.environ["OPENAI_SSL_VERIFY"] = "1" if self.cfg.get("openai_ssl_verify") else "0"
        os.environ["SKIP_NET_CHECK"] = "1" if self.cfg.get("skip_net_check") else "0"
        os.environ["MAILFREE_RANDOM_DOMAIN"] = "1" if self.cfg.get("mailfree_random_domain", True) else "0"
        os.environ["MAIL_ALLOWED_DOMAINS"] = json.dumps(
            self._normalize_domain_list(self.cfg.get("mail_domain_allowlist") or []),
            ensure_ascii=False,
        )

        speed_env_keys = [
            "OTP_POLL_INTERVAL_SEC",
            "OTP_POLL_MAX_ROUNDS",
            "HTTP_RETRY_BACKOFF_BASE_SEC",
            "TLS_RETRY_BASE_SEC",
            "TLS_RETRY_STEP_SEC",
            "SENTINEL_RETRY_BASE_SEC",
            "SENTINEL_RETRY_STEP_SEC",
            "REGISTER_POST_WAIT_SEC",
            "REGISTER_CONTINUE_WAIT_SEC",
            "REGISTER_WORKSPACE_WAIT_SEC",
        ]
        if self.cfg.get("fast_mode"):
            os.environ["OTP_POLL_INTERVAL_SEC"] = "1"
            os.environ["OTP_POLL_MAX_ROUNDS"] = "70"
            os.environ["HTTP_RETRY_BACKOFF_BASE_SEC"] = "0.9"
            os.environ["TLS_RETRY_BASE_SEC"] = "0.6"
            os.environ["TLS_RETRY_STEP_SEC"] = "0.45"
            os.environ["SENTINEL_RETRY_BASE_SEC"] = "0.6"
            os.environ["SENTINEL_RETRY_STEP_SEC"] = "0.45"
            os.environ["REGISTER_POST_WAIT_SEC"] = "0.4"
            os.environ["REGISTER_CONTINUE_WAIT_SEC"] = "0.3"
            os.environ["REGISTER_WORKSPACE_WAIT_SEC"] = "0.2"
        else:
            for key in speed_env_keys:
                os.environ.pop(key, None)

    @staticmethod
    def _normalize_flclash_controller(raw: str) -> str:
        url = str(raw or "").strip()
        if not url:
            return ""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"http://{url}"
        return url.rstrip("/")

    @staticmethod
    def _is_hk_node_name(name: str) -> bool:
        s = str(name or "").strip()
        if not s:
            return False

        if "🇭🇰" in s or "香港" in s or "港区" in s:
            return True

        low = s.lower()
        normalized = (
            low.replace("-", " ")
            .replace("_", " ")
            .replace("|", " ")
            .replace("/", " ")
            .replace("(", " ")
            .replace(")", " ")
        )
        compact = re.sub(r"[\s_\-|/()\[\]{}]+", "", low)

        if "hongkong" in compact or "hong kong" in normalized:
            return True
        if re.search(r"(^|[^a-z0-9])hkg([^a-z0-9]|$)", normalized):
            return True
        if re.search(r"(^|[^a-z0-9])hk\d*([^a-z0-9]|$)", normalized):
            return True
        # 兼容无分隔写法：hk01 / hk1 / hk02-us
        if re.search(r"(^|[^a-z0-9])hk\d+", low):
            return True
        return False

    @staticmethod
    def _flclash_request_json(
        controller: str,
        *,
        method: str,
        path: str,
        secret: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 15,
    ) -> dict[str, Any]:
        url = f"{controller}{path}"
        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = int(resp.getcode() or 0)
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {e.code}: {(text or '')[:220]}") from e
        except Exception as e:
            raise RuntimeError(str(e)) from e
        if not (200 <= code < 300):
            raise RuntimeError(f"HTTP {code}: {(text or '')[:220]}")
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except Exception:
            return {}
        if isinstance(data, dict):
            return data
        return {}

    def _mail_proxy(self) -> dict[str, str] | None:
        return _mail_mail_proxy(self)

    def _mail_client_signature(self) -> tuple[str, str, str, str, bool]:
        return _mail_mail_client_signature(self)

    def _get_mail_client(self):
        return _mail_get_mail_client(self)

    @staticmethod
    def _mail_content_preview(text: str, limit: int = 200) -> str:
        return _mail_mail_content_preview(text, limit=limit)

    @staticmethod
    def _mail_sender_text(raw_sender: Any) -> str:
        return _mail_mail_sender_text(raw_sender)

    def _record_mail_domain_error(self, domain: str) -> int:
        return _mail_record_mail_domain_error(self, domain)

    def _record_mail_domain_registered(self, domain: str) -> int:
        return _mail_record_mail_domain_registered(self, domain)

    def mail_domain_stats(self) -> dict[str, Any]:
        return _mail_mail_domain_stats(self)

    def mail_providers(self) -> dict[str, Any]:
        return _mail_mail_providers(self)

    def mail_overview(self, limit: Any = 120, offset: Any = 0) -> dict[str, Any]:
        return _mail_mail_overview(self, limit=limit, offset=offset)

    def mail_generate_mailbox(self) -> dict[str, Any]:
        return _mail_mail_generate_mailbox(self)

    def mail_list_emails(self, mailbox: str) -> dict[str, Any]:
        return _mail_mail_list_emails(self, mailbox)

    def mail_get_email_detail(self, email_id: str) -> dict[str, Any]:
        return _mail_mail_get_email_detail(self, email_id)

    def mail_delete_email(self, email_id: str) -> dict[str, Any]:
        return _mail_mail_delete_email(self, email_id)

    def mail_delete_emails(self, ids: list[Any]) -> dict[str, Any]:
        return _mail_mail_delete_emails(self, ids)

    def mail_clear_emails(self, mailbox: str) -> dict[str, Any]:
        return _mail_mail_clear_emails(self, mailbox)

    def mail_delete_mailbox(self, address: str) -> dict[str, Any]:
        return _mail_mail_delete_mailbox(self, address)

    def mail_delete_mailboxes(self, addresses: list[Any]) -> dict[str, Any]:
        return _mail_mail_delete_mailboxes(self, addresses)

    def start(self, run_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._running:
                raise RuntimeError("任务正在运行中")
        if run_cfg:
            self.update_config(run_cfg, emit_log=False)
        self._apply_to_env()
        self._stop.clear()
        self._set_running(True)
        self._set_status("运行中")
        self._set_progress(0)
        self._reset_run_stats(planned_total=0)
        self.log("开始注册任务")
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return self.status()
        self._stop.set()
        self._set_status("停止中")
        self.log("正在停止...")
        return self.status()

    def _worker(self) -> None:
        """后台注册循环：劫持 stdout 以收集 r_with_pwd 日志，结束后恢复。"""
        old_out, old_err = sys.stdout, sys.stderr
        cap = StdoutCapture(self.log)
        sys.stdout = cap
        sys.stderr = cap

        try:
            import r_with_pwd

            domain = str(self.cfg.get("worker_domain") or "").strip()
            if domain and not domain.startswith("http"):
                domain = f"https://{domain}"
            mail_provider = normalize_mail_provider(self.cfg.get("mail_service_provider") or "mailfree")
            r_with_pwd.WORKER_DOMAIN = domain.rstrip("/")
            r_with_pwd.FREEMAIL_USERNAME = str(self.cfg.get("freemail_username") or "")
            r_with_pwd.FREEMAIL_PASSWORD = str(self.cfg.get("freemail_password") or "")
            r_with_pwd.MAIL_SERVICE_PROVIDER = mail_provider
            r_with_pwd.MAIL_ALLOWED_DOMAINS = self._normalize_domain_list(
                self.cfg.get("mail_domain_allowlist") or []
            )
            r_with_pwd._freemail_session_cookie_reset()

            fp = str(self.cfg.get("freemail_password") or "")
            fp_mask = (fp[:3] + "***") if len(fp) >= 3 else ("***" if fp else "")
            random_domain_on = bool(self.cfg.get("mailfree_random_domain", True))
            allow_domains = list(r_with_pwd.MAIL_ALLOWED_DOMAINS or [])
            self.log(
                f"配置 -> mail={mail_provider}, domain={r_with_pwd.WORKER_DOMAIN}, "
                f"user={r_with_pwd.FREEMAIL_USERNAME}, pass={fp_mask}, "
                f"random_domain={'开启' if random_domain_on else '关闭'}"
            )
            if allow_domains:
                self.log(f"配置 -> 指定注册域名 {len(allow_domains)} 个")

            per_file_num = self._to_int(self.cfg.get("num_accounts"), 1, 1)
            num_files = self._to_int(self.cfg.get("num_files"), 1, 1, 200)
            concurrency = self._to_int(self.cfg.get("concurrency"), 1, 1, 6)
            smin = self._to_int(self.cfg.get("sleep_min"), 5, 1)
            smax = self._to_int(self.cfg.get("sleep_max"), 30, smin)
            if smax < smin:
                smax = smin
            fast_mode = bool(self.cfg.get("fast_mode", False))
            retry_403_wait = self._to_int(self.cfg.get("retry_403_wait_sec"), 10, 3, 30)
            if fast_mode:
                retry_403_wait = min(retry_403_wait, 6)
            proxy = str(self.cfg.get("proxy") or "").strip() or None
            outdir = os.getenv("TOKEN_OUTPUT_DIR", "").strip()

            flclash_enable = bool(self.cfg.get("flclash_enable_switch", False))
            flclash_controller = self._normalize_flclash_controller(
                str(self.cfg.get("flclash_controller") or "")
            )
            flclash_secret = str(self.cfg.get("flclash_secret") or "").strip()
            flclash_group = str(self.cfg.get("flclash_group") or "PROXY").strip() or "PROXY"
            flclash_policy = str(self.cfg.get("flclash_switch_policy") or "round_robin").strip().lower()
            if flclash_policy not in {"round_robin", "random"}:
                flclash_policy = "round_robin"
            flclash_wait = self._to_float(self.cfg.get("flclash_switch_wait_sec"), 1.2, 0.0, 10.0)
            flclash_delay_url = str(
                self.cfg.get("flclash_delay_test_url") or "https://www.gstatic.com/generate_204"
            ).strip()
            flclash_delay_timeout_ms = self._to_int(
                self.cfg.get("flclash_delay_timeout_ms", 4000),
                4000,
                500,
                20000,
            )
            flclash_delay_max_ms = self._to_int(
                self.cfg.get("flclash_delay_max_ms", 1800),
                1800,
                100,
                30000,
            )
            flclash_delay_retry = self._to_int(
                self.cfg.get("flclash_delay_retry", 1),
                1,
                0,
                5,
            )

            total_target = per_file_num * num_files
            self._reset_run_stats(planned_total=total_target)
            worker_count = min(concurrency, per_file_num)
            if flclash_enable and worker_count > 1:
                self.log(
                    "FlClash 动态换 IP + 多并发已启用：同一批并发任务共享同一个节点；"
                    "仅在该批并发全部结束后再切到下一节点"
                )
            max_attempts = max(per_file_num * 50, per_file_num + 100)
            self.log(
                f"本轮参数：文件 {num_files} × 每文件 {per_file_num} = 总目标 {total_target}，"
                f"并发 {worker_count}，冷却 {smin}-{smax}s，"
                f"加速模式 {'开启' if fast_mode else '关闭'}，最大尝试 {max_attempts}"
            )

            flclash_lock = threading.Lock()
            flclash_state = {
                "enabled": False,
                "controller": flclash_controller,
                "secret": flclash_secret,
                "group": flclash_group,
                "policy": flclash_policy,
                "wait": flclash_wait,
                "delay_url": flclash_delay_url,
                "delay_timeout_ms": flclash_delay_timeout_ms,
                "delay_max_ms": flclash_delay_max_ms,
                "delay_retry": flclash_delay_retry,
                "nodes": [],
                "current": "",
                "next_idx": 0,
                "blocked_hk_count": 0,
                "blocked_hk_sample": [],
            }

            def _flclash_load_nodes() -> tuple[str, list[str], str]:
                data = self._flclash_request_json(
                    flclash_state["controller"],
                    method="GET",
                    path="/proxies",
                    secret=flclash_state["secret"],
                    timeout=20,
                )
                proxies = data.get("proxies") if isinstance(data, dict) else None
                if not isinstance(proxies, dict):
                    raise RuntimeError("/proxies 返回格式异常")

                def _proxy_type(obj: Any) -> str:
                    if isinstance(obj, dict):
                        return str(obj.get("type") or "").strip().lower()
                    return ""

                preferred = [
                    str(flclash_state["group"] or "").strip(),
                    "节点选择",
                    "PROXY",
                    "GLOBAL",
                ]
                selector_candidates: list[tuple[str, dict[str, Any]]] = []
                for key, val in proxies.items():
                    if not isinstance(val, dict):
                        continue
                    all_nodes = val.get("all")
                    if not isinstance(all_nodes, list) or not all_nodes:
                        continue
                    t = _proxy_type(val)
                    if t in {"selector", "select"}:
                        selector_candidates.append((str(key), val))

                target_key = ""
                target_obj: dict[str, Any] | None = None
                for name in preferred:
                    if not name:
                        continue
                    obj = proxies.get(name)
                    if (
                        isinstance(obj, dict)
                        and isinstance(obj.get("all"), list)
                        and obj.get("all")
                        and _proxy_type(obj) in {"selector", "select"}
                    ):
                        target_key = str(name)
                        target_obj = obj
                        break
                if target_obj is None and selector_candidates:
                    target_key, target_obj = selector_candidates[0]
                if target_obj is None:
                    raise RuntimeError("未找到可切换的 Selector 代理组，请在设置中指定节点组名")

                raw_nodes = [str(x).strip() for x in (target_obj.get("all") or []) if str(x).strip()]
                filtered: list[str] = []
                blocked: list[str] = []
                strategy_skipped: list[str] = []
                for node in raw_nodes:
                    low = node.lower()
                    if low in {"direct", "reject", "pass"}:
                        continue
                    if self._is_hk_node_name(node):
                        blocked.append(node)
                        continue

                    node_obj = proxies.get(node)
                    node_type = _proxy_type(node_obj)
                    if node_type in {"urltest", "fallback", "loadbalance", "relay"}:
                        strategy_skipped.append(node)
                        continue
                    if node not in filtered:
                        filtered.append(node)

                if not filtered:
                    flclash_state["blocked_hk_count"] = len(blocked)
                    flclash_state["blocked_hk_sample"] = blocked[:6]
                    if blocked:
                        raise RuntimeError("可用节点均为香港节点，已按规则跳过")
                    if strategy_skipped:
                        raise RuntimeError(
                            "节点组候选均为自动策略组(URLTest/Fallback)，"
                            "请改用包含具体节点的 Selector 组"
                        )
                    raise RuntimeError("代理组没有可用节点")

                flclash_state["blocked_hk_count"] = len(blocked)
                flclash_state["blocked_hk_sample"] = blocked[:6]

                current = str(target_obj.get("now") or "").strip()
                if current and self._is_hk_node_name(current):
                    current = ""

                return target_key, filtered, current

            def _flclash_candidate_order(force_diff: bool) -> list[str]:
                nodes: list[str] = list(flclash_state["nodes"])
                if not nodes:
                    return []
                current = str(flclash_state["current"] or "")
                if flclash_state["policy"] == "random":
                    order = list(nodes)
                    random.shuffle(order)
                    if force_diff and len(order) > 1 and current in order:
                        order = [n for n in order if n != current] + [current]
                    return order

                idx = int(flclash_state["next_idx"] or 0)
                if idx < 0 or idx >= len(nodes):
                    idx = 0
                order = [nodes[(idx + i) % len(nodes)] for i in range(len(nodes))]
                if force_diff and len(order) > 1 and current in order:
                    order = [n for n in order if n != current] + [current]
                return order

            def _flclash_probe_node_delay(node: str, tag: str) -> tuple[bool, int, str]:
                node_name = str(node or "").strip()
                if not node_name:
                    return False, -1, "节点名为空"
                url_arg = str(flclash_state["delay_url"] or "").strip()
                timeout_ms = int(flclash_state["delay_timeout_ms"] or 4000)
                max_ms = int(flclash_state["delay_max_ms"] or 1800)
                retry = int(flclash_state["delay_retry"] or 0)

                path_node = urllib.parse.quote(node_name, safe="")
                qs = urllib.parse.urlencode({"url": url_arg, "timeout": str(timeout_ms)})
                path = f"/proxies/{path_node}/delay?{qs}"

                last_msg = ""
                for i in range(retry + 1):
                    try:
                        data = self._flclash_request_json(
                            flclash_state["controller"],
                            method="GET",
                            path=path,
                            secret=str(flclash_state["secret"]),
                            timeout=max(5, int(timeout_ms / 1000) + 2),
                        )
                        delay = int(data.get("delay") or -1)
                        if delay > 0 and delay <= max_ms:
                            return True, delay, ""
                        if delay > 0:
                            last_msg = f"延迟 {delay}ms 超过阈值 {max_ms}ms"
                        else:
                            last_msg = str(data.get("error") or "延迟测试失败")
                    except Exception as e:
                        last_msg = str(e)

                    if i < retry:
                        wait = round(0.25 * (i + 1), 2)
                        self.log(
                            f"[{tag}] 节点 {node_name} 延迟测试失败，{wait}s 后重试 ({i + 1}/{retry})"
                        )
                        time.sleep(wait)

                return False, -1, last_msg or "延迟测试失败"

            def _flclash_pick_usable_node(tag: str, force_diff: bool) -> tuple[str, int]:
                order = _flclash_candidate_order(force_diff=force_diff)
                if not order:
                    raise RuntimeError("无可用节点")
                last_reason = ""
                for node in order:
                    ok_delay, delay_ms, reason = _flclash_probe_node_delay(node, tag)
                    if ok_delay:
                        return node, delay_ms
                    last_reason = reason or "延迟测试失败"
                    self.log(f"[{tag}] 节点不可用: {node} ({last_reason})")
                raise RuntimeError(f"未找到可用节点: {last_reason}")

            def _flclash_switch(tag: str, *, force_diff: bool) -> bool:
                if not flclash_state["enabled"]:
                    return False
                with flclash_lock:
                    try:
                        if not flclash_state["nodes"]:
                            g, nodes, current = _flclash_load_nodes()
                            flclash_state["group"] = g
                            flclash_state["nodes"] = nodes
                            flclash_state["current"] = current
                            if current in nodes:
                                flclash_state["next_idx"] = (nodes.index(current) + 1) % len(nodes)
                            else:
                                flclash_state["next_idx"] = 0

                        target, delay_ms = _flclash_pick_usable_node(tag, force_diff=force_diff)
                        current = str(flclash_state["current"] or "")

                        if target != current:
                            grp = urllib.parse.quote(str(flclash_state["group"]), safe="")
                            self._flclash_request_json(
                                flclash_state["controller"],
                                method="PUT",
                                path=f"/proxies/{grp}",
                                secret=str(flclash_state["secret"]),
                                payload={"name": target},
                                timeout=20,
                            )

                            verify = self._flclash_request_json(
                                flclash_state["controller"],
                                method="GET",
                                path=f"/proxies/{grp}",
                                secret=str(flclash_state["secret"]),
                                timeout=20,
                            )
                            actual_now = str(verify.get("now") or "").strip()
                            if actual_now:
                                flclash_state["current"] = actual_now
                            else:
                                flclash_state["current"] = target

                            if actual_now and actual_now != target:
                                self.log(
                                    f"[{tag}] FlClash 请求切到 {target}，"
                                    f"但当前为 {actual_now}（组不支持或被策略接管）"
                                )
                            else:
                                if target in flclash_state["nodes"]:
                                    flclash_state["next_idx"] = (
                                        flclash_state["nodes"].index(target) + 1
                                    ) % len(flclash_state["nodes"])
                                self.log(f"[{tag}] FlClash 已切换节点: {target} · 延迟 {delay_ms}ms")
                        else:
                            if len(flclash_state["nodes"]) <= 1:
                                self.log(
                                    f"[{tag}] 仅 1 个可用非香港节点，延迟 {delay_ms}ms: {target}"
                                )
                            else:
                                self.log(f"[{tag}] FlClash 维持节点: {target} · 延迟 {delay_ms}ms")

                        wait_sec = float(flclash_state["wait"] or 0)
                    except Exception as e:
                        self.log(f"[{tag}] FlClash 切换失败: {e}")
                        return False

                if wait_sec > 0:
                    time.sleep(wait_sec)
                return True

            if flclash_enable:
                if not flclash_state["controller"]:
                    self.log("FlClash 动态换 IP 已关闭：未填写控制器地址")
                else:
                    try:
                        g, nodes, current = _flclash_load_nodes()
                        flclash_state["enabled"] = True
                        flclash_state["group"] = g
                        flclash_state["nodes"] = nodes
                        flclash_state["current"] = current
                        if current in nodes:
                            flclash_state["next_idx"] = (nodes.index(current) + 1) % len(nodes)
                        else:
                            flclash_state["next_idx"] = 0
                        sample = ", ".join(nodes[:5])
                        self.log(
                            f"FlClash 动态换 IP 已启用: controller={flclash_state['controller']}, "
                            f"group={g}, nodes={len(nodes)}, 已排除香港节点"
                        )
                        blocked_cnt = int(flclash_state.get("blocked_hk_count") or 0)
                        blocked_sample = [
                            str(x).strip()
                            for x in (flclash_state.get("blocked_hk_sample") or [])
                            if str(x).strip()
                        ]
                        if blocked_cnt > 0:
                            show = ", ".join(blocked_sample[:5])
                            suffix = " ..." if blocked_cnt > len(blocked_sample[:5]) else ""
                            if show:
                                self.log(f"FlClash 已屏蔽香港节点 {blocked_cnt} 个: {show}{suffix}")
                            else:
                                self.log(f"FlClash 已屏蔽香港节点 {blocked_cnt} 个")
                        self.log(
                            f"FlClash 延迟测试: url={flclash_state['delay_url']}, "
                            f"timeout={flclash_state['delay_timeout_ms']}ms, "
                            f"阈值<={flclash_state['delay_max_ms']}ms, "
                            f"重试={flclash_state['delay_retry']}"
                        )
                        if sample:
                            self.log(f"FlClash 候选节点示例: {sample}")
                    except Exception as e:
                        self.log(f"FlClash 动态换 IP 初始化失败，已禁用: {e}")

            global_ok = 0
            completed_files = 0
            all_files_ok = True

            def _run_single_file(file_no: int) -> tuple[int, int, int, bool]:
                file_target = per_file_num
                progress_base = global_ok

                task_queue: Queue[int] = Queue()
                for idx in range(1, file_target + 1):
                    task_queue.put(idx)

                write_lock = threading.Lock()
                state_lock = threading.Lock()
                ok = 0
                attempts_started = file_target
                attempts_done = 0
                next_ticket = file_target
                extra_added = 0

                flc_batch_lock = threading.Condition()
                flc_active_runs = 0
                flc_switching = False

                def _flclash_acquire_for_batch(tag: str) -> bool:
                    nonlocal flc_active_runs, flc_switching
                    if not flclash_state["enabled"]:
                        return True

                    with flc_batch_lock:
                        while flc_switching:
                            flc_batch_lock.wait()
                        if flc_active_runs == 0:
                            flc_switching = True
                        else:
                            flc_active_runs += 1
                            return True

                    ok = _flclash_switch(tag, force_diff=True)

                    with flc_batch_lock:
                        flc_switching = False
                        if ok:
                            flc_active_runs += 1
                        flc_batch_lock.notify_all()
                    return ok

                def _flclash_release_for_batch() -> None:
                    nonlocal flc_active_runs
                    if not flclash_state["enabled"]:
                        return
                    with flc_batch_lock:
                        if flc_active_runs > 0:
                            flc_active_runs -= 1
                        if flc_active_runs == 0:
                            flc_batch_lock.notify_all()

                def _schedule_retry() -> int | None:
                    nonlocal attempts_started, next_ticket, extra_added
                    with state_lock:
                        if self._stop.is_set() or ok >= file_target:
                            return None
                        if attempts_started >= max_attempts:
                            return None
                        attempts_started += 1
                        extra_added += 1
                        next_ticket += 1
                        return next_ticket

                def _can_exit() -> bool:
                    with state_lock:
                        if ok >= file_target:
                            return True
                        if attempts_done >= attempts_started and task_queue.empty():
                            return True
                    return False

                def _one_worker(worker_no: int) -> None:
                    nonlocal ok, attempts_done
                    self._log_ctx.prefix = f"线程{worker_no}"
                    try:
                        while not self._stop.is_set():
                            with state_lock:
                                if ok >= file_target:
                                    return

                            try:
                                idx = task_queue.get(timeout=0.6)
                            except Empty:
                                if _can_exit():
                                    return
                                continue

                            phase = (
                                f"{idx}/{file_target}"
                                if idx <= file_target
                                else f"补位#{idx - file_target}"
                            )
                            self.log(f"[F{file_no}W{worker_no}] >>> 尝试 {phase} <<<")

                            with state_lock:
                                ok_now = ok
                            self._set_status(
                                f"文件 {file_no}/{num_files} · 成功 {ok_now}/{file_target} · "
                                f"总 {progress_base + ok_now}/{total_target}"
                            )

                            need_retry = False
                            retry_reason = ""
                            flc_acquired = False
                            run_begin = time.time()

                            try:
                                if flclash_state["enabled"]:
                                    flc_acquired = _flclash_acquire_for_batch(f"F{file_no}W{worker_no}")
                                    if not flc_acquired:
                                        self.log(
                                            f"[F{file_no}W{worker_no}] 节点切换/延迟测试失败，跳过本次并补位重试"
                                        )
                                        need_retry = True
                                        retry_reason = "节点切换/延迟测试失败"
                                        continue
                                result = r_with_pwd.run(proxy)
                                if not isinstance(result, (tuple, list)):
                                    self.log(f"[F{file_no}W{worker_no}] 返回异常，跳过")
                                    need_retry = True
                                    retry_reason = "返回结果异常"
                                else:
                                    acct = result[0]
                                    pwd = result[1] if len(result) > 1 else ""
                                    meta = result[2] if len(result) > 2 and isinstance(result[2], dict) else {}

                                    err_code = str(meta.get("error_code") or "").strip().lower()
                                    err_domain = str(meta.get("email_domain") or "").strip().lower()
                                    meta_reason = self._retry_reason_from_meta(meta)
                                    if err_code == "registration_disallowed" and err_domain:
                                        now = self._record_mail_domain_error(err_domain)
                                        self.log(
                                            f"[F{file_no}W{worker_no}] 域名风控计数: {err_domain} -> {now}"
                                        )

                                    if acct == "retry_403":
                                        self.log(
                                            f"[F{file_no}W{worker_no}] 403，{retry_403_wait} 秒后继续..."
                                        )
                                        for _ in range(retry_403_wait):
                                            if self._stop.is_set():
                                                break
                                            time.sleep(1)
                                        need_retry = True
                                        retry_reason = "HTTP 403 限流"
                                    elif acct and isinstance(acct, dict):
                                        email = str(acct.get("name") or "")
                                        written = False
                                        with write_lock:
                                            with state_lock:
                                                can_write = ok < file_target
                                            if can_write:
                                                appended = bool(r_with_pwd._append_account_to_file(acct))
                                                if not appended:
                                                    self.log(
                                                        f"[F{file_no}W{worker_no}] "
                                                        "写入 JSON 失败，准备补位重试"
                                                    )
                                                    need_retry = True
                                                    retry_reason = "写入 JSON 失败"
                                                else:
                                                    with state_lock:
                                                        ok += 1
                                                        ok_now = ok
                                                    written = True
                                                    run_cost_ms = int((time.time() - run_begin) * 1000)
                                                    self._record_run_success(1, duration_ms=run_cost_ms)
                                                    if email and pwd:
                                                        try:
                                                            pf = (
                                                                os.path.join(outdir, ACCOUNTS_TXT)
                                                                if outdir
                                                                else ACCOUNTS_TXT
                                                            )
                                                            with open(pf, "a", encoding="utf-8") as af:
                                                                af.write(f"{email}----{pwd}\n")
                                                        except Exception as e:
                                                            self.log(
                                                                f"[F{file_no}W{worker_no}] "
                                                                f"写入 accounts.txt 失败: {e}"
                                                            )
                                        if written:
                                            succ_domain = self._email_domain(email)
                                            if succ_domain:
                                                self._record_mail_domain_registered(succ_domain)
                                            self.log(
                                                f"[F{file_no}W{worker_no}] 成功 ({ok_now}/{file_target}): {email}"
                                            )
                                        else:
                                            self.log(
                                                f"[F{file_no}W{worker_no}] 已达目标，忽略额外成功: {email}"
                                            )
                                    else:
                                        self.log(f"[F{file_no}W{worker_no}] 本次失败")
                                        need_retry = True
                                        retry_reason = meta_reason or "注册流程失败"
                            except Exception as e:
                                self.log(f"[F{file_no}W{worker_no}] 异常: {e}")
                                need_retry = True
                                retry_reason = f"运行异常({type(e).__name__})"
                            finally:
                                if flc_acquired:
                                    _flclash_release_for_batch()
                                with state_lock:
                                    attempts_done += 1
                                    done_now = attempts_done
                                    ok_now = ok
                                    started_now = attempts_started
                                self._set_progress((progress_base + ok_now) / total_target)
                                self._set_status(
                                    f"文件 {file_no}/{num_files} · 成功 {ok_now}/{file_target} · "
                                    f"总 {progress_base + ok_now}/{total_target} · "
                                    f"尝试 {done_now}/{started_now}"
                                )
                                task_queue.task_done()

                            if need_retry and not self._stop.is_set():
                                retry_ticket = _schedule_retry()
                                if retry_ticket is not None:
                                    why = str(retry_reason or "").strip() or "未知失败"
                                    retry_total, success_rate = self._record_run_retry(why)
                                    task_queue.put(retry_ticket)
                                    self.log(
                                        f"[F{file_no}W{worker_no}] "
                                        f"失败补位：已追加第 {retry_ticket - file_target} 次补位，"
                                        f"原因={why}，当前成功率={success_rate:.2f}%（重试 {retry_total}）"
                                    )
                                else:
                                    with state_lock:
                                        ok_now = ok
                                        done_now = attempts_done
                                        started_now = attempts_started
                                    if ok_now < file_target and done_now >= started_now:
                                        why = str(retry_reason or "").strip() or "未知失败"
                                        self.log(
                                            f"[F{file_no}W{worker_no}] "
                                            f"已达最大尝试上限 {max_attempts}，当前成功 {ok_now}/{file_target}，"
                                            f"最近失败原因={why}"
                                        )

                            with state_lock:
                                finished = ok >= file_target
                            if finished or self._stop.is_set():
                                continue

                            w = random.randint(smin, smax)
                            if w > 0:
                                self.log(f"[F{file_no}W{worker_no}] 冷却 {w} 秒...")
                                for _ in range(w):
                                    if self._stop.is_set():
                                        break
                                    time.sleep(1)
                    finally:
                        self._log_ctx.prefix = ""

                workers: list[threading.Thread] = []
                for worker_no in range(1, worker_count + 1):
                    t = threading.Thread(target=_one_worker, args=(worker_no,), daemon=True)
                    workers.append(t)
                    t.start()

                for t in workers:
                    t.join()

                with state_lock:
                    done_final = attempts_done
                    ok_final = ok
                    started_final = attempts_started
                    extra_final = extra_added

                file_ok = ok_final >= file_target
                if file_ok:
                    self.log(
                        f"[文件 {file_no}/{num_files}] 完成 "
                        f"(成功 {ok_final}/{file_target}，补位 {extra_final} 次)"
                    )
                else:
                    self.log(
                        f"[文件 {file_no}/{num_files}] 结束 "
                        f"(成功 {ok_final}/{file_target}，尝试 {done_final}/{started_final})"
                    )
                return ok_final, started_final, extra_final, file_ok

            for file_no in range(1, num_files + 1):
                if self._stop.is_set():
                    break
                acc_file = r_with_pwd._init_accounts_file(outdir)
                self.log(f"[文件 {file_no}/{num_files}] Accounts: {acc_file}")
                file_ok_count, _, _, file_ok = _run_single_file(file_no)
                global_ok += file_ok_count
                if file_ok:
                    completed_files += 1
                else:
                    all_files_ok = False
                    if not self._stop.is_set():
                        self.log(f"[文件 {file_no}/{num_files}] 未补齐，停止后续文件创建")
                    break

            with self._lock:
                retry_total = int(self._run_stats.get("retry_total") or 0)
                success_rate = float(self._run_stats.get("success_rate") or 100.0)
                top_reasons = self._top_retry_reasons(
                    dict(self._run_stats.get("retry_reasons") or {}),
                    limit=4,
                )
            if retry_total > 0:
                reason_text = "；".join(
                    [f"{str(x.get('reason') or '')} ×{int(x.get('count') or 0)}" for x in top_reasons]
                )
                self.log(
                    f"重试统计：{retry_total} 次 · 成功率 {success_rate:.2f}%"
                    + (f" · 原因：{reason_text}" if reason_text else "")
                )
            else:
                self.log(f"重试统计：0 次 · 成功率 {success_rate:.2f}%")

            with self._lock:
                self._refresh_run_elapsed_locked()
                elapsed_sec = float(self._run_stats.get("elapsed_sec") or 0.0)
                avg_sec = float(self._run_stats.get("avg_success_sec") or 0.0)
            self.log(f"耗时统计：总耗时 {elapsed_sec:.2f}s · 平均耗时 {avg_sec:.2f}s/成功")

            if self._stop.is_set() and global_ok < total_target:
                tag = (
                    f"已停止 (成功 {global_ok}/{total_target}，"
                    f"完成文件 {completed_files}/{num_files})"
                )
            elif all_files_ok and completed_files == num_files:
                tag = (
                    f"完成 (成功 {global_ok}/{total_target}，"
                    f"文件 {completed_files}/{num_files})"
                )
            else:
                tag = (
                    f"结束 (成功 {global_ok}/{total_target}，"
                    f"完成文件 {completed_files}/{num_files})，有文件未补齐"
                )
            self.log(tag)
        except Exception as e:
            self.log(f"运行异常: {e}")
        finally:
            self._mark_run_finished()
            cap.flush()
            sys.stdout = old_out
            sys.stderr = old_err
            self._set_running(False)
            self._set_status("就绪")
            self._set_progress(0)

    def _accounts_txt_path(self) -> str:
        return _data_accounts_txt_path(self)

    @staticmethod
    def _emails_from_accounts_json(fp: str) -> set[str]:
        return _data_emails_from_accounts_json(fp)

    @staticmethod
    def _email_from_account_entry(acc: dict[str, Any]) -> str:
        return _data_email_from_account_entry(acc)

    def _build_local_account_index(self) -> dict[str, dict[str, Any]]:
        return _data_build_local_account_index(self)

    def _build_email_source_files_map(self) -> dict[str, list[str]]:
        return _data_build_email_source_files_map(self)

    @staticmethod
    def _source_label(files: list[str]) -> str:
        return _data_source_label(files)

    def save_json_file_note(self, path: str, note: str) -> dict[str, Any]:
        return _data_save_json_file_note(self, path, note)

    def list_json_files(self) -> dict[str, Any]:
        return _data_list_json_files(self)

    def list_accounts(self) -> dict[str, Any]:
        return _data_list_accounts(self)

    def delete_json_files(self, paths: list[str]) -> dict[str, Any]:
        return _data_delete_json_files(self, paths)

    def sync_selected_accounts(self, emails: list[str]) -> dict[str, Any]:
        return _data_sync_selected_accounts(self, emails)

    @staticmethod
    def _remote_item_groups_label(it: dict[str, Any]) -> str:
        gs = it.get("groups")
        if not isinstance(gs, list) or not gs:
            return "-"
        names: list[str] = []
        for g in gs[:4]:
            if isinstance(g, dict) and g.get("name"):
                names.append(str(g["name"]))
        s = ", ".join(names)
        if len(gs) > 4:
            s += "…"
        return s or "-"

    @staticmethod
    def _usage_to_percent(v: Any) -> str:
        try:
            return f"{float(v):.1f}%"
        except (TypeError, ValueError):
            return "--"

    @staticmethod
    def _remote_name_key(name: Any) -> str:
        return str(name or "").strip().lower()

    def _refresh_remote_rows_derived_locked(self) -> None:
        """在锁内重建远端缓存派生字段：重复标记、邮箱计数。"""
        counts: dict[str, int] = {}
        for row in self._remote_rows:
            k = self._remote_name_key(row.get("name"))
            if not k:
                continue
            counts[k] = counts.get(k, 0) + 1

        self._remote_email_counts = counts
        for row in self._remote_rows:
            k = self._remote_name_key(row.get("name"))
            row["is_dup"] = bool(k and counts.get(k, 0) > 1)

    def fetch_remote_all_pages(self, search: str = "") -> dict[str, Any]:
        with self._lock:
            if self._remote_busy:
                raise RuntimeError("服务端列表请求进行中")
            self._remote_busy = True
            self._remote_sync_status_ready = False
            self._remote_rows = []
            self._remote_total = 0
            self._remote_pages = 1
            self._remote_email_counts = {}

        page_rows: dict[int, list[dict[str, Any]]] = {}
        total = 0
        pages = 1
        with self._lock:
            test_state_snapshot = dict(self._remote_test_state)

        try:
            tok = str(self.cfg.get("accounts_sync_bearer_token") or "").strip()
            base = str(self.cfg.get("accounts_list_api_base") or "").strip()
            if not tok:
                raise ValueError("请先填写 Bearer Token")
            if not base:
                raise ValueError("请先填写账号列表 API")

            psize = 10
            verify = bool(self.cfg.get("openai_ssl_verify", True))
            proxy_arg = str(self.cfg.get("proxy") or "").strip() or None
            fetch_workers = self._to_int(
                self.cfg.get("accounts_list_fetch_workers", 4),
                4,
                1,
                12,
            )
            ssl_retry_limit = self._to_int(
                self.cfg.get("accounts_list_ssl_retry", 3),
                3,
                0,
                8,
            )
            ssl_retry_wait = self._to_float(
                self.cfg.get("accounts_list_ssl_retry_wait_sec", 0.8),
                0.8,
                0.1,
                5.0,
            )
            tz = str(
                self.cfg.get(
                    "accounts_list_timezone",
                    DEFAULT_CONFIG["accounts_list_timezone"],
                )
            )
            auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
            search_kw = str(search or "").strip()
            self.log("开始循环拉取列表与额度（每页 10 条）…")
            if ssl_retry_limit > 0:
                self.log(
                    f"列表拉取 SSL 重试已启用：最多 {ssl_retry_limit} 次，基准等待 {ssl_retry_wait:.1f}s"
                )

            def _http_get_retry(
                *,
                url: str,
                headers: dict[str, Any],
                timeout_sec: int,
                tag: str,
            ) -> tuple[int, str]:
                ssl_http_codes = {495, 496, 525, 526}
                for attempt in range(ssl_retry_limit + 1):
                    code, text = _http_get(
                        url,
                        headers,
                        verify_ssl=verify,
                        timeout=timeout_sec,
                        proxy=proxy_arg,
                    )
                    if 200 <= code < 300:
                        return code, text

                    msg = str(text or "")
                    is_ssl = self._is_ssl_retryable_error(msg) or code in ssl_http_codes
                    if not is_ssl or attempt >= ssl_retry_limit:
                        return code, text

                    wait = round(ssl_retry_wait * (attempt + 1), 2)
                    self.log(
                        f"[{tag}] SSL/TLS 异常，{wait}s 后重试 ({attempt + 1}/{ssl_retry_limit})"
                    )
                    time.sleep(wait)

                return -1, "SSL 重试失败"

            def _fetch_one_page(page_no: int) -> tuple[int, int, int, list[dict[str, Any]]]:
                qs = urllib.parse.urlencode(
                    {
                        "page": str(page_no),
                        "page_size": str(psize),
                        "platform": "",
                        "type": "",
                        "status": "",
                        "group": "",
                        "search": search_kw,
                        "timezone": tz,
                    }
                )
                url = f"{base.rstrip('/')}?{qs}"
                code, text = _http_get_retry(
                    url=url,
                    headers={"Accept": "application/json", "Authorization": auth},
                    timeout_sec=90,
                    tag=f"列表第 {page_no} 页",
                )
                if not (200 <= code < 300):
                    raise RuntimeError(f"HTTP {code}: {(text or '')[:400]}")

                try:
                    j = json.loads(text)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"JSON 解析失败: {e}") from e

                if j.get("code") != 0:
                    raise RuntimeError(str(j.get("message") or "接口返回非成功"))

                data = j.get("data") or {}
                items = data.get("items") or []
                if not isinstance(items, list):
                    items = []
                total_now = int(data.get("total") or 0)
                pages_now = max(1, int(data.get("pages") or 1))
                page_now = int(data.get("page") or page_no)

                rows_page: list[dict[str, Any]] = []

                for idx, it in enumerate(items):
                    if not isinstance(it, dict):
                        continue
                    aid = str(it.get("id") or "")
                    name = str(it.get("name") or "")
                    plat = str(it.get("platform") or "")
                    typ = str(it.get("type") or "")
                    st = str(it.get("status") or "")
                    gl = self._remote_item_groups_label(it)

                    u5, u7 = "--", "--"
                    if aid.isdigit():
                        uurl = f"{base.rstrip('/')}/{aid}/usage?{urllib.parse.urlencode({'timezone': tz})}"
                        uc, ut = _http_get_retry(
                            url=uurl,
                            headers={"Accept": "application/json", "Authorization": auth},
                            timeout_sec=30,
                            tag=f"usage#{aid}",
                        )
                        if 200 <= uc < 300:
                            try:
                                uj = json.loads(ut)
                            except Exception:
                                uj = {}
                            if uj.get("code") == 0:
                                ud = uj.get("data") or {}
                                u5 = self._usage_to_percent(
                                    (ud.get("five_hour") or {}).get("utilization")
                                )
                                u7 = self._usage_to_percent(
                                    (ud.get("seven_day") or {}).get("utilization")
                                )

                    rows_page.append(
                        {
                            "key": f"{aid}-{page_now}-{idx}",
                            "id": aid,
                            "name": name,
                            "platform": plat,
                            "type": typ,
                            "status": st,
                            "groups": gl,
                            "u5h": u5,
                            "u7d": u7,
                            "test_status": str(
                                (test_state_snapshot.get(aid) or {}).get("status") or "未测试"
                            ),
                            "test_result": str(
                                (test_state_snapshot.get(aid) or {}).get("result") or "-"
                            ),
                            "test_at": str(
                                (test_state_snapshot.get(aid) or {}).get("at") or "-"
                            ),
                            "is_dup": False,
                        }
                    )

                return page_now, pages_now, total_now, rows_page

            def _flatten_rows() -> list[dict[str, Any]]:
                out: list[dict[str, Any]] = []
                for p in sorted(page_rows):
                    out.extend(page_rows[p])
                return out

            first_page, pages, total, first_rows = _fetch_one_page(1)
            page_rows[first_page] = first_rows
            self.log(f"列表第 {first_page}/{pages} 页：{len(first_rows)} 条")

            with self._lock:
                self._remote_rows = _flatten_rows()
                self._remote_total = total
                self._remote_pages = pages
                self._refresh_remote_rows_derived_locked()

            if pages > 1:
                worker_count = min(fetch_workers, pages - 1)
                self.log(f"并发拉取剩余页：{pages - 1} 页，线程 {worker_count}")
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    future_to_page = {
                        executor.submit(_fetch_one_page, p): p for p in range(2, pages + 1)
                    }
                    for future in as_completed(future_to_page):
                        page_req = future_to_page[future]
                        try:
                            p_no, p_pages, p_total, p_rows = future.result()
                        except Exception as e:
                            for f in future_to_page:
                                if f is not future:
                                    f.cancel()
                            raise RuntimeError(f"第 {page_req} 页拉取失败: {e}") from e

                        page_rows[p_no] = p_rows
                        if p_total > total:
                            total = p_total
                        if p_pages > pages:
                            pages = p_pages

                        self.log(f"列表第 {p_no}/{pages} 页：{len(p_rows)} 条")
                        with self._lock:
                            self._remote_rows = _flatten_rows()
                            self._remote_total = total
                            self._remote_pages = pages
                            self._refresh_remote_rows_derived_locked()

            rows = _flatten_rows()

            with self._lock:
                self._remote_rows = rows
                self._remote_total = total
                self._remote_pages = pages
                self._refresh_remote_rows_derived_locked()
                self._remote_sync_status_ready = True

            self.log(f"循环拉取完成：{pages} 页，{total} 条，额度已同步")
            return {
                "items": rows,
                "total": total,
                "pages": pages,
                "loaded": len(rows),
            }
        except Exception as e:
            self.log(f"循环拉取失败: {e}")
            raise RuntimeError(_hint_connect_error(str(e))) from e
        finally:
            with self._lock:
                self._remote_busy = False

    def remote_cache(self) -> dict[str, Any]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for it in self._remote_rows:
                row = dict(it)
                row.setdefault("test_status", "未测试")
                row.setdefault("test_result", "-")
                row.setdefault("test_at", "-")
                row.setdefault("is_dup", False)
                rows.append(row)
            return {
                "items": rows,
                "total": self._remote_total,
                "pages": self._remote_pages,
                "loaded": len(rows),
                "ready": self._remote_sync_status_ready,
                "testing": self._remote_test_busy,
                "test_total": int(self._remote_test_stats.get("total", 0)),
                "test_done": int(self._remote_test_stats.get("done", 0)),
                "test_ok": int(self._remote_test_stats.get("ok", 0)),
                "test_fail": int(self._remote_test_stats.get("fail", 0)),
            }

    @staticmethod
    def _consume_test_event_stream(resp) -> tuple[bool, str, str]:
        return _remote_consume_test_event_stream(resp)

    @staticmethod
    def _is_ssl_retryable_error(msg: str) -> bool:
        return _remote_is_ssl_retryable_error(msg)

    @staticmethod
    def _is_token_invalidated_error(msg: str) -> bool:
        return _remote_is_token_invalidated_error(msg)

    @staticmethod
    def _is_account_deactivated_error(msg: str) -> bool:
        return _remote_is_account_deactivated_error(msg)

    @staticmethod
    def _is_rate_limited_error(msg: str) -> bool:
        return _remote_is_rate_limited_error(msg)

    @staticmethod
    def _refresh_api_success(code: int, text: str) -> tuple[bool, str]:
        return _remote_refresh_api_success(code, text)

    def _try_refresh_remote_token(
        self,
        aid: str,
        *,
        base: str,
        auth: str,
        verify_ssl: bool,
        proxy_arg: str | None,
    ) -> tuple[bool, str, str]:
        return _remote_try_refresh_remote_token(
            self,
            aid,
            base=base,
            auth=auth,
            verify_ssl=verify_ssl,
            proxy_arg=proxy_arg,
        )

    def _set_remote_test_state(
        self,
        account_id: str,
        *,
        status_text: str,
        summary: str,
        duration_ms: int,
    ) -> None:
        _remote_set_remote_test_state(
            self,
            account_id,
            status_text=status_text,
            summary=summary,
            duration_ms=duration_ms,
        )

    def batch_test_remote_accounts(self, ids: list[Any]) -> dict[str, Any]:
        return _remote_batch_test_remote_accounts(self, ids)

    def revive_remote_tokens(self, ids: list[Any]) -> dict[str, Any]:
        return _remote_revive_remote_tokens(self, ids)

    def delete_remote_accounts(self, ids: list[Any]) -> dict[str, Any]:
        """批量删除远端账号。"""
        ordered_ids: list[str] = []
        seen: set[str] = set()
        for raw in ids:
            aid = str(raw).strip()
            if not aid or aid in seen:
                continue
            seen.add(aid)
            ordered_ids.append(aid)
        if not ordered_ids:
            raise ValueError("请先选择要删除的账号")

        with self._lock:
            if self._remote_busy:
                raise RuntimeError("服务端列表拉取中，请稍后再删")
            if self._remote_test_busy:
                raise RuntimeError("批量测试进行中，请稍后再删")

        tok = str(self.cfg.get("accounts_sync_bearer_token") or "").strip()
        base = str(self.cfg.get("accounts_list_api_base") or "").strip()
        if not tok:
            raise ValueError("请先填写 Bearer Token")
        if not base:
            raise ValueError("请先填写账号列表 API")

        verify_ssl = bool(self.cfg.get("openai_ssl_verify", True))
        proxy_arg = str(self.cfg.get("proxy") or "").strip() or None
        auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"

        ok = 0
        fail = 0
        deleted_ids: set[str] = set()
        results: list[dict[str, Any]] = []

        for i, aid in enumerate(ordered_ids, start=1):
            self.log(f"[批量删除] 开始 {i}/{len(ordered_ids)}: id={aid}")
            url = f"{base.rstrip('/')}/{urllib.parse.quote(aid)}"
            code, text = _http_delete(
                url,
                {
                    "Accept": "application/json",
                    "Authorization": auth,
                },
                verify_ssl=verify_ssl,
                timeout=60,
                proxy=proxy_arg,
            )

            success = False
            summary = ""
            if 200 <= code < 300:
                if (text or "").strip():
                    try:
                        j = json.loads(text)
                    except Exception:
                        j = {}
                    if isinstance(j, dict) and "code" in j:
                        try:
                            code_val = int(j.get("code") or 0)
                        except Exception:
                            code_val = -1
                        if code_val != 0:
                            success = False
                            summary = str(j.get("message") or "删除失败")
                        else:
                            success = True
                            summary = "已删除"
                    else:
                        success = True
                        summary = "已删除"
                else:
                    success = True
                    summary = "已删除"
            else:
                snippet = (text or "")[:220].replace("\n", " ")
                summary = f"HTTP {code}: {snippet}"

            if success:
                ok += 1
                deleted_ids.add(aid)
                self.log(f"[批量删除] id={aid} 成功")
            else:
                fail += 1
                self.log(f"[批量删除] id={aid} 失败: {summary}")

            results.append(
                {
                    "id": aid,
                    "success": success,
                    "summary": summary,
                }
            )

        if deleted_ids:
            with self._lock:
                self._remote_rows = [
                    row
                    for row in self._remote_rows
                    if str(row.get("id") or "").strip() not in deleted_ids
                ]
                for aid in deleted_ids:
                    self._remote_test_state.pop(aid, None)
                self._refresh_remote_rows_derived_locked()
                self._remote_total = max(0, int(self._remote_total) - len(deleted_ids))

        self.log(f"[批量删除] 结束：成功 {ok}，失败 {fail}")
        return {
            "ok": ok,
            "fail": fail,
            "total": len(ordered_ids),
            "deleted": sorted(deleted_ids),
            "results": results,
        }

__all__ = ["StdoutCapture", "RegisterService"]
