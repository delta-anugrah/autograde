# Rekam Video Per Line — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tombol rekam video per line di layar developer (`role=support`), merekam frame clean (tanpa bbox) ke folder `videos/`, dengan resolusi/fps/bitrate yang diatur dari UI — bukan `.env`.

**Architecture:** Konsol memegang setelan dan tombol; line yang merekam. Konsol menyimpan setelan di `sync_state` (satu baris, semua line) dan menembak `/internal/rekam/*` ke tiap line — pola yang sama persis dengan `setelan_grading` dan Uji PLC. Di line, `FrameCaptureWorker` melempar frame yang **sudah ada** ke antrean recorder; thread encoder terpisah menulis MP4. Antrean penuh = frame dibuang, tidak pernah mengerem deteksi.

**Tech Stack:** Python 3.12, FastAPI, OpenCV (`cv2.VideoWriter`), SQLite (`sync_state`), vanilla JS (console.html).

**Spec:** Tidak ada dokumen spec terpisah — keputusan diambil dalam diskusi 2026-09-22 dan diringkas di bagian "Keputusan Yang Sudah Dikunci" di bawah.

> **Status: SELESAI dikerjakan 2026-09-22.** Dokumen ini disimpan sebagai
> catatan rancangan, bukan petunjuk yang masih berlaku. Tiga hal berubah saat
> dikerjakan, dan yang benar adalah kodenya:
>
> - **Codec `avc1` (H.264), bukan `mp4v`.** Rencana ini menduga H.264 tidak
>   selalu ada; diukur ternyata ada, dan **5x lebih kecil** (0,48 vs 2,40
>   GB/jam). `mp4v` tinggal cadangan. Lihat `_CODEC` di `video_recorder.py` dan
>   `docs/runbooks/2026-09-22-ukur-biaya-encode-rekam.md`.
> - **Pemecahan berkas per jam tidak dibuat.** Tidak ada yang membuktikan itu
>   perlu, dan berkas yang dipecah menyulitkan menonton satu kejadian utuh.
> - **`_require_line` dipakai ulang**, bukan helper baru — kodenya sudah
>   terlokalisasi untuk layar.
> - **Env-nya `REKAMAN_DIR`, bukan `VIDEOS_DIR`** seperti tertulis di bawah.
>   `VIDEOS_DIR` pernah ada dengan arti **kebalikannya** (folder video sumber,
>   autograde#104) dan ada test yang menjaganya tidak kembali.

## Keputusan Yang Sudah Dikunci

Diputuskan bersama user 2026-09-22. **Jangan ditanya ulang, jangan diubah sepihak:**

1. **Rekam terus-menerus** sampai dihentikan manual — bukan per truk, bukan ring buffer.
2. **Satu tombol per line**, nyala/mati sendiri-sendiri.
3. **Restart container = rekaman mati.** Tidak dilanjutkan otomatis.
4. **Folder `videos/` sendiri**, TIDAK ikut retensi otomatis. Dihapus manual.
5. **Clean tanpa bbox** — diambil di `FrameCaptureWorker`, sebelum inference.
6. **Pengaturan di UI, bukan `.env`** — resolusi, fps, bitrate diatur dari layar developer.
7. **Support-only** (`role=support`), sama seperti tab dev lain.

## Global Constraints

- **Grading tidak boleh pernah melambat karena fitur ini.** Encode WAJIB di thread
  terpisah. Antrean penuh → frame DIBUANG, tidak pernah blocking. Ini pelajaran
  dari bug autograde#112: encode WebP 2448x2048 sinkron di thread deteksi = 590
  ms/janjang.
- **Disk penuh = grading berhenti menulis = pabrik berhenti.** Rekaman WAJIB
  berhenti sendiri di ambang `UPLOAD_DISK_MIN_FREE_GB` (`core/config.py:269`,
  default 20 GB).
- Bahasa kode & komentar: mengikuti sekitarnya (campur ID/EN sesuai file).
  String yang dilihat user: Indonesia + Inggris (dua kamus i18n di `console.html`).
- Nama field JSON konsol↔line: **Inggris** (skema konsol sudah diseragamkan
  Inggris, lihat memori `project_menu_developer_konsol`).
- `ruff check` dan `ruff format` harus bersih sebelum tiap commit.
- Semua test dijalankan dengan `.venv/bin/pytest` dari root `autograde/`.

---

## File Structure

| File | Tanggung jawab |
|---|---|
| `src/palmgrade/domain/setelan_rekam.py` | **baru** — validasi & batas setelan video (murni, tanpa I/O) |
| `src/palmgrade/services/video_recorder.py` | **baru** — antrean + thread encoder + tulis MP4 + rem disk |
| `src/palmgrade/workers/frame_capture_worker.py` | modifikasi — 1 baris: lempar frame ke recorder |
| `src/palmgrade/workers/runtime_state.py` | modifikasi — pegang instance recorder |
| `src/palmgrade/routes/internal.py` | modifikasi — 3 endpoint di line: mulai/stop/status |
| `src/palmgrade/integrations/notifications/line_client.py` | modifikasi — 3 fungsi proxy konsol→line |
| `src/palmgrade/services/console_service.py` | modifikasi — simpan setelan, sebar perintah, kumpulkan status |
| `src/palmgrade/routes/console.py` | modifikasi — 4 endpoint konsol (`/api/console/dev/rekam*`) |
| `src/palmgrade/static/console.html` | modifikasi — tab "Rekam Video" + i18n |
| `src/palmgrade/core/config.py` | modifikasi — `videos_dir` saja (setelan lain dari UI) |

**Urutan tugas** sengaja dari dalam ke luar: domain murni → recorder → sambungan line
→ sambungan konsol → UI. Tiap tugas bisa diuji sendiri tanpa menunggu tugas berikutnya.

---

### Task 1: Domain setelan rekam (validasi murni)

Modul murni tanpa I/O — batas kewarasan untuk resolusi/fps/bitrate. Mengikuti pola
`domain/setelan_grading.py` yang sudah ada.

**Files:**
- Create: `src/palmgrade/domain/setelan_rekam.py`
- Test: `tests/unit/domain/test_setelan_rekam.py`

**Interfaces:**
- Consumes: (tidak ada — tugas pertama)
- Produces:
  - `KUNCI_SETELAN_REKAM: str = "setelan_rekam"`
  - `BAWAAN: dict[str, int]` — `{"width": 1280, "height": 1024, "fps": 5, "bitrate_kbps": 2000}`
  - `class SetelanRekamTidakSah(ValueError)`
  - `bersihkan_setelan_rekam(payload: dict[str, Any]) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/domain/test_setelan_rekam.py`:

```python
import pytest

from palmgrade.domain.setelan_rekam import (
    BAWAAN,
    SetelanRekamTidakSah,
    bersihkan_setelan_rekam,
)


def test_payload_kosong_memakai_nilai_bawaan():
    assert bersihkan_setelan_rekam({}) == BAWAAN


def test_nilai_sah_dipakai_apa_adanya():
    hasil = bersihkan_setelan_rekam(
        {"width": 1920, "height": 1080, "fps": 10, "bitrate_kbps": 4000}
    )
    assert hasil == {"width": 1920, "height": 1080, "fps": 10, "bitrate_kbps": 4000}


def test_field_yang_hilang_diisi_bawaan():
    hasil = bersihkan_setelan_rekam({"fps": 12})
    assert hasil["fps"] == 12
    assert hasil["width"] == BAWAAN["width"]


def test_string_angka_diterima():
    # Layar HTML mengirim value input sebagai string.
    hasil = bersihkan_setelan_rekam({"fps": "8"})
    assert hasil["fps"] == 8


@pytest.mark.parametrize(
    "payload",
    [
        {"fps": 0},
        {"fps": 61},
        {"width": 0},
        {"width": 10_001},
        {"height": 0},
        {"height": 10_001},
        {"bitrate_kbps": 99},
        {"bitrate_kbps": 50_001},
    ],
)
def test_nilai_di_luar_batas_ditolak(payload):
    with pytest.raises(SetelanRekamTidakSah):
        bersihkan_setelan_rekam(payload)


def test_bukan_angka_ditolak():
    with pytest.raises(SetelanRekamTidakSah):
        bersihkan_setelan_rekam({"fps": "cepat"})


def test_lebar_ganjil_dibulatkan_ke_bawah():
    # H.264 menolak dimensi ganjil; membulatkan di sini membuat encoder tidak
    # pernah menerima nilai yang pasti gagal.
    hasil = bersihkan_setelan_rekam({"width": 1281, "height": 1025})
    assert hasil["width"] == 1280
    assert hasil["height"] == 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/domain/test_setelan_rekam.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.domain.setelan_rekam'`

- [ ] **Step 3: Write minimal implementation**

Create `src/palmgrade/domain/setelan_rekam.py`:

```python
"""Setelan rekam video yang boleh diubah dari layar developer, dan batas
kewarasannya.

Sengaja TIDAK di `.env`: mengubah `.env` di PC pabrik berarti AnyDesk, edit
berkas, lalu membuat ulang container — dan fitur ini dipakai justru saat sedang
menelusuri masalah, ketika membuat ulang container menghapus gejalanya.

Beda dari `setelan_grading`, angka di sini **tidak mengubah uang**: salah setel
cuma membuat videonya besar atau buram, tidak membuat janjang salah dibuang.
Jadi batasnya lebar dan tujuannya cuma menyaring nilai yang pasti gagal di
encoder.

Nilainya **satu untuk semua line**, seperti `setelan_grading` — penyimpanannya
satu baris di `sync_state`, bukan tiga.
"""
from __future__ import annotations

from typing import Any

KUNCI_SETELAN_REKAM = "setelan_rekam"

#: Nilai awal sebelum siapa pun menyimpan setelan. 1280x1024 @ 5 fps ≈ 1,3
#: GB/jam/line — cukup untuk mata manusia melihat gerakan janjang, dan jauh di
#: bawah resolusi sensor (2448x2048) yang dipakai model.
BAWAAN: dict[str, int] = {
    "width": 1280,
    "height": 1024,
    "fps": 5,
    "bitrate_kbps": 2000,
}

#: field -> (minimum inklusif, maksimum inklusif).
BATAS: dict[str, tuple[int, int]] = {
    # 10.000 px: jauh di atas sensor mana pun yang dipakai, jadi yang tersaring
    # cuma salah ketik yang benar-benar ngawur.
    "width": (2, 10_000),
    "height": (2, 10_000),
    # Di atas 60 fps tidak ada kamera di pabrik yang bisa memberi frame sebanyak
    # itu; 0 berarti video tanpa waktu.
    "fps": (1, 60),
    # Di bawah 100 kbps gambarnya hancur sampai tidak berguna; di atas 50 Mbps
    # ukurannya melebihi rekaman mentah tanpa manfaat.
    "bitrate_kbps": (100, 50_000),
}

#: Dimensi yang dipakai H.264 harus genap. Dibulatkan ke bawah, bukan ditolak:
#: operator yang mengetik 1281 bermaksud "sekitar 1280", bukan "gagalkan saya".
_GENAP = ("width", "height")


class SetelanRekamTidakSah(ValueError):
    """Nilai di luar batas, atau bukan angka."""


def bersihkan_setelan_rekam(payload: dict[str, Any]) -> dict[str, int]:
    """Kembalikan setelan lengkap yang sudah divalidasi.

    Field yang tidak disebut payload diisi dari `BAWAAN` — layar boleh mengirim
    satu field saja tanpa menghapus sisanya.
    """
    bersih: dict[str, int] = {}
    for field, bawaan in BAWAAN.items():
        if field not in payload or payload[field] is None:
            bersih[field] = bawaan
            continue

        mentah = payload[field]
        try:
            # `int(str)` supaya value input HTML ("8") diterima; `float` dulu
            # supaya 8.0 dari JSON tidak ditolak.
            nilai = int(float(str(mentah).strip()))
        except (TypeError, ValueError) as exc:
            raise SetelanRekamTidakSah(
                f"{field} harus angka, bukan {mentah!r}"
            ) from exc

        if field in _GENAP and nilai % 2:
            nilai -= 1

        bawah, atas = BATAS[field]
        if not bawah <= nilai <= atas:
            raise SetelanRekamTidakSah(
                f"{field} harus antara {bawah} dan {atas}, bukan {nilai}"
            )
        bersih[field] = nilai
    return bersih
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/domain/test_setelan_rekam.py -v`
Expected: PASS (semua test)

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/domain/setelan_rekam.py tests/unit/domain/test_setelan_rekam.py
.venv/bin/ruff format src/palmgrade/domain/setelan_rekam.py tests/unit/domain/test_setelan_rekam.py
git add src/palmgrade/domain/setelan_rekam.py tests/unit/domain/test_setelan_rekam.py
git commit -m "feat(rekam): batas setelan video yang diatur dari layar developer"
```

---

### Task 2: `videos_dir` di config

Satu-satunya setelan yang tetap di `.env` — **letak folder**, bukan isi setelan.
Alasannya: jalurnya berbeda antara container dan host, jadi harus bisa di-mount.

**Files:**
- Modify: `src/palmgrade/core/config.py`
- Test: `tests/unit/core/test_config_videos_dir.py`

**Interfaces:**
- Consumes: (tidak ada)
- Produces: `Settings.videos_dir -> Path` (property), env `VIDEOS_DIR`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_config_videos_dir.py`:

```python
from pathlib import Path

from palmgrade.core.config import Settings


def test_videos_dir_bawaan_relatif_ke_state(monkeypatch):
    monkeypatch.delenv("VIDEOS_DIR", raising=False)
    s = Settings()
    assert s.videos_dir.name == "videos"


def test_videos_dir_bisa_ditimpa_env(monkeypatch):
    monkeypatch.setenv("VIDEOS_DIR", "/data/rekaman")
    s = Settings()
    assert s.videos_dir == Path("/data/rekaman")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_config_videos_dir.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'videos_dir'`

- [ ] **Step 3: Write minimal implementation**

Di `src/palmgrade/core/config.py`, tambahkan field di dekat setelan folder lain
(cari `upload_disk_min_free_gb` di sekitar baris 269 dan letakkan sesudahnya):

```python
    # Folder rekaman video developer. SENGAJA di luar `artifacts/`: rekaman ini
    # bukan bukti grading dan TIDAK ikut retensi otomatis — dihapus manual oleh
    # yang merekam. Menaruhnya di `artifacts/` akan membuat retensi menghapusnya
    # diam-diam di tengah penelusuran masalah.
    # Jalurnya beda antara container dan host, jadi ini satu-satunya bagian
    # fitur rekam yang tetap di `.env`; resolusi/fps/bitrate diatur dari UI.
    videos_dir_raw: str = field(default_factory=lambda: os.getenv("VIDEOS_DIR", "").strip())
```

Lalu tambahkan property (letakkan di dekat property folder lain, mis. sesudah
`media_dir`):

```python
    @property
    def videos_dir(self) -> Path:
        """Folder rekaman video. Bawaannya `videos/` bersebelahan dengan state."""
        if self.videos_dir_raw:
            return Path(self.videos_dir_raw)
        return Path(self.state_db_path).parent / "videos"
```

CATATAN untuk implementer: periksa nama field state yang sebenarnya di
`config.py` (`state_db_path` atau serupa) dan sesuaikan — jangan asal salin
kalau namanya beda.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_config_videos_dir.py -v`
Expected: PASS

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/core/config.py tests/unit/core/test_config_videos_dir.py
git add src/palmgrade/core/config.py tests/unit/core/test_config_videos_dir.py
git commit -m "feat(rekam): folder videos/ di luar artifacts supaya lepas dari retensi"
```

---

### Task 3: `VideoRecorder` — antrean, drop policy, rem disk

Inti fitur. Thread encoder terpisah; antrean penuh = frame dibuang.

**Files:**
- Create: `src/palmgrade/services/video_recorder.py`
- Test: `tests/unit/services/test_video_recorder.py`

**Interfaces:**
- Consumes: `bersihkan_setelan_rekam`, `BAWAAN` (Task 1)
- Produces:
  - `class VideoRecorder`
  - `VideoRecorder(videos_dir: Path, line_code: str, disk_min_free_gb: float = 20.0, ukuran_antrean: int = 30)`
  - `.mulai(setelan: dict[str, int]) -> dict[str, Any]` — raise `RekamSedangJalan` kalau sudah jalan
  - `.stop() -> dict[str, Any]`
  - `.tulis(frame) -> None` — dipanggil dari thread capture, TIDAK PERNAH blocking
  - `.status() -> dict[str, Any]` — `{"merekam", "berkas", "mulai_epoch", "frame_ditulis", "frame_dibuang", "bytes", "alasan_berhenti"}`
  - `class RekamSedangJalan(RuntimeError)`
  - `class RekamTidakJalan(RuntimeError)`
  - `class DiskMepet(RuntimeError)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/services/test_video_recorder.py`:

```python
import threading
import time

import numpy as np
import pytest

from palmgrade.services.video_recorder import (
    DiskMepet,
    RekamSedangJalan,
    RekamTidakJalan,
    VideoRecorder,
)

SETELAN = {"width": 320, "height": 240, "fps": 5, "bitrate_kbps": 500}


def _frame(h=240, w=320):
    return np.zeros((h, w, 3), dtype=np.uint8)


@pytest.fixture
def rekaman(tmp_path):
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    yield r
    if r.status()["merekam"]:
        r.stop()


def test_status_awal_tidak_merekam(rekaman):
    assert rekaman.status()["merekam"] is False


def test_mulai_lalu_stop_menghasilkan_berkas(rekaman, tmp_path):
    rekaman.mulai(SETELAN)
    for _ in range(5):
        rekaman.tulis(_frame())
    hasil = rekaman.stop()

    berkas = tmp_path / hasil["berkas"]
    assert berkas.exists()
    assert berkas.stat().st_size > 0


def test_nama_berkas_memuat_line_dan_waktu(rekaman):
    hasil = rekaman.mulai(SETELAN)
    assert hasil["berkas"].startswith("line1_")
    assert hasil["berkas"].endswith(".mp4")


def test_mulai_dua_kali_ditolak(rekaman):
    rekaman.mulai(SETELAN)
    with pytest.raises(RekamSedangJalan):
        rekaman.mulai(SETELAN)


def test_stop_tanpa_mulai_ditolak(rekaman):
    with pytest.raises(RekamTidakJalan):
        rekaman.stop()


def test_tulis_saat_tidak_merekam_diabaikan_diam_diam(rekaman):
    # Thread capture memanggil ini tiap frame; melempar di sini akan
    # menjatuhkan capture worker.
    rekaman.tulis(_frame())
    assert rekaman.status()["frame_ditulis"] == 0


def test_tulis_tidak_pernah_blocking_saat_antrean_penuh(tmp_path):
    r = VideoRecorder(
        videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0, ukuran_antrean=2
    )
    # Encoder ditahan supaya antrean pasti penuh.
    r._jeda_uji = threading.Event()
    r.mulai(SETELAN)
    try:
        mulai = time.monotonic()
        for _ in range(50):
            r.tulis(_frame())
        lama = time.monotonic() - mulai
        # 50 frame ke antrean berukuran 2 harus selesai seketika, bukan menunggu
        # encoder. Ambang longgar supaya tidak flaky di CI yang sibuk.
        assert lama < 1.0
        assert r.status()["frame_dibuang"] > 0
    finally:
        r._jeda_uji.set()
        r.stop()


def test_frame_dihitung_ditulis_atau_dibuang(rekaman):
    rekaman.mulai(SETELAN)
    for _ in range(3):
        rekaman.tulis(_frame())
    time.sleep(0.3)
    s = rekaman.status()
    assert s["frame_ditulis"] + s["frame_dibuang"] == 3


def test_disk_mepet_menolak_mulai(tmp_path):
    r = VideoRecorder(
        videos_dir=tmp_path, line_code="line1", disk_min_free_gb=10_000_000.0
    )
    with pytest.raises(DiskMepet):
        r.mulai(SETELAN)
    assert r.status()["merekam"] is False


def test_disk_mepet_di_tengah_rekaman_menghentikan_sendiri(tmp_path, monkeypatch):
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    r.mulai(SETELAN)
    try:
        # Setelah rekaman jalan, disk "menyusut" di bawah ambang.
        r._disk_min_free_gb = 10_000_000.0
        for _ in range(60):
            r.tulis(_frame())
        # Beri encoder waktu memeriksa disk dan berhenti sendiri.
        for _ in range(50):
            if not r.status()["merekam"]:
                break
            time.sleep(0.1)
        s = r.status()
        assert s["merekam"] is False
        assert s["alasan_berhenti"] == "disk_mepet"
    finally:
        if r.status()["merekam"]:
            r.stop()


def test_frame_ukuran_beda_diresize_bukan_menjatuhkan_rekaman(rekaman):
    rekaman.mulai(SETELAN)
    rekaman.tulis(_frame(h=2048, w=2448))
    time.sleep(0.3)
    s = rekaman.status()
    assert s["merekam"] is True
    assert s["frame_ditulis"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/services/test_video_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.services.video_recorder'`

- [ ] **Step 3: Write minimal implementation**

Create `src/palmgrade/services/video_recorder.py`:

```python
"""Rekam frame kamera ke MP4, untuk developer menelusuri masalah line.

**Aturan yang tidak boleh dilanggar: grading tidak pernah melambat karena
modul ini.** `tulis()` dipanggil dari thread capture setiap frame dan HARUS
kembali seketika. Kalau encoder ketinggalan, yang dikorbankan videonya (bolong),
bukan deteksinya. Ini pelajaran dari autograde#112: encode WebP 2448x2048
sinkron di thread deteksi memakan ~590 ms per janjang dan terbaca operator
sebagai "ngelag 1 detik".

Frame yang direkam diambil di `FrameCaptureWorker`, jadi **clean tanpa bbox**
tanpa kerja tambahan — bbox digambar jauh setelah titik itu.

Rekaman berhenti sendiri kalau disk menipis. Disk penuh berarti grading berhenti
menulis, yaitu pabrik berhenti — fitur developer tidak boleh bisa menyebabkan
itu.
"""
from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Berapa sering encoder memeriksa sisa disk, dalam frame. Memeriksa tiap frame
#: memanggil statvfs puluhan kali per detik tanpa guna.
_PERIKSA_DISK_TIAP = 50


class RekamSedangJalan(RuntimeError):
    """Diminta mulai padahal line ini sudah merekam."""


class RekamTidakJalan(RuntimeError):
    """Diminta stop padahal tidak ada rekaman."""


class DiskMepet(RuntimeError):
    """Sisa disk di bawah ambang — rekaman tidak dimulai / dihentikan."""


class VideoRecorder:
    """Satu recorder per line. Aman dipanggil dari beberapa thread."""

    def __init__(
        self,
        videos_dir: Path,
        line_code: str,
        *,
        disk_min_free_gb: float = 20.0,
        ukuran_antrean: int = 30,
    ) -> None:
        self._videos_dir = Path(videos_dir)
        self._line_code = line_code
        self._disk_min_free_gb = disk_min_free_gb
        self._ukuran_antrean = ukuran_antrean

        self._lock = threading.Lock()
        self._antrean: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._berhenti = threading.Event()

        self._merekam = False
        self._berkas: str | None = None
        self._mulai_epoch: float | None = None
        self._setelan: dict[str, int] | None = None
        self._frame_ditulis = 0
        self._frame_dibuang = 0
        self._alasan_berhenti: str | None = None

        #: Hanya untuk test: menahan encoder supaya antrean bisa dibuat penuh.
        self._jeda_uji: threading.Event | None = None

    # ----------------------------------------------------------------- publik

    def mulai(self, setelan: dict[str, int]) -> dict[str, Any]:
        """Mulai merekam. Raise kalau sudah jalan atau disk mepet."""
        with self._lock:
            if self._merekam:
                raise RekamSedangJalan(f"{self._line_code} sudah merekam")
            self._pastikan_disk_cukup()

            self._videos_dir.mkdir(parents=True, exist_ok=True)
            stempel = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            berkas = f"{self._line_code}_{stempel}.mp4"

            self._setelan = dict(setelan)
            self._berkas = berkas
            self._mulai_epoch = time.time()
            self._frame_ditulis = 0
            self._frame_dibuang = 0
            self._alasan_berhenti = None
            self._antrean = queue.Queue(maxsize=self._ukuran_antrean)
            self._berhenti.clear()
            self._merekam = True

            self._thread = threading.Thread(
                target=self._jalan_encoder,
                name=f"video-encoder-{self._line_code}",
                daemon=True,
            )
            self._thread.start()

        logger.warning(
            "Rekam video MULAI %s -> %s (%dx%d @ %d fps)",
            self._line_code, berkas, setelan["width"], setelan["height"], setelan["fps"],
        )
        return self.status()

    def stop(self) -> dict[str, Any]:
        """Hentikan rekaman dan tutup berkas dengan rapi."""
        with self._lock:
            if not self._merekam:
                raise RekamTidakJalan(f"{self._line_code} tidak sedang merekam")
            thread = self._thread
            self._alasan_berhenti = self._alasan_berhenti or "diminta"

        self._berhenti.set()
        if thread is not None:
            # Encoder menutup VideoWriter sendiri; tanpa join, berkas bisa
            # terbaca rusak oleh pemanggil yang langsung membukanya.
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.error(
                    "Encoder %s tidak berhenti dalam 10 detik — berkas mungkin tidak lengkap",
                    self._line_code,
                )

        with self._lock:
            self._merekam = False
            self._thread = None
            self._antrean = None

        logger.warning(
            "Rekam video STOP %s -> %s (%d frame ditulis, %d dibuang)",
            self._line_code, self._berkas, self._frame_ditulis, self._frame_dibuang,
        )
        return self.status()

    def tulis(self, frame: Any) -> None:
        """Serahkan satu frame ke encoder. TIDAK PERNAH blocking.

        Dipanggil dari thread capture tiap frame. Kalau tidak sedang merekam,
        atau antrean penuh, frame dibuang diam-diam — melempar di sini akan
        menjatuhkan capture worker dan mematikan line.
        """
        antrean = self._antrean
        if not self._merekam or antrean is None or frame is None:
            return
        try:
            antrean.put_nowait(frame)
        except queue.Full:
            self._frame_dibuang += 1

    def status(self) -> dict[str, Any]:
        bytes_kini = 0
        if self._berkas:
            jalur = self._videos_dir / self._berkas
            if jalur.exists():
                bytes_kini = jalur.stat().st_size
        return {
            "line_code": self._line_code,
            "merekam": self._merekam,
            "berkas": self._berkas,
            "mulai_epoch": self._mulai_epoch,
            "frame_ditulis": self._frame_ditulis,
            "frame_dibuang": self._frame_dibuang,
            "bytes": bytes_kini,
            "setelan": dict(self._setelan) if self._setelan else None,
            "alasan_berhenti": self._alasan_berhenti,
        }

    # ---------------------------------------------------------------- privat

    def _sisa_disk_gb(self) -> float:
        induk = self._videos_dir if self._videos_dir.exists() else self._videos_dir.parent
        try:
            return shutil.disk_usage(induk).free / 1e9
        except OSError:
            # Folder belum ada / tidak terbaca: jangan memblokir rekaman karena
            # pemeriksaan yang gagal, tapi catat supaya tidak senyap.
            logger.warning("Sisa disk tidak terbaca untuk %s", induk)
            return float("inf")

    def _pastikan_disk_cukup(self) -> None:
        if self._disk_min_free_gb <= 0:
            return
        sisa = self._sisa_disk_gb()
        if sisa < self._disk_min_free_gb:
            raise DiskMepet(
                f"sisa disk {sisa:.1f} GB di bawah ambang {self._disk_min_free_gb:.1f} GB"
            )

    def _jalan_encoder(self) -> None:
        setelan = self._setelan or {}
        lebar, tinggi = setelan["width"], setelan["height"]
        jalur = self._videos_dir / (self._berkas or "rekaman.mp4")

        # mp4v ada di setiap build OpenCV, termasuk `opencv-python-headless` di
        # image kita. H.264 (`avc1`) lebih kecil tapi TIDAK selalu terpasang —
        # memilihnya di sini akan membuat rekaman gagal senyap di sebagian mesin.
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(jalur), fourcc, float(setelan["fps"]), (lebar, tinggi))
        if not writer.isOpened():
            logger.error("VideoWriter gagal membuka %s — rekaman dibatalkan", jalur)
            with self._lock:
                self._merekam = False
                self._alasan_berhenti = "writer_gagal"
            return

        sejak_periksa = 0
        try:
            while not self._berhenti.is_set():
                if self._jeda_uji is not None and not self._jeda_uji.is_set():
                    time.sleep(0.01)
                    continue

                antrean = self._antrean
                if antrean is None:
                    break
                try:
                    frame = antrean.get(timeout=0.2)
                except queue.Empty:
                    continue

                if frame.shape[0] != tinggi or frame.shape[1] != lebar:
                    frame = cv2.resize(frame, (lebar, tinggi), interpolation=cv2.INTER_AREA)
                writer.write(np.ascontiguousarray(frame))
                self._frame_ditulis += 1

                sejak_periksa += 1
                if sejak_periksa >= _PERIKSA_DISK_TIAP:
                    sejak_periksa = 0
                    if self._disk_min_free_gb > 0 and self._sisa_disk_gb() < self._disk_min_free_gb:
                        logger.error(
                            "Rekam video %s BERHENTI SENDIRI: sisa disk di bawah %.1f GB",
                            self._line_code, self._disk_min_free_gb,
                        )
                        with self._lock:
                            self._alasan_berhenti = "disk_mepet"
                            self._merekam = False
                        break
        finally:
            writer.release()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/services/test_video_recorder.py -v`
Expected: PASS (semua test)

CATATAN: kalau `test_disk_mepet_di_tengah_rekaman_menghentikan_sendiri` flaky,
JANGAN menaikkan `sleep` sampai hijau — periksa dulu bahwa pemeriksaan disk
benar-benar berjalan (turunkan `_PERIKSA_DISK_TIAP` lewat monkeypatch di test).

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/services/video_recorder.py tests/unit/services/test_video_recorder.py
.venv/bin/ruff format src/palmgrade/services/video_recorder.py tests/unit/services/test_video_recorder.py
git add src/palmgrade/services/video_recorder.py tests/unit/services/test_video_recorder.py
git commit -m "feat(rekam): VideoRecorder dengan drop policy dan rem disk"
```

---

### Task 4: Sambungkan recorder ke `FrameCaptureWorker`

Satu baris di jalur frame. Tidak boleh mengubah alur deteksi.

**Files:**
- Modify: `src/palmgrade/workers/runtime_state.py`
- Modify: `src/palmgrade/workers/frame_capture_worker.py:85-110`
- Test: `tests/unit/workers/test_frame_capture_rekam.py`

**Interfaces:**
- Consumes: `VideoRecorder` (Task 3)
- Produces: `RuntimeState.video_recorder: VideoRecorder | None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/workers/test_frame_capture_rekam.py`:

```python
import numpy as np

from palmgrade.workers.frame_capture_worker import FrameCaptureWorker


class _RecorderPalsu:
    def __init__(self, meledak: bool = False):
        self.diterima = []
        self._meledak = meledak

    def tulis(self, frame):
        if self._meledak:
            raise RuntimeError("encoder rusak")
        self.diterima.append(frame)


class _KameraPalsu:
    def __init__(self, frames):
        self._frames = list(frames)
        self.exhausted = False
        self.rewound = False
        self.supports_reconnect = True

    def grab_frame(self):
        return self._frames.pop(0) if self._frames else None

    def get_fps(self):
        return 0.0

    def connect(self, **kw):
        pass

    def disconnect(self):
        pass


def _worker(state, frames):
    return FrameCaptureWorker(camera=_KameraPalsu(frames), state=state, target_fps=0)


def test_frame_diteruskan_ke_recorder(runtime_state_kosong):
    state = runtime_state_kosong
    rec = _RecorderPalsu()
    state.video_recorder = rec
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    _worker(state, [frame]).run_once()

    assert len(rec.diterima) == 1


def test_tanpa_recorder_tetap_jalan(runtime_state_kosong):
    state = runtime_state_kosong
    state.video_recorder = None
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    _worker(state, [frame]).run_once()

    assert state.latest_raw_frame is not None


def test_recorder_meledak_tidak_menjatuhkan_capture(runtime_state_kosong):
    # Fitur developer tidak boleh bisa mematikan line.
    state = runtime_state_kosong
    state.video_recorder = _RecorderPalsu(meledak=True)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    _worker(state, [frame]).run_once()

    assert state.latest_raw_frame is not None
```

CATATAN untuk implementer: `runtime_state_kosong` mungkin belum ada sebagai
fixture. Periksa `tests/unit/workers/conftest.py`; kalau belum ada, buat fixture
yang mengembalikan `RuntimeState` kosong sesuai konstruktor aslinya — jangan
mengarang field.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/workers/test_frame_capture_rekam.py -v`
Expected: FAIL — `AttributeError: 'RuntimeState' object has no attribute 'video_recorder'`

- [ ] **Step 3: Write minimal implementation**

Di `src/palmgrade/workers/runtime_state.py`, tambahkan field (sesuaikan gaya
dataclass/attr yang dipakai file itu):

```python
    #: Recorder video developer, kalau ada. `None` selama tidak ada yang
    #: merekam — jalur normal line tidak pernah menyentuh modul rekam.
    video_recorder: Any = None
```

Di `src/palmgrade/workers/frame_capture_worker.py`, tepat SESUDAH baris
`self.state.latest_raw_frame = frame`:

```python
        # Rekaman developer (kalau menyala). Dibungkus try: recorder rusak
        # tidak boleh menjatuhkan capture worker — itu akan mematikan line
        # demi fitur yang cuma dipakai saat menelusuri masalah.
        recorder = self.state.video_recorder
        if recorder is not None:
            try:
                recorder.tulis(frame)
            except Exception:
                logger.exception("Recorder video menolak frame — rekaman diabaikan")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/workers/test_frame_capture_rekam.py -v`
Expected: PASS

Lalu pastikan capture worker lama tidak rusak:

Run: `.venv/bin/pytest tests/unit/workers/ -v`
Expected: PASS (semua)

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/workers/
git add src/palmgrade/workers/ tests/unit/workers/test_frame_capture_rekam.py
git commit -m "feat(rekam): teruskan frame clean dari capture worker ke recorder"
```

---

### Task 5: Endpoint `/internal/rekam/*` di line

**Files:**
- Modify: `src/palmgrade/routes/internal.py`
- Test: `tests/e2e/test_internal_rekam.py`

**Interfaces:**
- Consumes: `VideoRecorder` (Task 3), `RuntimeState.video_recorder` (Task 4), `bersihkan_setelan_rekam` (Task 1)
- Produces: `POST /internal/rekam/mulai`, `POST /internal/rekam/stop`, `GET /internal/rekam/status`

- [ ] **Step 1: Write the failing test**

Create `tests/e2e/test_internal_rekam.py`:

```python
def test_status_awal_tidak_merekam(client_line):
    r = client_line.get("/internal/rekam/status")
    assert r.status_code == 200
    assert r.json()["merekam"] is False


def test_mulai_lalu_status_merekam(client_line):
    r = client_line.post(
        "/internal/rekam/mulai",
        json={"width": 320, "height": 240, "fps": 5, "bitrate_kbps": 500},
    )
    assert r.status_code == 200
    assert r.json()["merekam"] is True

    assert client_line.get("/internal/rekam/status").json()["merekam"] is True
    client_line.post("/internal/rekam/stop")


def test_mulai_dua_kali_jawab_409(client_line):
    client_line.post("/internal/rekam/mulai", json={"width": 320, "height": 240, "fps": 5})
    r = client_line.post("/internal/rekam/mulai", json={"width": 320, "height": 240, "fps": 5})
    assert r.status_code == 409
    client_line.post("/internal/rekam/stop")


def test_stop_tanpa_mulai_jawab_409(client_line):
    assert client_line.post("/internal/rekam/stop").status_code == 409


def test_setelan_ngawur_jawab_400(client_line):
    r = client_line.post("/internal/rekam/mulai", json={"fps": 999})
    assert r.status_code == 400


def test_stop_mengembalikan_nama_berkas(client_line):
    client_line.post("/internal/rekam/mulai", json={"width": 320, "height": 240, "fps": 5})
    hasil = client_line.post("/internal/rekam/stop").json()
    assert hasil["berkas"].endswith(".mp4")
```

CATATAN: pakai fixture client line yang sudah ada di `tests/e2e/conftest.py`
(cari yang dipakai test `/internal/setelan`) — jangan membuat app baru.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/e2e/test_internal_rekam.py -v`
Expected: FAIL — 404 pada semua endpoint

- [ ] **Step 3: Write minimal implementation**

Di `src/palmgrade/routes/internal.py`, mengikuti gaya endpoint `/internal/setelan`
yang sudah ada di file itu:

```python
def _recorder(state, settings) -> VideoRecorder:
    """Recorder line ini, dibuat saat pertama dibutuhkan.

    Dibuat malas supaya line yang tidak pernah merekam tidak menyentuh folder
    `videos/` sama sekali.
    """
    if state.video_recorder is None:
        state.video_recorder = VideoRecorder(
            videos_dir=settings.videos_dir,
            line_code=settings.line_code,
            disk_min_free_gb=settings.upload_disk_min_free_gb,
        )
    return state.video_recorder


@router.post("/rekam/mulai")
async def rekam_mulai(payload: Annotated[dict, Body()] = None) -> dict:
    """Mulai merekam line ini. Setelan datang dari konsol tiap kali mulai —
    line tidak menyimpannya, jadi restart = rekaman mati (keputusan 2026-09-22)."""
    try:
        bersih = bersihkan_setelan_rekam(payload or {})
    except SetelanRekamTidakSah as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return _recorder(state, settings).mulai(bersih)
    except RekamSedangJalan as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DiskMepet as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@router.post("/rekam/stop")
async def rekam_stop() -> dict:
    try:
        return _recorder(state, settings).stop()
    except RekamTidakJalan as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/rekam/status")
async def rekam_status() -> dict:
    return _recorder(state, settings).status()
```

CATATAN untuk implementer: `state` dan `settings` di `internal.py` diperoleh
lewat dependency/closure yang sudah ada di file itu — **ikuti pola endpoint
tetangga**, jangan menyalin `state, settings` sebagai variabel global.
`settings.line_code` mungkin bernama lain; periksa `config.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/e2e/test_internal_rekam.py -v`
Expected: PASS

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/routes/internal.py tests/e2e/test_internal_rekam.py
git add src/palmgrade/routes/internal.py tests/e2e/test_internal_rekam.py
git commit -m "feat(rekam): endpoint mulai/stop/status di line"
```

---

### Task 6: Proxy konsol→line di `line_client`

**Files:**
- Modify: `src/palmgrade/integrations/notifications/line_client.py`
- Test: `tests/unit/integrations/test_line_client_rekam.py`

**Interfaces:**
- Consumes: endpoint Task 5
- Produces:
  - `LineClient.rekam_mulai(line, setelan: dict) -> dict`
  - `LineClient.rekam_stop(line) -> dict`
  - `LineClient.rekam_status(line) -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/integrations/test_line_client_rekam.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_rekam_mulai_menembak_url_line(line_client, line_satu, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8001/internal/rekam/mulai", json={"merekam": True}
    )
    hasil = await line_client.rekam_mulai(line_satu, {"fps": 5})
    assert hasil["merekam"] is True


@pytest.mark.asyncio
async def test_rekam_stop_menembak_url_line(line_client, line_satu, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8001/internal/rekam/stop", json={"merekam": False}
    )
    assert (await line_client.rekam_stop(line_satu))["merekam"] is False


@pytest.mark.asyncio
async def test_rekam_status_menembak_url_line(line_client, line_satu, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8001/internal/rekam/status", json={"merekam": False}
    )
    assert (await line_client.rekam_status(line_satu))["merekam"] is False
```

CATATAN: ikuti fixture dan cara mock HTTP yang sudah dipakai test `line_client`
lain di repo (`kirim_setelan`). Kalau `httpx_mock` tidak dipakai di sana, pakai
cara yang sama dengan test tetangga — jangan memperkenalkan library baru.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/integrations/test_line_client_rekam.py -v`
Expected: FAIL — `AttributeError: 'LineClient' object has no attribute 'rekam_mulai'`

- [ ] **Step 3: Write minimal implementation**

Di `src/palmgrade/integrations/notifications/line_client.py`, mengikuti pola
`kirim_setelan` (baris ~168):

```python
    async def rekam_mulai(self, line, setelan: dict) -> dict:
        """Suruh line mulai merekam dengan setelan ini."""
        url = f"{self._settings.console_line_host}:{line.port}/internal/rekam/mulai"
        return await self._post(url, json=setelan)

    async def rekam_stop(self, line) -> dict:
        url = f"{self._settings.console_line_host}:{line.port}/internal/rekam/stop"
        return await self._post(url, json={})

    async def rekam_status(self, line) -> dict:
        url = f"{self._settings.console_line_host}:{line.port}/internal/rekam/status"
        return await self._get(url)
```

CATATAN: nama helper (`self._post` / `self._get`) harus disesuaikan dengan yang
benar-benar ada di file itu — baca `kirim_setelan` dan tiru persis, termasuk cara
menangani error dan timeout.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/integrations/test_line_client_rekam.py -v`
Expected: PASS

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/integrations/notifications/line_client.py tests/unit/integrations/test_line_client_rekam.py
git add src/palmgrade/integrations/notifications/line_client.py tests/unit/integrations/test_line_client_rekam.py
git commit -m "feat(rekam): proxy konsol ke line untuk mulai/stop/status"
```

---

### Task 7: Service konsol — simpan setelan, sebar perintah

**Files:**
- Modify: `src/palmgrade/services/console_service.py`
- Test: `tests/unit/services/test_console_rekam.py`

**Interfaces:**
- Consumes: Task 1 (`KUNCI_SETELAN_REKAM`, `bersihkan_setelan_rekam`), Task 6 (proxy)
- Produces:
  - `ConsoleService.setelan_rekam() -> dict`
  - `ConsoleService.simpan_setelan_rekam(payload, *, diubah_oleh) -> dict`
  - `ConsoleService.rekam_status_semua() -> dict` — `{"lines": [...], "setelan": {...}, "disk_bebas_gb": float}`
  - `ConsoleService.rekam_mulai(line_code, *, diubah_oleh) -> dict`
  - `ConsoleService.rekam_stop(line_code, *, diubah_oleh) -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/services/test_console_rekam.py`:

```python
import pytest

from palmgrade.domain.setelan_rekam import BAWAAN


def test_setelan_awal_memakai_bawaan(console_service):
    assert console_service.setelan_rekam()["width"] == BAWAAN["width"]


@pytest.mark.asyncio
async def test_simpan_setelan_lalu_terbaca(console_service):
    await console_service.simpan_setelan_rekam(
        {"width": 640, "height": 480, "fps": 10, "bitrate_kbps": 1000},
        diubah_oleh="support@test",
    )
    assert console_service.setelan_rekam()["width"] == 640


@pytest.mark.asyncio
async def test_setelan_ngawur_tidak_menimpa_yang_lama(console_service):
    from palmgrade.domain.setelan_rekam import SetelanRekamTidakSah

    await console_service.simpan_setelan_rekam({"fps": 10}, diubah_oleh="a@b")
    with pytest.raises(SetelanRekamTidakSah):
        await console_service.simpan_setelan_rekam({"fps": 999}, diubah_oleh="a@b")
    assert console_service.setelan_rekam()["fps"] == 10


@pytest.mark.asyncio
async def test_mulai_memakai_setelan_tersimpan(console_service, line_client_palsu):
    await console_service.simpan_setelan_rekam({"fps": 7}, diubah_oleh="a@b")
    await console_service.rekam_mulai("line1", diubah_oleh="a@b")
    assert line_client_palsu.dipanggil[-1]["setelan"]["fps"] == 7


@pytest.mark.asyncio
async def test_line_tak_dikenal_ditolak(console_service):
    with pytest.raises(KeyError):
        await console_service.rekam_mulai("line99", diubah_oleh="a@b")


@pytest.mark.asyncio
async def test_status_semua_menyebut_tiap_line(console_service, line_client_palsu):
    hasil = await console_service.rekam_status_semua()
    assert len(hasil["lines"]) == len(console_service.lines)
    assert "disk_bebas_gb" in hasil


@pytest.mark.asyncio
async def test_line_mati_tidak_menjatuhkan_status_semua(
    console_service, line_client_palsu
):
    # Satu line tidak menjawab tidak boleh membuat seluruh layar kosong.
    line_client_palsu.meledak_untuk = "line2"
    hasil = await console_service.rekam_status_semua()
    baris = {b["line_code"]: b for b in hasil["lines"]}
    assert baris["line2"]["terbaca"] is False
    assert baris["line1"]["terbaca"] is True
```

CATATAN: pakai fixture `console_service` yang sudah ada di repo (dipakai test
`setelan_grading`). `line_client_palsu` kemungkinan perlu dibuat — modelkan dari
fake yang sudah dipakai test konsol lain.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/services/test_console_rekam.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'setelan_rekam'`

- [ ] **Step 3: Write minimal implementation**

Di `src/palmgrade/services/console_service.py`, tepat sesudah blok
`simpan_setelan_grading` (baris ~563), meniru polanya:

```python
    # -------------------------------------------------------- rekam video dev

    def setelan_rekam(self) -> dict[str, Any]:
        """Setelan rekam yang berlaku. Konsol pemegang kebenarannya; line cuma
        menerima salinannya tiap kali diminta mulai."""
        tersimpan = self.store.get_state(KUNCI_SETELAN_REKAM)
        if tersimpan:
            return {**BAWAAN, **json.loads(tersimpan)}
        return dict(BAWAAN)

    async def simpan_setelan_rekam(
        self, payload: dict[str, Any], *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Simpan setelan rekam. Tidak menyentuh rekaman yang sedang jalan —
        setelan baru berlaku pada rekaman BERIKUTNYA, karena mengubah resolusi
        di tengah berkas MP4 menghasilkan berkas rusak."""
        bersih = bersihkan_setelan_rekam(payload)
        self.store.set_state(KUNCI_SETELAN_REKAM, json.dumps(bersih))
        logger.warning(
            "Setelan rekam diubah oleh %s: %dx%d @ %d fps, %d kbps",
            diubah_oleh, bersih["width"], bersih["height"],
            bersih["fps"], bersih["bitrate_kbps"],
        )
        return bersih

    def _line(self, line_code: str):
        for line in self.lines:
            if line.line_code == line_code:
                return line
        raise KeyError(f"line tidak dikenal: {line_code}")

    async def rekam_mulai(self, line_code: str, *, diubah_oleh: str) -> dict[str, Any]:
        line = self._line(line_code)
        setelan = self.setelan_rekam()
        logger.warning("Rekam video %s dimulai oleh %s", line_code, diubah_oleh)
        return await self.line_client.rekam_mulai(line, setelan)

    async def rekam_stop(self, line_code: str, *, diubah_oleh: str) -> dict[str, Any]:
        line = self._line(line_code)
        logger.warning("Rekam video %s dihentikan oleh %s", line_code, diubah_oleh)
        return await self.line_client.rekam_stop(line)

    async def rekam_status_semua(self) -> dict[str, Any]:
        """Status tiap line + setelan + sisa disk.

        Line yang tidak menjawab dilaporkan `terbaca: False`, bukan menjatuhkan
        seluruh jawaban — satu line mati tidak boleh mengosongkan layar.
        """
        baris = []
        for line in self.lines:
            try:
                status = await self.line_client.rekam_status(line)
                baris.append({**status, "line_code": line.line_code, "terbaca": True})
            except Exception as exc:
                logger.warning("Status rekam belum terbaca dari %s: %s", line.line_code, exc)
                baris.append(
                    {
                        "line_code": line.line_code,
                        "terbaca": False,
                        "merekam": False,
                        "alasan": str(exc)[:200],
                    }
                )
        try:
            disk_bebas_gb = shutil.disk_usage(self.settings.videos_dir.parent).free / 1e9
        except OSError:
            disk_bebas_gb = None
        return {
            "lines": baris,
            "setelan": self.setelan_rekam(),
            "disk_bebas_gb": disk_bebas_gb,
        }
```

Tambahkan import di kepala file: `shutil`, dan dari `..domain.setelan_rekam`:
`BAWAAN`, `KUNCI_SETELAN_REKAM`, `bersihkan_setelan_rekam`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/services/test_console_rekam.py -v`
Expected: PASS

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/services/console_service.py tests/unit/services/test_console_rekam.py
git add src/palmgrade/services/console_service.py tests/unit/services/test_console_rekam.py
git commit -m "feat(rekam): setelan tersimpan di konsol dan sebar perintah ke line"
```

---

### Task 8: Endpoint konsol `/api/console/dev/rekam*`

**Files:**
- Modify: `src/palmgrade/routes/console.py`
- Test: `tests/e2e/test_console_rekam_routes.py`

**Interfaces:**
- Consumes: Task 7
- Produces:
  - `GET /api/console/dev/rekam` — status semua line + setelan + disk
  - `POST /api/console/dev/rekam/setelan` — simpan setelan
  - `POST /api/console/dev/rekam/{line_code}/mulai`
  - `POST /api/console/dev/rekam/{line_code}/stop`

- [ ] **Step 1: Write the failing test**

Create `tests/e2e/test_console_rekam_routes.py`:

```python
def test_operator_ditolak(client_konsol, sesi_operator):
    r = client_konsol.get("/api/console/dev/rekam", cookies=sesi_operator)
    assert r.status_code == 403


def test_tanpa_login_ditolak(client_konsol):
    assert client_konsol.get("/api/console/dev/rekam").status_code == 401


def test_support_bisa_baca_status(client_konsol, sesi_support):
    r = client_konsol.get("/api/console/dev/rekam", cookies=sesi_support)
    assert r.status_code == 200
    assert "lines" in r.json()
    assert "setelan" in r.json()


def test_support_bisa_simpan_setelan(client_konsol, sesi_support):
    r = client_konsol.post(
        "/api/console/dev/rekam/setelan",
        json={"width": 640, "height": 480, "fps": 10, "bitrate_kbps": 1000},
        cookies=sesi_support,
    )
    assert r.status_code == 200
    assert r.json()["width"] == 640


def test_setelan_ngawur_jawab_400(client_konsol, sesi_support):
    r = client_konsol.post(
        "/api/console/dev/rekam/setelan", json={"fps": 999}, cookies=sesi_support
    )
    assert r.status_code == 400


def test_operator_tidak_bisa_mulai_rekam(client_konsol, sesi_operator):
    r = client_konsol.post(
        "/api/console/dev/rekam/line1/mulai", cookies=sesi_operator
    )
    assert r.status_code == 403


def test_line_tak_dikenal_jawab_404(client_konsol, sesi_support):
    r = client_konsol.post(
        "/api/console/dev/rekam/line99/mulai", cookies=sesi_support
    )
    assert r.status_code == 404
```

CATATAN: pakai fixture sesi yang sudah ada (`sesi_support` / `sesi_operator`) —
cari di `tests/e2e/conftest.py` yang dipakai test `dev/setelan`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/e2e/test_console_rekam_routes.py -v`
Expected: FAIL — 404 pada semua

- [ ] **Step 3: Write minimal implementation**

Di `src/palmgrade/routes/console.py`, sesudah blok `dev_setelan_simpan`
(baris ~535), meniru polanya persis:

```python
@router.get("/api/console/dev/rekam")
async def dev_rekam_status(service: Service, operator: Support) -> dict:
    """Status rekaman tiap line, setelan yang berlaku, dan sisa disk."""
    return await service.rekam_status_semua()


@router.post("/api/console/dev/rekam/setelan")
async def dev_rekam_setelan(
    service: Service, operator: Support, payload: Annotated[dict, Body()]
) -> dict:
    """Ubah resolusi/fps/bitrate rekaman. Berlaku pada rekaman BERIKUTNYA."""
    try:
        return await service.simpan_setelan_rekam(
            payload, diubah_oleh=operator["email"]
        )
    except SetelanRekamTidakSah as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/dev/rekam/{line_code}/mulai")
async def dev_rekam_mulai(
    line_code: str, service: Service, operator: Support
) -> dict:
    try:
        return await service.rekam_mulai(line_code, diubah_oleh=operator["email"])
    except KeyError as exc:
        raise _operator_error(404, exc) from exc


@router.post("/api/console/dev/rekam/{line_code}/stop")
async def dev_rekam_stop(
    line_code: str, service: Service, operator: Support
) -> dict:
    try:
        return await service.rekam_stop(line_code, diubah_oleh=operator["email"])
    except KeyError as exc:
        raise _operator_error(404, exc) from exc
```

Tambahkan import `SetelanRekamTidakSah` dari `..domain.setelan_rekam`.

CATATAN: error dari line (409 sudah merekam, 507 disk mepet) diteruskan apa
adanya oleh `line_client` — periksa bagaimana `kirim_setelan` menangani error
HTTP line dan ikuti pola yang sama supaya pesannya sampai ke layar.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/e2e/test_console_rekam_routes.py -v`
Expected: PASS

- [ ] **Step 5: Lint dan commit**

```bash
.venv/bin/ruff check src/palmgrade/routes/console.py tests/e2e/test_console_rekam_routes.py
git add src/palmgrade/routes/console.py tests/e2e/test_console_rekam_routes.py
git commit -m "feat(rekam): endpoint konsol untuk layar rekam video"
```

---

### Task 9: Tab "Rekam Video" di console.html

**Files:**
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/e2e/test_console_html_rekam.py`

**Interfaces:**
- Consumes: Task 8 (endpoint konsol)
- Produces: tab `data-tab="rekam"` (support-only), kunci i18n `judulRekamVideo` dst.

- [ ] **Step 1: Write the failing test**

Create `tests/e2e/test_console_html_rekam.py`:

```python
from pathlib import Path

HTML = Path("src/palmgrade/static/console.html").read_text(encoding="utf-8")


def test_tab_rekam_ada_dan_ditandai_dev():
    assert 'data-tab="rekam"' in HTML
    # `data-dev="1"` yang membuat tab ini hilang untuk operator.
    baris = [b for b in HTML.splitlines() if 'data-tab="rekam"' in b][0]
    assert 'data-dev="1"' in baris


def test_kunci_i18n_ada_di_dua_bahasa():
    # Dua kamus: Indonesia dan Inggris. Kunci yang cuma ada di satu bikin
    # layar menampilkan nama kunci mentah saat bahasa lain dipilih.
    assert HTML.count("judulRekamVideo:") == 2


def test_memanggil_endpoint_rekam():
    assert "/api/console/dev/rekam" in HTML


def test_tidak_ada_referensi_https():
    # Konsol harus hidup saat internet putus — nol referensi https://.
    assert "https://" not in HTML
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/e2e/test_console_html_rekam.py -v`
Expected: FAIL — `data-tab="rekam"` tidak ada

- [ ] **Step 3: Write minimal implementation**

**3a.** Tambahkan tombol tab sesudah baris `data-tab="sumber-kamera"`
(console.html:840):

```html
  <button data-tab="rekam" data-dev="1" data-t="judulRekamVideo">Rekam Video</button>
```

**3b.** Tambahkan kunci i18n di **kedua** kamus (ID di sekitar baris 1414, EN di
sekitar 1486):

```javascript
    // kamus Indonesia
    judulRekamVideo:"Rekam Video",
    rekamMulai:"Rekam",
    rekamStop:"Stop",
    rekamSedangMerekam:"Merekam",
    rekamMati:"Mati",
    rekamTakTerbaca:"Tak terbaca",
    rekamDiskBebas:"Disk bebas",
    rekamSetelanJudul:"Setelan rekaman",
    rekamLebar:"Lebar",
    rekamTinggi:"Tinggi",
    rekamFps:"FPS",
    rekamBitrate:"Bitrate (kbps)",
    rekamSimpanSetelan:"Simpan setelan",
    rekamSetelanTersimpan:"Setelan tersimpan — berlaku untuk rekaman berikutnya",
    rekamCatatan:"Rekaman tidak dihapus otomatis. Hapus sendiri dari folder videos/.",
```

```javascript
    // kamus Inggris
    judulRekamVideo:"Record Video",
    rekamMulai:"Record",
    rekamStop:"Stop",
    rekamSedangMerekam:"Recording",
    rekamMati:"Off",
    rekamTakTerbaca:"Unreachable",
    rekamDiskBebas:"Free disk",
    rekamSetelanJudul:"Recording settings",
    rekamLebar:"Width",
    rekamTinggi:"Height",
    rekamFps:"FPS",
    rekamBitrate:"Bitrate (kbps)",
    rekamSimpanSetelan:"Save settings",
    rekamSetelanTersimpan:"Saved — applies to the next recording",
    rekamCatatan:"Recordings are never deleted automatically. Clear the videos/ folder yourself.",
```

**3c.** Panel tab — ikuti struktur panel `sumber-kamera` yang sudah ada
(console.html:3418). Isi: tabel per line (status, durasi, ukuran, tombol),
form setelan, sisa disk, dan catatan retensi manual.

**3d.** Daftarkan pemuat tab di `MUAT_TAB` (dipakai baris ~2795) supaya tab
memuat datanya saat dibuka, dan pasang polling tiap ~3 detik **hanya saat tab
rekam sedang terbuka** — polling terus-menerus di tab lain membebani line tanpa
guna.

⚠️ **Jebakan dari PR #130:** `<select>`/tombol di dalam `display:grid` bisa
menciut jadi 0 px tanpa error. Setelah layar jadi, **buka di browser dan lihat**
— jangan percaya "kodenya ada" saja.

⚠️ **Jebakan kedua dari PR #130:** `$()` di berkas ini mengambil **id**, bukan
selector CSS. Periksa definisinya sebelum memakai.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/e2e/test_console_html_rekam.py -v`
Expected: PASS

Lalu periksa dengan mata:

```bash
make console
```

Buka `http://localhost:8100`, login sebagai support, buka tab Rekam Video.
Pastikan: tombol terlihat (bukan 0 px), status berubah saat ditekan, angka
setelan tersimpan setelah refresh.

- [ ] **Step 5: Lint dan commit**

```bash
git add src/palmgrade/static/console.html tests/e2e/test_console_html_rekam.py
git commit -m "feat(rekam): layar Rekam Video di menu developer"
```

---

### Task 10: Mount folder `videos/` di compose + dokumentasi

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `docs/MANUAL.md` (bagian tab support)
- Test: `tests/e2e/test_compose_videos_mount.py`

**Interfaces:**
- Consumes: `settings.videos_dir` (Task 2)
- Produces: bind-mount `videos/` di tiap service line

- [ ] **Step 1: Write the failing test**

Create `tests/e2e/test_compose_videos_mount.py`:

```python
from pathlib import Path

import yaml

DASAR = yaml.safe_load(Path("docker-compose.yml").read_text())
PROD = yaml.safe_load(Path("docker-compose.prod.yml").read_text())


def _mounts(doc, service):
    return doc.get("services", {}).get(service, {}).get("volumes", []) or []


def test_tiap_line_memount_videos_di_dasar():
    for svc in ("line1", "line2", "line3"):
        assert any("videos" in str(v) for v in _mounts(DASAR, svc)), svc


def test_prod_juga_memount_videos():
    # Override MENGGANTI blok dasar, bukan menambahinya: begitu prod menyebut
    # `volumes:` untuk sebuah service, daftar di docker-compose.yml dibuang
    # seluruhnya. Terbukti di Lampung (Compose v2.40.3).
    for svc in ("line1", "line2", "line3"):
        mounts = _mounts(PROD, svc)
        if mounts:
            assert any("videos" in str(v) for v in mounts), svc
```

CATATAN: nama service (`line1`…) mungkin beda di repo — periksa dulu
`docker-compose.yml` dan pakai nama yang sebenarnya.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/e2e/test_compose_videos_mount.py -v`
Expected: FAIL — tidak ada mount `videos`

- [ ] **Step 3: Write minimal implementation**

Di `docker-compose.yml`, tambahkan pada tiap service line:

```yaml
      - ./videos:/app/videos
```

dan env `VIDEOS_DIR=/app/videos`.

Di `docker-compose.prod.yml`, **tulis ulang seluruh daftar `volumes:`** untuk
tiap line kalau blok itu disebut di sana — override mengganti, bukan menambah.

Di `docs/MANUAL.md`, tambahkan di bagian tab support: apa itu tab Rekam Video,
bahwa rekaman **tidak dihapus otomatis**, dan di mana berkasnya di PC pabrik
(`/opt/palmgrade/autograde/videos/`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/e2e/test_compose_videos_mount.py -v`
Expected: PASS

Buktikan juga compose-nya sah:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config | grep -A5 videos
```

- [ ] **Step 5: Lint dan commit**

```bash
git add docker-compose.yml docker-compose.prod.yml docs/MANUAL.md tests/e2e/test_compose_videos_mount.py
git commit -m "feat(rekam): mount folder videos dan catat di manual"
```

---

### Task 11: Ukur biaya encode, lalu seluruh test

Ini tugas **pengukuran**, bukan tebakan. Hasilnya menentukan apakah fitur ini
aman dipakai di pabrik.

**Files:**
- Create: `docs/runbooks/2026-09-22-ukur-biaya-encode-rekam.md`

- [ ] **Step 1: Jalankan seluruh test**

```bash
.venv/bin/pytest tests/unit -q
.venv/bin/pytest tests/e2e -q
```

Expected: nol merah. Kalau ada yang merah dan **sudah merah sebelum kerjaan ini**,
catat di runbook — jangan diperbaiki diam-diam di PR ini.

- [ ] **Step 2: Ukur fps deteksi TANPA rekaman**

```bash
make line
```

Biarkan 2 menit, catat angka `[FPS]` dari log. Ini garis dasarnya.

- [ ] **Step 3: Ukur fps deteksi DENGAN rekaman**

Nyalakan rekaman dari konsol, biarkan 2 menit, catat `[FPS]` lagi, dan catat
`frame_dibuang` dari status.

- [ ] **Step 4: Tulis runbook**

Catat di `docs/runbooks/2026-09-22-ukur-biaya-encode-rekam.md`:
- fps sebelum vs sesudah (angka nyata, bukan kesan)
- ukuran berkas per menit, dikalikan jadi per jam
- berapa frame dibuang
- **kesimpulan: aman atau tidak dipakai di 3 line sekaligus di PC Lampung**

⚠️ Mac ini CPU-only dan jauh lebih lambat dari RTX 3060 di Lampung — angka di
sini **batas bawah**, bukan ramalan. Kalau di Mac saja fps deteksi turun tajam,
itu sinyal kuat untuk berhenti dan lapor sebelum ini masuk pabrik.

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/2026-09-22-ukur-biaya-encode-rekam.md
git commit -m "docs(rekam): hasil ukur biaya encode terhadap fps deteksi"
```

---

## Sesudah Semua Task

1. Jalankan `.venv/bin/pytest tests/unit tests/e2e -q` sekali lagi — semua hijau.
2. Buka PR ke `staging` (bukan `main`), sebutkan hasil ukur dari Task 11.
3. **Jangan tag rilis** sebelum user membaca hasil ukur dan setuju.
