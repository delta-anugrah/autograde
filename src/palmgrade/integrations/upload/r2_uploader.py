"""Klien Cloudflare R2 — bodoh & stateless (spec 2026-07-10 §3.2).

Satu tugas: PUT file lokal ke bucket. Tanpa retry sendiri, tanpa state —
kegagalan dibiarkan naik ke pemanggil (manifest yang mengatur requeue).
r2_key deterministik dari path → re-upload selalu menimpa objek yang sama
(S3 PUT overwrite) → tidak pernah ada duplikat di R2.
"""
from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ...domain.capture_layout import build_r2_key  # noqa: F401
from ...domain.sinkron import galat_jaringan_http

#: Objek yang dicek Last Sync. Ada begitu manifest pertama naik; sebelum itu R2
#: menjawab 404, dan 404 itu sudah cukup membuktikan R2 terjangkau dan kuncinya sah.
KUNCI_CEK = "viewer.html"

# Cek tiap menit tidak boleh menggantung semenit penuh seperti bawaan boto3
# (connect 60 dtk, ulang 4 kali): statusnya jadi terlambat justru saat putus.
_CONFIG_CEK = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1})


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
        self._client_cek = client

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{self._account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
            )
        return self._client

    def cek(self) -> None:
        """Last Sync: melempar kalau R2 tidak terjangkau atau menolak kuncinya."""
        if self._client_cek is None:
            # Sesi sendiri: sesi bawaan boto3 tidak aman dipakai dua thread yang membuat
            # klien bersamaan (cek ini di satu thread, manifest kunjungan di thread lain).
            self._client_cek = boto3.session.Session().client(
                "s3",
                endpoint_url=f"https://{self._account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                config=_CONFIG_CEK,
            )
        try:
            self._client_cek.head_object(Bucket=self.bucket, Key=KUNCI_CEK)
        except ClientError as exc:
            kode = str(exc.response.get("Error", {}).get("Code", ""))
            if kode in {"404", "NoSuchKey", "NotFound"}:
                return
            raise

    def put(self, local_path: Path, r2_key: str, *, content_type: str = "image/webp") -> None:
        self.put_bytes(local_path.read_bytes(), r2_key, content_type=content_type)

    def put_bytes(self, body: bytes, r2_key: str, *, content_type: str) -> None:
        self._get_client().put_object(Bucket=self.bucket, Key=r2_key, Body=body, ContentType=content_type)


def galat_jaringan(exc: BaseException) -> bool:
    """Last Sync: R2 tidak terjangkau (bukan menolak). Jawaban HTTP 4xx atau 500 dari R2
    berarti R2 menjawab; tanpa jawaban atau gateway mati berarti jaringan."""
    if isinstance(exc, ClientError):
        return galat_jaringan_http(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode"))
    return True
