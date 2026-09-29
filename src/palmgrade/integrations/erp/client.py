"""HTTP client for AutoERP (contract §5).

Frappe's own REST is the entire server side, so this stays thin: the token
header, the call shapes the console needs, and one honest verdict per answer.
Every caller acts on that verdict:

- `ErpRejected` (4xx): AutoERP refused THIS request. Repeating it changes nothing.
- `ErpServerError` (a 5xx carrying Frappe's own error envelope): AutoERP is up and
  THIS request crashed one of its handlers. Per message, like a refusal.
- `ErpUnavailable`: nothing usable came back. Network, timeout, a gateway
  (502/503/504), a 5xx page that is not Frappe's, or a 2xx whose body is not a
  Frappe JSON object (a captive portal, a wrong `ERP_URL`). Worth another try.

Nothing else leaves `_request` (batch 2.7). A 200 whose body did not parse used to
escape as a bare `JSONDecodeError` that the outbox worker did not catch: the oldest
row was retried first every 30 s, never backed off, and nothing behind it moved.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

_TIMEOUT_S = 15.0
_REASON_CHARS = 300
_BODY_CHARS = 120
# A gateway in front of Frappe answered for it: says nothing about this request.
_GATEWAY = (502, 503, 504)
# Keys only Frappe's own error envelope carries (`frappe.app.handle_exception`).
_FRAPPE_ERROR_KEYS = ("exc_type", "exception", "exc")


class ErpError(Exception):
    def __init__(self, message: str, *, status: int | None = None, exc_type: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.exc_type = exc_type


class ErpRejected(ErpError):
    """AutoERP refused the request as sent (4xx). Repeating it changes nothing."""


class ErpServerError(ErpError):
    """AutoERP answered 5xx with Frappe's error envelope: the server is up and this
    request crashed a handler. Kept per message with Frappe's reason; it never holds
    the messages queued behind it."""


class ErpUnavailable(ErpError):
    """Nothing usable came back (network, timeout, gateway, a page that is not
    Frappe's). Worth another try."""


class ErpClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = _TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"token {api_key}:{api_secret}"}
        self._transport = transport
        self._timeout = timeout

    async def list_modified_since(
        self, doctype: str, fields: tuple[str, ...] | list[str], since: str | None, *, limit: int
    ) -> list[dict[str, Any]]:
        """One page of a DocType, oldest change first.

        Every field must exist on the DocType: Frappe answers 417 for a single
        unknown one, and the whole page is lost.
        """
        params: dict[str, Any] = {
            "fields": json.dumps(list(fields)),
            "limit_page_length": limit,
            "order_by": "modified asc",
        }
        if since:
            params["filters"] = json.dumps([["modified", ">", since]])
        body = await self._request("GET", f"/api/resource/{doctype}", params=params)
        return body.get("data") or []

    async def ping(self) -> None:
        """Cek ringan untuk Last Sync: `frappe.handler.ping` menjawab "pong".

        Lewat `_request` yang sama, jadi token yang salah terbaca gagal di sini juga,
        bukan baru ketahuan saat kunjungan pertama ditolak.
        """
        await self._request("GET", "/api/method/ping")

    async def call_method(self, method: str, payload: dict[str, Any]) -> Any:
        """POST one whitelisted method and return what it answered."""
        body = await self._request("POST", f"/api/method/{method}", json=payload)
        return body.get("message")

    async def _request(self, verb: str, path: str, **kwargs: Any) -> dict[str, Any]:
        where = f"{verb} {path}"
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(verb, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ErpUnavailable(f"{where}: {exc}") from exc

        status = response.status_code
        body = _json_object(response)
        if status >= 500:
            if status not in _GATEWAY and _is_frappe_error(body):
                raise ErpServerError(
                    f"{where}: {_reason(response, body)}",
                    status=status,
                    exc_type=(body or {}).get("exc_type"),
                )
            raise ErpUnavailable(f"{where}: HTTP {status}", status=status)
        if status >= 400:
            raise ErpRejected(
                f"{where}: {_reason(response, body)}",
                status=status,
                exc_type=(body or {}).get("exc_type"),
            )
        if body is None:
            # Not Frappe speaking. `status=None` on purpose: Last Sync reads it as "not
            # reached" (`galat_jaringan`), which is the truth for a portal or a wrong URL.
            raise ErpUnavailable(
                f"{where}: HTTP {status} is not a Frappe JSON answer: {_snippet(response)}"
            )
        return body


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    """The body as a JSON object, or None for anything else (HTML, text, a list)."""
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _is_frappe_error(body: dict[str, Any] | None) -> bool:
    return body is not None and any(key in body for key in _FRAPPE_ERROR_KEYS)


def _reason(response: httpx.Response, body: dict[str, Any] | None) -> str:
    """Frappe's own words. This is the only trace of why a message never lands."""
    known = body or {}
    detail = known.get("exception") or known.get("message") or response.text
    return f"HTTP {response.status_code}: {str(detail)[:_REASON_CHARS]}"


def _snippet(response: httpx.Response) -> str:
    return repr(" ".join(response.text.split())[:_BODY_CHARS])


def galat_jaringan(exc: BaseException) -> bool:
    """Last Sync: AutoERP tidak terjangkau, bukan menjawab dengan penolakan.

    Diklasifikasi lewat TIPE exception, bukan status HTTP-nya. Setiap `ErpUnavailable`
    berarti tidak ada jawaban yang bisa dipakai (jaringan, timeout, gateway, halaman 5xx
    yang bukan Frappe, atau 2xx yang bukan objek JSON Frappe), apa pun status yang
    menempel di dalamnya. Sebelum ini status 500 non-Frappe (nginx di depan Frappe yang
    mati) lolos dari `galat_jaringan_http` (yang cuma mengenal None/502/503/504), jadi
    Last Sync tetap hijau, dan bahkan membersihkan galat jaringan sungguhan yang lebih
    lama. `ErpRejected` dan `ErpServerError` tetap bukan galat jaringan: AutoERP MENJAWAB.
    """
    return isinstance(exc, ErpUnavailable)
