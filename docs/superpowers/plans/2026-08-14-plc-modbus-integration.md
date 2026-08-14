# PLC Modbus Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kirim hasil grading tiap line (ACC / REJ / ERROR) dari `palmgrade-vision` ke PLC Mitsubishi lewat remote IO ODOT CN-8031 via Modbus-TCP, plus baca status motor/E-stop balik dari PLC.

**Architecture:** Tiap container line konek sendiri sebagai Modbus-TCP **client** ke CN-8031 (coupler support 5 client bareng, kita pakai 3). `FrameProcessingWorker` cuma **enqueue** hasil ke `state.plc_queue` — tidak pernah menyentuh socket, sesuai Critical Rule #1 repo ini. Sebuah `PlcWorker` thread yang menguras antrean itu, menerjemahkannya jadi pulse coil lewat `PulseScheduler` (murni logika, di `domain/`), meng-toggle bit alive, dan polling discrete input. Semua nomor coil, lebar pulse, dan host berasal dari env — nol angka hardcoded.

**Tech Stack:** Python 3.11, `pymodbus` (baru), dataclass murni untuk scheduler, pytest.

**Spec:** Tidak ada dokumen spec formal. Sumber kebenarannya adalah skematik PDF *"REMOTE IO — CONVEYOR SAWIT"* (DW.26/07/27 hal. 19–20, PT Nexio Teknologi Otomasi) plus percakapan WhatsApp dengan pak Ocit. **PDF itu tidak ada di repo** — semua fakta yang mengikat sudah disalin ke `## Global Constraints` di bawah, dan Task 7 memasukkannya ke `docs/plc-integration.md` supaya berhenti jadi pengetahuan lisan.

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
- **Repo rule:** semua env var baru dideklarasikan di `core/config.py` (`Settings`, `@dataclass(frozen=True)`, pola `field(default_factory=lambda: os.getenv(...))`). Jangan pernah `os.getenv` di luar file itu.
- **Repo rule:** `domain/` = logika murni tanpa I/O. Scheduler pulse wajib tinggal di sana supaya bisa dites tanpa hardware maupun pymodbus.
- **Branch:** dari `staging`, PR-only. Commit message **tidak boleh** menyebut Claude / AI.

**Belum diputuskan (lihat Task 8):** lebar pulse, jeda antar pulse, dan apakah 1 sinyal = 1 buah. Semuanya sudah jadi env var dengan default yang masuk akal, jadi bukan blocker — tapi harus dikonfirmasi sebelum commissioning.

---

### Task 1: Konfigurasi PLC di Settings

Semua task berikutnya membaca dari sini, jadi ini duluan.

**Files:**
- Modify: `src/palmgrade/core/config.py`
- Modify: `.env.example`
- Test: `tests/unit/test_plc_config.py`

**Interfaces:**
- Consumes: —
- Produces: `Settings.plc_enabled: bool`, `Settings.plc_host: str`, `Settings.plc_port: int`, `Settings.plc_unit_id: int`, `Settings.plc_coil_base: int`, `Settings.plc_coil_alive: tuple[int, ...]`, `Settings.plc_pulse_ms: int`, `Settings.plc_pulse_gap_ms: int`, `Settings.plc_queue_max: int`, `Settings.plc_poll_ms: int`, `Settings.plc_di_count: int`, dan property `Settings.plc_coil_ok / plc_coil_ng / plc_coil_error -> int`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tests/unit/test_plc_config.py
import os
import pytest
from palmgrade.core.config import Settings, parse_coil_list


def test_coil_offsets_derive_from_base():
    os.environ["PLC_COIL_BASE"] = "3"
    s = Settings()
    assert (s.plc_coil_ok, s.plc_coil_ng, s.plc_coil_error) == (3, 4, 5)
    del os.environ["PLC_COIL_BASE"]


def test_plc_disabled_by_default():
    assert Settings().plc_enabled is False


def test_parse_coil_list_handles_blank_and_spaces():
    assert parse_coil_list("") == ()
    assert parse_coil_list(" 9 , 10 ") == (9, 10)
    assert parse_coil_list("12") == (12,)


def test_parse_coil_list_rejects_garbage():
    with pytest.raises(ValueError):
        parse_coil_list("9,abc")
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd palmgrade-vision && python -m pytest tests/unit/test_plc_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_coil_list'`

- [ ] **Step 3: Implementasi**

Di `src/palmgrade/core/config.py`, tambahkan helper di dekat `_as_bool`:

```python
def parse_coil_list(value: str | None) -> tuple[int, ...]:
    """'9,10' -> (9, 10). String kosong -> (). Raise ValueError kalau ada yang bukan angka."""
    if not value or not value.strip():
        return ()
    return tuple(int(part.strip()) for part in value.split(","))
```

Lalu tambahkan blok field di dalam `class Settings`, setelah blok upload/R2:

```python
    # ── PLC / ODOT CN-8031 (Modbus-TCP) ──────────────────────────
    # Coil map lengkap: docs/plc-integration.md. plc_coil_base = 0/3/6 per line,
    # di-set docker-compose. plc_coil_alive = bit "line ini hidup" yang di-toggle
    # PlcWorker; kosong = fitur mati.
    plc_enabled: bool = field(default_factory=lambda: _as_bool(os.getenv("PLC_ENABLED"), False))
    plc_host: str = field(default_factory=lambda: os.getenv("PLC_HOST", ""))
    plc_port: int = field(default_factory=lambda: int(os.getenv("PLC_PORT", "502")))
    plc_unit_id: int = field(default_factory=lambda: int(os.getenv("PLC_UNIT_ID", "1")))
    plc_coil_base: int = field(default_factory=lambda: int(os.getenv("PLC_COIL_BASE", "0")))
    plc_coil_alive: tuple[int, ...] = field(
        default_factory=lambda: parse_coil_list(os.getenv("PLC_COIL_ALIVE"))
    )
    plc_pulse_ms: int = field(default_factory=lambda: int(os.getenv("PLC_PULSE_MS", "200")))
    plc_pulse_gap_ms: int = field(default_factory=lambda: int(os.getenv("PLC_PULSE_GAP_MS", "100")))
    plc_queue_max: int = field(default_factory=lambda: int(os.getenv("PLC_QUEUE_MAX", "20")))
    plc_poll_ms: int = field(default_factory=lambda: int(os.getenv("PLC_POLL_MS", "200")))
    plc_di_count: int = field(default_factory=lambda: int(os.getenv("PLC_DI_COUNT", "16")))
```

Dan property-nya, di bawah property `backend_*` yang sudah ada:

```python
    @property
    def plc_coil_ok(self) -> int:
        return self.plc_coil_base + 0

    @property
    def plc_coil_ng(self) -> int:
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self) -> int:
        return self.plc_coil_base + 2
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/test_plc_config.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Dokumentasikan di `.env.example`**

Tambahkan blok berikut di akhir `.env.example`:

```bash
# ── PLC / ODOT CN-8031 (Modbus-TCP) ──────────────────────────
# Mati secara default. Cuma PC pabrik yang menyalakan ini.
PLC_ENABLED=false
PLC_HOST=
PLC_PORT=502
PLC_UNIT_ID=1
# Line 1 = 0, line 2 = 3, line 3 = 6 (di-set docker-compose, bukan di sini)
PLC_COIL_BASE=0
# Bit "line ini hidup" yang di-toggle tiap detik. Kosong = mati.
PLC_COIL_ALIVE=
# Lebar pulse OK/NG dan jeda WAJIB di antara dua pulse pada coil yang sama.
# BELUM dikonfirmasi engineer PLC — lihat docs/plc-integration.md.
PLC_PULSE_MS=200
PLC_PULSE_GAP_MS=100
PLC_QUEUE_MAX=20
PLC_POLL_MS=200
PLC_DI_COUNT=16
```

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/core/config.py .env.example tests/unit/test_plc_config.py
git commit -m "feat(plc): tambah konfigurasi Modbus/ODOT di Settings"
```

---

### Task 2: PulseScheduler — logika murni

Ini inti fiturnya, dan satu-satunya bagian yang berubah kalau pak Ocit menjawab pertanyaan pulse. Sengaja dipisah supaya jawabannya cuma menyentuh satu file.

**Files:**
- Create: `src/palmgrade/domain/plc_pulse.py`
- Test: `tests/unit/test_plc_pulse.py`

**Interfaces:**
- Consumes: nilai `plc_pulse_ms` / `plc_pulse_gap_ms` / `plc_queue_max` dari Task 1.
- Produces: `PulseScheduler(pulse_s: float, gap_s: float, queue_max: int)` dengan method `enqueue(coil: int) -> bool`, `tick(now: float) -> dict[int, bool]`, dan atribut `dropped: int`.

**Kenapa ini rumit:** dua pulse pada coil yang **sama** tidak boleh menyatu jadi satu sinyal panjang — PLC menghitung tepi naik, jadi dua buah REJ berturut-turut yang menyatu akan terhitung satu. Scheduler menjamin selalu ada periode OFF minimal `gap_s` di antara dua pulse pada coil yang sama. Konsekuensinya throughput per coil dibatasi `1 / (pulse_s + gap_s)` — dengan default 200 ms + 100 ms cuma ~3,3 sinyal/detik, sementara YOLO bisa memutuskan jauh lebih cepat. Kalau antrean penuh, item **dibuang dan dihitung**, bukan ditunda: sinyal yang telat akan menempel pada buah yang salah, dan itu lebih berbahaya daripada sinyal yang hilang.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tests/unit/test_plc_pulse.py
import pytest
from palmgrade.domain.plc_pulse import PulseScheduler


def _sched(pulse=0.2, gap=0.1, queue_max=20):
    return PulseScheduler(pulse_s=pulse, gap_s=gap, queue_max=queue_max)


def test_gap_must_be_positive():
    # gap 0 akan membuat OFF dan ON terjadi pada tick yang sama -> PLC tak pernah
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

Run: `python -m pytest tests/unit/test_plc_pulse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.domain.plc_pulse'`

- [ ] **Step 3: Implementasi**

```python
# src/palmgrade/domain/plc_pulse.py
"""Penjadwal pulse coil — logika murni, tanpa I/O.

Menerjemahkan "satu keputusan grading" jadi satu pulse ON/OFF pada satu coil,
dengan jaminan ada jeda OFF di antara dua pulse pada coil yang sama supaya PLC
selalu melihat tepi naik yang terpisah.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _CoilState:
    on_until: float = 0.0   # waktu monotonic saat pulse aktif harus dimatikan; 0 = sedang OFF
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
            raise ValueError("gap_s harus > 0 — tanpa jeda, dua pulse menyatu dan PLC menghitungnya satu")

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

Run: `python -m pytest tests/unit/test_plc_pulse.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Lint**

Run: `ruff check src/palmgrade/domain/plc_pulse.py tests/unit/test_plc_pulse.py`
Expected: `All checks passed!` (`domain/` sudah masuk scope ruff CI)

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/domain/plc_pulse.py tests/unit/test_plc_pulse.py
git commit -m "feat(plc): penjadwal pulse coil dengan jaminan jeda antar pulse"
```

---

### Task 3: Klien Modbus

**Files:**
- Create: `src/palmgrade/integrations/plc/__init__.py`
- Create: `src/palmgrade/integrations/plc/modbus_client.py`
- Modify: `requirements.txt`
- Test: `tests/unit/test_modbus_client.py`

**Interfaces:**
- Consumes: —
- Produces: `ModbusPlcClient(host: str, port: int, unit_id: int)` dengan `write_coil(address: int, value: bool) -> bool`, `read_discrete_inputs(start: int, count: int) -> list[bool] | None`, `close() -> None`, dan atribut `connected: bool`.

**Kenapa pymodbus dan bukan socket mentah:** permukaan yang kita pakai memang cuma dua function code, tapi bagian yang bikin repot bukan framingnya — melainkan pencocokan transaction id, frame yang terbelah di beberapa segmen TCP, dan reconnect. Itu justru kelas bug yang muncul jam 3 pagi di pabrik. pymodbus murni-python dan ringan, jadi CI tidak jadi berat. **Seluruh sentuhan API pymodbus dikurung di file ini** — kalau versinya berganti, cuma satu file yang perlu disesuaikan.

- [ ] **Step 1: Tambahkan dependency**

Di `requirements.txt`, di bawah blok HTTP Client:

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
# tests/unit/test_modbus_client.py
from palmgrade.integrations.plc.modbus_client import ModbusPlcClient


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


class _FakeReply:
    def __init__(self, error, bits=None):
        self._error = error
        self.bits = bits or []

    def isError(self):
        return self._error


def test_write_coil_forwards_address_and_value():
    inner = _FakeInner()
    c = ModbusPlcClient(host="1.2.3.4", port=502, unit_id=1, _client_factory=lambda: inner)
    assert c.write_coil(4, True) is True
    assert inner.writes == [(4, True)]


def test_write_coil_returns_false_on_exception_instead_of_raising():
    # Worker loop tidak boleh mati gara-gara kabel dicabut.
    inner = _FakeInner(raises=True)
    c = ModbusPlcClient(host="1.2.3.4", port=502, unit_id=1, _client_factory=lambda: inner)
    assert c.write_coil(4, True) is False
    assert c.connected is False


def test_read_discrete_inputs_returns_exactly_count_bits():
    inner = _FakeInner()
    c = ModbusPlcClient(host="1.2.3.4", port=502, unit_id=1, _client_factory=lambda: inner)
    assert c.read_discrete_inputs(0, 16) == [True] + [False] * 15


def test_failed_connect_reports_disconnected():
    inner = _FakeInner(connect_ok=False)
    c = ModbusPlcClient(host="1.2.3.4", port=502, unit_id=1, _client_factory=lambda: inner)
    assert c.write_coil(0, True) is False
    assert c.connected is False
```

- [ ] **Step 4: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/test_modbus_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.integrations.plc'`

- [ ] **Step 5: Implementasi**

```python
# src/palmgrade/integrations/plc/__init__.py
from palmgrade.integrations.plc.modbus_client import ModbusPlcClient

__all__ = ["ModbusPlcClient"]
```

```python
# src/palmgrade/integrations/plc/modbus_client.py
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

Run: `python -m pytest tests/unit/test_modbus_client.py -v`
Expected: PASS (4 test)

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/integrations/plc/ tests/unit/test_modbus_client.py requirements.txt
git commit -m "feat(plc): klien Modbus-TCP untuk coupler ODOT CN-8031"
```

---

### Task 4: PlcWorker + RuntimeState

**Files:**
- Create: `src/palmgrade/workers/plc_worker.py`
- Modify: `src/palmgrade/workers/runtime_state.py:18` (setelah `event_queue`)
- Modify: `src/palmgrade/main.py:136-140` (daftar `worker_threads`)
- Test: `tests/unit/test_plc_worker.py`

**Interfaces:**
- Consumes: `PulseScheduler` (Task 2), `ModbusPlcClient` (Task 3), field `Settings.plc_*` (Task 1).
- Produces: `PlcWorker(client, scheduler, state, settings)` dengan `run_once() -> None` dan `run_loop() -> None`; `RuntimeState.plc_queue: Queue[str]` dan `RuntimeState.plc_inputs: list[bool]`.

- [ ] **Step 1: Tambahkan field ke RuntimeState**

Di `src/palmgrade/workers/runtime_state.py`, tepat di bawah `event_queue` (baris 18):

```python
    # Keputusan grading yang menunggu dikirim ke PLC. Isinya "acc" / "rej".
    # FrameProcessingWorker cuma put_nowait ke sini — dia tidak pernah menyentuh socket.
    plc_queue: Queue[str] = field(default_factory=lambda: Queue(maxsize=50))
    # Snapshot discrete input terakhir dari PLC (motor fault + E-stop). Ditulis PlcWorker.
    plc_inputs: list[bool] = field(default_factory=list)
```

- [ ] **Step 2: Tulis test yang gagal**

```python
# tests/unit/test_plc_worker.py
from queue import Queue

from palmgrade.domain.plc_pulse import PulseScheduler
from palmgrade.workers.plc_worker import PlcWorker


class _FakeClient:
    def __init__(self):
        self.writes: list[tuple[int, bool]] = []
        self.connected = True
        self.di = [False] * 16

    def write_coil(self, address, value):
        self.writes.append((address, value))
        return True

    def read_discrete_inputs(self, start, count):
        return self.di[start:start + count]


class _FakeState:
    def __init__(self):
        self.plc_queue = Queue(maxsize=50)
        self.plc_inputs = []


class _Cfg:
    plc_coil_base = 3
    plc_coil_alive = (11,)
    plc_pulse_ms = 200
    plc_pulse_gap_ms = 100
    plc_queue_max = 20
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


def _worker():
    state, client = _FakeState(), _FakeClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        state=state,
        settings=_Cfg(),
    )
    return w, state, client


def test_acc_maps_to_ok_coil_of_this_line():
    w, state, client = _worker()
    state.plc_queue.put("acc")
    w.run_once(now=0.0)
    assert (3, True) in client.writes


def test_rej_maps_to_ng_coil_of_this_line():
    w, state, client = _worker()
    state.plc_queue.put("rej")
    w.run_once(now=0.0)
    assert (4, True) in client.writes


def test_alive_coil_toggles_between_ticks():
    w, _, client = _worker()
    w.run_once(now=0.0)
    w.run_once(now=1.0)
    w.run_once(now=2.0)
    alive = [v for (addr, v) in client.writes if addr == 11]
    assert alive == [True, False, True]


def test_discrete_inputs_are_snapshotted_into_state():
    w, state, client = _worker()
    client.di[10] = True          # EMERGENCY STOP
    w.run_once(now=0.0)
    assert state.plc_inputs[10] is True


def test_unknown_status_is_ignored_not_crashed():
    w, state, client = _worker()
    state.plc_queue.put("tp")
    w.run_once(now=0.0)
    assert all(addr not in (3, 4) for (addr, _) in client.writes)
```

- [ ] **Step 3: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/test_plc_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'palmgrade.workers.plc_worker'`

- [ ] **Step 4: Implementasi**

```python
# src/palmgrade/workers/plc_worker.py
"""Worker yang bicara ke coupler ODOT CN-8031.

Satu-satunya thread yang menyentuh socket Modbus. Tugasnya empat:
menguras state.plc_queue jadi pulse coil, meng-toggle bit alive line ini,
memantulkan discrete input PLC ke state, dan — sebagai efek samping dari
polling reguler — menahan watchdog ODOT supaya tidak mereset output.
"""

from __future__ import annotations

import logging
import queue
import time

logger = logging.getLogger(__name__)


class PlcWorker:
    def __init__(self, client, scheduler, state, settings) -> None:
        self.client = client
        self.scheduler = scheduler
        self.state = state
        self.settings = settings
        self._alive_level = False
        self._next_alive_toggle = 0.0

    def run_once(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now

        # 1. Antrean keputusan -> pulse terjadwal
        while True:
            try:
                status = self.state.plc_queue.get_nowait()
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
            self.state.plc_inputs = bits

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

- [ ] **Step 5: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/test_plc_worker.py -v`
Expected: PASS (5 test)

- [ ] **Step 6: Daftarkan di lifespan**

Di `src/palmgrade/main.py`, tepat setelah blok `outbox_worker` (setelah baris 157):

```python
        # PlcWorker — sinyal grading ke PLC lewat coupler ODOT (Modbus-TCP).
        # Mati secara default; cuma PC pabrik yang menyalakan PLC_ENABLED.
        if settings.plc_enabled and settings.plc_host:
            plc_worker = PlcWorker(
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
                state=state,
                settings=settings,
            )
            plc_thread = _start_worker("plc", plc_worker.run_loop)
            state.worker_threads.append(("plc", plc_thread, plc_worker))
        elif settings.plc_enabled:
            logger.warning("PLC_ENABLED=true tapi PLC_HOST kosong — PlcWorker tidak dijalankan")
```

Tambahkan importnya di blok import atas `main.py` — perhatikan file ini memakai import **relatif**, bukan absolut:

```python
from .domain.plc_pulse import PulseScheduler
from .integrations.plc import ModbusPlcClient
from .workers.plc_worker import PlcWorker
```

Karena worker didaftarkan ke `state.worker_threads`, watchdog 10 detik yang sudah ada otomatis merestart thread ini kalau mati.

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/workers/plc_worker.py src/palmgrade/workers/runtime_state.py src/palmgrade/main.py tests/unit/test_plc_worker.py
git commit -m "feat(plc): PlcWorker untuk pulse coil, bit alive, dan baca discrete input"
```

---

### Task 5: Sambungkan keputusan grading

**Files:**
- Modify: `src/palmgrade/workers/frame_processing_worker.py:262-265`
- Test: `tests/unit/test_plc_enqueue.py`

**Interfaces:**
- Consumes: `RuntimeState.plc_queue` (Task 4).
- Produces: —

`ripeness_status` diputuskan sekali per track (dijaga `_processed_objects`, Critical Rule #2), jadi satu buah = satu enqueue. Tidak ada risiko dobel-pulse untuk buah yang sama.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tests/unit/test_plc_enqueue.py
import queue

from palmgrade.workers.frame_processing_worker import enqueue_plc_status


def test_enqueue_puts_status_on_queue():
    q = queue.Queue(maxsize=2)
    enqueue_plc_status(q, "rej")
    assert q.get_nowait() == "rej"


def test_enqueue_drops_silently_when_full():
    # Thread deteksi tidak boleh blocking, apa pun keadaan antreannya.
    q = queue.Queue(maxsize=1)
    enqueue_plc_status(q, "acc")
    enqueue_plc_status(q, "acc")   # tidak boleh raise, tidak boleh menggantung
    assert q.qsize() == 1
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/test_plc_enqueue.py -v`
Expected: FAIL — `ImportError: cannot import name 'enqueue_plc_status'`

- [ ] **Step 3: Implementasi**

Di `src/palmgrade/workers/frame_processing_worker.py`, tambahkan fungsi modul-level di dekat import atas:

```python
def enqueue_plc_status(plc_queue, ripeness_status: str) -> None:
    """Kirim keputusan grading ke PlcWorker. Tidak pernah blocking, tidak pernah raise.

    Antrean penuh berarti PLC tidak sanggup mengejar; membuang di sini lebih baik
    daripada menahan thread deteksi.
    """
    try:
        plc_queue.put_nowait(ripeness_status)
    except queue.Full:
        pass
```

Lalu di baris 262-265, tepat setelah `ripeness_conf = score`:

```python
                    ripeness_conf = score
                    enqueue_plc_status(self.state.plc_queue, ripeness_status)
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/test_plc_enqueue.py -v`
Expected: PASS (2 test)

- [ ] **Step 5: Jalankan seluruh suite — pastikan tidak ada yang rusak**

Run: `python -m pytest tests/unit/ -q`
Expected: semua lulus, tidak ada regresi

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/workers/frame_processing_worker.py tests/unit/test_plc_enqueue.py
git commit -m "feat(plc): kirim keputusan grading ke antrean PLC"
```

---

### Task 6: Coil ERROR per line

Coil `base+2` adalah **level**, bukan pulse: ON selama line ini tidak sehat, OFF kalau sehat. Sumber ketidaksehatan yang benar-benar kita tahu: kamera terputus, dan antrean pulse meluap.

**Files:**
- Modify: `src/palmgrade/workers/plc_worker.py`
- Test: `tests/unit/test_plc_worker.py` (tambah case)

**Interfaces:**
- Consumes: `PlcWorker` (Task 4).
- Produces: perilaku baru pada coil `settings.plc_coil_error`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `tests/unit/test_plc_worker.py`:

```python
def test_error_coil_raised_when_pulses_are_dropped():
    w, state, client = _worker()
    w.scheduler.queue_max = 1
    for _ in range(5):
        state.plc_queue.put("rej")
    w.run_once(now=0.0)
    assert (5, True) in client.writes      # coil base+2 = 5


def test_error_coil_written_once_not_every_tick():
    w, state, client = _worker()
    w.run_once(now=0.0)
    w.run_once(now=0.2)
    w.run_once(now=0.4)
    assert [v for (addr, v) in client.writes if addr == 5] == [False]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `python -m pytest tests/unit/test_plc_worker.py -v -k error_coil`
Expected: FAIL — coil 5 tidak pernah ditulis

- [ ] **Step 3: Implementasi**

Di `PlcWorker.__init__` tambahkan:

```python
        self._error_level: bool | None = None   # None = belum pernah ditulis
```

Di akhir `run_once`, setelah langkah 4:

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
        return getattr(self.state, "camera_connected", True) is False
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `python -m pytest tests/unit/test_plc_worker.py -v`
Expected: PASS (7 test)

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/workers/plc_worker.py tests/unit/test_plc_worker.py
git commit -m "feat(plc): coil ERROR per line sebagai level, ditulis hanya saat berubah"
```

---

### Task 7: Deployment, dokumentasi, CI

**Files:**
- Modify: `docker-compose.yml` (tiga blok service line)
- Create: `docs/plc-integration.md`
- Modify: `.github/workflows/ci.yml:34`
- Modify: `CLAUDE.md`
- Modify: `docs/backend-overview.md`

- [ ] **Step 1: Env per line di docker-compose**

Untuk tiap service line, tambahkan ke blok `environment` (nilai `PLC_COIL_BASE` **berbeda per line**):

```yaml
      PLC_ENABLED: ${PLC_ENABLED:-false}
      PLC_HOST: ${PLC_HOST:-}
      PLC_PORT: ${PLC_PORT:-502}
      PLC_UNIT_ID: ${PLC_UNIT_ID:-1}
      PLC_COIL_BASE: "0"        # line-2 -> "3", line-3 -> "6"
      PLC_COIL_ALIVE: ${LINE_1_PLC_COIL_ALIVE:-}   # line-2 -> LINE_2_..., line-3 -> LINE_3_...
      PLC_PULSE_MS: ${PLC_PULSE_MS:-200}
      PLC_PULSE_GAP_MS: ${PLC_PULSE_GAP_MS:-100}
      PLC_QUEUE_MAX: ${PLC_QUEUE_MAX:-20}
      PLC_POLL_MS: ${PLC_POLL_MS:-200}
      PLC_DI_COUNT: ${PLC_DI_COUNT:-16}
```

`PLC_COIL_BASE` sengaja literal, bukan dari env — angkanya properti fisik line itu, bukan setelan yang boleh berbeda antar PC.

- [ ] **Step 2: Perluas scope ruff**

Ruff di repo ini di-scope ke daftar path eksplisit, bukan seluruh `src/`. Baca dulu barisnya supaya tidak ada path lama yang hilang:

Run: `sed -n '30,40p' .github/workflows/ci.yml`

Di baris `ruff check ...` itu, **sisipkan dua path baru** dan biarkan sisanya persis apa adanya:

```
src/palmgrade/integrations/plc/ src/palmgrade/workers/plc_worker.py
```

`src/palmgrade/domain/` sudah ada di daftar, jadi `plc_pulse.py` otomatis tercakup.

- [ ] **Step 3: Tulis `docs/plc-integration.md`**

Ini menggantikan PDF yang tidak ada di repo. Tabel alamatnya disalin apa adanya:

```markdown
### Coil / DO — vision menulis (zero-based)

| Coil | Alamat PLC | Arti          |
| ---- | ---------- | ------------- |
| 0    | X0300      | CAM 1 OK      |
| 1    | X0301      | CAM 1 NG      |
| 2    | X0302      | CAM 1 ERROR   |
| 3    | X0303      | CAM 2 OK      |
| 4    | X0304      | CAM 2 NG      |
| 5    | X0305      | CAM 2 ERROR   |
| 6    | X0306      | CAM 3 OK      |
| 7    | X0307      | CAM 3 NG      |
| 8    | X0308      | CAM 3 ERROR   |
| 9    | X0309      | HEARTBEAT PC  |
| 10–15| X030A–X030F| SPARE         |

### Discrete input / DI — vision membaca (zero-based)

| DI    | Alamat PLC  | Arti                |
| ----- | ----------- | ------------------- |
| 0–9   | Y0310–Y0319 | MOTOR 1–10 FAULT    |
| 10    | Y031A       | EMERGENCY STOP      |
| 11–15 | Y031B–Y031F | SPARE               |
```

Selain tabel di atas, dokumen wajib memuat:
- Part number hardware: CN-8031, CT-222F, CT-122F, CT-5801, AJ65SBTB1-16D1, AJ65SBTB1-16T1.
- Catatan sink/source: CT-222F source/PNP → 16D1 dengan COM di 0V; 16T1 sink (COM di 0V) → CT-122F low-aktif. Cocok, tanpa relay.
- Tabel env `PLC_*` dengan arti dan nilai per line.
- Matematika throughput: `1 / (pulse_s + gap_s)` sinyal per detik per coil, dan apa yang terjadi saat meluap (drop + coil ERROR naik).
- Bagian "Belum diputuskan" yang menyalin Task 8.

- [ ] **Step 4: Perbarui CLAUDE.md**

- Baris daftar `workers/` — tambahkan `plc`.
- Baris daftar `integrations/` — tambahkan `plc/ (ModbusPlcClient)`.
- Tabel Tech Stack — tambahkan `pymodbus`.
- Bagian Pointers — tambahkan `docs/plc-integration.md`.

- [ ] **Step 5: Perbarui `docs/backend-overview.md`**

Tambahkan semua env `PLC_*` ke tabel env var, dengan default dan keterangan per line.

- [ ] **Step 6: Verifikasi seluruh gate**

Run: `python -m pytest tests/unit/ -q && ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/plc/ src/palmgrade/workers/plc_worker.py`
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

- `domain/plc_pulse.py` — penjadwal pulse murni, menjamin ada jeda OFF di antara
  dua pulse pada coil yang sama supaya PLC tidak menghitung dua buah jadi satu
- `integrations/plc/modbus_client.py` — satu-satunya file yang menyentuh pymodbus
- `workers/plc_worker.py` — satu-satunya thread yang menyentuh socket Modbus
- `frame_processing_worker.py` — hanya `put_nowait`, tidak pernah blocking

Mati secara default (`PLC_ENABLED=false`); hanya PC pabrik yang menyalakan.
Lebar pulse dan jeda berupa env var supaya bisa dikalibrasi di lapangan tanpa
rebuild. Coil map lengkap ada di `docs/plc-integration.md`.

Nol perubahan di palmgrade-api dan palmgrade-frontend.
EOF
)"
```

---

### Task 8: Commissioning di lapangan (bukan pekerjaan koding)

Dikerjakan di PC pabrik dengan hardware terpasang, setelah PR merge. Tidak ada test otomatis yang bisa menggantikan langkah-langkah ini.

- [ ] **Step 1: Konfirmasi offset alamat sebelum apa pun disambungkan**

Pakai tool konfigurasi ODOT, paksa coil `0` jadi ON. LED **DO00** pada CT-222F harus menyala. Kalau yang menyala DO01, seluruh peta bergeser satu dan `PLC_COIL_BASE` harus disesuaikan. Lima menit, dan menutup satu-satunya keraguan yang tersisa soal alamat.

- [ ] **Step 2: Uji satu kanal sebelum 16 kanal**

Sambungkan DO00 → X0300 saja. Paksa ON, pastikan PLC melihatnya. Baru kabelkan sisanya.

- [ ] **Step 3: Isi `.env` PC pabrik**

`PLC_ENABLED=true`, `PLC_HOST=<ip ODOT>`, dan `LINE_1/2/3_PLC_COIL_ALIVE` sesuai jawaban pak Ocit soal spare bit.

- [ ] **Step 4: Verifikasi bit alive dari sisi PLC**

Jalankan `make restart`. Bit alive harus toggle tiap detik. Matikan container line 2 — bit alive line 2 harus berhenti toggle dalam 3 detik, sementara line 1 dan 3 jalan terus.

- [ ] **Step 5: Verifikasi watchdog**

Cabut kabel LAN ke ODOT. Semua coil kita harus jatuh ke 0 dalam waktu watchdog. **Kalau masih 30 detik, ini gagal** — minta pak Ocit menurunkannya ke 2–3 detik.

- [ ] **Step 6: Kalibrasi lebar pulse dengan buah asli**

Jalankan conveyor pada kecepatan produksi. Hitung berapa sinyal yang dilihat PLC vs berapa buah yang lewat. Naikkan `PLC_PULSE_MS` kalau PLC melewatkan sinyal; turunkan `PLC_PULSE_MS` + `PLC_PULSE_GAP_MS` kalau antrean meluap (coil ERROR naik). Tidak perlu rebuild — cukup ubah `.env` lalu `make restart`.

- [ ] **Step 7: Tutup pertanyaan yang menggantung dengan pak Ocit**

Empat hal ini ada di sisi dia, bukan di kode kita, tapi hasil akhirnya bergantung padanya:

1. **Lebar pulse + jeda + apakah 1 sinyal = 1 buah + cycle time actuator.** Bawa angka ini: pulse 200 ms + gap 100 ms = maksimum ~3,3 sinyal/detik per coil, sementara YOLO bisa memutuskan lebih cepat dari itu.
2. **Watchdog turun dari 30 detik ke 2–3 detik.**
3. **Polaritas EMERGENCY STOP dibalik jadi NC** — CT-122F low-aktif plus `Fault Action for Input: Cleaning Input Value` berarti kabel putus terbaca persis seperti "aman". Bit harus ON selama normal dan OFF saat E-stop ditekan.
4. **Spare bit 10/11/12 jadi LINE 1/2/3 ALIVE.** Kabelnya sudah ada; yang dibutuhkan cuma ladder.

---

## Catatan Eksekusi

- **Task 1–7 bisa jalan sekarang** tanpa menunggu jawaban apa pun. Semua yang belum diputuskan sudah berupa env var.
- **Kalau jawaban pulse berubah total** (misalnya "level, bukan pulse"), yang berubah cuma `domain/plc_pulse.py` plus testnya. Task 1 dan 3–7 tidak tersentuh.
- **`palmgrade-api` dan `palmgrade-frontend` nol perubahan.** Tidak ada migrasi SQL, tidak ada rilis terkoordinasi, tidak ada tag GHCR — vision hanya berjalan on-prem, jadi deploy-nya `make restart` di PC pabrik.
