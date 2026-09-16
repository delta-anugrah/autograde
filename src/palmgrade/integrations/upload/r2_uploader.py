"""Klien Cloudflare R2 — bodoh & stateless (spec 2026-07-10 §3.2).

Satu tugas: PUT file lokal ke bucket. Tanpa retry sendiri, tanpa state —
kegagalan dibiarkan naik ke pemanggil (manifest yang mengatur requeue).
r2_key deterministik dari path → re-upload selalu menimpa objek yang sama
(S3 PUT overwrite) → tidak pernah ada duplikat di R2.
"""
from __future__ import annotations

from pathlib import Path

import boto3

from ...domain.capture_layout import build_r2_key  # noqa: F401


class R2Uploader:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        client=None,
    ) -> None:
        self._account_id = account_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self.bucket = bucket
        self._client = client  # injectable untuk test; lazy untuk runtime

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{self._account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
            )
        return self._client

    def put(self, local_path: Path, r2_key: str, *, content_type: str = "image/webp") -> None:
        self.put_bytes(local_path.read_bytes(), r2_key, content_type=content_type)

    def put_bytes(self, body: bytes, r2_key: str, *, content_type: str) -> None:
        self._get_client().put_object(Bucket=self.bucket, Key=r2_key, Body=body, ContentType=content_type)
