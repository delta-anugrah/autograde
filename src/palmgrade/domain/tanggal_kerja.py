"""Batas hari kerja pabrik (§6.1 rencana PalmOS).

Pabrik jalan ~20 jam/hari dan LEWAT tengah malam. Batas hari UTC memotong satu
shift jadi dua tanggal, jadi `tanggal_kerja` dihitung dari timestamp event itu
sendiri saat ingest lalu DISIMPAN sebagai kolom — jangan pernah diturunkan dari
`creation`, `now()`, atau nama folder. Event yang datang telat (outbox retry
setelah listrik mati) tetap mendarat di harinya sendiri.

Bebas dependensi berat supaya bisa dites tanpa kamera/torch.
"""
from __future__ import annotations

from datetime import UTC, datetime, tzinfo


def tanggal_kerja_for(timestamp_iso: str, tz: tzinfo) -> str:
    """`YYYY-MM-DD` menurut zona pabrik. ValueError kalau timestamp tak terbaca.

    Timestamp tanpa offset dianggap UTC — itu yang dikirim line kamera
    (`datetime.now(timezone.utc).isoformat()` kadang tanpa suffix di data lama).
    Sengaja melempar, bukan jatuh ke hari ini: ingest membalas 400, outbox line
    menahan lalu mencoba lagi, dan barisnya muncul sebagai `outbox_failed` —
    jauh lebih baik daripada tonase diam-diam nempel di tanggal yang salah.
    """
    raw = timestamp_iso.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)  # ValueError kalau bentuknya bukan ISO
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).strftime("%Y-%m-%d")
