"""Format Hikrobot MVS SDK return codes untuk logging yang bisa dibaca.

SDK mengembalikan `int` 32-bit (mis. 0x80000203). Di Python nilai itu tampil
sebagai desimal negatif (-2147483133) yang tidak bisa dicocokkan langsung ke
tabel error MVS — memperlambat debugging (insiden Line 2). Helper ini murni
(tanpa cv2/numpy/SDK) supaya bisa diunit-test di host.
"""

from __future__ import annotations

# Subset error MVS yang sering muncul di lapangan. Nilai dari MvErrorDefine.h.
_MVS_ERROR_NAMES: dict[int, str] = {
    0x00000000: "MV_OK",
    0x80000000: "MV_E_HANDLE",
    0x80000001: "MV_E_SUPPORT",
    0x80000002: "MV_E_BUFOVER",
    0x80000003: "MV_E_CALLORDER",
    0x80000004: "MV_E_PARAMETER",
    0x80000006: "MV_E_RESOURCE",
    0x80000007: "MV_E_NODATA",
    0x80000008: "MV_E_PRECONDITION",
    0x80000009: "MV_E_VERSION",
    0x8000000A: "MV_E_NOENOUGH_BUF",
    0x8000000B: "MV_E_ABNORMAL_IMAGE",
    0x80000203: "MV_E_ACCESS_DENIED",
    0x80000204: "MV_E_TIMEOUT",
    0x800000FF: "MV_E_UNKNOW",
}


def format_mvs_ret(ret: int) -> str:
    """Kembalikan representasi mudah dibaca dari return code SDK.

    Contoh: 0x80000203 → "0x80000203 (MV_E_ACCESS_DENIED)".
    Nilai negatif (int Python) dinormalisasi ke unsigned 32-bit dulu.
    """
    code = ret & 0xFFFFFFFF
    name = _MVS_ERROR_NAMES.get(code)
    hex_str = f"0x{code:08X}"
    return f"{hex_str} ({name})" if name else hex_str
