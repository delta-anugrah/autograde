"""Pemilihan kamera Hikrobot berdasarkan **serial number** (stabil), bukan
posisi array hasil enumerate (yang urutannya tidak deterministik antar
container / boot untuk GigE — bergantung timing balasan discovery jaringan).

Modul ini **murni** (tidak import SDK MvImport / ctypes / cv2) supaya bisa
di-unit-test tanpa hardware. Ia bekerja di atas objek device apa pun yang
punya atribut `nTLayerType` + `SpecialInfo.{stGigEInfo,stUsb3VInfo}.chSerialNumber`
(struct SDK asli maupun dummy di test).

Root cause yang diperbaiki: 3 line assign kamera lewat `CAMERA_DEVICE_INDEX`
(= `pDeviceInfo[index]`). Karena urutan enum GigE tidak stabil, saat 3 container
start bersamaan bisa saling rebut kamera → `MV_E_ACCESS_DENIED` (0x80000203) di
line yang kebagian device yang sudah dibuka exclusive. Selektor by-serial membuat
tiap line **selalu** memilih kamera fisik yang sama.
"""

from __future__ import annotations

from collections.abc import Iterable

# Nilai konstanta transport-layer dari SDK (CameraParams_const.py).
# Di-hardcode di sini supaya modul tetap murni (tanpa import SDK).
MV_GIGE_DEVICE = 0x00000001
MV_USB_DEVICE = 0x00000004


def decode_serial(raw: Iterable[int]) -> str:
    """Decode `chSerialNumber` (array of unsigned byte) → str ASCII.

    Berhenti di null-terminator pertama; byte non-printable diabaikan.
    Menerima ctypes `c_ubyte * N` maupun list int biasa (untuk test).
    """
    out = bytearray()
    for b in raw:
        b = int(b)
        if b == 0:
            break
        out.append(b)
    return out.decode("ascii", errors="ignore").strip()


def extract_serial(device_info) -> str:
    """Ambil serial dari satu `MV_CC_DEVICE_INFO`, lintas GigE/USB.

    Pilih sub-struct sesuai `nTLayerType`; default ke GigE kalau tipe lain
    (line ini pakai kamera GigE). Return "" kalau tidak terbaca.
    """
    special = device_info.SpecialInfo
    tlayer = int(device_info.nTLayerType)
    if tlayer == MV_USB_DEVICE:
        info = special.stUsb3VInfo
    else:
        # GigE (dan fallback aman untuk tipe lain)
        info = special.stGigEInfo
    return decode_serial(info.chSerialNumber)


def find_index_by_serial(device_infos: list, serial: str) -> int:
    """Cari index device yang serial-nya sama dengan `serial`.

    `device_infos` = list objek device (sudah di-`cast().contents`).
    Perbandingan case-insensitive + strip (serial MVS uppercase, tapi jaga-jaga).
    Raise `ValueError` kalau tidak ada yang cocok — pemanggil mengubahnya jadi
    error connect yang bisa dibaca (dan reconnect loop akan retry).
    """
    want = serial.strip().casefold()
    available = []
    for idx, dev in enumerate(device_infos):
        got = extract_serial(dev)
        available.append(got)
        if got.casefold() == want:
            return idx
    raise ValueError(
        f"Kamera dengan serial {serial!r} tidak ditemukan. "
        f"Serial ter-enumerate: {available}"
    )
