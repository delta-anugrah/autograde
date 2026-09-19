"""HTTP client for AutoERP (contract §5).

Frappe's own REST is the entire server side, so this stays thin: the token
header, the two call shapes the console needs, and one honest distinction —
AutoERP refused the request, or AutoERP could not answer. Every caller acts on
that difference: a refusal is kept with its reason, an outage is retried later.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

_TIMEOUT_S = 15.0
_REASON_CHARS = 300


class ErpError(Exception):
    def __init__(self, message: str, *, status: int | None = None, exc_type: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.exc_type = exc_type


class ErpRejected(ErpError):
    """AutoERP refused the request as sent (4xx). Repeating it changes nothing."""


class ErpUnavailable(ErpError):
    """AutoERP could not answer (network, timeout, 5xx). Worth another try."""


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

    async def call_method(self, method: str, payload: dict[str, Any]) -> Any:
        """POST one whitelisted method and return what it answered."""
        body = await self._request("POST", f"/api/method/{method}", json=payload)
        return body.get("message")

    async def _request(self, verb: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(verb, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ErpUnavailable(f"{verb} {path}: {exc}") from exc

        if response.status_code >= 500:
            raise ErpUnavailable(
                f"{verb} {path}: HTTP {response.status_code}", status=response.status_code
            )
        if response.status_code >= 400:
            raise ErpRejected(
                f"{verb} {path}: {_reason(response)}",
                status=response.status_code,
                exc_type=_body(response).get("exc_type"),
            )
        return response.json()


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _reason(response: httpx.Response) -> str:
    """Frappe's own words. This is the only trace of why a message never lands."""
    body = _body(response)
    detail = body.get("exception") or body.get("message") or response.text
    return f"HTTP {response.status_code}: {str(detail)[:_REASON_CHARS]}"
