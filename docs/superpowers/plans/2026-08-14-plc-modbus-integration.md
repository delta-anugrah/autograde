# PLC Modbus Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kirim hasil grading tiap line (ACC / REJ / ERROR) dari `palmgrade-vision` ke PLC Mitsubishi lewat remote IO ODOT CN-8031 via Modbus-TCP, plus baca status motor/E-stop balik dari PLC.

**Architecture:** Seluruh logika fitur tinggal di **satu paket baru, `src/palmgrade/plc/`**. Paket itu memaparkan tiga fungsi, dan itulah satu-satunya cara kode existing menyentuhnya. Tiap container line konek sendiri sebagai Modbus-TCP **client** ke CN-8031 (coupler support 5 client bareng, kita pakai 3). `FrameProcessingWorker` cuma memanggil `submit_grading(status)` — tidak pernah menyentuh socket, sesuai Critical Rule #1 repo ini.

**Tech Stack:** Python 3.11, `pymodbus` (baru), dataclass murni untuk scheduler, pytest.

**Spec:** Tidak ada dokumen spec formal. Sumber kebenarannya adalah skematik PDF *"REMOTE IO — CONVEYOR SAWIT"* (DW.26/07/27 hal. 19–20, PT Nexio Teknologi Otomasi) plus percakapan WhatsApp dengan pak Ocit. **PDF itu tidak ada di repo** — semua fakta yang mengikat sudah disalin ke `## Global Constraints` di bawah, dan Task 7 memasukkannya ke `docs/plc-integration.md` supaya berhenti jadi pengetahuan lisan.

**Baseline (diverifikasi 2026-08-15):** ketiga repo di `staging` terbaru — api `1b5aa11` (rilis `v1.7.0`), frontend `2f0278f` (`v1.4.4`), vision `68fc4e7` (`v1.1.0`). **Perubahan hanya di `palmgrade-vision`; api dan frontend nol baris.**

---

## Global Constraints

Nilai-nilai ini datang dari skematik dan **tidak boleh ditebak ulang**:

- **Coil / DO (vision menulis), zero-based:** `0,1,2` = CAM1 OK/NG/ERROR · `3,4,5` = CAM2 OK/NG/ERROR · `6,7,8` = CAM3 OK/NG/ERROR · `9` = HEARTBEAT PC ON · `10–15` = SPARE (sudah dikabelkan ke X030A–X030F, memakainya tidak butuh kerja panel).
- **Discrete input / DI (vision membaca), zero-based:** `0–9` = MOTOR 1–10 FAULT · `10` = EMERGENCY STOP · `11–15` = SPARE.
- **Modbus:** TCP port `502`, function code `05` (write single coil) dan `02` (read discrete inputs).
- **Coupler:** ODOT CN-8031, maksimum **5 client bersamaan**. Tiga container line memakai 3 slot.
- **Watchdog ODOT** me-reset output ke 0 kalau tidak ada trafik Modbus. Polling reguler kita berfungsi sebagai keepalive-nya.
- **Default nilai coil aman = `0` (OFF)** untuk semua coil yang kita miliki.
- **Repo rule (Critical Rule #1):** worker deteksi tidak boleh blocking pada I/O jaringan. Pola wajib: `put_nowait` + drop-on-full, persis seperti `state.event_queue` yang sudah ada.
- **Repo rule (CLAUDE.md § Conventions):** env var baru **wajib** dideklarasikan di `core/config.py` dengan default yang masuk akal. Karena itu blok `PLC_*` masuk ke `Settings`, bukan bikin config sendiri — logikanya saja yang terkurung di `plc/`.
- **Branch:** dari `staging`, PR-only, squash merge. Commit message **tidak boleh** menyebut Claude / AI.

**Belum diputuskan (lihat Task 0):** lebar pulse, jeda antar pulse, dan apakah 1 sinyal = 1 buah. Semuanya sudah jadi env var dengan default yang masuk akal, jadi bukan blocker untuk mulai — tapi harus dikonfirmasi sebelum commissioning.

---

## File Structure

### Paket baru — semua logika PLC ada di sini

```
src/palmgrade/plc/
├── __init__.py         # Permukaan publik: start_plc_worker(), submit_grading(), inputs()
├── pulse.py            # PulseScheduler — logika murni, nol I/O
├── modbus_client.py    # ModbusPlcClient — satu-satunya file yang menyentuh pymodbus
└── worker.py           # PlcWorker — satu-satunya thread yang menyentuh socket

tests/unit/plc/
├── test_plc_pulse.py
├── test_plc_modbus_client.py
└── test_plc_worker.py
```

### Jejak di kode existing — semuanya di sini, tidak ada yang lain

| File | Perubahan |
| --- | --- |
| `src/palmgrade/core/config.py` | +1 helper, +11 field, +3 property (satu blok berlabel) |
| `src/palmgrade/main.py` | +1 import, +2 baris pendaftaran worker |
| `src/palmgrade/workers/frame_processing_worker.py` | +1 import, +1 baris panggilan |
| `requirements.txt` | +1 baris (`pymodbus`) |
| `docker-compose.yml` | blok `environment` per line |
| `.env.example`, `docs/`, `CLAUDE.md` | dokumentasi |
| `.github/workflows/ci.yml` | +1 path di scope ruff |

**Empat baris Python** di luar `config.py`. Mencabut fitur ini = hapus folder `plc/`, hapus blok env, hapus 4 baris.

### Dua keputusan struktur yang perlu diketahui reviewer

1. **Env `PLC_*` masuk `core/config.py`, bukan config sendiri di `plc/`.** CLAUDE.md repo ini menyebut satu sumber kebenaran untuk env, dan blok inert 15 baris berlabel tidak melanggar isolasi yang kita kejar — yang mahal untuk dilacak itu logika dan wiring, bukan data.
2. **Antrean grading hidup di dalam `PlcWorker`, bukan di `RuntimeState`.** Konsekuensinya `runtime_state.py` tidak disentuh sama sekali, dan saat `PLC_ENABLED=false` panggilan `submit_grading()` langsung `return` — tidak ada antrean yang diam-diam terisi lalu penuh.

---

### Task 0: Kirim spec ke pak Ocit — jalan paralel, mulai hari ini

**Bukan pekerjaan koding, dan tidak boleh menunggu Task 1.** Empat hal di bawah ada di sisi pak Ocit dan butuh waktu ladder + kerja panel. Kalau baru dikirim saat commissioning, kita yang nunggu dia. Task 1–7 jalan terus tanpa jawabannya.

- [ ] **Step 1: Konfirmasi ulang offset alamat**

Kirim: *"Pak, BIT 1 di Address Map ODOT itu coil address 0 atau 1? Saya perlu pastikan sebelum coding, kalau salah semua sinyal geser satu kolom."*

Dia sudah pernah menjawab "DI/DO mulai dari 0", jadi ini konfirmasi tertulis terakhir. Tetap diverifikasi ulang di hardware pada Task 8 Step 1.

- [ ] **Step 2: Minta pulse spec — ini yang paling menentukan**

Bawa angkanya, jangan tanya terbuka:

> Pak, kamera kami always-ON, jadi keputusan ACC/REJ bisa keluar sampai ~10× per detik per line. Yang saya perlu dari bapak:
> 1. Sinyal OK/NG ini pulse atau level? Kalau level, PLC nggak bisa bedain 1 buah sama 5 buah.
> 2. Kalau pulse: lebar berapa ms, dan jeda minimum antar pulse berapa ms?
> 3. Satu sinyal = satu buah, atau status batch?
> 4. Cycle time actuator penyortirnya berapa?
>
> Patokan saya sekarang pulse 200 ms + jeda 100 ms, artinya maksimum ~3,3 sinyal/detik per coil. Kalau actuator bapak cuma sanggup 2×/detik ya percuma kami kirim lebih cepat, dan saya set sesuai kemampuan actuator.

- [ ] **Step 3: Minta watchdog diturunkan ke 2–3 detik**

Sekarang 30 detik. PC kita polling tiap 200 ms, jadi 2–3 detik aman dan tidak akan false-trip. Dengan 30 detik, PC mati berarti coil terakhir nyangkut setengah menit — cukup lama untuk menyortir banyak buah pakai keputusan basi.

- [ ] **Step 4: Minta polaritas EMERGENCY STOP dibalik jadi NC**

Ini yang paling penting dari sisi keselamatan. CT-122F low-aktif, dan setting ODOT `Fault Action for Input: Cleaning Input Value` berarti **kabel putus terbaca persis sama dengan "aman"**. Minta bit ON selama kondisi normal dan OFF saat E-stop ditekan, supaya kabel putus jatuh ke sisi aman.

- [ ] **Step 5: Minta spare bit 10/11/12 dijadikan LINE 1/2/3 ALIVE**

Vision jalan 3 container terpisah. Kalau container line 2 mati sendirian, bit CAM2 ERROR-nya beku — yang harusnya menulis ya proses yang mati — dan watchdog ODOT tidak terpicu karena line 1 dan 3 masih menjaga koneksi. PLC jadi buta terhadap satu line yang hilang.

Solusinya bit yang **toggle** tiap detik, bukan level. Berhenti toggle = line itu mati. Kabelnya sudah ada (DO10–DO15 → X030A–X030F), yang dibutuhkan cuma ladder.

Sekalian: coil `9` (HEARTBEAT PC ON) ikut ditoggle oleh container line 1. Di sisi kita ini nol perubahan kode — `PLC_COIL_ALIVE` menerima daftar, jadi line 1 diisi `"9,10"`, line 2 `"11"`, line 3 `"12"`.

- [ ] **Step 6: Minta IP ODOT dan konfirmasi jalur jaringannya**

NIC PC pabrik sudah dipakai 3 kamera GigE. Perlu tahu ODOT nyambung ke switch yang mana dan IP-nya berapa, karena itu yang masuk `PLC_HOST`.

---

### Task 1: Konfigurasi PLC di Settings

Semua task berikutnya membaca dari sini, jadi ini duluan.

**Files:**
- Modify: `src/palmgrade/core/config.py`
- Modify: `.env.example`
- Create: `tests/unit/plc/test_plc_config.py`

**Interfaces:**
- Consumes: `_as_bool` yang sudah ada di `core/config.py:11`
- Produces: `parse_coil_list(value: str | None) -> tuple[int, ...]`, dan pada `Settings`: `plc_enabled: bool`, `plc_host: str`, `plc_port: int`, `plc_unit_id: int`, `plc_coil_base: int`, `plc_coil_alive: tuple[int, ...]`, `plc_pulse_ms: int`, `plc_pulse_gap_ms: int`, `plc_queue_max: int`, `plc_poll_ms: int`, `plc_di_count: int`, plus property `plc_coil_ok / plc_coil_ng / plc_coil_error -> int`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tests/unit/plc/test_plc_config.py
import os

import pytest

from palmgrade.core.config import Settings, parse_coil_list


def test_coil_offsets_derive_from_base():
    os.environ["PLC_COIL_BASE"] = "3"
    try:
        s = Settings()
        assert (s.plc_coil_ok, s.plc_coil_ng, s.plc_coil_error) == (3, 4, 5)
    finally:
        del os.environ["PLC_COIL_BASE"]


def test_plc_disabled_by_default():
    assert Settings().plc_enabled is False


def test_parse_coil_list_handles_blank_and_spaces():
    assert parse_coil_list("") == ()
    assert parse_coil_list(None) == ()
    assert parse_coil_list(" 9 , 10 ") == (9, 10)
    assert parse_coil_list("12") == (12,)


def test_parse_coil_list_rejects_garbage():
    with pytest.raises(ValueError):
        parse_coil_list("9,abc")
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd palmgrade-vision && python -m pytest tests/unit/plc/test_plc_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_coil_list'`

- [ ] **Step 3: Implementasi**

Di `src/palmgrade/core/config.py`, tambahkan helper tepat di bawah `_as_bool`:

```python
def parse_coil_list(value: str | None) -> tuple[int, ...]:
    """'9,10' -> (9, 10). Kosong -> (). Raise ValueError kalau ada yang bukan angka."""
    if not value or not value.strip():
        return ()
    return tuple(int(part.strip()) for part in value.split(","))
```

Lalu blok field di dalam `class Settings`, setelah blok upload/R2:

```python
    # ── PLC / ODOT CN-8031 (Modbus-TCP) ──────────────────────────
    # Logikanya ada di src/palmgrade/plc/. Coil map lengkap:
    # docs/plc-integration.md. Mati secara default — cuma PC pabrik yang
    # menyalakan. plc_coil_base = 0/3/6 per line, di-set docker-compose.
    plc_enabled: bool = field(default_factory=lambda: _as_bool(os.getenv("PLC_ENABLED"), False))
    plc_host: str = field(default_factory=lambda: os.getenv("PLC_HOST", ""))
    plc_port: int = field(default_factory=lambda: int(os.getenv("PLC_PORT", "502")))
    plc_unit_id: int = field(default_factory=lambda: int(os.getenv("PLC_UNIT_ID", "1")))
    plc_coil_base: int = field(default_factory=lambda: int(os.getenv("PLC_COIL_BASE", "0")))
    # Bit "line ini hidup" yang di-toggle PlcWorker tiap detik. Daftar, karena
    # line 1 juga memegang coil 9 (HEARTBEAT PC). Kosong = fitur alive mati.
    plc_coil_alive: tuple[int, ...] = field(
        default_factory=lambda: parse_coil_list(os.getenv("PLC_COIL_ALIVE"))
    )
    plc_pulse_ms: int = field(default_factory=lambda: int(os.getenv("PLC_PULSE_MS", "200")))
    plc_pulse_gap_ms: int = field(default_factory=lambda: int(os.getenv("PLC_PULSE_GAP_MS", "100")))
    plc_queue_max: int = field(default_factory=lambda: int(os.getenv("PLC_QUEUE_MAX", "20")))
    plc_poll_ms: int = field(default_factory=lambda: int(os.getenv("PLC_POLL_MS", "200")))
    plc_di_count: int = field(default_factory=lambda: int(os.getenv("PLC_DI_COUNT", "16")))
```

Dan property-nya, di dekat property `backend_*` yang sudah ada:

```python
    @property
    def plc_coil_ok(self) -> int:
        return self.plc_coil_base

    @property
    def plc_coil_ng(self) -> int:
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self) -> int:
        return self.plc_coil_base + 2
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/plc/test_plc_config.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Pastikan suite lama tidak terganggu**

Subfolder test baru tanpa `__init__.py` bisa bikin pytest bingung kalau ada nama file yang bentrok. Semua file di sini berawalan `test_plc_`, jadi tidak ada bentrokan — tapi buktikan:

Run: `python -m pytest tests/unit/ -q`
Expected: semua test lama lulus, tidak ada error kolektor

- [ ] **Step 6: Dokumentasikan di `.env.example`**

```bash
# ── PLC / ODOT CN-8031 (Modbus-TCP) ──────────────────────────
# Mati secara default. Cuma PC pabrik yang menyalakan ini.
PLC_ENABLED=false
PLC_HOST=
PLC_PORT=502
PLC_UNIT_ID=1
# Line 1 = 0, line 2 = 3, line 3 = 6 (di-set docker-compose, bukan di sini)
PLC_COIL_BASE=0
# Bit alive yang di-toggle tiap detik. Line 1 = "9,10" (9 = HEARTBEAT PC),
# line 2 = "11", line 3 = "12". Kosong = mati.
PLC_COIL_ALIVE=
# Lebar pulse OK/NG dan jeda WAJIB di antara dua pulse pada coil yang sama.
# BELUM dikonfirmasi pak Ocit — lihat Task 0 dan docs/plc-integration.md.
PLC_PULSE_MS=200
PLC_PULSE_GAP_MS=100
PLC_QUEUE_MAX=20
PLC_POLL_MS=200
PLC_DI_COUNT=16
```

- [ ] **Step 7: Commit**

```bash
git checkout -b feat/plc-modbus-integration
git add src/palmgrade/core/config.py .env.example tests/unit/plc/test_plc_config.py
git commit -m "feat(plc): konfigurasi Modbus/ODOT di Settings"
```

---

### Task 2: PulseScheduler — logika murni

Ini inti fiturnya, dan satu-satunya bagian yang berubah kalau jawaban Task 0 Step 2 berbeda dari dugaan. Sengaja dipisah supaya jawabannya cuma menyentuh satu file.

**Files:**
- Create: `src/palmgrade/plc/__init__.py`
- Create: `src/palmgrade/plc/pulse.py`
- Create: `tests/unit/plc/test_plc_pulse.py`

**Interfaces:**
- Consumes: nilai `plc_pulse_ms` / `plc_pulse_gap_ms` / `plc_queue_max` dari Task 1.
- Produces: `PulseScheduler(pulse_s: float, gap_s: float, queue_max: int)` dengan method `enqueue(coil: int) -> bool`, `tick(now: float) -> dict[int, bool]`, dan atribut `dropped: int`.

**Kenapa ini rumit:** dua pulse pada coil yang **sama** tidak boleh menyatu jadi satu sinyal panjang — PLC menghitung tepi naik, jadi dua buah REJ berturut-turut yang menyatu akan terhitung satu. Scheduler menjamin selalu ada periode OFF minimal `gap_s` di antara dua pulse pada coil yang sama. Konsekuensinya throughput per coil dibatasi `1 / (pulse_s + gap_s)` — dengan default 200 ms + 100 ms cuma ~3,3 sinyal/detik, sementara YOLO bisa memutuskan jauh lebih cepat. Kalau antrean penuh, item **dibuang dan dihitung**, bukan ditunda: sinyal yang telat akan menempel pada buah yang salah, dan itu lebih berbahaya daripada sinyal yang hilang.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tests/unit/plc/test_plc_pulse.py
import pytest

from palmgrade.plc.pulse import PulseScheduler


def _sched(pulse=0.2, gap=0.1, queue_max=20):
    return PulseScheduler(pulse_s=pulse, gap_s=gap, queue_max=queue_max)


def test_gap_must_be_positive():
    # gap 0 membuat OFF dan ON jatuh pada tick yang sama -> PLC tak pernah
    # melihat tepi turun. Dilarang di konstruktor, bukan ditemukan di pabrik.
    with pytest.raises(ValueError):
        PulseScheduler(pulse_s=0.2, gap_s=0.0, queue_max=20)


def test_single_pulse_turns_on_then_off():
    s = _sched()
    assert s.enqueue(4) is True
    assert s.tick(now=0.0) == {4: True}
    assert s.tick(now=0.1) == {}          # masih di tengah pulse
    assert s.tick(now=0.2) == {4: False}  # tepat di ujung pulse


def test_two_pulses_same_coil_do_not_merge():
    s = _sched()
    s.enqueue(4)
    s.enqueue(4)
    assert s.tick(now=0.0) == {4: True}
    assert s.tick(now=0.2) == {4: False}   # pulse pertama selesai
    assert s.tick(now=0.25) == {}          # masih di dalam gap
    assert s.tick(now=0.3) == {4: True}    # pulse kedua baru mulai
    assert s.tick(now=0.5) == {4: False}


def test_different_coils_are_independent():
    s = _sched()
    s.enqueue(0)
    s.enqueue(1)
    assert s.tick(now=0.0) == {0: True, 1: True}


def test_overflow_drops_and_counts():
    s = _sched(queue_max=2)
    assert s.enqueue(0) is True
    assert s.enqueue(0) is True
    assert s.enqueue(0) is False
    assert s.dropped == 1


def test_idle_scheduler_reports_no_changes():
    assert _sched().tick(now=1.0) == {}
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/plc/test_plc_pulse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.plc'`

- [ ] **Step 3: Implementasi**

```python
# src/palmgrade/plc/__init__.py
"""Integrasi PLC lewat coupler ODOT CN-8031 (Modbus-TCP).

Permukaan publik paket ini diisi di Task 4.
"""
```

```python
# src/palmgrade/plc/pulse.py
"""Penjadwal pulse coil — logika murni, tanpa I/O.

Menerjemahkan "satu keputusan grading" jadi satu pulse ON/OFF pada satu coil,
dengan jaminan ada jeda OFF di antara dua pulse pada coil yang sama supaya PLC
selalu melihat tepi naik yang terpisah.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _CoilState:
    on_until: float = 0.0   # waktu pulse aktif harus dimatikan; 0 = sedang OFF
    free_at: float = 0.0    # waktu paling awal pulse berikutnya boleh mulai
    pending: int = 0


@dataclass
class PulseScheduler:
    pulse_s: float
    gap_s: float
    queue_max: int
    dropped: int = 0
    _coils: dict[int, _CoilState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.pulse_s <= 0:
            raise ValueError("pulse_s harus > 0")
        if self.gap_s <= 0:
            raise ValueError(
                "gap_s harus > 0 — tanpa jeda, dua pulse menyatu dan PLC menghitungnya satu"
            )

    def enqueue(self, coil: int) -> bool:
        """Antrekan satu pulse. False = antrean penuh dan pulse ini dibuang."""
        st = self._coils.setdefault(coil, _CoilState())
        if st.pending >= self.queue_max:
            self.dropped += 1
            return False
        st.pending += 1
        return True

    def tick(self, now: float) -> dict[int, bool]:
        """Kembalikan {coil: level} HANYA untuk coil yang levelnya berubah pada tick ini."""
        changes: dict[int, bool] = {}
        for coil, st in self._coils.items():
            if st.on_until:
                if now < st.on_until:
                    continue                      # pulse masih jalan, jangan diganggu
                changes[coil] = False
                st.on_until = 0.0
                st.free_at = now + self.gap_s     # gap_s > 0 menjamin ON tidak ikut di tick ini
            if st.pending and now >= st.free_at:
                st.pending -= 1
                st.on_until = now + self.pulse_s
                changes[coil] = True
        return changes
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/plc/test_plc_pulse.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/plc/ tests/unit/plc/test_plc_pulse.py
git commit -m "feat(plc): penjadwal pulse coil dengan jaminan jeda antar pulse"
```

---

### Task 3: Klien Modbus

**Files:**
- Create: `src/palmgrade/plc/modbus_client.py`
- Create: `tests/unit/plc/test_plc_modbus_client.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: —
- Produces: `ModbusPlcClient(host: str, port: int = 502, unit_id: int = 1, _client_factory=None)` dengan `write_coil(address: int, value: bool) -> bool`, `read_discrete_inputs(start: int, count: int) -> list[bool] | None`, `close() -> None`, dan atribut `connected: bool`.

**Kenapa pymodbus dan bukan socket mentah:** permukaan yang kita pakai memang cuma dua function code, tapi bagian yang bikin repot bukan framingnya — melainkan pencocokan transaction id, frame yang terbelah di beberapa segmen TCP, dan reconnect. Itu justru kelas bug yang muncul jam 3 pagi di pabrik. pymodbus murni-python (~1 MB), jadi tidak menambah berat image 10.3 GB secara berarti. **Seluruh sentuhan API pymodbus dikurung di file ini** — kalau versinya berganti, cuma satu file yang perlu disesuaikan.

- [ ] **Step 1: Tambahkan dependency**

Di `requirements.txt`, blok baru setelah `# ── HTTP Client ──`:

```
# ── PLC / Modbus-TCP ─────────────────────────────────────────
pymodbus==3.6.9
```

Run: `pip install pymodbus==3.6.9`

- [ ] **Step 2: Verifikasi nama kwarg pymodbus sebelum menulis wrapper**

Versi pymodbus berbeda memakai `slave=` atau `unit=` untuk unit id. Konfirmasi sekali:

Run: `python -c "from pymodbus.client import ModbusTcpClient; import inspect; print(inspect.signature(ModbusTcpClient.write_coil))"`
Expected: signature memuat `slave`. Kalau ternyata bukan `slave`, pakai nama yang muncul di output — itu satu-satunya tempat yang perlu disesuaikan.

- [ ] **Step 3: Tulis test yang gagal**

Test memakai klien palsu, jadi tidak butuh hardware maupun jaringan.

```python
# tests/unit/plc/test_plc_modbus_client.py
from palmgrade.plc.modbus_client import ModbusPlcClient


class _FakeReply:
    def __init__(self, error, bits=None):
        self._error = error
        self.bits = bits or []

    def isError(self):
        return self._error


class _FakeInner:
    def __init__(self, connect_ok=True, raises=False):
        self._connect_ok = connect_ok
        self._raises = raises
        self.writes: list[tuple[int, bool]] = []
        self.closed = False

    def connect(self):
        return self._connect_ok

    def write_coil(self, address, value, slave=1):
        if self._raises:
            raise OSError("boom")
        self.writes.append((address, value))
        return _FakeReply(error=False)

    def read_discrete_inputs(self, address, count, slave=1):
        return _FakeReply(error=False, bits=[True] + [False] * (count - 1))

    def close(self):
        self.closed = True


def _client(inner):
    return ModbusPlcClient(host="1.2.3.4", port=502, unit_id=1, _client_factory=lambda: inner)


def test_write_coil_forwards_address_and_value():
    inner = _FakeInner()
    assert _client(inner).write_coil(4, True) is True
    assert inner.writes == [(4, True)]


def test_write_coil_returns_false_on_exception_instead_of_raising():
    # Worker loop tidak boleh mati gara-gara kabel dicabut.
    c = _client(_FakeInner(raises=True))
    assert c.write_coil(4, True) is False
    assert c.connected is False


def test_read_discrete_inputs_returns_exactly_count_bits():
    c = _client(_FakeInner())
    assert c.read_discrete_inputs(0, 16) == [True] + [False] * 15


def test_failed_connect_reports_disconnected():
    c = _client(_FakeInner(connect_ok=False))
    assert c.write_coil(0, True) is False
    assert c.connected is False
```

- [ ] **Step 4: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/plc/test_plc_modbus_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.plc.modbus_client'`

- [ ] **Step 5: Implementasi**

```python
# src/palmgrade/plc/modbus_client.py
"""Klien Modbus-TCP untuk coupler ODOT CN-8031.

Satu-satunya tempat di repo ini yang menyentuh API pymodbus. Semua method
mengembalikan nilai sentinel (False / None) alih-alih melempar exception:
PlcWorker berjalan di thread panjang dan tidak boleh mati karena kabel dicabut.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ModbusPlcClient:
    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        _client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._factory = _client_factory or self._default_factory
        self._client: Any = None
        self.connected = False

    def _default_factory(self) -> Any:
        from pymodbus.client import ModbusTcpClient

        return ModbusTcpClient(self._host, port=self._port, timeout=1.0)

    def _ensure(self) -> bool:
        if self.connected and self._client is not None:
            return True
        try:
            self._client = self._factory()
            self.connected = bool(self._client.connect())
        except Exception as exc:
            logger.warning("PLC connect ke %s:%s gagal: %s", self._host, self._port, exc)
            self.connected = False
        return self.connected

    def _drop(self, exc: Exception) -> None:
        logger.warning("PLC I/O gagal (%s) — menandai terputus, akan reconnect", exc)
        self.connected = False
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None

    def write_coil(self, address: int, value: bool) -> bool:
        if not self._ensure():
            return False
        try:
            reply = self._client.write_coil(address, value, slave=self._unit_id)
        except Exception as exc:
            self._drop(exc)
            return False
        if reply.isError():
            logger.warning("PLC menolak write coil %s = %s", address, value)
            return False
        return True

    def read_discrete_inputs(self, start: int, count: int) -> list[bool] | None:
        if not self._ensure():
            return None
        try:
            reply = self._client.read_discrete_inputs(start, count, slave=self._unit_id)
        except Exception as exc:
            self._drop(exc)
            return None
        if reply.isError():
            return None
        return list(reply.bits)[:count]

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self.connected = False
```

- [ ] **Step 6: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/plc/test_plc_modbus_client.py -v`
Expected: PASS (4 test)

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/plc/modbus_client.py tests/unit/plc/test_plc_modbus_client.py requirements.txt
git commit -m "feat(plc): klien Modbus-TCP untuk coupler ODOT CN-8031"
```

---

### Task 4: PlcWorker dan permukaan publik paket

Setelah task ini paket `plc/` lengkap dan bisa dites penuh — tapi belum ada satu pun kode existing yang memanggilnya. Penyambungan baru terjadi di Task 6.

**Files:**
- Create: `src/palmgrade/plc/worker.py`
- Create: `tests/unit/plc/test_plc_worker.py`
- Modify: `src/palmgrade/plc/__init__.py`

**Interfaces:**
- Consumes: `PulseScheduler` (Task 2), `ModbusPlcClient` (Task 3), field `Settings.plc_*` (Task 1).
- Produces:
  - `PlcWorker(client, scheduler, settings, health_check=None)` dengan `submit(status: str) -> None`, `run_once(now: float | None = None) -> None`, `run_loop() -> None`, dan atribut `inputs: list[bool]`.
  - Permukaan publik paket: `start_plc_worker(settings, health_check=None) -> PlcWorker | None`, `submit_grading(status: str) -> None`, `inputs() -> list[bool]`.

`submit_grading` dan `inputs` bekerja lewat satu instance modul-level. Itu benar untuk proses ini: satu container = satu line = satu koneksi PLC. Kalau `start_plc_worker` tidak pernah dipanggil atau `PLC_ENABLED=false`, keduanya jadi no-op — inilah yang membuat fitur ini benar-benar tidak ada saat dimatikan.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tests/unit/plc/test_plc_worker.py
from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker


class _FakeClient:
    def __init__(self):
        self.writes: list[tuple[int, bool]] = []
        self.di = [False] * 16

    def write_coil(self, address, value):
        self.writes.append((address, value))
        return True

    def read_discrete_inputs(self, start, count):
        return self.di[start:start + count]


class _Cfg:
    plc_coil_base = 3
    plc_coil_alive = (11,)
    plc_poll_ms = 200
    plc_di_count = 16

    @property
    def plc_coil_ok(self):
        return self.plc_coil_base

    @property
    def plc_coil_ng(self):
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self):
        return self.plc_coil_base + 2


def _worker(health_check=None):
    client = _FakeClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_Cfg(),
        health_check=health_check,
    )
    return w, client


def test_acc_maps_to_ok_coil_of_this_line():
    w, client = _worker()
    w.submit("acc")
    w.run_once(now=0.0)
    assert (3, True) in client.writes


def test_rej_maps_to_ng_coil_of_this_line():
    w, client = _worker()
    w.submit("rej")
    w.run_once(now=0.0)
    assert (4, True) in client.writes


def test_submit_never_blocks_when_queue_is_full():
    # Thread deteksi memanggil ini. Antrean penuh harus dibuang, bukan menggantung.
    w, _ = _worker()
    for _ in range(500):
        w.submit("rej")          # tidak boleh raise, tidak boleh menggantung


def test_alive_coils_toggle_between_ticks():
    w, client = _worker()
    w.run_once(now=0.0)
    w.run_once(now=1.0)
    w.run_once(now=2.0)
    assert [v for (addr, v) in client.writes if addr == 11] == [True, False, True]


def test_discrete_inputs_are_snapshotted():
    w, client = _worker()
    client.di[10] = True          # EMERGENCY STOP
    w.run_once(now=0.0)
    assert w.inputs[10] is True


def test_unknown_status_is_ignored_not_crashed():
    w, client = _worker()
    w.submit("tp")
    w.run_once(now=0.0)
    assert all(addr not in (3, 4) for (addr, _) in client.writes)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/plc/test_plc_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.plc.worker'`

- [ ] **Step 3: Implementasi**

```python
# src/palmgrade/plc/worker.py
"""Worker yang bicara ke coupler ODOT CN-8031.

Satu-satunya thread yang menyentuh socket Modbus. Tugasnya empat:
menguras antrean keputusan jadi pulse coil, meng-toggle bit alive line ini,
memantulkan discrete input PLC ke memori, dan — sebagai efek samping dari
polling reguler — menahan watchdog ODOT supaya tidak mereset output.
"""

from __future__ import annotations

import logging
import queue
import time
from typing import Callable

logger = logging.getLogger(__name__)


class PlcWorker:
    def __init__(
        self,
        client,
        scheduler,
        settings,
        health_check: Callable[[], bool] | None = None,
    ) -> None:
        self.client = client
        self.scheduler = scheduler
        self.settings = settings
        self.health_check = health_check
        self.inputs: list[bool] = []
        self._queue: queue.Queue[str] = queue.Queue(maxsize=50)
        self._alive_level = False
        self._next_alive_toggle = 0.0
        self._error_level: bool | None = None   # None = belum pernah ditulis

    def submit(self, status: str) -> None:
        """Dipanggil dari thread deteksi. Tidak pernah blocking, tidak pernah raise."""
        try:
            self._queue.put_nowait(status)
        except queue.Full:
            self.scheduler.dropped += 1

    def run_once(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now

        # 1. Antrean keputusan -> pulse terjadwal
        while True:
            try:
                status = self._queue.get_nowait()
            except queue.Empty:
                break
            coil = self._coil_for(status)
            if coil is None:
                logger.debug("Status PLC tidak dikenal, dilewati: %r", status)
                continue
            if not self.scheduler.enqueue(coil):
                logger.warning(
                    "Antrean pulse PLC penuh — sinyal dibuang (total %s). "
                    "Buah datang lebih cepat dari yang bisa dihitung PLC.",
                    self.scheduler.dropped,
                )

        # 2. Terapkan perubahan level coil
        for coil, level in self.scheduler.tick(now).items():
            self.client.write_coil(coil, level)

        # 3. Bit alive — toggle, bukan ON statis, supaya proses yang hang ikut ketahuan
        if self.settings.plc_coil_alive and now >= self._next_alive_toggle:
            self._alive_level = not self._alive_level
            for coil in self.settings.plc_coil_alive:
                self.client.write_coil(coil, self._alive_level)
            self._next_alive_toggle = now + 1.0

        # 4. Baca balik status dari PLC
        bits = self.client.read_discrete_inputs(0, self.settings.plc_di_count)
        if bits is not None:
            self.inputs = bits

    def _coil_for(self, status: str) -> int | None:
        normalized = (status or "").strip().lower()
        if normalized == "acc":
            return self.settings.plc_coil_ok
        if normalized == "rej":
            return self.settings.plc_coil_ng
        return None

    def run_loop(self) -> None:
        interval = self.settings.plc_poll_ms / 1000.0
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("PlcWorker.run_once gagal — loop tetap jalan")
            time.sleep(interval)
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/plc/test_plc_worker.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Isi permukaan publik paket**

Ganti seluruh isi `src/palmgrade/plc/__init__.py`:

```python
"""Integrasi PLC lewat coupler ODOT CN-8031 (Modbus-TCP).

Kode di luar paket ini hanya boleh menyentuh tiga fungsi di bawah. Kalau
PLC_ENABLED=false, ketiganya jadi no-op dan tidak ada thread yang jalan.
Coil map lengkap: docs/plc-integration.md.
"""

from __future__ import annotations

import logging
from typing import Callable

from .modbus_client import ModbusPlcClient
from .pulse import PulseScheduler
from .worker import PlcWorker

__all__ = [
    "ModbusPlcClient",
    "PlcWorker",
    "PulseScheduler",
    "inputs",
    "start_plc_worker",
    "submit_grading",
]

logger = logging.getLogger(__name__)

# Satu proses = satu line = satu koneksi PLC, jadi satu instance sudah benar.
_worker: PlcWorker | None = None


def start_plc_worker(settings, health_check: Callable[[], bool] | None = None) -> PlcWorker | None:
    """Bangun worker dari Settings. Kembalikan None kalau fitur PLC dimatikan.

    Pemanggil bertanggung jawab menjalankan run_loop() di thread-nya sendiri.
    """
    global _worker
    if not settings.plc_enabled:
        return None
    if not settings.plc_host:
        logger.warning("PLC_ENABLED=true tapi PLC_HOST kosong — PLC tidak dijalankan")
        return None

    _worker = PlcWorker(
        client=ModbusPlcClient(
            host=settings.plc_host,
            port=settings.plc_port,
            unit_id=settings.plc_unit_id,
        ),
        scheduler=PulseScheduler(
            pulse_s=settings.plc_pulse_ms / 1000.0,
            gap_s=settings.plc_pulse_gap_ms / 1000.0,
            queue_max=settings.plc_queue_max,
        ),
        settings=settings,
        health_check=health_check,
    )
    logger.info(
        "PLC aktif: %s:%s, coil OK/NG/ERROR = %s/%s/%s, alive = %s",
        settings.plc_host,
        settings.plc_port,
        settings.plc_coil_ok,
        settings.plc_coil_ng,
        settings.plc_coil_error,
        settings.plc_coil_alive or "(mati)",
    )
    return _worker


def submit_grading(status: str) -> None:
    """Kirim satu keputusan grading ('acc' / 'rej') ke PLC. No-op kalau PLC mati."""
    if _worker is not None:
        _worker.submit(status)


def inputs() -> list[bool]:
    """Snapshot discrete input terakhir dari PLC (motor fault + E-stop)."""
    return _worker.inputs if _worker is not None else []
```

- [ ] **Step 6: Buktikan permukaan publik aman saat PLC mati**

Tambahkan ke `tests/unit/plc/test_plc_worker.py`:

```python
class _OffCfg:
    plc_enabled = False
    plc_host = ""


class _NoHostCfg:
    plc_enabled = True
    plc_host = ""


def test_facade_is_noop_when_plc_disabled(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    assert plc.start_plc_worker(_OffCfg()) is None
    plc.submit_grading("rej")     # tidak boleh raise
    assert plc.inputs() == []


def test_enabled_without_host_refuses_to_start(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    assert plc.start_plc_worker(_NoHostCfg()) is None
```

Run: `python -m pytest tests/unit/plc/test_plc_worker.py -v`
Expected: PASS (8 test)

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/plc/ tests/unit/plc/test_plc_worker.py
git commit -m "feat(plc): PlcWorker untuk pulse coil, bit alive, dan baca discrete input"
```

---

### Task 5: Coil ERROR per line

Coil `base+2` adalah **level**, bukan pulse: ON selama line ini tidak sehat, OFF kalau sehat. Dua sumber ketidaksehatan: antrean pulse meluap, dan kamera terputus.

**Files:**
- Modify: `src/palmgrade/plc/worker.py`
- Modify: `tests/unit/plc/test_plc_worker.py`

**Interfaces:**
- Consumes: `PlcWorker` (Task 4), termasuk parameter `health_check` yang sudah ada di konstruktornya.
- Produces: perilaku baru pada coil `settings.plc_coil_error`.

Sumber flag kamera sudah diverifikasi ada: `camera.connected`, dipakai `services/health_service.py:40` untuk `/health/detail`. Task 6 yang mengopernya.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `tests/unit/plc/test_plc_worker.py`:

```python
def test_error_coil_raised_when_pulses_are_dropped():
    w, client = _worker()
    w.scheduler.queue_max = 1
    for _ in range(5):
        w.submit("rej")
    w.run_once(now=0.0)
    assert (5, True) in client.writes      # coil base+2 = 5


def test_error_coil_raised_when_health_check_says_unhealthy():
    w, client = _worker(health_check=lambda: False)
    w.run_once(now=0.0)
    assert (5, True) in client.writes


def test_error_coil_written_once_not_every_tick():
    w, client = _worker(health_check=lambda: True)
    w.run_once(now=0.0)
    w.run_once(now=0.2)
    w.run_once(now=0.4)
    assert [v for (addr, v) in client.writes if addr == 5] == [False]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/plc/test_plc_worker.py -v -k error_coil`
Expected: FAIL — coil 5 tidak pernah ditulis

- [ ] **Step 3: Implementasi**

Di akhir `PlcWorker.run_once`, setelah langkah 4:

```python
        # 5. Coil ERROR — level, bukan pulse. Ditulis hanya saat berubah supaya
        #    tidak membanjiri bus dengan nilai yang sama tiap 200 ms.
        desired = self._is_unhealthy()
        if desired != self._error_level:
            self.client.write_coil(self.settings.plc_coil_error, desired)
            self._error_level = desired
```

Dan methodnya:

```python
    def _is_unhealthy(self) -> bool:
        if self.scheduler.dropped:
            return True
        if self.health_check is not None:
            return not self.health_check()
        return False
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/plc/ -v`
Expected: PASS (semua test paket plc)

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/plc/worker.py tests/unit/plc/test_plc_worker.py
git commit -m "feat(plc): coil ERROR per line sebagai level, ditulis hanya saat berubah"
```

---

### Task 6: Sambungkan ke kode existing

Ini satu-satunya task yang menyentuh file di luar `plc/` dan `config.py`. Totalnya **empat baris**. Reviewer harus bisa menolak task ini tanpa membatalkan Task 1–5.

**Files:**
- Modify: `src/palmgrade/main.py` (blok import, dan setelah baris 157)
- Modify: `src/palmgrade/workers/frame_processing_worker.py` (blok import, dan setelah baris 265)

**Interfaces:**
- Consumes: `start_plc_worker`, `submit_grading` (Task 4).
- Produces: —

- [ ] **Step 1: Daftarkan worker di `main.py`**

Di blok import atas — perhatikan file ini memakai import **relatif**:

```python
from .plc import start_plc_worker
```

Lalu di dalam `lifespan`, tepat setelah baris 157 (`state.worker_threads.append(("outbox_retry", outbox_thread, outbox_worker))`):

```python
        # PLC — sinyal grading ke PLC lewat coupler ODOT (Modbus-TCP).
        # Mengembalikan None kalau PLC_ENABLED=false, jadi di cloud dan di PC
        # dev tidak ada thread tambahan sama sekali. Didaftarkan ke
        # worker_threads supaya ikut di-restart watchdog 10 detik kalau mati.
        if (plc_worker := start_plc_worker(settings, health_check=lambda: camera.connected)) is not None:
            state.worker_threads.append(("plc", _start_worker("plc", plc_worker.run_loop), plc_worker))
```

`settings` dan `camera` dua-duanya variabel level-modul (`main.py:79–103`), jadi keduanya terlihat dari dalam `lifespan` tanpa tambahan apa pun — persis seperti `camera` yang sudah dipakai `FrameCaptureWorker` di baris 120.

- [ ] **Step 2: Panggil dari titik keputusan grading**

Di `src/palmgrade/workers/frame_processing_worker.py`, blok import atas:

```python
from ..plc import submit_grading
```

Lalu tepat setelah baris 265 (`ripeness_conf = score`):

```python
                    ripeness_conf = score
                    submit_grading(ripeness_status)
```

`ripeness_status` diputuskan sekali per track (dijaga `_processed_objects`, Critical Rule #2), jadi satu buah = satu panggilan. Tidak ada risiko dobel-pulse untuk buah yang sama.

Taruh panggilan ini **sebelum** `self.pipeline.draw_boxes(...)` dan `_save_ripeness(...)` di baris 267–273: keduanya menyentuh disk dan CPU, dan sinyal ke PLC tidak boleh menunggu penyimpanan gambar.

- [ ] **Step 3: Buktikan perilaku existing tidak berubah saat PLC mati**

Run: `python -m pytest tests/ -q`
Expected: seluruh suite lulus, nol regresi. `PLC_ENABLED` tidak di-set di lingkungan test, jadi `submit_grading` adalah no-op dan `start_plc_worker` mengembalikan None.

- [ ] **Step 4: Buktikan aplikasi masih naik**

Run: `python -c "from palmgrade.main import create_app; create_app()"`
Expected: tidak ada exception (import baru tidak memecahkan urutan import)

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/main.py src/palmgrade/workers/frame_processing_worker.py
git commit -m "feat(plc): sambungkan keputusan grading dan lifespan ke paket plc"
```

---

### Task 7: Deployment, dokumentasi, CI

**Files:**
- Modify: `docker-compose.yml` (tiga service `ripe-line-1/2/3`)
- Create: `docs/plc-integration.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `CLAUDE.md`, `docs/backend-overview.md`

- [ ] **Step 1: Env per line di docker-compose**

Untuk tiap service (`ripe-line-1`, `ripe-line-2`, `ripe-line-3`), tambahkan ke blok `environment`. **Dua nilai berbeda per line:**

```yaml
      PLC_ENABLED: ${PLC_ENABLED:-false}
      PLC_HOST: ${PLC_HOST:-}
      PLC_PORT: ${PLC_PORT:-502}
      PLC_UNIT_ID: ${PLC_UNIT_ID:-1}
      PLC_COIL_BASE: "0"          # line-2 -> "3", line-3 -> "6"
      PLC_COIL_ALIVE: "9,10"      # line-2 -> "11", line-3 -> "12"
      PLC_PULSE_MS: ${PLC_PULSE_MS:-200}
      PLC_PULSE_GAP_MS: ${PLC_PULSE_GAP_MS:-100}
      PLC_QUEUE_MAX: ${PLC_QUEUE_MAX:-20}
      PLC_POLL_MS: ${PLC_POLL_MS:-200}
      PLC_DI_COUNT: ${PLC_DI_COUNT:-16}
```

`PLC_COIL_BASE` dan `PLC_COIL_ALIVE` sengaja literal, bukan dari env — angkanya properti fisik line itu, bukan setelan yang boleh berbeda antar PC. Line 1 memegang `9` (HEARTBEAT PC) di samping bit alive-nya sendiri.

- [ ] **Step 2: Perluas scope ruff**

Baris `ruff check` di `.github/workflows/ci.yml` saat ini persis:

```
run: ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ src/palmgrade/license/ src/palmgrade/workers/batch_upload_worker.py
```

Sisipkan `src/palmgrade/plc/` di daftar itu (satu path menutupi seluruh fitur — keuntungan langsung dari menaruhnya di satu paket):

```
run: ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ src/palmgrade/license/ src/palmgrade/plc/ src/palmgrade/workers/batch_upload_worker.py
```

Perbarui juga komentar di atasnya (baris "Lint hanya modul yang sudah bersih...") supaya menyebut `plc`.

Run: `ruff check src/palmgrade/plc/ tests/unit/plc/`
Expected: `All checks passed!`

- [ ] **Step 3: Tulis `docs/plc-integration.md`**

Ini menggantikan PDF yang tidak ada di repo. Tabel alamatnya disalin apa adanya:

```markdown
### Coil / DO — vision menulis (zero-based)

| Coil  | Alamat PLC  | Arti         | Ditulis oleh |
| ----- | ----------- | ------------ | ------------ |
| 0     | X0300       | CAM 1 OK     | line 1       |
| 1     | X0301       | CAM 1 NG     | line 1       |
| 2     | X0302       | CAM 1 ERROR  | line 1       |
| 3     | X0303       | CAM 2 OK     | line 2       |
| 4     | X0304       | CAM 2 NG     | line 2       |
| 5     | X0305       | CAM 2 ERROR  | line 2       |
| 6     | X0306       | CAM 3 OK     | line 3       |
| 7     | X0307       | CAM 3 NG     | line 3       |
| 8     | X0308       | CAM 3 ERROR  | line 3       |
| 9     | X0309       | HEARTBEAT PC | line 1       |
| 10    | X030A       | LINE 1 ALIVE | line 1       |
| 11    | X030B       | LINE 2 ALIVE | line 2       |
| 12    | X030C       | LINE 3 ALIVE | line 3       |
| 13–15 | X030D–X030F | SPARE        | —            |

### Discrete input / DI — vision membaca (zero-based)

| DI    | Alamat PLC  | Arti             |
| ----- | ----------- | ---------------- |
| 0–9   | Y0310–Y0319 | MOTOR 1–10 FAULT |
| 10    | Y031A       | EMERGENCY STOP   |
| 11–15 | Y031B–Y031F | SPARE            |
```

Selain tabel di atas, dokumen wajib memuat:
- Part number hardware: CN-8031, CT-222F, CT-122F, CT-5801, AJ65SBTB1-16D1, AJ65SBTB1-16T1.
- Catatan sink/source: CT-222F source/PNP → 16D1 dengan COM di 0V; 16T1 sink (COM di 0V) → CT-122F low-aktif. Cocok, tanpa relay.
- Tabel env `PLC_*` dengan arti dan nilai per line.
- Matematika throughput: `1 / (pulse_s + gap_s)` sinyal per detik per coil, dan apa yang terjadi saat meluap (drop + coil ERROR naik).
- Peta paket `src/palmgrade/plc/` — file apa bertanggung jawab atas apa, dan bahwa kode luar hanya boleh menyentuh `start_plc_worker` / `submit_grading` / `inputs`.
- Bagian "Belum diputuskan" yang menyalin Task 0.

- [ ] **Step 4: Perbarui `CLAUDE.md`**

- § Project Structure — tambahkan `plc/` sebagai entri setara `workers/` dan `domain/`, satu kalimat: seluruh integrasi PLC terkurung di sana, permukaannya 3 fungsi.
- § Tech Stack — tambahkan `pymodbus`.
- § Run/Build/Test — di baris Lint, tambahkan `plc/` ke daftar scope ruff.
- § Pointers — tambahkan `docs/plc-integration.md`.

- [ ] **Step 5: Perbarui `docs/backend-overview.md`**

Tambahkan semua env `PLC_*` ke tabel env var, dengan default dan nilai per line.

- [ ] **Step 6: Verifikasi seluruh gate**

Run: `python -m pytest tests/ -q && ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ src/palmgrade/license/ src/palmgrade/plc/ src/palmgrade/workers/batch_upload_worker.py`
Expected: semua test lulus, `All checks passed!`

- [ ] **Step 7: Commit dan buka PR**

```bash
git add docker-compose.yml docs/plc-integration.md .github/workflows/ci.yml CLAUDE.md docs/backend-overview.md
git commit -m "docs(plc): coil map, env per line, dan scope lint"
git push -u origin feat/plc-modbus-integration
gh pr create --base staging \
  --title "feat: integrasi PLC lewat ODOT CN-8031 (Modbus-TCP)" \
  --body "$(cat <<'EOF'
Vision mengirim hasil grading tiap line (ACC/REJ/ERROR) ke PLC Mitsubishi lewat
remote IO ODOT CN-8031 via Modbus-TCP, dan membaca balik motor fault + E-stop.

Seluruh logika terkurung di paket baru `src/palmgrade/plc/`. Jejak di kode yang
sudah jalan totalnya empat baris, di luar satu blok env di `core/config.py`:

- `main.py` — 1 import + 2 baris pendaftaran worker
- `frame_processing_worker.py` — 1 import + 1 panggilan `submit_grading()`

Mati secara default (`PLC_ENABLED=false`): `start_plc_worker()` mengembalikan
None, tidak ada thread yang jalan, dan `submit_grading()` langsung return.
Perilaku cloud dan PC dev tidak berubah sama sekali.

Lebar pulse dan jeda berupa env var supaya bisa dikalibrasi di lapangan tanpa
rebuild. Coil map lengkap ada di `docs/plc-integration.md`.

Nol perubahan di palmgrade-api dan palmgrade-frontend.
EOF
)"
```

---

### Task 8: Commissioning di lapangan

Dikerjakan di PC pabrik dengan hardware terpasang, setelah PR merge dan image rilis. Tidak ada test otomatis yang bisa menggantikan langkah-langkah ini.

- [ ] **Step 1: Konfirmasi offset alamat di hardware sebelum apa pun disambungkan**

Pakai tool konfigurasi ODOT, paksa coil `0` jadi ON. LED **DO00** pada CT-222F harus menyala. Kalau yang menyala DO01, seluruh peta bergeser satu dan `PLC_COIL_BASE` harus disesuaikan. Lima menit, dan menutup satu-satunya keraguan yang tersisa soal alamat — jawaban tertulis pak Ocit di Task 0 Step 1 tidak menggantikan tes ini.

- [ ] **Step 2: Uji satu kanal sebelum 16 kanal**

Sambungkan DO00 → X0300 saja. Paksa ON, pastikan PLC melihatnya. Baru kabelkan sisanya.

- [ ] **Step 3: Rilis image dan isi `.env` PC pabrik**

Tag rilis vision (`vX.Y.Z`) lewat GitHub Actions, pull di PC pabrik. Lalu di `.env`: `PLC_ENABLED=true` dan `PLC_HOST=<ip ODOT dari Task 0 Step 6>`.

Karena `COPY . .` di `Dockerfile:73` ada **setelah** `pip install` di baris 71, perubahan kode PLC berikutnya hanya menginvalidasi layer source — pull-nya beberapa MB, bukan 10,3 GB. Yang sekali mahal cuma rilis pertama ini, karena `pymodbus` mengubah `requirements.txt`.

- [ ] **Step 4: Verifikasi bit alive dari sisi PLC**

Jalankan `make restart`. Coil 9, 10, 11, 12 harus toggle tiap detik. Matikan container line 2 — coil 11 harus berhenti toggle dalam 3 detik, sementara 9, 10, dan 12 jalan terus. Ini yang membuktikan PLC bisa melihat satu line mati sendirian.

- [ ] **Step 5: Verifikasi watchdog**

Cabut kabel LAN ke ODOT. Semua coil kita harus jatuh ke 0 dalam waktu watchdog. **Kalau masih 30 detik, ini gagal** — kembali ke Task 0 Step 3.

- [ ] **Step 6: Verifikasi polaritas E-stop**

Baca `inputs()[10]` saat kondisi normal. Kalau permintaan NC di Task 0 Step 4 sudah dikerjakan, bit ini harus **ON** saat normal dan OFF saat E-stop ditekan. Kalau masih terbalik, catat sebagai risiko terbuka — jangan diam-diam dikompensasi di kode kita, karena kabel putus tetap akan terbaca "aman".

- [ ] **Step 7: Kalibrasi lebar pulse dengan buah asli**

Jalankan conveyor pada kecepatan produksi. Hitung berapa sinyal yang dilihat PLC vs berapa buah yang lewat. Naikkan `PLC_PULSE_MS` kalau PLC melewatkan sinyal; turunkan `PLC_PULSE_MS` + `PLC_PULSE_GAP_MS` kalau antrean meluap (coil ERROR naik dan log memuat "Antrean pulse PLC penuh"). Tidak perlu rebuild — cukup ubah `.env` lalu `make restart`.

---

## Catatan Eksekusi

- **Task 0 jalan paralel dan mulai hari ini.** Isinya kerja orang lain (ladder + panel), jadi itu yang paling mungkin jadi jalur kritis. Task 1–7 tidak menunggunya.
- **Task 1–5 tidak menyentuh alur yang sudah jalan.** `config.py` cuma dapat blok field inert. Kalau semuanya berhenti di situ, repo tetap berperilaku persis seperti sekarang.
- **Task 6 adalah satu-satunya titik risiko regresi**, dan isinya empat baris. Kalau ada yang aneh, membatalkannya cukup `git revert` satu commit.
- **Kalau jawaban pulse di Task 0 Step 2 berubah total** (misalnya "level, bukan pulse"), yang berubah cuma `plc/pulse.py` plus testnya.
- **`palmgrade-api` dan `palmgrade-frontend` nol perubahan.** Tidak ada migrasi SQL, tidak ada rilis terkoordinasi. Deploy = tag vision + pull + `make restart` di PC pabrik.
