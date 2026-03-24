from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from typing import Any

# Cloudflare 等会拦截 urllib 默认 User-Agent；管理端 API 使用常见桌面 Chrome 指纹。
_HTTP_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _merge_http_headers(extra: dict[str, Any] | None) -> dict[str, str]:
    """先铺浏览器类头，再由 extra 覆盖（保留 Authorization、Content-Type 等）。"""
    h: dict[str, str] = dict(_HTTP_BROWSER_HEADERS)
    if extra:
        for k, v in extra.items():
            if v is not None:
                h[str(k)] = str(v)
    return h


def _urlopen_request(
    req: urllib.request.Request,
    *,
    verify_ssl: bool,
    timeout: int,
    proxy: str | None = None,
):
    """发起请求：可选走 HTTP(S) 代理（与 r_with_pwd 一致），可选关闭 SSL 校验。"""
    p = (proxy or "").strip()
    if not p and verify_ssl:
        return urllib.request.urlopen(req, timeout=timeout)
    handlers: list[Any] = []
    if p:
        handlers.append(urllib.request.ProxyHandler({"http": p, "https": p}))
    if not verify_ssl:
        ctx = ssl._create_unverified_context()
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)


def _http_post_json(
    url: str,
    body: bytes,
    headers: dict[str, Any],
    *,
    verify_ssl: bool,
    timeout: int = 120,
    proxy: str | None = None,
) -> tuple[int, str]:
    """POST JSON，返回 (HTTP 状态码, 响应体文本)。"""
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=_merge_http_headers(headers),
    )
    try:
        with _urlopen_request(
            req,
            verify_ssl=verify_ssl,
            timeout=timeout,
            proxy=proxy,
        ) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, raw
    except Exception as e:
        return -1, str(e)


def _http_get(
    url: str,
    headers: dict[str, Any],
    *,
    verify_ssl: bool,
    timeout: int = 60,
    proxy: str | None = None,
) -> tuple[int, str]:
    """GET，返回 (HTTP 状态码, 响应体文本)。"""
    req = urllib.request.Request(
        url,
        method="GET",
        headers=_merge_http_headers(headers),
    )
    try:
        with _urlopen_request(
            req,
            verify_ssl=verify_ssl,
            timeout=timeout,
            proxy=proxy,
        ) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, raw
    except Exception as e:
        return -1, str(e)


def _http_delete(
    url: str,
    headers: dict[str, Any],
    *,
    verify_ssl: bool,
    timeout: int = 60,
    proxy: str | None = None,
) -> tuple[int, str]:
    """DELETE，返回 (HTTP 状态码, 响应体文本)。"""
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers=_merge_http_headers(headers),
    )
    try:
        with _urlopen_request(
            req,
            verify_ssl=verify_ssl,
            timeout=timeout,
            proxy=proxy,
        ) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, raw
    except Exception as e:
        return -1, str(e)


def _hint_connect_error(msg: str) -> str:
    """为常见连接失败补充简短排查提示。"""
    if not msg:
        return msg
    low = msg.lower()
    if (
        "10061" in msg
        or "拒绝" in msg
        or "connection refused" in low
        or "timed out" in low
        or "超时" in msg
    ):
        return (
            f"{msg}\n\n"
            "排查：1) 服务地址/端口是否正确、服务是否在运行；2) 防火墙是否拦截；"
            "3) 若访问该 API 需翻墙，请在「工作台」填写与注册相同的 HTTP 代理（如 http://127.0.0.1:7890）。"
        )
    if "1010" in msg or "browser_signature" in low or "access denied" in low:
        return (
            f"{msg}\n\n"
            "若页面为 Cloudflare：多为请求指纹被拦。本程序已为 API 请求附带桌面 Chrome 风格 UA；"
            "若仍 403，需在服务端放宽规则或使用与浏览器一致的代理出口。"
        )
    return msg
