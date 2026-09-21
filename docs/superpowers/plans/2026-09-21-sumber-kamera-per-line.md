# Sumber Kamera Per-Line Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support memilih sumber kamera tiap line (Hikrobot / Webcam / Video / Foto) dari layar konsol, tanpa mengedit `.env` lewat AnyDesk.

**Architecture:** Setelan sumber pindah ke berkas `media.env` terpisah yang ditulis konsol dan dibaca Compose lewat `env_file`. Berkas media dipilih dari folder `media/` yang di-mount utuh (bukan bind-mount per berkas). Line membaca setelannya dari environment saat boot; konsol merestart line yang berubah lewat `POST /internal/restart`.

**Tech Stack:** Python 3.12, FastAPI, pytest, Docker Compose, cv2 (hanya untuk pembuktian berkas di konsol), HTML/JS vanilla di `console.html`.

**Spec:** `docs/superpowers/specs/2026-09-21-sumber-kamera-per-line-design.md`

## Global Constraints

- **Bahasa kode**: docstring dan komentar boleh Indonesia; nama simbol Inggris kecuali mengikuti tetangganya yang sudah Indonesia (`bersihkan_*`, `SetelanTidakSah`). Ikuti berkas yang disentuh.
- **Judul & body PR wajib Inggris.** Pesan commit boleh Indonesia.
- **`domain/` tidak boleh import cv2/torch/numpy.** Unit suite berjalan tanpa cv2 dengan sengaja; satu import saja menarik seluruh jalur capture keluar dari CI ringan.
- **Empat pilihan layar → tiga nilai `CAMERA_TYPE`:** `hikrobot`→`hikrobot`, `webcam`→`opencv`, `video`→`opencv`, `foto`→`photo`.
- **`MEDIA_FILE` adalah NAMA BERKAS, bukan path.** Selalu di-join ke `/media` oleh kode, tidak pernah dipakai mentah.
- **Tiga line**: `line-1`, `line-2`, `line-3`. Prefix env `LINE_1_`, `LINE_2_`, `LINE_3_`.
- **Berkas rahasia `.env` tidak pernah ditulis kode.** Hanya `media.env`.
- **Branch**: `feat/sumber-kamera-per-line` (sudah dibuat, spec sudah di-commit di sana).
- **Verifikasi**: `.venv/bin/python -m pytest tests/unit -q` untuk unit, `.venv/bin/python -m pytest tests/e2e -q` untuk e2e, `.venv/bin/ruff check src tests` untuk lint.

---

### Task 1: Aturan sumber kamera (domain, tanpa I/O)

**Files:**
- Create: `src/palmgrade/domain/sumber_kamera.py`
- Test: `tests/unit/test_sumber_kamera.py`

**Interfaces:**
- Consumes: tidak ada (tugas pertama)
- Produces:
  - `SUMBER: tuple[str, ...]` = `("hikrobot", "webcam", "video", "foto")`
  - `BUTUH_BERKAS: frozenset[str]` = `{"video", "foto"}`
  - `CAMERA_TYPE_UNTUK: dict[str, str]` — pilihan layar → nilai `CAMERA_TYPE`
  - `SumberTidakSah(ValueError)`
  - `bersihkan_sumber(payload: dict) -> dict` → `{"sumber": str, "berkas": str, "ulang": bool}`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sumber_kamera.py
"""Aturan sumber kamera per line — tanpa I/O, tanpa cv2."""
from __future__ import annotations

import pytest

from palmgrade.domain.sumber_kamera import (
    BUTUH_BERKAS,
    CAMERA_TYPE_UNTUK,
    SUMBER,
    SumberTidakSah,
    bersihkan_sumber,
)


def test_empat_pilihan_layar():
    assert SUMBER == ("hikrobot", "webcam", "video", "foto")


def test_pemetaan_ke_camera_type():
    # Empat pilihan layar memetakan ke tiga nilai CAMERA_TYPE: webcam dan video
    # sama-sama OpenCVCamera, yang membedakan cuma ada-tidaknya berkas.
    assert CAMERA_TYPE_UNTUK == {
        "hikrobot": "hikrobot",
        "webcam": "opencv",
        "video": "opencv",
        "foto": "photo",
    }


def test_hikrobot_tanpa_berkas_sah():
    assert bersihkan_sumber({"sumber": "hikrobot"}) == {
        "sumber": "hikrobot",
        "berkas": "",
        "ulang": False,
    }


def test_video_dengan_berkas_sah():
    hasil = bersihkan_sumber({"sumber": "video", "berkas": "konveyor.mp4", "ulang": True})
    assert hasil == {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True}


def test_pilihan_asing_ditolak():
    with pytest.raises(SumberTidakSah, match="sumber harus salah satu"):
        bersihkan_sumber({"sumber": "gopro"})


def test_video_tanpa_berkas_ditolak():
    # Tanpa ini line boot, PhotoCamera/OpenCVCamera raise, container mati,
    # restart:unless-stopped menyalakannya lagi — loop yang cuma bisa
    # dihentikan lewat AnyDesk.
    with pytest.raises(SumberTidakSah, match="video butuh berkas"):
        bersihkan_sumber({"sumber": "video", "berkas": ""})


def test_foto_tanpa_berkas_ditolak():
    with pytest.raises(SumberTidakSah, match="foto butuh berkas"):
        bersihkan_sumber({"sumber": "foto"})


def test_hikrobot_dengan_berkas_ditolak():
    # Berkas yang diisi tapi tidak pernah dibaca adalah keadaan yang terlihat
    # benar di layar dan tidak melakukan apa-apa.
    with pytest.raises(SumberTidakSah, match="hikrobot tidak memakai berkas"):
        bersihkan_sumber({"sumber": "hikrobot", "berkas": "konveyor.mp4"})


@pytest.mark.parametrize(
    "nama",
    ["../rahasia.env", "/etc/passwd", "sub/dir.mp4", "..", "a\\b.mp4"],
)
def test_nama_berkas_berbahaya_ditolak(nama):
    with pytest.raises(SumberTidakSah, match="nama berkas"):
        bersihkan_sumber({"sumber": "video", "berkas": nama})


def test_berkas_dipangkas_spasi():
    hasil = bersihkan_sumber({"sumber": "foto", "berkas": "  sawit.jpg  "})
    assert hasil["berkas"] == "sawit.jpg"


def test_ulang_dari_string():
    # Input HTML mengirim "true"/"on", bukan boolean JSON.
    assert bersihkan_sumber({"sumber": "video", "berkas": "a.mp4", "ulang": "true"})["ulang"] is True
    assert bersihkan_sumber({"sumber": "video", "berkas": "a.mp4", "ulang": "off"})["ulang"] is False


def test_field_asing_ditolak():
    with pytest.raises(SumberTidakSah, match="field tidak dikenal"):
        bersihkan_sumber({"sumber": "hikrobot", "warna": "merah"})


def test_payload_bukan_objek_ditolak():
    with pytest.raises(SumberTidakSah, match="harus objek"):
        bersihkan_sumber(["hikrobot"])


def test_butuh_berkas_isinya_video_dan_foto():
    assert BUTUH_BERKAS == frozenset({"video", "foto"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_sumber_kamera.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.domain.sumber_kamera'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/palmgrade/domain/sumber_kamera.py
"""Sumber kamera satu line: pilihan yang sah dan batas kewarasannya.

`CAMERA_TYPE` dulu cuma hidup di `.env`, satu nilai untuk keempat container.
Mengubahnya berarti AnyDesk ke PC pabrik, edit berkas, restart. Sekarang tiap
line dipilih sendiri dari layar support.

**Empat pilihan layar, tiga nilai `CAMERA_TYPE`.** `webcam` dan `video`
sama-sama `OpenCVCamera`; yang membedakan cuma ada-tidaknya berkas. Pemisahan
itu ada di layar, bukan di `CAMERA_TYPE`, supaya nilai env-nya tidak berubah
arti bagi kode yang sudah membacanya.

**Berkas wajib untuk `video` dan `foto`, terlarang untuk dua lainnya.**
`OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat berkasnya tidak terbaca
(fail-fast), berbeda dengan `hikrobot` yang cuma memberi peringatan. Berkas
kosong yang lolos ke sini berarti: line boot, gagal, mati, `restart:
unless-stopped` menyalakannya lagi, gagal lagi — selamanya. Sebaliknya berkas
yang diisi untuk `hikrobot` tidak pernah dibaca siapa pun: keadaan yang terlihat
benar di layar dan tidak melakukan apa-apa.

Nama berkas **disaring, bukan di-escape**. Berkas dipilih dari daftar yang
konsol susun sendiri dari folder `media/`, jadi nilai di luar daftar itu payload
yang dibuat tangan, dan satu-satunya alasan membuatnya adalah keluar dari
folder itu.

Bebas dari numpy/torch/cv2 supaya ikut CI ringan (aturan yang sama dengan
`domain/grade_class.py`).
"""
from __future__ import annotations

from typing import Any

#: Pilihan sebagaimana layar menampilkannya, dalam urutan tampil.
SUMBER: tuple[str, ...] = ("hikrobot", "webcam", "video", "foto")

#: Pilihan yang berkasnya wajib ada. Sisanya justru menolak berkas.
BUTUH_BERKAS: frozenset[str] = frozenset({"video", "foto"})

#: Pilihan layar -> nilai `CAMERA_TYPE` yang dibaca `Settings`.
CAMERA_TYPE_UNTUK: dict[str, str] = {
    "hikrobot": "hikrobot",
    "webcam": "opencv",
    "video": "opencv",
    "foto": "photo",
}

#: Karakter yang membuat nama berkas bisa menunjuk keluar dari `media/`.
_BERBAHAYA = ("/", "\\", "..", "\x00")

_FIELD = frozenset({"sumber", "berkas", "ulang"})


class SumberTidakSah(ValueError):
    """Nilai di luar batas. Route menerjemahkannya jadi 400."""


def _boolean(nilai: Any) -> bool:
    """`True`/`False` dari boolean JSON, string input HTML, atau apa pun."""
    if isinstance(nilai, str):
        return nilai.strip().lower() in ("1", "true", "ya", "on")
    return bool(nilai)


def bersihkan_sumber(payload: dict[str, Any]) -> dict[str, Any]:
    """Payload satu line dari layar -> dict siap simpan.

    Field asing ditolak, tidak diabaikan: salah ketik nama field akan terlihat
    berhasil padahal tidak mengubah apa pun.
    """
    if not isinstance(payload, dict):
        raise SumberTidakSah("setelan sumber harus objek")

    asing = set(payload) - _FIELD
    if asing:
        raise SumberTidakSah(f"field tidak dikenal: {', '.join(sorted(asing))}")

    sumber = str(payload.get("sumber") or "").strip().lower()
    if sumber not in SUMBER:
        raise SumberTidakSah(f"sumber harus salah satu dari: {', '.join(SUMBER)}")

    berkas = str(payload.get("berkas") or "").strip()
    if berkas and any(tanda in berkas for tanda in _BERBAHAYA):
        raise SumberTidakSah(
            "nama berkas tidak boleh memuat pemisah folder atau '..'"
        )

    if sumber in BUTUH_BERKAS and not berkas:
        raise SumberTidakSah(f"{sumber} butuh berkas")
    if sumber not in BUTUH_BERKAS and berkas:
        raise SumberTidakSah(f"{sumber} tidak memakai berkas")

    return {"sumber": sumber, "berkas": berkas, "ulang": _boolean(payload.get("ulang"))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_sumber_kamera.py -q`
Expected: PASS, 14 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/domain/sumber_kamera.py tests/unit/test_sumber_kamera.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/domain/sumber_kamera.py tests/unit/test_sumber_kamera.py
git commit -m "feat(sumber): aturan sumber kamera per line

Empat pilihan layar memetakan ke tiga nilai CAMERA_TYPE. Berkas wajib untuk
video/foto dan terlarang untuk hikrobot/webcam — yang pertama mencegah loop
boot-gagal-restart, yang kedua mencegah field terisi yang tidak pernah dibaca.
Nama berkas disaring, bukan di-escape."
```

---

### Task 2: Terjemahan pilihan → kamera mana (resolver)

**Files:**
- Create: `src/palmgrade/domain/sumber_kamera_resolver.py`
- Test: `tests/unit/test_sumber_kamera_resolver.py`

**Interfaces:**
- Consumes: `CAMERA_TYPE_UNTUK`, `SUMBER` dari Task 1
- Produces:
  - `MEDIA_DIR: str` = `"/media"`
  - `RencanaKamera` — dataclass beku: `camera_type: str`, `video_path: str`, `photo_path: str`, `loop: bool`
  - `rencana_kamera(sumber: str, berkas: str, ulang: bool, media_dir: str = MEDIA_DIR) -> RencanaKamera`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sumber_kamera_resolver.py
"""Pilihan layar -> kamera mana yang dipakai, dan path apa yang diberikan."""
from __future__ import annotations

import pytest

from palmgrade.domain.sumber_kamera_resolver import (
    MEDIA_DIR,
    RencanaKamera,
    rencana_kamera,
)


def test_media_dir_tetap():
    assert MEDIA_DIR == "/media"


def test_hikrobot():
    r = rencana_kamera("hikrobot", "", False)
    assert r == RencanaKamera(camera_type="hikrobot", video_path="", photo_path="", loop=False)


def test_webcam_tidak_memakai_path():
    # OpenCVCamera dengan video_path kosong = webcam lewat device index.
    r = rencana_kamera("webcam", "", False)
    assert r == RencanaKamera(camera_type="opencv", video_path="", photo_path="", loop=False)


def test_video_mengisi_video_path():
    r = rencana_kamera("video", "konveyor.mp4", True)
    assert r == RencanaKamera(
        camera_type="opencv", video_path="/media/konveyor.mp4", photo_path="", loop=True
    )


def test_foto_mengisi_photo_path():
    r = rencana_kamera("foto", "sawit.jpg", False)
    assert r == RencanaKamera(
        camera_type="photo", video_path="", photo_path="/media/sawit.jpg", loop=False
    )


def test_ulang_diabaikan_selain_video():
    # `loop` cuma berarti bagi OpenCVCamera yang membaca berkas video.
    assert rencana_kamera("foto", "sawit.jpg", True).loop is False
    assert rencana_kamera("hikrobot", "", True).loop is False
    assert rencana_kamera("webcam", "", True).loop is False


def test_media_dir_bisa_diganti_untuk_tes():
    r = rencana_kamera("video", "a.mp4", False, media_dir="/tmp/m")
    assert r.video_path == "/tmp/m/a.mp4"


def test_sumber_asing_ditolak():
    with pytest.raises(ValueError, match="sumber tidak dikenal"):
        rencana_kamera("gopro", "", False)


def test_rencana_beku():
    r = rencana_kamera("hikrobot", "", False)
    with pytest.raises(Exception):
        r.camera_type = "opencv"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_sumber_kamera_resolver.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.domain.sumber_kamera_resolver'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/palmgrade/domain/sumber_kamera_resolver.py
"""Pilihan layar -> kamera mana yang dibangun, dan path apa yang diberikan.

Pemetaan ini sebelumnya berupa if-else di `main.py`, terjalin dengan
`connect()`, penanganan galat, dan `set_camera()`. Dipisahkan supaya bisa diuji
tanpa menyalakan aplikasi — dan supaya satu-satunya tempat yang tahu "webcam
berarti OpenCVCamera tanpa path" adalah berkas ini.

Nama berkas di-join ke `MEDIA_DIR` DI SINI, satu tempat. Nama itu datang dari
layar; menyerahkannya mentah ke pemanggil berarti tiap pemanggil harus ingat
menggabungkannya, dan yang lupa akan membuka berkas relatif terhadap direktori
kerja container.

Bebas cv2/torch (lihat `sumber_kamera`).
"""
from __future__ import annotations

from dataclasses import dataclass

from .sumber_kamera import CAMERA_TYPE_UNTUK

#: Folder media di dalam container, di-mount read-only dari host.
MEDIA_DIR = "/media"


@dataclass(frozen=True)
class RencanaKamera:
    """Apa yang `main.py` butuhkan untuk membangun kamera, tanpa membangunnya.

    Beku supaya tidak ada yang menambal satu field di tengah jalur boot dan
    membuat dua bagian `main.py` melihat rencana yang berbeda.
    """

    camera_type: str
    video_path: str
    photo_path: str
    loop: bool


def rencana_kamera(
    sumber: str, berkas: str, ulang: bool, media_dir: str = MEDIA_DIR
) -> RencanaKamera:
    """Satu line: pilihan layar -> rencana kamera.

    `ulang` sengaja diabaikan selain untuk `video`: mengulang hanya berarti
    sesuatu bagi `OpenCVCamera` yang membaca berkas. Membiarkannya `True` untuk
    foto akan menyimpan nilai yang tidak pernah dibaca — keadaan yang terlihat
    aktif di layar dan tidak melakukan apa-apa.
    """
    camera_type = CAMERA_TYPE_UNTUK.get(sumber)
    if camera_type is None:
        raise ValueError(f"sumber tidak dikenal: {sumber!r}")

    path = f"{media_dir}/{berkas}" if berkas else ""
    return RencanaKamera(
        camera_type=camera_type,
        video_path=path if sumber == "video" else "",
        photo_path=path if sumber == "foto" else "",
        loop=ulang if sumber == "video" else False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_sumber_kamera_resolver.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/domain/sumber_kamera_resolver.py tests/unit/test_sumber_kamera_resolver.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/domain/sumber_kamera_resolver.py tests/unit/test_sumber_kamera_resolver.py
git commit -m "feat(sumber): resolver pilihan layar ke rencana kamera

Nama berkas di-join ke /media di satu tempat. `ulang` diabaikan selain untuk
video, supaya tidak ada nilai tersimpan yang tidak pernah dibaca."
```

---

### Task 3: Baca & tulis `media.env`

**Files:**
- Create: `src/palmgrade/services/media_env_service.py`
- Test: `tests/unit/test_media_env_service.py`

**Interfaces:**
- Consumes: `SUMBER` dari Task 1 (untuk bawaan)
- Produces:
  - `MediaEnvService(path: Path)`
  - `.baca() -> dict[str, dict]` — kunci `"line-1"`/`"line-2"`/`"line-3"`, nilai `{"sumber","berkas","ulang"}`
  - `.tulis(setelan: dict[str, dict]) -> None`
  - `LINE_CODES: tuple[str, ...]` = `("line-1", "line-2", "line-3")`
  - `BAWAAN: dict` = `{"sumber": "hikrobot", "berkas": "", "ulang": False}`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_media_env_service.py
"""Baca & tulis media.env — satu-satunya yang tahu bentuk berkas itu."""
from __future__ import annotations

from palmgrade.services.media_env_service import (
    BAWAAN,
    LINE_CODES,
    MediaEnvService,
)


def test_line_codes_tiga():
    assert LINE_CODES == ("line-1", "line-2", "line-3")


def test_berkas_belum_ada_memberi_bawaan(tmp_path):
    svc = MediaEnvService(tmp_path / "media.env")
    hasil = svc.baca()
    assert hasil == {kode: dict(BAWAAN) for kode in LINE_CODES}


def test_bawaan_hikrobot(tmp_path):
    # PC pabrik yang belum punya media.env harus tetap memakai kamera sungguhan.
    svc = MediaEnvService(tmp_path / "media.env")
    assert svc.baca()["line-1"]["sumber"] == "hikrobot"


def test_tulis_lalu_baca_bolak_balik(tmp_path):
    svc = MediaEnvService(tmp_path / "media.env")
    setelan = {
        "line-1": {"sumber": "hikrobot", "berkas": "", "ulang": False},
        "line-2": {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True},
        "line-3": {"sumber": "foto", "berkas": "sawit.jpg", "ulang": False},
    }
    svc.tulis(setelan)
    assert svc.baca() == setelan


def test_isi_berkas_bentuk_env(tmp_path):
    path = tmp_path / "media.env"
    MediaEnvService(path).tulis(
        {
            "line-1": {"sumber": "video", "berkas": "a.mp4", "ulang": True},
            "line-2": {"sumber": "hikrobot", "berkas": "", "ulang": False},
            "line-3": {"sumber": "hikrobot", "berkas": "", "ulang": False},
        }
    )
    isi = path.read_text(encoding="utf-8")
    assert "LINE_1_CAMERA_TYPE=opencv" in isi
    assert "LINE_1_MEDIA_FILE=a.mp4" in isi
    assert "LINE_1_VIDEO_LOOP=true" in isi
    assert "LINE_2_CAMERA_TYPE=hikrobot" in isi
    assert "LINE_2_MEDIA_FILE=" in isi


def test_baris_tak_dikenal_diabaikan(tmp_path):
    # Berkas yang ditulis versi lebih baru tidak boleh mematikan versi lama.
    path = tmp_path / "media.env"
    path.write_text(
        "LINE_1_CAMERA_TYPE=photo\n"
        "LINE_1_MEDIA_FILE=sawit.jpg\n"
        "LINE_9_WARNA=merah\n"
        "BUKAN_BARIS_ENV\n"
        "# komentar\n"
        "\n",
        encoding="utf-8",
    )
    hasil = MediaEnvService(path).baca()
    assert hasil["line-1"] == {"sumber": "foto", "berkas": "sawit.jpg", "ulang": False}
    assert hasil["line-2"] == dict(BAWAAN)


def test_camera_type_asing_jatuh_ke_bawaan(tmp_path):
    # Berkas disunting tangan dengan nilai ngawur: line tetap boot memakai
    # kamera sungguhan, bukan gagal.
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=gopro\n", encoding="utf-8")
    assert MediaEnvService(path).baca()["line-1"] == dict(BAWAAN)


def test_opencv_tanpa_berkas_terbaca_webcam(tmp_path):
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=opencv\nLINE_1_MEDIA_FILE=\n", encoding="utf-8")
    assert MediaEnvService(path).baca()["line-1"]["sumber"] == "webcam"


def test_opencv_dengan_berkas_terbaca_video(tmp_path):
    path = tmp_path / "media.env"
    path.write_text("LINE_1_CAMERA_TYPE=opencv\nLINE_1_MEDIA_FILE=a.mp4\n", encoding="utf-8")
    assert MediaEnvService(path).baca()["line-1"]["sumber"] == "video"


def test_tulis_tidak_meninggalkan_berkas_separo(tmp_path, monkeypatch):
    # Menulis lewat berkas sementara + os.replace: berkas setengah tertulis
    # membuat ketiga line gagal boot.
    import os

    path = tmp_path / "media.env"
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})
    asli = path.read_text(encoding="utf-8")

    def replace_gagal(src, dst):
        raise OSError("disk penuh")

    monkeypatch.setattr(os, "replace", replace_gagal)
    try:
        MediaEnvService(path).tulis(
            {
                "line-1": {"sumber": "video", "berkas": "b.mp4", "ulang": False},
                "line-2": dict(BAWAAN),
                "line-3": dict(BAWAAN),
            }
        )
    except OSError:
        pass
    assert path.read_text(encoding="utf-8") == asli


def test_tulis_membuat_folder_induk(tmp_path):
    path = tmp_path / "config" / "media.env"
    MediaEnvService(path).tulis({kode: dict(BAWAAN) for kode in LINE_CODES})
    assert path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_media_env_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.services.media_env_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/palmgrade/services/media_env_service.py
"""Baca & tulis `media.env` — berkas setelan sumber kamera per line.

Berkas TERPISAH dari `.env`, sengaja. `.env` memuat `LICENSE_TOKEN`,
`R2_SECRET_ACCESS_KEY`, dan `WEBHOOK_SECRET`; me-mount berkas itu writable ke
konsol berarti satu bug penulisan bisa merusak kredensial produksi. `media.env`
paling jauh rusak berarti ketiga line kembali ke bawaan `hikrobot`.

Bentuk berkasnya cuma diketahui modul ini. Compose membacanya lewat `env_file`,
line membacanya sebagai environment biasa — tidak ada yang mem-parsing-nya lagi
di tempat lain.

`baca()` MEMAAFKAN, `tulis()` tidak. Baris tak dikenal dan nilai ngawur jatuh ke
bawaan, karena berkas yang disunting tangan atau ditulis versi lebih baru tidak
boleh membuat line gagal boot. Yang rewel adalah gerbang simpan di
`domain/sumber_kamera`, sebelum nilainya sampai ke sini.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Tiga line, dalam urutan tampil. Prefix env-nya `LINE_1_` dst.
LINE_CODES: tuple[str, ...] = ("line-1", "line-2", "line-3")

#: Setelan satu line yang belum pernah diatur. `hikrobot` supaya PC pabrik yang
#: belum punya berkas ini tetap memakai kamera sungguhan.
BAWAAN: dict[str, Any] = {"sumber": "hikrobot", "berkas": "", "ulang": False}

_NOMOR = {kode: str(i + 1) for i, kode in enumerate(LINE_CODES)}

_KEPALA = (
    "# Sumber kamera per line — ditulis layar Support di konsol.\n"
    "# JANGAN disunting tangan saat konsol jalan: simpan berikutnya menimpanya.\n"
    "# Rahasia (lisensi, R2, webhook) TIDAK ada di sini; itu di .env.\n"
)


def _sumber_dari(camera_type: str, berkas: str) -> str:
    """`CAMERA_TYPE` + ada-tidaknya berkas -> pilihan layar.

    Kebalikan dari `CAMERA_TYPE_UNTUK`: `opencv` memetakan ke dua pilihan, dan
    berkaslah yang membedakannya.
    """
    if camera_type == "photo":
        return "foto"
    if camera_type == "opencv":
        return "video" if berkas else "webcam"
    return "hikrobot"


class MediaEnvService:
    """Satu-satunya pembaca dan penulis `media.env`."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # ------------------------------------------------------------------ baca

    def baca(self) -> dict[str, dict[str, Any]]:
        """Setelan ketiga line, dilengkapi bawaan untuk apa pun yang hilang."""
        mentah = self._baris()
        hasil: dict[str, dict[str, Any]] = {}
        for kode in LINE_CODES:
            n = _NOMOR[kode]
            camera_type = mentah.get(f"LINE_{n}_CAMERA_TYPE", "").strip().lower()
            berkas = mentah.get(f"LINE_{n}_MEDIA_FILE", "").strip()
            if camera_type not in ("hikrobot", "opencv", "photo"):
                # Disunting tangan dengan nilai ngawur. Line tetap boot memakai
                # kamera sungguhan, bukan gagal.
                hasil[kode] = dict(BAWAAN)
                continue
            hasil[kode] = {
                "sumber": _sumber_dari(camera_type, berkas),
                "berkas": berkas,
                "ulang": mentah.get(f"LINE_{n}_VIDEO_LOOP", "").strip().lower() == "true",
            }
        return hasil

    def _baris(self) -> dict[str, str]:
        """`KUNCI=nilai` dari berkas. Berkas tidak ada / tak terbaca -> kosong."""
        try:
            teks = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            logger.warning("media.env tidak terbaca (%s) — memakai bawaan", exc)
            return {}

        pasangan: dict[str, str] = {}
        for baris in teks.splitlines():
            baris = baris.strip()
            if not baris or baris.startswith("#") or "=" not in baris:
                continue
            kunci, nilai = baris.split("=", 1)
            pasangan[kunci.strip()] = nilai.strip()
        return pasangan

    # ----------------------------------------------------------------- tulis

    def tulis(self, setelan: dict[str, dict[str, Any]]) -> None:
        """Timpa seluruh berkas dengan setelan ketiga line.

        Lewat berkas sementara di folder yang sama lalu `os.replace`, yang
        atomik di POSIX: berkas setengah tertulis akibat mati listrik akan
        membuat ketiga line gagal boot sekaligus.
        """
        from ..domain.sumber_kamera import CAMERA_TYPE_UNTUK

        bagian = [_KEPALA]
        for kode in LINE_CODES:
            n = _NOMOR[kode]
            satu = {**BAWAAN, **setelan.get(kode, {})}
            bagian.append(
                f"LINE_{n}_CAMERA_TYPE={CAMERA_TYPE_UNTUK[satu['sumber']]}\n"
                f"LINE_{n}_MEDIA_FILE={satu['berkas']}\n"
                f"LINE_{n}_VIDEO_LOOP={'true' if satu['ulang'] else 'false'}\n"
            )
        isi = "".join(bagian)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, sementara = tempfile.mkstemp(
            dir=self._path.parent, prefix=".media.env.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(isi)
                f.flush()
                os.fsync(f.fileno())
            os.replace(sementara, self._path)
        except BaseException:
            Path(sementara).unlink(missing_ok=True)
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_media_env_service.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/services/media_env_service.py tests/unit/test_media_env_service.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/services/media_env_service.py tests/unit/test_media_env_service.py
git commit -m "feat(sumber): baca & tulis media.env

Berkas terpisah dari .env supaya konsol tidak pernah bisa menulis kredensial.
Tulis lewat berkas sementara + os.replace: berkas separo membuat ketiga line
gagal boot. Baca memaafkan baris tak dikenal dan nilai ngawur, gerbang simpan
yang rewel."
```

---

### Task 4: Daftar berkas di folder `media/`

**Files:**
- Create: `src/palmgrade/services/media_library.py`
- Test: `tests/unit/test_media_library.py`

**Interfaces:**
- Consumes: tidak ada
- Produces:
  - `MediaLibrary(folder: Path)`
  - `.daftar_video() -> list[str]` — nama berkas saja, terurut
  - `.daftar_foto() -> list[str]`
  - `.ada(nama: str) -> bool`
  - `EKSTENSI_VIDEO: frozenset[str]`, `EKSTENSI_FOTO: frozenset[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_media_library.py
"""Isi folder /media, untuk mengisi dropdown layar."""
from __future__ import annotations

from palmgrade.services.media_library import (
    EKSTENSI_FOTO,
    EKSTENSI_VIDEO,
    MediaLibrary,
)


def test_ekstensi_yang_dikenal():
    assert EKSTENSI_VIDEO == frozenset({".mp4", ".avi", ".mkv"})
    assert EKSTENSI_FOTO == frozenset({".jpg", ".jpeg", ".png"})


def test_folder_tidak_ada_memberi_daftar_kosong(tmp_path):
    # Layar kosong bisa dibaca ("belum ada berkas"); layar yang gagal dimuat tidak.
    lib = MediaLibrary(tmp_path / "tidak-ada")
    assert lib.daftar_video() == []
    assert lib.daftar_foto() == []


def test_folder_kosong(tmp_path):
    assert MediaLibrary(tmp_path).daftar_video() == []


def test_menyaring_ekstensi(tmp_path):
    for nama in ("a.mp4", "b.avi", "c.jpg", "d.png", "e.txt", "f.env"):
        (tmp_path / nama).touch()
    lib = MediaLibrary(tmp_path)
    assert lib.daftar_video() == ["a.mp4", "b.avi"]
    assert lib.daftar_foto() == ["c.jpg", "d.png"]


def test_ekstensi_huruf_besar_ikut(tmp_path):
    (tmp_path / "A.MP4").touch()
    (tmp_path / "B.JPG").touch()
    lib = MediaLibrary(tmp_path)
    assert lib.daftar_video() == ["A.MP4"]
    assert lib.daftar_foto() == ["B.JPG"]


def test_terurut(tmp_path):
    for nama in ("z.mp4", "a.mp4", "m.mp4"):
        (tmp_path / nama).touch()
    assert MediaLibrary(tmp_path).daftar_video() == ["a.mp4", "m.mp4", "z.mp4"]


def test_folder_diabaikan(tmp_path):
    (tmp_path / "bukan-berkas.mp4").mkdir()
    assert MediaLibrary(tmp_path).daftar_video() == []


def test_ada(tmp_path):
    (tmp_path / "a.mp4").touch()
    lib = MediaLibrary(tmp_path)
    assert lib.ada("a.mp4") is True
    assert lib.ada("b.mp4") is False


def test_ada_menolak_nama_berbahaya(tmp_path):
    # Lapis kedua: `bersihkan_sumber` sudah menolaknya, tapi `ada()` dipanggil
    # juga dari jalur lain dan tidak boleh mengintip keluar folder.
    (tmp_path.parent / "rahasia.env").touch()
    lib = MediaLibrary(tmp_path)
    assert lib.ada("../rahasia.env") is False
    assert lib.ada("/etc/passwd") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_media_library.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.services.media_library'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/palmgrade/services/media_library.py
"""Isi folder media — apa yang boleh dipilih di layar.

Daftar, bukan kolom ketik. Path yang salah ketik adalah cara paling mudah
membuat line gagal boot (`OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat
berkasnya tidak terbaca), dan daftar menghapus kemungkinannya.

Folder tidak ada atau tidak terbaca memberi daftar KOSONG, bukan galat: layar
kosong bisa dibaca ("belum ada berkas"), layar yang gagal dimuat tidak.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EKSTENSI_VIDEO: frozenset[str] = frozenset({".mp4", ".avi", ".mkv"})
EKSTENSI_FOTO: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})


class MediaLibrary:
    """Berkas video dan foto yang tersedia di folder media."""

    def __init__(self, folder: Path) -> None:
        self._folder = Path(folder)

    def daftar_video(self) -> list[str]:
        return self._daftar(EKSTENSI_VIDEO)

    def daftar_foto(self) -> list[str]:
        return self._daftar(EKSTENSI_FOTO)

    def ada(self, nama: str) -> bool:
        """Berkas itu benar-benar ada di folder ini — bukan di atasnya.

        Lapis kedua setelah `bersihkan_sumber`: nama dibandingkan dengan isi
        daftar, bukan di-stat langsung, jadi `../x` tidak pernah menyentuh disk
        di luar folder.
        """
        return nama in set(self._daftar(EKSTENSI_VIDEO | EKSTENSI_FOTO))

    def _daftar(self, ekstensi: frozenset[str]) -> list[str]:
        try:
            isi = list(self._folder.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError as exc:
            logger.warning("Folder media tidak terbaca (%s)", exc)
            return []
        return sorted(
            p.name for p in isi if p.is_file() and p.suffix.lower() in ekstensi
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_media_library.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/services/media_library.py tests/unit/test_media_library.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/services/media_library.py tests/unit/test_media_library.py
git commit -m "feat(sumber): daftar berkas folder media

Daftar, bukan kolom ketik: path salah ketik membuat line gagal boot. Folder
hilang memberi daftar kosong, bukan galat — layar kosong bisa dibaca, layar
yang gagal dimuat tidak."
```

---

### Task 5: `main.py` memakai resolver

**Files:**
- Modify: `src/palmgrade/core/config.py:165-181` (tambah `media_file`)
- Modify: `src/palmgrade/main.py:128-157`
- Test: `tests/unit/test_main_sumber_kamera.py`

**Interfaces:**
- Consumes: `rencana_kamera`, `RencanaKamera`, `MEDIA_DIR` dari Task 2; `_sumber_dari` logika dari Task 3 (ditulis ulang di `Settings`, bukan diimpor — `config.py` tidak boleh bergantung pada `services/`)
- Produces:
  - `Settings.media_file: str` — env `MEDIA_FILE`
  - `Settings.sumber_kamera() -> str` — pilihan layar dari `camera_type` + `media_file`
  - `main.py` membangun kamera dari `rencana_kamera(...)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_main_sumber_kamera.py
"""Settings menurunkan pilihan layar, dan main.py membangun kamera dari rencana."""
from __future__ import annotations

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.sumber_kamera_resolver import rencana_kamera


@pytest.fixture(autouse=True)
def _bersihkan_env(monkeypatch):
    for nama in ("CAMERA_TYPE", "MEDIA_FILE", "CAMERA_VIDEO_PATH", "CAMERA_PHOTO_PATH"):
        monkeypatch.delenv(nama, raising=False)


def test_media_file_terbaca(monkeypatch):
    monkeypatch.setenv("MEDIA_FILE", "konveyor.mp4")
    assert Settings().media_file == "konveyor.mp4"


def test_media_file_bawaan_kosong():
    assert Settings().media_file == ""


def test_sumber_hikrobot_bawaan():
    assert Settings().sumber_kamera() == "hikrobot"


def test_sumber_webcam(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    assert Settings().sumber_kamera() == "webcam"


def test_sumber_video(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    monkeypatch.setenv("MEDIA_FILE", "a.mp4")
    assert Settings().sumber_kamera() == "video"


def test_sumber_foto(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "photo")
    monkeypatch.setenv("MEDIA_FILE", "a.jpg")
    assert Settings().sumber_kamera() == "foto"


def test_camera_type_asing_jatuh_ke_hikrobot(monkeypatch):
    # Line tetap boot memakai kamera sungguhan, bukan gagal.
    monkeypatch.setenv("CAMERA_TYPE", "gopro")
    assert Settings().sumber_kamera() == "hikrobot"


def test_rencana_dari_settings(monkeypatch):
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    monkeypatch.setenv("MEDIA_FILE", "konveyor.mp4")
    monkeypatch.setenv("CAMERA_VIDEO_LOOP", "true")
    s = Settings()
    r = rencana_kamera(s.sumber_kamera(), s.media_file, s.camera_video_loop)
    assert r.camera_type == "opencv"
    assert r.video_path == "/media/konveyor.mp4"
    assert r.loop is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_main_sumber_kamera.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'media_file'`

- [ ] **Step 3a: Tambah `media_file` dan `sumber_kamera()` di `Settings`**

Di `src/palmgrade/core/config.py`, tepat setelah baris `camera_photo_path` (baris 181), tambahkan:

```python
    # Nama berkas media (BUKAN path) yang dipilih layar Support, di-join ke
    # `/media` oleh `domain/sumber_kamera_resolver`. Menggantikan
    # CAMERA_VIDEO_PATH/CAMERA_PHOTO_PATH sebagai jalur yang dipakai layar;
    # keduanya masih dibaca supaya `.env` lama tetap jalan.
    media_file: str = field(default_factory=lambda: os.getenv("MEDIA_FILE", ""))
```

Lalu, di dalam kelas yang sama, tambahkan method (letakkan dekat method lain milik `Settings`, mis. sebelum `validate_for_runtime`):

```python
    def sumber_kamera(self) -> str:
        """Pilihan layar yang setara dengan `CAMERA_TYPE` + `MEDIA_FILE`.

        Kebalikan dari pemetaan di `domain/sumber_kamera`: `opencv` memetakan ke
        dua pilihan layar, dan berkaslah yang membedakan webcam dari video.

        Nilai `CAMERA_TYPE` asing jatuh ke `hikrobot`, tidak melempar: berkas
        yang disunting tangan dengan nilai ngawur harus tetap membuat line boot
        memakai kamera sungguhan. Yang rewel gerbang simpan di konsol.

        Ditulis di sini, bukan diimpor dari `services/media_env_service`:
        `config.py` dibaca setiap proses termasuk line, dan tidak boleh
        bergantung pada lapis service.
        """
        camera_type = self.camera_type.strip().lower()
        berkas = (self.media_file or self.camera_video_path or self.camera_photo_path).strip()
        if camera_type == "photo":
            return "foto"
        if camera_type == "opencv":
            return "video" if berkas else "webcam"
        return "hikrobot"
```

- [ ] **Step 3b: Jalankan test**

Run: `.venv/bin/python -m pytest tests/unit/test_main_sumber_kamera.py -q`
Expected: PASS, 8 passed

- [ ] **Step 3c: Pakai resolver di `main.py`**

Ganti blok `main.py` baris 128-148 (dari komentar `# Init kamera` sampai `camera = HikrobotCamera()`) dengan:

```python
        # Sumber kamera — `CAMERA_TYPE` + `MEDIA_FILE`, disusun layar Support
        # dan diteruskan Compose lewat `media.env`. Pemetaannya hidup di
        # `domain/sumber_kamera_resolver` supaya bisa diuji tanpa menyalakan
        # aplikasi; di sini tinggal membangun apa yang direncanakan.
        rencana = rencana_kamera(
            settings.sumber_kamera(), settings.media_file, settings.camera_video_loop
        )
        camera_type = rencana.camera_type
        if camera_type == "opencv":
            # `video_path` kosong = webcam lewat device index.
            opencv_source: int | str = rencana.video_path or settings.camera_device_index
            camera: CameraSource = OpenCVCamera(
                source=opencv_source,
                width=settings.camera_width,
                height=settings.camera_height,
                fps=settings.camera_fps,
                is_video_file=bool(rencana.video_path),
                loop=rencana.loop,
            )
        elif camera_type == "photo":
            camera = PhotoCamera(path=rencana.photo_path)
        else:
            camera = HikrobotCamera()
```

Tambahkan import di dekat import domain lain di `main.py`:

```python
from .domain.sumber_kamera_resolver import rencana_kamera
```

- [ ] **Step 3d: Jaga `.env` lama tetap jalan**

`rencana_kamera` menerima nama berkas, sedangkan `.env` lama menulis path penuh
di `CAMERA_VIDEO_PATH`. Tambahkan test ini ke berkas test yang sama:

```python
def test_env_lama_video_path_masih_jalan(monkeypatch):
    # .env lama menulis path penuh, bukan nama berkas. Tetap terbaca sebagai
    # "video" supaya PC yang belum pindah ke media.env tidak berhenti.
    monkeypatch.setenv("CAMERA_TYPE", "opencv")
    monkeypatch.setenv("CAMERA_VIDEO_PATH", "/videos/video-in")
    assert Settings().sumber_kamera() == "video"
```

Dan di `main.py`, tepat setelah `rencana = rencana_kamera(...)`, sisipkan:

```python
        # `.env` lama menulis PATH penuh di CAMERA_VIDEO_PATH/CAMERA_PHOTO_PATH,
        # bukan nama berkas. Selama berkas itu masih dipakai (PC yang belum
        # pindah ke media.env), path aslinya menang atas hasil join ke /media.
        if not settings.media_file:
            if settings.camera_video_path:
                rencana = replace(rencana, video_path=settings.camera_video_path)
            if settings.camera_photo_path:
                rencana = replace(rencana, photo_path=settings.camera_photo_path)
```

Tambahkan `from dataclasses import replace` di import `main.py`.

- [ ] **Step 4: Run all related tests**

Run: `.venv/bin/python -m pytest tests/unit/test_main_sumber_kamera.py tests/unit/test_config_validation.py tests/unit/test_camera_fps_kosong.py -q`
Expected: PASS, semua hijau

- [ ] **Step 5: Run full unit suite (regresi)**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS, tidak ada yang merah karena perubahan ini

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check src/palmgrade/main.py src/palmgrade/core/config.py tests/unit/test_main_sumber_kamera.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/main.py src/palmgrade/core/config.py tests/unit/test_main_sumber_kamera.py
git commit -m "feat(sumber): main.py membangun kamera dari resolver

Pemetaan pilihan->kamera keluar dari if-else main.py supaya bisa diuji tanpa
menyalakan aplikasi. CAMERA_VIDEO_PATH/CAMERA_PHOTO_PATH tetap menang saat
MEDIA_FILE kosong, jadi .env lama tidak berhenti."
```

---

### Task 6: Endpoint restart di line

**Files:**
- Modify: `src/palmgrade/routes/internal.py` (tambah route)
- Modify: `src/palmgrade/schemas/internal_schema.py` (tambah response)
- Test: `tests/unit/test_internal_restart.py`

**Interfaces:**
- Consumes: `_verify_internal_secret` (sudah ada, dipasang di router)
- Produces:
  - `POST /internal/restart` → `RestartResponse{status: str, jeda_detik: float}`
  - `RestartResponse` di `schemas/internal_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_internal_restart.py
"""POST /internal/restart — line mematikan diri, Docker menyalakannya lagi."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INTERNAL_SECRET", "rahasia-tes")
    monkeypatch.setenv("APP_MODE", "line")
    from palmgrade.core.config import Settings
    from palmgrade.core.dependencies import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    from fastapi import FastAPI

    from palmgrade.routes.internal import router

    app = FastAPI()
    app.include_router(router)
    assert Settings().internal_secret == "rahasia-tes"
    return TestClient(app)


def test_tanpa_secret_ditolak(client):
    r = client.post("/internal/restart")
    assert r.status_code == 401


def test_dengan_secret_menjawab_200_lebih_dulu(client):
    # Line menjawab DULU, baru keluar. Keluar sebelum menjawab membuat konsol
    # melihat koneksi putus dan melaporkannya sebagai gagal, padahal berhasil.
    with patch("palmgrade.routes.internal._jadwalkan_keluar") as jadwal:
        r = client.post("/internal/restart", headers={"X-Internal-Secret": "rahasia-tes"})
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"
    jadwal.assert_called_once()


def test_jeda_disebut_di_jawaban(client):
    with patch("palmgrade.routes.internal._jadwalkan_keluar"):
        r = client.post("/internal/restart", headers={"X-Internal-Secret": "rahasia-tes"})
    assert r.json()["jeda_detik"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_internal_restart.py -q`
Expected: FAIL — 404 pada `/internal/restart`

- [ ] **Step 3a: Tambah schema**

Di `src/palmgrade/schemas/internal_schema.py`, tambahkan:

```python
class RestartResponse(BaseModel):
    """Jawaban `POST /internal/restart`, dikirim SEBELUM proses keluar."""

    status: str
    jeda_detik: float
```

- [ ] **Step 3b: Tambah route**

Di `src/palmgrade/routes/internal.py`, tambahkan import `RestartResponse` ke blok
import schema yang sudah ada, lalu tambahkan di akhir berkas:

```python
#: Jeda antara menjawab dan keluar. Cukup bagi respons untuk sampai ke konsol
#: melalui loop event, tidak cukup lama untuk membuat layar terasa menggantung.
_JEDA_KELUAR_DETIK = 1.0


def _jadwalkan_keluar(jeda: float) -> None:
    """Keluar `jeda` detik dari sekarang, di thread terpisah.

    `os._exit` dan bukan `sys.exit`: yang dituju adalah container berhenti
    supaya `restart: unless-stopped` menyalakannya lagi dengan environment yang
    Compose baca ulang. `sys.exit` dari thread non-utama hanya menghentikan
    thread itu — proses tetap hidup dan setelan baru tidak pernah berlaku,
    tanpa satu pun galat yang terlihat.
    """
    def keluar() -> None:
        time.sleep(jeda)
        logger.warning("Keluar atas permintaan konsol — Docker akan menyalakan ulang")
        os._exit(0)

    threading.Thread(target=keluar, daemon=True, name="restart").start()


@router.post("/restart", response_model=RestartResponse)
async def restart() -> RestartResponse:
    """Matikan diri supaya Docker menyalakan ulang dengan setelan baru.

    Dipanggil konsol sesudah `media.env` ditulis. Line membaca sumber kameranya
    dari environment saat boot, jadi setelan baru baru berlaku setelah proses
    ini benar-benar mati dan `restart: unless-stopped` membangunnya kembali.

    Menjawab lebih dulu, keluar belakangan: konsol yang melihat koneksi putus
    akan melaporkannya sebagai gagal padahal berhasil, dan support akan menekan
    Simpan lagi.
    """
    logger.warning("Permintaan restart diterima dari konsol")
    _jadwalkan_keluar(_JEDA_KELUAR_DETIK)
    return RestartResponse(status="restarting", jeda_detik=_JEDA_KELUAR_DETIK)
```

Tambahkan di blok import teratas `internal.py`:

```python
import os
import threading
import time
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_internal_restart.py -q`
Expected: PASS, 3 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/routes/internal.py src/palmgrade/schemas/internal_schema.py tests/unit/test_internal_restart.py`
Expected: `All checks passed!` (kalau ruff mengeluh soal `os._exit`, tambahkan `# noqa: SLF001` — akses itu disengaja dan dijelaskan di docstring)

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/routes/internal.py src/palmgrade/schemas/internal_schema.py tests/unit/test_internal_restart.py
git commit -m "feat(sumber): endpoint restart di line

Menjawab dulu, keluar 1 detik kemudian: konsol yang melihat koneksi putus akan
melaporkan gagal padahal berhasil. os._exit dan bukan sys.exit — sys.exit dari
thread non-utama hanya menghentikan thread itu, proses tetap hidup dan setelan
baru tidak pernah berlaku."
```

---

### Task 7: Konsol memanggil restart line

**Files:**
- Modify: `src/palmgrade/integrations/notifications/line_client.py`
- Test: `tests/unit/test_line_client_restart.py`

**Interfaces:**
- Consumes: `LineEndpoint`, `_post` (sudah ada di `line_client.py`)
- Produces: `LineClient.restart(line: LineEndpoint) -> None` — melempar kalau line tidak menjawab

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_line_client_restart.py
"""Konsol menyuruh satu line restart."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable


@pytest.fixture
def line():
    """Endpoint line pertama menurut Settings — `LineEndpoint` adalah
    NamedTuple, jadi field-nya harus cocok persis dan lebih aman diambil dari
    sumbernya daripada dirakit tangan."""
    return Settings().console_lines[0]


@pytest.mark.asyncio
async def test_restart_memanggil_endpoint(line):
    client = LineClient(Settings())
    with patch.object(client, "_post", new=AsyncMock()) as post:
        await client.restart(line)
    post.assert_awaited_once()
    assert post.await_args.args[1] == "/internal/restart"


@pytest.mark.asyncio
async def test_restart_melempar_saat_line_diam(line):
    client = LineClient(Settings())
    mati = LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
    with patch.object(client, "_post", new=AsyncMock(side_effect=mati)):
        with pytest.raises(LineUnavailable):
            await client.restart(line)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_line_client_restart.py -q`
Expected: FAIL — `AttributeError: 'LineClient' object has no attribute 'restart'`

- [ ] **Step 3: Write implementation**

Buka `src/palmgrade/integrations/notifications/line_client.py`. Sesuaikan
`LineEndpoint` dan `LineUnavailable` dengan nama yang benar-benar ada di berkas
itu (baca dulu; test di atas memakai nama yang terlihat dari `grep` dan mungkin
perlu disesuaikan). Tambahkan method setelah `kirim_setelan`:

```python
    async def restart(self, line: LineEndpoint) -> None:
        """Suruh satu line mematikan diri supaya Docker menyalakannya ulang.

        Dipakai sesudah `media.env` ditulis: line membaca sumber kameranya dari
        environment saat boot, jadi setelan baru tidak berlaku sampai prosesnya
        benar-benar mati.

        Melempar kalau line tidak menjawab. Pemanggil TIDAK membatalkan
        penyimpanan karena itu: berkasnya sudah sah, tinggal line itu yang belum
        membacanya — dan ia akan membacanya sendiri saat hidup lagi.
        """
        await self._post(line, "/internal/restart", {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_line_client_restart.py -q`
Expected: PASS, 2 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/integrations/notifications/line_client.py tests/unit/test_line_client_restart.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/integrations/notifications/line_client.py tests/unit/test_line_client_restart.py
git commit -m "feat(sumber): konsol menyuruh line restart

Line yang tidak menjawab tidak membatalkan penyimpanan: berkasnya sudah sah,
dan line itu membacanya sendiri saat hidup lagi."
```

---

### Task 8: Service konsol — validasi, pembuktian berkas, simpan, restart

**Files:**
- Modify: `src/palmgrade/services/console_service.py`
- Modify: `src/palmgrade/core/config.py` (tambah `media_dir`, `media_env_path`)
- Test: `tests/unit/test_console_sumber_kamera.py`

**Interfaces:**
- Consumes: `bersihkan_sumber`/`SumberTidakSah` (Task 1), `MediaEnvService`/`LINE_CODES` (Task 3), `MediaLibrary` (Task 4), `LineClient.restart` (Task 7)
- Produces:
  - `Settings.media_dir: str` (env `MEDIA_DIR`, bawaan `/media`)
  - `Settings.media_env_path: str` (env `MEDIA_ENV_PATH`, bawaan `/config/media.env`)
  - `ConsoleService.sumber_kamera() -> dict` — `{"lines": {...}, "video": [...], "foto": [...]}`
  - `ConsoleService.simpan_sumber_kamera(payload, *, diubah_oleh) -> dict`
  - `ConsoleService._buktikan_berkas(sumber, berkas) -> None` — melempar `SumberTidakSah`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_console_sumber_kamera.py
"""Layar Support: baca daftar, simpan, restart line yang berubah."""
from __future__ import annotations

from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.domain.sumber_kamera import SumberTidakSah
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    """Line palsu — mencatat restart, atau menolak kalau `down`.

    Bentuknya mengikuti `FakeLine` di `test_console_piston.py`: kelas kecil,
    bukan `AsyncMock`, supaya tanda tangan yang salah ketahuan saat test jalan
    dan bukan diterima diam-diam.
    """

    def __init__(self, *, down: bool = False) -> None:
        self.restarted: list[str] = []
        self.down = down

    async def restart(self, line):
        if self.down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        self.restarted.append(line.line_code)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """ConsoleService dengan media.env dan folder media di tmp_path."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "konveyor.mp4").touch()
    (media / "sawit.jpg").touch()
    monkeypatch.setenv("MEDIA_DIR", str(media))
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))

    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())
    # Pembuktian berkas memakai cv2; unit suite berjalan tanpa cv2 dengan
    # sengaja, jadi dilewati di sini dan diuji sungguhan di e2e (Task 12).
    service._buktikan_berkas = lambda sumber, berkas: None  # type: ignore[method-assign]
    return service


def test_baca_memberi_bawaan_dan_daftar(svc):
    hasil = svc.sumber_kamera()
    assert hasil["lines"]["line-1"]["sumber"] == "hikrobot"
    assert hasil["video"] == ["konveyor.mp4"]
    assert hasil["foto"] == ["sawit.jpg"]


@pytest.mark.asyncio
async def test_simpan_menulis_dan_merestart_yang_berubah(svc):
    payload = {
        "line-1": {"sumber": "hikrobot"},
        "line-2": {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True},
        "line-3": {"sumber": "hikrobot"},
    }
    hasil = await svc.simpan_sumber_kamera(payload, diubah_oleh="support@x")

    # Hanya line-2 yang berubah dari bawaan.
    direstart = [b["line_code"] for b in hasil["lines"] if b["direstart"]]
    assert direstart == ["line-2"]
    assert svc.line_client.restarted == ["line-2"]
    assert svc.sumber_kamera()["lines"]["line-2"]["berkas"] == "konveyor.mp4"


@pytest.mark.asyncio
async def test_tidak_ada_yang_berubah_tidak_merestart(svc):
    payload = {kode: {"sumber": "hikrobot"} for kode in ("line-1", "line-2", "line-3")}
    hasil = await svc.simpan_sumber_kamera(payload, diubah_oleh="support@x")
    assert svc.line_client.restarted == []
    assert all(not b["direstart"] for b in hasil["lines"])


@pytest.mark.asyncio
async def test_berkas_tidak_ada_ditolak_tanpa_menulis(svc):
    sebelum = svc.sumber_kamera()["lines"]
    with pytest.raises(SumberTidakSah, match="tidak ada di folder media"):
        await svc.simpan_sumber_kamera(
            {
                "line-1": {"sumber": "video", "berkas": "hantu.mp4"},
                "line-2": {"sumber": "hikrobot"},
                "line-3": {"sumber": "hikrobot"},
            },
            diubah_oleh="support@x",
        )
    assert svc.sumber_kamera()["lines"] == sebelum
    assert svc.line_client.restarted == []


@pytest.mark.asyncio
async def test_payload_cacat_ditolak_tanpa_menulis(svc):
    sebelum = svc.sumber_kamera()["lines"]
    with pytest.raises(SumberTidakSah):
        await svc.simpan_sumber_kamera(
            {
                "line-1": {"sumber": "video", "berkas": ""},
                "line-2": {"sumber": "hikrobot"},
                "line-3": {"sumber": "hikrobot"},
            },
            diubah_oleh="support@x",
        )
    assert svc.sumber_kamera()["lines"] == sebelum


@pytest.mark.asyncio
async def test_line_kurang_ditolak(svc):
    with pytest.raises(SumberTidakSah, match="line belum diisi"):
        await svc.simpan_sumber_kamera({"line-1": {"sumber": "hikrobot"}}, diubah_oleh="x")


@pytest.mark.asyncio
async def test_line_asing_ditolak(svc):
    payload = {kode: {"sumber": "hikrobot"} for kode in ("line-1", "line-2", "line-3")}
    payload["line-9"] = {"sumber": "hikrobot"}
    with pytest.raises(SumberTidakSah, match="line tidak dikenal"):
        await svc.simpan_sumber_kamera(payload, diubah_oleh="x")


@pytest.mark.asyncio
async def test_line_diam_tidak_membatalkan_simpan(svc):
    svc.line_client.down = True
    hasil = await svc.simpan_sumber_kamera(
        {
            "line-1": {"sumber": "hikrobot"},
            "line-2": {"sumber": "video", "berkas": "konveyor.mp4"},
            "line-3": {"sumber": "hikrobot"},
        },
        diubah_oleh="support@x",
    )
    # Tersimpan, tapi dilaporkan belum direstart.
    assert svc.sumber_kamera()["lines"]["line-2"]["berkas"] == "konveyor.mp4"
    baris = next(b for b in hasil["lines"] if b["line_code"] == "line-2")
    assert baris["direstart"] is False
    assert "alasan" in baris
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_console_sumber_kamera.py -q`
Expected: FAIL — `AttributeError: 'ConsoleService' object has no attribute 'sumber_kamera'`

- [ ] **Step 3a: Tambah dua setelan path di `Settings`**

Di `src/palmgrade/core/config.py`, dekat `media_file` dari Task 5:

```python
    # Folder media yang di-mount dari host, read-only bagi line dan konsol.
    media_dir: str = field(default_factory=lambda: os.getenv("MEDIA_DIR", "/media"))
    # Berkas setelan sumber kamera. Dibaca Compose lewat `env_file`, ditulis
    # konsol. TERPISAH dari `.env`, yang memuat rahasia dan tidak pernah ditulis
    # kode mana pun.
    media_env_path: str = field(
        default_factory=lambda: os.getenv("MEDIA_ENV_PATH", "/config/media.env")
    )
```

- [ ] **Step 3b: Tambah method di `ConsoleService`**

Di `src/palmgrade/services/console_service.py`, tambahkan import di atas:

```python
from ..domain.sumber_kamera import SumberTidakSah, bersihkan_sumber
from .media_env_service import LINE_CODES, MediaEnvService
from .media_library import MediaLibrary
```

Lalu tambahkan method setelah `simpan_setelan_grading`:

```python
    # ────────────────────────────────────── sumber kamera (layar Support) ───

    def _media_env(self) -> MediaEnvService:
        return MediaEnvService(Path(self.settings.media_env_path))

    def _media_library(self) -> MediaLibrary:
        return MediaLibrary(Path(self.settings.media_dir))

    def sumber_kamera(self) -> dict[str, Any]:
        """Setelan ketiga line + daftar berkas yang boleh dipilih."""
        pustaka = self._media_library()
        return {
            "lines": self._media_env().baca(),
            "video": pustaka.daftar_video(),
            "foto": pustaka.daftar_foto(),
        }

    def _buktikan_berkas(self, sumber: str, berkas: str) -> None:
        """Buktikan berkasnya benar-benar bisa dibuka, sebelum menyimpannya.

        `OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat berkasnya tidak
        terbaca. Tanpa pembuktian di sini, memilih berkas rusak berarti: line
        boot, gagal, mati, `restart: unless-stopped` menyalakannya lagi, gagal
        lagi — selamanya, dan satu-satunya jalan keluar AnyDesk.

        Ada-tidaknya berkas sudah dicek pemanggil; yang dibuktikan di sini
        isinya.
        """
        import cv2  # lokal: konsol tidak mengimpornya di jalur boot

        path = str(Path(self.settings.media_dir) / berkas)
        if sumber == "foto":
            if cv2.imread(path) is None:
                raise SumberTidakSah(f"{berkas} tidak bisa dibaca sebagai gambar")
            return

        cap = cv2.VideoCapture(path)
        try:
            terbaca, _ = cap.read() if cap.isOpened() else (False, None)
        finally:
            cap.release()
        if not terbaca:
            raise SumberTidakSah(f"{berkas} tidak bisa dibaca sebagai video")

    async def simpan_sumber_kamera(
        self, payload: dict[str, Any], *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Validasi, buktikan berkas, tulis, lalu restart line yang berubah.

        Gagal validasi atau pembuktian TIDAK menulis apa pun: setelan lama tetap
        berlaku. Gagal restart sebaliknya dibiarkan — berkasnya sudah sah, dan
        line yang tidak menjawab akan membacanya sendiri saat hidup lagi.
        Rollback berarti menulis dan merestart lagi, dua langkah yang bisa gagal
        dengan cara yang sama dan meninggalkan keadaan yang lebih sulit dibaca.
        """
        if not isinstance(payload, dict):
            raise SumberTidakSah("payload harus objek")
        asing = set(payload) - set(LINE_CODES)
        if asing:
            raise SumberTidakSah(f"line tidak dikenal: {', '.join(sorted(asing))}")
        kurang = set(LINE_CODES) - set(payload)
        if kurang:
            raise SumberTidakSah(f"line belum diisi: {', '.join(sorted(kurang))}")

        bersih = {kode: bersihkan_sumber(payload[kode]) for kode in LINE_CODES}

        pustaka = self._media_library()
        for kode, satu in bersih.items():
            if not satu["berkas"]:
                continue
            if not pustaka.ada(satu["berkas"]):
                raise SumberTidakSah(
                    f"{kode}: {satu['berkas']} tidak ada di folder media"
                )
            self._buktikan_berkas(satu["sumber"], satu["berkas"])

        env = self._media_env()
        sebelum = env.baca()
        env.tulis(bersih)
        logger.warning(
            "Sumber kamera diubah oleh %s: %s",
            diubah_oleh,
            ", ".join(f"{k}={v['sumber']}:{v['berkas'] or '-'}" for k, v in bersih.items()),
        )

        hasil = []
        for line in self.lines:
            kode = line.line_code
            if sebelum.get(kode) == bersih[kode]:
                hasil.append({"line_code": kode, "direstart": False, "berubah": False})
                continue
            try:
                await self.line_client.restart(line)
                hasil.append({"line_code": kode, "direstart": True, "berubah": True})
            except Exception as exc:  # LineUnavailable / apa pun
                logger.warning("Restart %s gagal: %s", kode, exc)
                hasil.append(
                    {
                        "line_code": kode,
                        "direstart": False,
                        "berubah": True,
                        "alasan": str(exc)[:200],
                    }
                )
        return {"lines": hasil, **self.sumber_kamera()}
```

Pastikan `from pathlib import Path` sudah ada di import `console_service.py`;
tambahkan kalau belum.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_console_sumber_kamera.py -q`
Expected: PASS, 8 passed

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/services/console_service.py src/palmgrade/core/config.py tests/unit/test_console_sumber_kamera.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/services/console_service.py src/palmgrade/core/config.py tests/unit/test_console_sumber_kamera.py
git commit -m "feat(sumber): service konsol simpan sumber kamera

Validasi lalu buktikan berkas benar-benar terbaca SEBELUM menulis: berkas rusak
yang lolos membuat line boot-gagal-restart selamanya. Gagal restart dibiarkan,
tidak di-rollback."
```

---

### Task 9: Route konsol (support only)

**Files:**
- Modify: `src/palmgrade/routes/console.py`
- Test: `tests/unit/test_console_sumber_routes.py`

**Interfaces:**
- Consumes: `ConsoleService.sumber_kamera`/`simpan_sumber_kamera` (Task 8), `Support` dependency (sudah ada)
- Produces:
  - `GET /api/console/dev/sumber-kamera` → hasil `sumber_kamera()`
  - `POST /api/console/dev/sumber-kamera` → hasil `simpan_sumber_kamera()`, 400 saat `SumberTidakSah`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_console_sumber_routes.py
"""Rute layar Support untuk sumber kamera — support saja, 400 saat cacat."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_PY = REPO_ROOT / "src" / "palmgrade" / "routes" / "console.py"


def _sumber() -> str:
    return CONSOLE_PY.read_text(encoding="utf-8")


def test_dua_rute_terdaftar():
    isi = _sumber()
    assert '@router.get("/api/console/dev/sumber-kamera")' in isi
    assert '@router.post("/api/console/dev/sumber-kamera")' in isi


def test_kedua_rute_minta_support():
    # Satu chokepoint: lane dev mana pun yang lupa `Support` membuka layar
    # developer untuk operator biasa.
    isi = _sumber()
    for nama in ("dev_sumber_kamera_baca", "dev_sumber_kamera_simpan"):
        blok = re.search(rf"async def {nama}\((.*?)\)\s*->", isi, re.S)
        assert blok, f"{nama} tidak ditemukan"
        assert "Support" in blok.group(1), f"{nama} tidak dijaga Support"


def test_simpan_menerjemahkan_sumber_tidak_sah_jadi_400():
    isi = _sumber()
    blok = re.search(r"async def dev_sumber_kamera_simpan.*?(?=\n@router|\Z)", isi, re.S)
    assert blok
    assert "SumberTidakSah" in blok.group(0)
    assert "400" in blok.group(0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_console_sumber_routes.py -q`
Expected: FAIL — rute belum ada

- [ ] **Step 3: Write implementation**

Di `src/palmgrade/routes/console.py`, tambahkan import:

```python
from ..domain.sumber_kamera import SumberTidakSah
```

Lalu tambahkan setelah `dev_setelan_simpan`:

```python
@router.get("/api/console/dev/sumber-kamera")
async def dev_sumber_kamera_baca(service: Service, operator: Support) -> dict:
    """Sumber tiap line + daftar berkas yang boleh dipilih."""
    return service.sumber_kamera()


@router.post("/api/console/dev/sumber-kamera")
async def dev_sumber_kamera_simpan(
    service: Service, operator: Support, payload: Annotated[dict, Body()]
) -> dict:
    """Ubah sumber kamera per line, lalu restart line yang berubah.

    `role=support` saja: salah pilih membuat line berhenti grading. Tiap
    perubahan dicatat WARNING menyebut siapa yang mengubah.
    """
    try:
        return await service.simpan_sumber_kamera(
            payload, diubah_oleh=operator["email"]
        )
    except SumberTidakSah as exc:
        raise HTTPException(400, str(exc)) from exc
```

Kalau `dev_setelan_simpan` membungkus galatnya dengan bentuk lain (mis.
`OperatorError`), ikuti bentuk yang sama supaya layar menanganinya seragam —
baca blok itu dulu sebelum menulis.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_console_sumber_routes.py tests/unit/test_console_routes_auth.py -q`
Expected: PASS

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/palmgrade/routes/console.py tests/unit/test_console_sumber_routes.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/routes/console.py tests/unit/test_console_sumber_routes.py
git commit -m "feat(sumber): rute layar Support untuk sumber kamera

Keduanya lewat Support, satu chokepoint seperti lane dev lainnya."
```

---

### Task 10: Layar Support di `console.html`

**Files:**
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/unit/test_console_html_sumber.py`

**Interfaces:**
- Consumes: `GET`/`POST /api/console/dev/sumber-kamera` (Task 9)
- Produces: elemen DOM `#sumber-kamera-panel`, tombol `#sumber-simpan`, tiga blok `[data-sumber-line]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_console_html_sumber.py
"""Invarian HTML layar Sumber Kamera — dijaga sebagai teks, seperti tetangganya.

Konsol tidak punya test runner JS, jadi yang bisa dijaga di CI adalah bahwa
elemen dan endpoint yang dipakai skrip benar-benar ada di berkas yang sama.
Itu menangkap kesalahan yang paling sering: rute diganti namanya di Python dan
HTML-nya tertinggal.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(encoding="utf-8")


def test_panel_ada():
    assert 'id="sumber-kamera-panel"' in HTML


def test_tiga_line_punya_blok():
    for n in (1, 2, 3):
        assert f'data-sumber-line="line-{n}"' in HTML


def test_empat_pilihan_tiap_line():
    for pilihan in ("hikrobot", "webcam", "video", "foto"):
        assert f'value="{pilihan}"' in HTML


def test_endpoint_dipanggil():
    assert "/api/console/dev/sumber-kamera" in HTML


def test_peringatan_restart_disebut():
    # Support harus tahu menyimpan memutus grading sebentar, sebelum menekan.
    assert "restart" in HTML.lower()


def test_tombol_simpan_ada():
    assert 'id="sumber-simpan"' in HTML
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_console_html_sumber.py -q`
Expected: FAIL — `assert 'id="sumber-kamera-panel"' in HTML`

- [ ] **Step 3: Write implementation**

Buka `src/palmgrade/static/console.html`. Cari panel lane dev yang sudah ada
(cari `dev/setelan`) dan tiru bentuknya — kelas CSS, cara memanggil `fetch`,
cara menampilkan toast. Tambahkan panel baru:

```html
<section id="sumber-kamera-panel" class="panel" hidden>
  <h2>Sumber Kamera</h2>
  <p class="muted">
    Setiap line bisa memakai sumber berbeda. Menyimpan akan
    <strong>restart</strong> line yang berubah (sekitar 10 detik).
  </p>

  <div data-sumber-line="line-1" class="sumber-baris">
    <strong>Line 1</strong>
    <label><input type="radio" name="sumber-line-1" value="hikrobot"> Kamera Hikrobot</label>
    <label><input type="radio" name="sumber-line-1" value="webcam"> Webcam</label>
    <label><input type="radio" name="sumber-line-1" value="video"> Video</label>
    <label><input type="radio" name="sumber-line-1" value="foto"> Foto</label>
    <div class="sumber-berkas" hidden>
      Berkas <select data-berkas="line-1"></select>
      <label><input type="checkbox" data-ulang="line-1"> Ulang terus</label>
    </div>
  </div>

  <!-- line-2 dan line-3: salin blok di atas, ganti angkanya -->

  <button id="sumber-simpan" type="button">Simpan &amp; Restart</button>
</section>
```

Salin blok `data-sumber-line` dua kali untuk `line-2` dan `line-3`, mengganti
setiap `line-1` jadi `line-2`/`line-3` dan label `Line 1` jadi `Line 2`/`Line 3`.

Tambahkan skrip, mengikuti gaya pemanggilan `fetch` yang sudah dipakai lane dev
lain di berkas ini:

```javascript
const LINE_KODE = ['line-1', 'line-2', 'line-3'];

async function muatSumberKamera() {
  const r = await fetch('/api/console/dev/sumber-kamera');
  if (!r.ok) return;
  const data = await r.json();
  for (const kode of LINE_KODE) {
    const satu = data.lines[kode];
    const blok = document.querySelector(`[data-sumber-line="${kode}"]`);
    blok.querySelector(`input[value="${satu.sumber}"]`).checked = true;
    blok.querySelector(`[data-ulang="${kode}"]`).checked = satu.ulang;
    isiBerkas(kode, satu.sumber, satu.berkas, data);
    perbaruiTampak(kode);
  }
}

function isiBerkas(kode, sumber, terpilih, data) {
  const pilih = document.querySelector(`[data-berkas="${kode}"]`);
  const daftar = sumber === 'foto' ? data.foto : data.video;
  pilih.innerHTML = '';
  for (const nama of daftar) {
    const opt = document.createElement('option');
    opt.value = nama;
    opt.textContent = nama;
    opt.selected = nama === terpilih;
    pilih.appendChild(opt);
  }
  if (!daftar.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'belum ada berkas di folder media';
    pilih.appendChild(opt);
  }
}

function perbaruiTampak(kode) {
  const blok = document.querySelector(`[data-sumber-line="${kode}"]`);
  const sumber = blok.querySelector('input[type=radio]:checked')?.value;
  // Baris berkas hanya untuk video dan foto — dua lainnya menolak berkas.
  blok.querySelector('.sumber-berkas').hidden = !(sumber === 'video' || sumber === 'foto');
}

document.querySelectorAll('[data-sumber-line] input[type=radio]').forEach((el) => {
  el.addEventListener('change', async () => {
    const kode = el.closest('[data-sumber-line]').dataset.sumberLine;
    perbaruiTampak(kode);
    // Daftar berkas berbeda antara video dan foto, jadi diisi ulang.
    const r = await fetch('/api/console/dev/sumber-kamera');
    if (r.ok) isiBerkas(kode, el.value, '', await r.json());
  });
});

document.getElementById('sumber-simpan').addEventListener('click', async () => {
  const payload = {};
  for (const kode of LINE_KODE) {
    const blok = document.querySelector(`[data-sumber-line="${kode}"]`);
    const sumber = blok.querySelector('input[type=radio]:checked')?.value || 'hikrobot';
    const pakaiBerkas = sumber === 'video' || sumber === 'foto';
    payload[kode] = {
      sumber,
      berkas: pakaiBerkas ? blok.querySelector(`[data-berkas="${kode}"]`).value : '',
      ulang: sumber === 'video' && blok.querySelector(`[data-ulang="${kode}"]`).checked,
    };
  }
  const r = await fetch('/api/console/dev/sumber-kamera', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!r.ok) {
    tampilkanToast(data.detail || 'Gagal menyimpan', 'error');
    return;
  }
  const gagal = data.lines.filter((b) => b.berubah && !b.direstart);
  if (gagal.length) {
    // Tersimpan tetap sah: line yang diam akan membacanya saat hidup lagi.
    tampilkanToast(
      `Tersimpan. ${gagal.map((b) => b.line_code).join(', ')} tidak menjawab — ` +
        'berlaku saat line itu hidup lagi.',
      'warn',
    );
  } else {
    tampilkanToast('Tersimpan, line yang berubah sedang restart.', 'ok');
  }
});
```

Sesuaikan `tampilkanToast` dengan nama fungsi toast yang benar-benar ada di
berkas itu (cari `toast` di `console.html`), dan pasang `muatSumberKamera()` di
tempat lane dev lain dimuat saat tabnya dibuka.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_console_html_sumber.py tests/unit/test_console_html.py -q`
Expected: PASS

- [ ] **Step 5: Lihat dengan mata**

```bash
make console
```

Buka `http://localhost:8100`, login sebagai support, buka tab Sumber Kamera.
Periksa: baris berkas muncul hanya untuk Video/Foto, dropdown terisi, tombol
Simpan memberi toast.

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/static/console.html tests/unit/test_console_html_sumber.py
git commit -m "feat(sumber): layar Support sumber kamera per line

Berkas dipilih dari daftar, bukan diketik. Peringatan restart disebut sebelum
tombol, dan line yang tidak menjawab dilaporkan tanpa membuat simpan terlihat
gagal."
```

---

### Task 11: Compose, `media.env`, dan folder `media/`

**Files:**
- Modify: `docker-compose.yml`
- Create: `media.env.example`
- Create: `media/.gitkeep`
- Modify: `.gitignore`
- Modify: `.env.example`
- Test: `tests/unit/test_compose_sumber_kamera.py`

**Interfaces:**
- Consumes: nama env dari Task 3 (`LINE_N_CAMERA_TYPE`, `LINE_N_MEDIA_FILE`, `LINE_N_VIDEO_LOOP`) dan Task 8 (`MEDIA_DIR`, `MEDIA_ENV_PATH`)
- Produces: compose yang meneruskan `CAMERA_TYPE`/`MEDIA_FILE`/`CAMERA_VIDEO_LOOP` per line dan me-mount `media/` + `media.env`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_compose_sumber_kamera.py
"""Compose meneruskan setelan sumber per line dan me-mount media.

Setelan yang dibaca `Settings` tapi tidak diteruskan compose tidak terlihat di
container dan diam-diam jatuh ke bawaan. Itu cara ERP_COMPANY dulu terkirim
tanpa pernah terbaca — membaca kedua berkas satu sama lain adalah satu-satunya
pemeriksaan yang menangkapnya.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

LINES = ("ripe-line-1", "ripe-line-2", "ripe-line-3")


def _env(service: str) -> dict[str, str]:
    entries = COMPOSE["services"][service]["environment"]
    return dict(e.split("=", 1) for e in entries)


def _volumes(service: str) -> list[str]:
    return COMPOSE["services"][service].get("volumes", [])


def test_tiap_line_memakai_prefix_line_sendiri():
    for i, service in enumerate(LINES, start=1):
        env = _env(service)
        assert env["CAMERA_TYPE"] == f"${{LINE_{i}_CAMERA_TYPE:-hikrobot}}"
        assert env["MEDIA_FILE"] == f"${{LINE_{i}_MEDIA_FILE:-}}"
        assert env["CAMERA_VIDEO_LOOP"] == f"${{LINE_{i}_VIDEO_LOOP:-false}}"


def test_line_memount_media_read_only():
    for service in LINES:
        assert "./media:/media:ro" in _volumes(service)


def test_konsol_memount_media_dan_berkas_setelan():
    vols = _volumes("console")
    assert "./media:/media:ro" in vols
    # Berkas setelan writable; itulah satu-satunya yang konsol boleh tulis.
    assert "./media.env:/config/media.env" in vols


def test_konsol_tidak_memount_dotenv():
    # `.env` memuat lisensi, R2, dan webhook secret. Konsol tidak boleh bisa
    # menulisnya, dan tidak perlu membacanya lewat mount.
    vols = _volumes("console")
    assert not any(v.startswith("./.env") for v in vols)


def test_bind_mount_video_lama_dibuang():
    # Bind-mount per berkas memilih berkasnya saat container DIBUAT; itulah yang
    # membuat memilih berkas dari layar mustahil sebelum ini.
    for service in LINES:
        assert not any("/videos/video-in" in v for v in _volumes(service))


def test_env_file_dipasang_di_keempat_service():
    for service in (*LINES, "console"):
        env_file = COMPOSE["services"][service].get("env_file")
        assert env_file, f"{service} tidak memakai env_file"
        assert "media.env" in str(env_file)


def test_konsol_tahu_letak_media():
    env = _env("console")
    assert env["MEDIA_DIR"] == "${MEDIA_DIR:-/media}"
    assert env["MEDIA_ENV_PATH"] == "${MEDIA_ENV_PATH:-/config/media.env}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_compose_sumber_kamera.py -q`
Expected: FAIL — `CAMERA_TYPE` masih `${CAMERA_TYPE:-hikrobot}` tanpa prefix line

- [ ] **Step 3a: Ubah tiap blok line di `docker-compose.yml`**

Untuk `ripe-line-1` (dan ulangi untuk line-2 dengan `LINE_2_`, line-3 dengan
`LINE_3_`), ganti tiga baris:

```yaml
      # Sumber kamera line ini, disusun layar Support dan ditulis ke media.env.
      # Per line, bukan satu untuk semua: satu PC bisa menguji video di satu
      # line sementara dua lainnya memakai kamera sungguhan.
      - CAMERA_TYPE=${LINE_1_CAMERA_TYPE:-hikrobot}
      # NAMA berkas di folder media, bukan path. Kode yang menggabungkannya.
      - MEDIA_FILE=${LINE_1_MEDIA_FILE:-}
      - CAMERA_VIDEO_LOOP=${LINE_1_VIDEO_LOOP:-false}
```

Hapus baris `- CAMERA_VIDEO_PATH=${CAMERA_VIDEO_PATH:+/videos/video-in}` dan
`- CAMERA_PHOTO_PATH=${CAMERA_PHOTO_PATH:-}` dari ketiga line.

Di bagian `volumes:` tiap line, hapus:

```yaml
      - ${CAMERA_VIDEO_PATH:-/dev/null}:/videos/video-in:ro
```

dan tambahkan:

```yaml
      # Folder media utuh, bukan bind-mount per berkas: itulah yang membuat
      # ganti berkas cukup restart, bukan `docker compose up` ulang.
      - ./media:/media:ro
```

Tambahkan di tiap line (sejajar dengan `environment:`):

```yaml
    env_file:
      - media.env
```

- [ ] **Step 3b: Ubah blok `console`**

Tambahkan ke `environment:`:

```yaml
      - MEDIA_DIR=${MEDIA_DIR:-/media}
      - MEDIA_ENV_PATH=${MEDIA_ENV_PATH:-/config/media.env}
```

Tambahkan ke `volumes:`:

```yaml
      - ./media:/media:ro
      # Satu-satunya berkas host yang konsol boleh tulis. `.env` sengaja TIDAK
      # di-mount: ia memuat lisensi, R2, dan webhook secret.
      - ./media.env:/config/media.env
```

Tambahkan `env_file:` seperti pada line.

- [ ] **Step 3c: Buat berkas pendamping**

`media.env.example`:

```bash
# Sumber kamera per line — disalin jadi `media.env` saat pemasangan.
# Sesudah itu layar Support yang menulisnya; jangan disunting tangan saat
# konsol jalan, simpan berikutnya menimpanya.
#
# CAMERA_TYPE: hikrobot | opencv | photo
#   opencv tanpa MEDIA_FILE = webcam, dengan MEDIA_FILE = berkas video
# MEDIA_FILE: NAMA berkas di folder `media/`, bukan path.

LINE_1_CAMERA_TYPE=hikrobot
LINE_1_MEDIA_FILE=
LINE_1_VIDEO_LOOP=false

LINE_2_CAMERA_TYPE=hikrobot
LINE_2_MEDIA_FILE=
LINE_2_VIDEO_LOOP=false

LINE_3_CAMERA_TYPE=hikrobot
LINE_3_MEDIA_FILE=
LINE_3_VIDEO_LOOP=false
```

Buat `media/.gitkeep` (kosong) supaya foldernya ada setelah clone.

Di `.gitignore`, tambahkan:

```
# Setelan sumber kamera — per mesin, ditulis konsol.
media.env
# Berkas video/foto uji; foldernya sendiri dipertahankan .gitkeep.
media/*
!media/.gitkeep
```

Di `.env.example`, ganti tiga baris kamera lama dengan penunjuk:

```bash
# CAMERA_TYPE / CAMERA_VIDEO_PATH / CAMERA_PHOTO_PATH pindah ke `media.env`
# (per line, diatur dari layar Support). Lihat `media.env.example`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_compose_sumber_kamera.py tests/unit/test_console_compose_env.py -q`
Expected: PASS

- [ ] **Step 5: Buktikan compose benar-benar sah**

```bash
cp media.env.example media.env
docker compose config > /dev/null && echo "compose sah"
```

Expected: `compose sah`

⚠️ Ini membuktikan sintaksnya, BUKAN bahwa penggabungannya benar di pabrik.
Compose di MacBook v5.5.1; Lampung v2.40.3. Pembuktian sebenarnya di Task 13.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml media.env.example media/.gitkeep .gitignore .env.example tests/unit/test_compose_sumber_kamera.py
git commit -m "feat(sumber): compose per-line + mount folder media

Bind-mount per berkas dibuang: ia memilih berkasnya saat container dibuat,
yang membuat memilih dari layar mustahil. Folder di-mount utuh, jadi ganti
berkas cukup restart. .env tidak pernah di-mount ke konsol."
```

---

### Task 12: E2E — alur simpan lengkap

**Files:**
- Create: `tests/e2e/test_sumber_kamera_lane.py`

**Interfaces:**
- Consumes: semua task sebelumnya, lewat HTTP

- [ ] **Step 1: Write the failing test**

```python
# tests/e2e/test_sumber_kamera_lane.py
"""Alur simpan sumber kamera lewat HTTP, dari layar sampai berkas di disk.

Dirakit seperti `test_dev_lane_role.py` — router asli, sesi asli, store di
tmp_path — bukan lewat `create_console_app()`, yang akan menyentuh
`state/console.db` milik pengembang dan meninggalkan baris tes di sana.

Di sinilah `_buktikan_berkas` benar-benar dijalankan: unit suite melewatinya
karena berjalan tanpa cv2 dengan sengaja.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sokongan2026"


class FakeLine:
    def __init__(self) -> None:
        self.restarted: list[str] = []

    async def restart(self, line):
        self.restarted.append(line.line_code)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """Konsol nyata dengan folder media dan media.env di tmp_path."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    media = tmp_path / "media"
    media.mkdir()
    # Gambar sungguhan, supaya pembuktian cv2 di service benar-benar jalan.
    cv2.imwrite(str(media / "sawit.jpg"), np.zeros((32, 32, 3), dtype=np.uint8))

    monkeypatch.setenv("MEDIA_DIR", str(media))
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))

    store = ConsoleStore(tmp_path / "console.db")
    for email, role in (("operator@pks.test", ROLE_OPERATOR), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual(
            {
                "email": email,
                "full_name": email,
                "password_hash": hash_password(SANDI),
                "role": role,
            }
        )

    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, store, FakeLine())

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return TestClient(app), service, tmp_path


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_simpan_foto_menulis_berkas_dan_merestart(lane):
    client, service, tmp_path = lane
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/sumber-kamera",
        json={
            "line-1": {"sumber": "foto", "berkas": "sawit.jpg"},
            "line-2": {"sumber": "hikrobot"},
            "line-3": {"sumber": "hikrobot"},
        },
    )
    assert r.status_code == 200, r.text

    isi = (tmp_path / "media.env").read_text(encoding="utf-8")
    assert "LINE_1_CAMERA_TYPE=photo" in isi
    assert "LINE_1_MEDIA_FILE=sawit.jpg" in isi
    assert service.line_client.restarted == ["line-1"]


def test_berkas_hantu_ditolak_400_tanpa_menulis(lane):
    client, service, tmp_path = lane
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/sumber-kamera",
        json={
            "line-1": {"sumber": "video", "berkas": "hantu.mp4"},
            "line-2": {"sumber": "hikrobot"},
            "line-3": {"sumber": "hikrobot"},
        },
    )
    assert r.status_code == 400
    assert not (tmp_path / "media.env").exists()
    assert service.line_client.restarted == []


def test_berkas_rusak_ditolak_400(lane, tmp_path):
    # Berkas ADA tapi isinya bukan gambar: ini yang `_buktikan_berkas` tangkap
    # dan `MediaLibrary.ada()` tidak.
    client, service, tmp_path_lane = lane
    (tmp_path_lane / "media" / "rusak.jpg").write_bytes(b"bukan gambar")
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/sumber-kamera",
        json={
            "line-1": {"sumber": "foto", "berkas": "rusak.jpg"},
            "line-2": {"sumber": "hikrobot"},
            "line-3": {"sumber": "hikrobot"},
        },
    )
    assert r.status_code == 400
    assert service.line_client.restarted == []


def test_operator_biasa_ditolak_403(lane):
    client, _, _ = lane
    _masuk(client, "operator@pks.test")
    assert client.get("/api/console/dev/sumber-kamera").status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/e2e/test_sumber_kamera_lane.py -q`
Expected: FAIL — rute `/api/console/dev/sumber-kamera` belum lengkap atau
`upsert_operator_manual` bernama lain

- [ ] **Step 3: Sesuaikan sampai hijau**

Kalau ada nama yang meleset (`upsert_operator_manual`, `get_auth_service`),
baca `tests/e2e/test_dev_lane_role.py` dan tiru persis — berkas itu sudah
merakit konsol nyata dengan cara yang benar.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/e2e/test_sumber_kamera_lane.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Run full suites**

Run: `.venv/bin/python -m pytest tests/unit -q && .venv/bin/python -m pytest tests/e2e -q`
Expected: keduanya hijau, tidak ada regresi

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/test_sumber_kamera_lane.py
git commit -m "test(sumber): e2e alur simpan sumber kamera

Berkas hantu ditolak 400 tanpa menulis apa pun, dan operator biasa tidak bisa
membuka layarnya."
```

---

### Task 13: Dokumentasi + pembuktian di Linux

**Files:**
- Modify: `README.md`
- Modify: `docs/SETUP.md`
- Create: `docs/runbooks/2026-09-21-sumber-kamera-per-line.md`

**Interfaces:**
- Consumes: semua task sebelumnya

- [ ] **Step 1: Perbarui `README.md`**

Cari blok yang menyebut `CAMERA_TYPE=hikrobot # hikrobot | opencv | photo`
(sekitar baris 239) dan ganti dengan:

```bash
# Sumber kamera pindah ke `media.env` (per line, diatur layar Support).
# Salin contohnya sekali saat pemasangan:
cp media.env.example media.env
# Berkas video/foto ditaruh di folder `media/`.
```

Perbarui juga pohon folder di sekitar baris 206 supaya menyebut `media/`.

- [ ] **Step 2: Perbarui `docs/SETUP.md`**

Tambahkan langkah `cp media.env.example media.env` dan pembuatan folder `media/`
di bagian pemasangan, sebelum `docker compose up`.

- [ ] **Step 3: Tulis runbook**

Buat `docs/runbooks/2026-09-21-sumber-kamera-per-line.md`:

```markdown
# Mengganti sumber kamera satu line

Layar: konsol → login support → tab **Sumber Kamera**.

## Yang bisa dipilih

| Pilihan | Dipakai untuk | Butuh berkas |
|---|---|---|
| Kamera Hikrobot | produksi | tidak |
| Webcam | dev di laptop | tidak |
| Video | uji ulang rekaman | ya |
| Foto | uji satu frame | ya |

## Menaruh berkas

Salin video atau foto ke folder `media/` di host:

- MacBook dev: `<repo>/media/`
- PC pabrik: `/opt/palmgrade/autograde/media/`

Berkas muncul di dropdown tanpa restart apa pun — daftarnya dibaca saat layar
dibuka.

## Menyimpan

Tekan **Simpan & Restart**. Hanya line yang setelannya berubah yang direstart,
sekitar 10 detik. Line lain terus grading.

## Kalau satu line tidak menjawab

Setelan **tetap tersimpan**. Line itu akan memakainya saat hidup lagi. Layar
menyebut line mana yang belum kena — tidak perlu menyimpan ulang.

## Jebakan

⚠️ **Jangan menyunting `media.env` tangan saat konsol jalan.** Simpan berikutnya
menimpanya seluruhnya.

⚠️ **`media.env` tidak ikut git.** PC baru butuh `cp media.env.example media.env`
sekali; tanpa itu ketiga line jatuh ke bawaan `hikrobot` (yang benar untuk
pabrik, jadi gejalanya tidak terlihat sampai seseorang mencoba mode video).

⚠️ **`docker compose config` di MacBook tidak membuktikan apa-apa** soal Compose
di pabrik. Versinya berbeda jauh (v5.5.1 vs v2.40.3) dan berkas rusak pun
terlihat sehat di sana — sudah terbukti sekali, autograde#120.
```

- [ ] **Step 4: Buktikan di Linux**

Di mesin Linux dengan Compose seumur pabrik (v2.x), dari clone bersih:

```bash
cp media.env.example media.env
printf 'LINE_2_CAMERA_TYPE=photo\nLINE_2_MEDIA_FILE=sawit.jpg\n' >> media.env
docker compose config | grep -A2 'CAMERA_TYPE'
```

Expected: `ripe-line-2` memakai `photo`, dua line lain `hikrobot`.

Catat hasilnya di runbook, bagian baru "Terbukti di", menyebut versi Compose dan
tanggal. Kalau `env_file` ternyata TIDAK digabung seperti yang diharapkan di
versi itu, **berhenti** dan laporkan — seluruh Task 11 perlu bentuk lain
(menulis nilai langsung ke `.env` alih-alih berkas terpisah).

- [ ] **Step 5: Run full verification**

```bash
.venv/bin/ruff check src tests
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/e2e -q
```

Expected: lint bersih, kedua suite hijau.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/SETUP.md docs/runbooks/2026-09-21-sumber-kamera-per-line.md
git commit -m "docs(sumber): cara mengganti sumber kamera per line

Runbook menyebut jebakan media.env yang tidak ikut git dan bahwa compose config
di MacBook tidak membuktikan apa pun soal Compose pabrik."
```

---

## Verifikasi akhir sebelum PR

- [ ] `.venv/bin/ruff check src tests` — bersih
- [ ] `.venv/bin/python -m pytest tests/unit -q` — hijau
- [ ] `.venv/bin/python -m pytest tests/e2e -q` — hijau
- [ ] `docker compose config` sah dengan `media.env` tersalin
- [ ] Task 13 Step 4 sudah dijalankan **di Linux** dan hasilnya dicatat
- [ ] Layar dibuka dengan mata: `make console`, tab Sumber Kamera, ganti satu line

PR ke `staging`, judul dan body **Inggris**.
