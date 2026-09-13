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

from palmgrade.integrations.erp.client import ErpClient, ErpRejected, ErpUnavailable

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
