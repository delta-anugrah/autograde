"""The AutoERP client (contract §5, backlog AG-2).

Pinned: the token header, the request shapes both callers depend on, and the one
distinction every caller acts on — AutoERP refused this request (4xx, retrying
now changes nothing) or AutoERP could not be reached (network, timeout, 5xx).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from palmgrade.integrations.erp.client import (
    ErpClient,
    ErpRejected,
    ErpServerError,
    ErpUnavailable,
    galat_jaringan,
)

ERP = "http://erp.local"


def _client(handler) -> ErpClient:
    return ErpClient(ERP, "k", "s", transport=httpx.MockTransport(handler))


def _frappe_error(status: int, exc_type: str, message: str) -> httpx.Response:
    """Frappe's own error envelope, as observed against autoerp 51d3bf2."""
    return httpx.Response(
        status,
        json={"exc_type": exc_type, "exception": f"frappe.exceptions.{exc_type}: {message}"},
    )


def test_call_method_posts_json_and_returns_the_message():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"name": "BE 1 AA"}})

    result = asyncio.run(
        _client(handler).call_method(
            "erpnext.palm_mill.api.upsert_truck", {"plate_number": "BE 1 AA"}
        )
    )

    assert result == {"name": "BE 1 AA"}
    request = seen[0]
    assert (request.method, request.url.path) == (
        "POST", "/api/method/erpnext.palm_mill.api.upsert_truck",
    )
    assert request.headers["authorization"] == "token k:s"
    assert json.loads(request.content) == {"plate_number": "BE 1 AA"}


def test_list_modified_since_asks_for_one_page_in_modified_order():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"name": "BE 1 AA"}]})

    rows = asyncio.run(
        _client(handler).list_modified_since(
            "Truck", ("name", "modified"), "2026-09-07 13:51:05.000000", limit=500
        )
    )

    assert rows == [{"name": "BE 1 AA"}]
    params = seen[0].url.params
    assert seen[0].url.path == "/api/resource/Truck"
    assert json.loads(params["fields"]) == ["name", "modified"]
    assert json.loads(params["filters"]) == [["modified", ">", "2026-09-07 13:51:05.000000"]]
    assert (params["order_by"], params["limit_page_length"]) == ("modified asc", "500")


def test_the_first_pull_has_no_cursor_and_so_no_filter():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    asyncio.run(_client(handler).list_modified_since("Supplier", ("name",), None, limit=500))

    assert "filters" not in seen[0].url.params


@pytest.mark.parametrize(
    "status, exc_type",
    [(417, "ValidationError"), (401, "AuthenticationError"), (403, "PermissionError")],
)
def test_a_4xx_is_a_rejection_that_carries_frappes_reason(status, exc_type):
    def handler(request: httpx.Request) -> httpx.Response:
        return _frappe_error(status, exc_type, "Nomor polisi harus berisi huruf atau angka")

    with pytest.raises(ErpRejected) as caught:
        asyncio.run(_client(handler).call_method("m", {}))

    assert (caught.value.status, caught.value.exc_type) == (status, exc_type)
    # The reason is the only trace of why one message never lands.
    assert "Nomor polisi" in str(caught.value)


def test_a_5xx_means_autoerp_could_not_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(ErpUnavailable) as caught:
        asyncio.run(_client(handler).call_method("m", {}))

    assert caught.value.status == 502


def test_a_dead_link_means_autoerp_could_not_be_reached():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(ErpUnavailable):
        asyncio.run(_client(handler).call_method("m", {}))


# ── batch 2.7: nothing but an ErpError ever leaves the client ────────────────


def test_a_200_that_is_not_json_is_unavailable_not_a_crash():
    """A captive portal or a wrong ERP_URL answers 200 with HTML. `response.json()` used
    to raise a bare JSONDecodeError past every caller, and the outbox worker stalled."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Login hotspot</body></html>")

    with pytest.raises(ErpUnavailable) as caught:
        asyncio.run(_client(handler).call_method("m", {}))

    # Read as "not reached", like a dead link: it is not AutoERP that answered.
    assert caught.value.status is None
    assert galat_jaringan(caught.value)
    assert "HTTP 200" in str(caught.value) and "Login hotspot" in str(caught.value)


@pytest.mark.parametrize("body", [[1, 2], "pong", 42, None])
def test_json_that_is_not_an_object_is_not_frappe_either(body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(ErpUnavailable):
        asyncio.run(_client(handler).call_method("m", {}))


def test_every_call_shape_is_protected():
    """The master-data pull and the Last Sync ping share `_request` with the outbox."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = _client(handler)
    for call in (
        lambda: client.ping(),
        lambda: client.list_modified_since("Truck", ("name",), None, limit=1),
        lambda: client.call_method("m", {}),
    ):
        with pytest.raises(ErpUnavailable):
            asyncio.run(call())


def test_a_frappe_500_is_a_server_error_that_carries_frappes_reason():
    """AutoERP is up and THIS payload crashed a handler: a per-message problem."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _frappe_error(500, "KeyError", "'counts'")

    with pytest.raises(ErpServerError) as caught:
        asyncio.run(_client(handler).call_method("m", {}))

    assert (caught.value.status, caught.value.exc_type) == (500, "KeyError")
    assert "KeyError: 'counts'" in str(caught.value)
    assert not galat_jaringan(caught.value)


def test_a_500_page_that_is_not_frappes_is_still_unavailable():
    """nginx in front of a dead Frappe: says nothing about this payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html><center>nginx</center></html>")

    with pytest.raises(ErpUnavailable) as caught:
        asyncio.run(_client(handler).call_method("m", {}))

    assert caught.value.status == 500


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_gateway_status_is_unavailable_even_with_a_frappe_looking_body(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return _frappe_error(status, "OperationalError", "database is down")

    with pytest.raises(ErpUnavailable) as caught:
        asyncio.run(_client(handler).call_method("m", {}))

    assert galat_jaringan(caught.value)
