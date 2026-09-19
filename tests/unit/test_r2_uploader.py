"""Unit tests klien R2 (spec §3.2, §7.4). boto3 client di-inject & di-fake —
tanpa jaringan, tanpa kredensial, tanpa moto."""
from __future__ import annotations

from unittest.mock import Mock

from palmgrade.integrations.upload.r2_uploader import R2Uploader, build_r2_key


def test_r2_key_deterministic():
    # path sama = key sama → re-upload menimpa dirinya sendiri (anti-duplikat lapis 2)
    a = build_r2_key("M1", "captures/results/2026-07-10/x_auto.webp")
    b = build_r2_key("M1", "captures/results/2026-07-10/x_auto.webp")
    assert a == b == "M1/results/2026-07-10/x_auto.webp"


def test_r2_key_machine_prefix_isolates_lines():
    p = "captures/results/2026-07-10/x_auto.webp"
    assert build_r2_key("M1", p) != build_r2_key("M2", p)


def test_put_calls_put_object(tmp_path):
    f = tmp_path / "x.webp"
    f.write_bytes(b"webp-bytes")
    fake = Mock()
    up = R2Uploader(account_id="acc", access_key_id="k", secret_access_key="s",
                    bucket="palmgrade", client=fake)
    up.put(f, "M1/results/2026-07-10/x.webp")
    kwargs = fake.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "palmgrade"
    assert kwargs["Key"] == "M1/results/2026-07-10/x.webp"
    assert kwargs["ContentType"] == "image/webp"
    assert kwargs["Body"] == b"webp-bytes"


def test_put_propagates_client_error(tmp_path):
    f = tmp_path / "x.webp"
    f.write_bytes(b"d")
    fake = Mock()
    fake.put_object.side_effect = ConnectionError("R2 down")
    up = R2Uploader(account_id="a", access_key_id="k", secret_access_key="s",
                    bucket="b", client=fake)
    try:
        up.put(f, "k")
        raise AssertionError("harus raise")
    except ConnectionError:
        pass  # retry = urusan manifest, bukan uploader


def test_put_bytes_with_a_content_type():
    fake = Mock()
    up = R2Uploader(account_id="a", access_key_id="k", secret_access_key="s", bucket="b", client=fake)
    up.put_bytes(b'{"a":1}', "visits/v-1.json", content_type="application/json")
    kwargs = fake.put_object.call_args.kwargs
    assert (kwargs["Key"], kwargs["ContentType"], kwargs["Body"]) == ("visits/v-1.json", "application/json", b'{"a":1}')
