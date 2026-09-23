# Pita Alarm PLC (motor fault + E-stop) di Layar Operator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kalau PLC melaporkan motor fault atau E-stop (bit M1100–M1111 dari daftar pak Ocit), operator melihat pita merah besar di tab operator konsol — bukan cuma angka mentah di tab support.

**Architecture:** Bit PLC sudah dibaca tiap 200 ms oleh `PlcWorker` di tiap proses line dan tersedia lewat `plc.inputs()`. Yang belum ada: penerjemahan bit → nama alarm, dan jalur ke layar operator. Kita tambah satu modul domain murni (`plc_alarm.py`) yang memetakan offset bit ke kode alarm, ikutkan daftar kode itu di `/internal/status` (yang sudah di-poll `LineStatusWorker` tiap 1 detik), dan gambar **satu** pita global di atas kartu line. Satu pita, bukan per kartu: ketiga proses line membaca **blok M yang sama** dari satu PLC, jadi motor fault itu keadaan pabrik, bukan keadaan line.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic; `static/console.html` vanilla JS tanpa build step; pytest (unit tanpa cv2/torch, e2e boleh).

**Spec:** Keputusan di percakapan 2026-09-23: E-stop = **tanda saja**, grading TIDAK dihentikan (menghentikan = keputusan keselamatan yang butuh konfirmasi pak Ocit). Peta bit: `docs/plc-mc-handoff.md` bab 2.2.

## Global Constraints

- Kerja di worktree `.claude/worktrees/plc-sync`, branch `feat/plc-mc-protocol`. Jangan `cd` ke checkout utama (sesi lain memakainya). Salin `.env` repo utama ke worktree dulu kalau belum ada — tanpa itu 2 unit test merah palsu (`tests/conftest.py` membaca daftar kunci dari `.env` root).
- Python: `/Users/nexiomacbookpro/Desktop/Projects/sawit/autograde/.venv/bin/python` (worktree tidak punya venv).
- Offset bit dalam blok (`PLC_DI_BASE=1100`, `PLC_DI_COUNT=16`): **0–10 = MOTOR 1–11 FAULT, 11 = E-STOP OP PANEL**, 12–15 belum dialokasikan. Kode tidak boleh tahu angka 1100 — dia cuma melihat `inputs[i]`.
- **Asumsi polaritas: bit ON (True) = fault / E-stop ditekan.** Daftar Ocit tidak menyebut polaritas; catat di dokumen sebagai butir yang harus dikonfirmasi. Jangan dikompensasi di kode.
- Kode alarm bahasa-netral (`motor_fault`, `estop`); teks manusia hanya di `KAMUS` konsol, dua bahasa (`id`, `en`) — dijaga test.
- `console.html`: nol `https://`, nol handler inline `on*=`, semua nilai server lewat `esc()`. Test `tests/unit/test_console_html.py` menjaga ini.
- Commit message bahasa Indonesia, tanpa baris co-author. Jangan `git stash`.

---

### Task 1: Modul domain `plc_alarm` — bit → kode alarm

**Files:**
- Create: `src/palmgrade/domain/plc_alarm.py`
- Test: `tests/unit/test_plc_alarm.py`

**Interfaces:**
- Produces: `ALARM_MOTOR_FAULT = "motor_fault"`, `ALARM_ESTOP = "estop"`, `MOTOR_COUNT = 11`, `ESTOP_OFFSET = 11`, dan
  `alarms_from_inputs(inputs: list[bool]) -> list[dict]` yang mengembalikan mis. `[{"code": "motor_fault", "n": 3}, {"code": "estop"}]`, urut naik, kosong kalau tidak ada. Bit di luar 0–11 diabaikan (belum dialokasikan). Input pendek/kosong = tidak ada alarm.

- [ ] **Step 1: Tulis test yang gagal**

```python
"""Bit PLC (blok M1100..) -> daftar alarm yang bisa dibaca manusia.

Logika murni, nol I/O, supaya bisa dites tanpa PLC dan tanpa cv2/torch.
Offset mengikuti daftar pak Ocit 2026-09-23: 0-10 motor 1-11 fault, 11 E-stop.
"""
from palmgrade.domain.plc_alarm import (
    ALARM_ESTOP,
    ALARM_MOTOR_FAULT,
    ESTOP_OFFSET,
    MOTOR_COUNT,
    alarms_from_inputs,
)


def _bits(*aktif: int, panjang: int = 16) -> list[bool]:
    b = [False] * panjang
    for i in aktif:
        b[i] = True
    return b


def test_tanpa_bit_aktif_tidak_ada_alarm():
    assert alarms_from_inputs(_bits()) == []


def test_inputs_kosong_berarti_tidak_ada_alarm_bukan_error():
    # PLC mati (PLC_ENABLED=false) -> plc.inputs() = []. Layar harus tenang.
    assert alarms_from_inputs([]) == []


def test_motor_dinomori_dari_satu_bukan_nol():
    # Offset 2 = MOTOR 3 di daftar Ocit (M1102). Salah satu, teknisi buka panel motor yang salah.
    assert alarms_from_inputs(_bits(2)) == [{"code": ALARM_MOTOR_FAULT, "n": 3}]


def test_motor_terakhir_adalah_sebelas():
    assert alarms_from_inputs(_bits(MOTOR_COUNT - 1)) == [{"code": ALARM_MOTOR_FAULT, "n": 11}]


def test_estop_di_offset_sebelas():
    assert ESTOP_OFFSET == 11
    assert alarms_from_inputs(_bits(11)) == [{"code": ALARM_ESTOP}]


def test_beberapa_alarm_urut_naik():
    assert alarms_from_inputs(_bits(11, 0, 4)) == [
        {"code": ALARM_MOTOR_FAULT, "n": 1},
        {"code": ALARM_MOTOR_FAULT, "n": 5},
        {"code": ALARM_ESTOP},
    ]


def test_bit_belum_dialokasikan_diabaikan():
    # 12-15 kosong di daftar Ocit. Kalau ladder memakainya untuk hal lain,
    # layar operator tidak boleh menyebutnya "motor 13".
    assert alarms_from_inputs(_bits(12, 15)) == []


def test_blok_lebih_pendek_dari_dua_belas_tetap_aman():
    assert alarms_from_inputs([True, False, False]) == [{"code": ALARM_MOTOR_FAULT, "n": 1}]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd .claude/worktrees/plc-sync && ../../.venv/bin/python -m pytest tests/unit/test_plc_alarm.py -q`
Expected: `ModuleNotFoundError: No module named 'palmgrade.domain.plc_alarm'`

- [ ] **Step 3: Implementasi minimal**

```python
"""Bit yang dibaca dari PLC -> daftar alarm untuk layar operator.

Logika murni, nol I/O — pola yang sama dengan `plc_signal.py`. Offsetnya
mengikuti daftar pak Ocit 2026-09-23 (blok mulai `PLC_DI_BASE`, M1100):

    offset 0..10  MOTOR 1..11 FAULT   (M1100..M1110)
    offset 11     E-STOP OP PANEL     (M1111)
    offset 12..15 belum dialokasikan  (M1112..M1115)

Modul ini sengaja tidak tahu angka 1100: `PlcWorker` sudah menyimpan blok
sebagai daftar mulai offset 0, dan `PLC_DI_BASE` boleh berubah tanpa
menyentuh apa pun di sini.

Kode alarm bahasa-netral; teks manusia hidup di KAMUS konsol, dua bahasa.

⚠️ Polaritas: bit ON dianggap "fault / ditekan". Daftar Ocit tidak menyebut
polaritas — dicatat sebagai butir konfirmasi di docs/plc-mc-handoff.md,
bukan dikompensasi di sini.
"""
from __future__ import annotations

ALARM_MOTOR_FAULT = "motor_fault"
ALARM_ESTOP = "estop"

#: Motor 1..11 menempati offset 0..10.
MOTOR_COUNT = 11
#: E-stop tepat sesudah motor terakhir.
ESTOP_OFFSET = MOTOR_COUNT

#: Semua kode yang bisa muncul — dipakai test konsol untuk memastikan
#: tiap kode punya terjemahan di kedua bahasa.
ALARM_CODES = (ALARM_MOTOR_FAULT, ALARM_ESTOP)


def alarms_from_inputs(inputs: list[bool]) -> list[dict]:
    """Bit yang ON -> alarm, urut naik. Bit di luar 0..11 diabaikan.

    `[]` untuk PLC mati (`inputs` kosong) dan untuk blok tanpa bit aktif —
    keduanya berarti "layar tenang", bukan error.
    """
    alarms: list[dict] = []
    for offset in range(min(len(inputs), MOTOR_COUNT)):
        if inputs[offset]:
            alarms.append({"code": ALARM_MOTOR_FAULT, "n": offset + 1})
    if len(inputs) > ESTOP_OFFSET and inputs[ESTOP_OFFSET]:
        alarms.append({"code": ALARM_ESTOP})
    return alarms
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `../../.venv/bin/python -m pytest tests/unit/test_plc_alarm.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/domain/plc_alarm.py tests/unit/test_plc_alarm.py
git commit -m "feat(plc): domain plc_alarm — bit M1100.. jadi daftar alarm motor/E-stop"
```

---

### Task 2: `/internal/status` membawa `alarms`

**Files:**
- Modify: `src/palmgrade/schemas/internal_schema.py:65-69` (`LineStatusResponse`)
- Modify: `src/palmgrade/controllers/internal_controller.py:118-127` (`line_status`)
- Test: `tests/e2e/test_internal_status_alarm.py` (e2e karena `internal_controller` menyeret cv2/torch, sama seperti `test_internal_plc_lane.py`)

**Interfaces:**
- Consumes: `alarms_from_inputs` (Task 1); `palmgrade.plc.inputs()` → `list[bool]` (sudah ada, `[]` saat PLC mati).
- Produces: field `alarms: list[dict]` di JSON `/internal/status`, mis. `"alarms": [{"code": "motor_fault", "n": 3}]`. Kosong = tidak ada alarm ATAU PLC mati — konsol tidak perlu membedakan.

- [ ] **Step 1: Tulis test yang gagal**

```python
"""`/internal/status` membawa alarm PLC supaya konsol tidak perlu jalur baru.

`LineStatusWorker` sudah memanggil endpoint ini tiap detik untuk piston;
alarm cukup menumpang. Di `tests/e2e/` karena `internal_controller` menyeret
cv2/torch lewat CaptureService — lihat docstring test_internal_plc_lane.py.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("torch")

from palmgrade.controllers import internal_controller  # noqa: E402
from palmgrade.workers.runtime_state import RuntimeState  # noqa: E402


def _status(monkeypatch, bits):
    monkeypatch.setattr(internal_controller, "_plc_inputs", lambda: bits, raising=False)
    return asyncio.run(internal_controller.line_status(RuntimeState()))


def test_status_membawa_alarm_dari_bit_plc(monkeypatch):
    bits = [False] * 16
    bits[2] = True      # MOTOR 3
    bits[11] = True     # E-STOP
    jawab = _status(monkeypatch, bits)
    assert jawab.alarms == [{"code": "motor_fault", "n": 3}, {"code": "estop"}]


def test_plc_mati_berarti_alarms_kosong_bukan_error(monkeypatch):
    jawab = _status(monkeypatch, [])
    assert jawab.alarms == []
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `../../.venv/bin/python -m pytest tests/e2e/test_internal_status_alarm.py -q`
Expected: FAIL — `AttributeError: 'LineStatusResponse' object has no attribute 'alarms'` (atau `_plc_inputs` tidak ada; keduanya benar untuk merah pertama).

- [ ] **Step 3: Implementasi**

Di `src/palmgrade/schemas/internal_schema.py`, ganti kelas:

```python
class LineStatusResponse(BaseModel):
    machine_id: str
    truck_id: str | None
    ffb_source: str | None
    piston: dict | None
    # Alarm dari blok M yang dibaca line ini (motor fault, E-stop). Kosong =
    # tidak ada alarm ATAU PLC mati; konsol memperlakukan keduanya sama.
    # Default [] supaya konsol lama yang tidak mengenal field ini tetap jalan.
    alarms: list[dict] = []
```

Di `src/palmgrade/controllers/internal_controller.py`, tambah di dekat import modul (atas berkas, setelah import yang ada):

```python
def _plc_inputs() -> list[bool]:
    """Dibungkus supaya test bisa menyuntik bit tanpa menjalankan PlcWorker."""
    from ..plc import inputs

    return inputs()
```

lalu ganti `line_status`:

```python
async def line_status(state: RuntimeState) -> LineStatusResponse:
    from ..core.dependencies import get_settings
    from ..domain.plc_alarm import alarms_from_inputs
    from ..plc import piston_state

    return LineStatusResponse(
        machine_id=get_settings().machine_id,
        truck_id=state.current_truck_id,
        ffb_source=state.current_ffb_source,
        piston=piston_state(),
        alarms=alarms_from_inputs(_plc_inputs()),
    )
```

- [ ] **Step 4: Jalankan, pastikan lulus (plus lane lama tidak pecah)**

Run: `../../.venv/bin/python -m pytest tests/e2e/test_internal_status_alarm.py tests/e2e/test_internal_plc_lane.py -q`
Expected: semua passed (atau skipped kalau torch tidak ada — di MacBook ini torch ada).

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/schemas/internal_schema.py src/palmgrade/controllers/internal_controller.py tests/e2e/test_internal_status_alarm.py
git commit -m "feat(plc): /internal/status membawa alarms dari bit PLC"
```

---

### Task 3: `LineStatusWorker` menyimpan `alarms`

**Files:**
- Modify: `src/palmgrade/workers/line_status_worker.py:36-43`
- Test: `tests/unit/test_line_status_alarm.py`

**Interfaces:**
- Consumes: JSON `/internal/status` dengan `alarms` (Task 2).
- Produces: `worker.snapshot()[line_code]["alarms"]` → `list[dict]`; `[]` kalau line tidak menjawab atau field tidak ada (line versi lama). `ConsoleService.state()` sudah meneruskan seluruh dict ini sebagai `lines[i]["plc"]` — **tidak perlu diubah**.

- [ ] **Step 1: Tulis test yang gagal**

```python
"""Alarm PLC ikut disimpan worker status line, supaya /api/console/state
membawanya tanpa memanggil line secara langsung (satu line mati tidak boleh
membekukan konsol — lihat docstring line_status_worker.py)."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.workers.line_status_worker import LineStatusWorker


class _Line:
    def __init__(self, jawab=None, down=False):
        self._jawab = jawab
        self._down = down

    async def status(self, line):
        if self._down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        return self._jawab


def _worker(line_client):
    # `console_lines` adalah PROPERTY (core/config.py:623), bukan method.
    lines = replace(Settings(), factory_tz="Asia/Jakarta").console_lines[:1]
    return LineStatusWorker(lines, line_client, interval_s=0)


def test_alarms_disimpan_apa_adanya():
    w = _worker(_Line({"piston": None, "ffb_source": None,
                       "alarms": [{"code": "motor_fault", "n": 3}]}))
    asyncio.run(w.run_once())
    (status,) = w.snapshot().values()
    assert status["alarms"] == [{"code": "motor_fault", "n": 3}]


def test_line_versi_lama_tanpa_field_alarms_dibaca_kosong():
    w = _worker(_Line({"piston": None, "ffb_source": None}))
    asyncio.run(w.run_once())
    (status,) = w.snapshot().values()
    assert status["alarms"] == []


def test_line_mati_tidak_punya_alarms_palsu():
    w = _worker(_Line(down=True))
    asyncio.run(w.run_once())
    (status,) = w.snapshot().values()
    assert status == {"reachable": False}
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `../../.venv/bin/python -m pytest tests/unit/test_line_status_alarm.py -q`
Expected: `KeyError: 'alarms'` pada dua test pertama.

- [ ] **Step 3: Implementasi**

Di `run_once`, ganti blok penyimpanan:

```python
            piston = jawab.get("piston") or {}
            self._state[line.line_code] = {
                "reachable": True,
                "ffb_source": jawab.get("ffb_source"),
                "piston_requested": piston.get("requested"),
                "piston_open": piston.get("confirmed_open"),
                # `or []`: line versi lama tidak mengirim field ini, dan None
                # di layar akan membuat pita alarm gagal merender.
                "alarms": jawab.get("alarms") or [],
            }
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `../../.venv/bin/python -m pytest tests/unit/test_line_status_alarm.py tests/unit/test_console_piston.py -q`
Expected: semua passed.

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/workers/line_status_worker.py tests/unit/test_line_status_alarm.py
git commit -m "feat(konsol): worker status line ikut menyimpan alarm PLC"
```

---

### Task 4: Pita alarm global di tab operator

**Files:**
- Modify: `src/palmgrade/static/console.html` — CSS dekat `.pita-piston` (±baris 520), markup sebelum `<div id="lines"></div>` (baris 871), KAMUS `id` (dekat baris 1514) dan `en` (dekat 1657), fungsi baru dekat `pitaPiston` (baris 2236), pemanggilan di `refresh()` (baris ~3079).
- Test: `tests/unit/test_console_html_alarm.py`

**Interfaces:**
- Consumes: `s.lines[i].plc.alarms` dari `/api/console/state` (Task 3).
- Produces: `<div id="pita-alarm" hidden>` yang terisi/tersembunyi tiap poll; fungsi JS `gabungAlarm(lines)` dan `gambarPitaAlarm(lines)`.

- [ ] **Step 1: Tulis guard test yang gagal**

```python
"""Penjaga statis pita alarm PLC di console.html (tidak ada test runner JS).

Yang dijaga: pita ada di HTML, fungsinya dipanggil dari refresh(), dan tiap
kode alarm dari domain punya terjemahan di KEDUA bahasa — satu kode tanpa
terjemahan tampil sebagai kunci mentah "alarm_estop" di layar pabrik.
"""
from __future__ import annotations

import re
from pathlib import Path

from palmgrade.domain.plc_alarm import ALARM_CODES

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def test_pita_alarm_ada_di_atas_kartu_line():
    assert HTML.index('id="pita-alarm"') < HTML.index('<div id="lines"></div>')


def test_pita_alarm_digambar_tiap_refresh():
    refresh = HTML.split("async function refresh() {", 1)[1].split("\n}\n", 1)[0]
    assert "gambarPitaAlarm(s.lines)" in refresh


def test_setiap_kode_alarm_diterjemahkan_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [c for c in ALARM_CODES if f"alarm_{c}:" not in isi]
        assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


def test_pita_alarm_memakai_esc_bukan_innerhtml_mentah():
    fn = HTML.split("function gambarPitaAlarm(", 1)[1].split("\n}\n", 1)[0]
    assert "esc(" in fn
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `../../.venv/bin/python -m pytest tests/unit/test_console_html_alarm.py -q`
Expected: 4 FAILED (`id="pita-alarm"` tidak ada, dst).

- [ ] **Step 3: Implementasi di `console.html`**

**(a) CSS** — tepat setelah blok `@keyframes denyut-pita { ... }`:

```css
  /* Alarm PLC (motor fault / E-stop): satu pita untuk seluruh layar, bukan per
     kartu - ketiga line membaca blok M yang sama dari satu PLC, jadi ini
     keadaan pabrik. Palet dan denyut sama dengan pita piston supaya dua hal
     "bahaya" di layar ini tidak punya dua bahasa visual. */
  #pita-alarm { margin:10px 13px 0; padding:11px 13px; border-radius:var(--r-sm);
                background:var(--danger-fg); color:var(--danger-bg);
                font-size:1.15rem; font-weight:700; text-align:center;
                text-transform:uppercase; letter-spacing:.04em;
                animation:denyut-pita 1.6s ease-in-out infinite; }
  #pita-alarm span { display:inline-block; margin:0 .6em; }
```

**(b) Markup** — ganti `<div id="lines"></div>` dengan:

```html
<div id="pita-alarm" hidden></div>
<div id="lines"></div>
```

**(c) KAMUS** — di blok `id`, tepat setelah baris `pistonTerbuka:"PISTON TERBUKA - hati-hati, besi bergerak",`:

```js
    alarm_motor_fault:"MOTOR {n} FAULT", alarm_estop:"E-STOP DITEKAN - line berhenti darurat",
```

di blok `en`, tepat setelah `pistonTerbuka:"PISTON OPEN - moving metal, stand clear",`:

```js
    alarm_motor_fault:"MOTOR {n} FAULT", alarm_estop:"E-STOP PRESSED - emergency stop active",
```

**(d) Fungsi** — tepat setelah fungsi `pitaPiston(l)`:

```js
// Alarm PLC (motor fault / E-stop) dari blok M yang dibaca tiap line. Semua
// line membaca blok yang sama, jadi daftarnya digabung dan dideduplikasi;
// line yang mati tidak menyumbang apa-apa (l.plc.alarms undefined). Kunci
// dedup memakai kode+nomor supaya "MOTOR 3" dari line 1 dan line 2 tampil sekali.
function gabungAlarm(lines) {
  const seen = new Set();
  const hasil = [];
  for (const l of lines || []) {
    for (const a of ((l.plc || {}).alarms || [])) {
      const kunci = a.code + ":" + (a.n === undefined ? "" : a.n);
      if (seen.has(kunci)) continue;
      seen.add(kunci);
      hasil.push(a);
    }
  }
  return hasil;
}

// Satu pita di atas semua kartu. Teks lewat t() dengan kunci "alarm_<code>",
// dan {n} diganti nomor motor. Kode yang tidak dikenal KAMUS tampil apa adanya
// lewat t() - lebih baik "alarm_xyz" terlihat daripada alarm hilang diam-diam.
function gambarPitaAlarm(lines) {
  const el = $("pita-alarm");
  if (!el) return;
  const alarms = gabungAlarm(lines);
  if (!alarms.length) { el.hidden = true; el.textContent = ""; return; }
  el.innerHTML = alarms.map((a) => {
    const teks = t("alarm_" + a.code).replace("{n}", a.n === undefined ? "" : String(a.n));
    return `<span>${esc(teks)}</span>`;
  }).join("");
  el.hidden = false;
}
```

`t()` di berkas ini adalah `const t = (k) => KAMUS[bahasa][k] ?? k;` (baris ±1727) — kunci yang tidak ada kembali apa adanya, jadi komentar di atas benar, tidak perlu pembungkus.

**(e) Panggilan** — di `async function refresh()`, tepat setelah baris `isiTally(s.lines);`:

```js
    gambarPitaAlarm(s.lines);
```

- [ ] **Step 4: Jalankan guard test + guard lama**

Run: `../../.venv/bin/python -m pytest tests/unit/test_console_html_alarm.py tests/unit/test_console_html.py -q`
Expected: semua passed (guard lama memastikan tidak ada `on*=` inline dan `esc` masih utuh).

- [ ] **Step 5: Lihat dengan mata**

Run konsol lokal: `make console` dari worktree (baca Makefile: target `console` pakai `devsecret`), buka `http://127.0.0.1:8100/console`, login operator. Tanpa PLC, pita harus **tidak** muncul. Lalu uji dengan menyuntik lewat DevTools console browser:

```js
gambarPitaAlarm([{plc:{alarms:[{code:"motor_fault",n:3},{code:"estop"}]}}])
```

Expected: pita merah berdenyut di atas kartu, teks `MOTOR 3 FAULT   E-STOP DITEKAN - LINE BERHENTI DARURAT`. Lalu `gambarPitaAlarm([])` → pita hilang. Ganti bahasa ke `en` (tombol bahasa di header) dan ulangi: teks Inggris.

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/static/console.html tests/unit/test_console_html_alarm.py
git commit -m "feat(konsol): pita alarm PLC — motor fault dan E-stop terbaca operator dari jauh"
```

---

### Task 5: Tab Uji PLC menampilkan nama bit, bukan cuma nomor

**Files:**
- Modify: `src/palmgrade/static/console.html` — fungsi `isiDiPlc(inputs)` (±baris 3475) dan KAMUS (dekat kunci `diAktif`, baris 1538 dan 1681).
- Test: tambah ke `tests/unit/test_console_html_alarm.py`

**Interfaces:**
- Consumes: `data.inputs` dari `/api/console/dev/plc/<line>` (sudah ada).
- Produces: teks per bit `M+offset: NAMA = Aktif/Mati`, mis. `2: MOTOR 3 = Aktif`, `11: E-STOP = Mati`, `13: - = Mati`.

- [ ] **Step 1: Tulis guard test yang gagal** (tambahkan di berkas Task 4)

```python
def test_uji_plc_memberi_nama_bit():
    fn = HTML.split("function isiDiPlc(", 1)[1].split("\n}\n", 1)[0]
    assert "namaBitPlc(" in fn
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("diMotor:", "diEstop:", "diKosong:"):
            assert kunci in isi, f"KAMUS.{bahasa} tanpa {kunci}"
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `../../.venv/bin/python -m pytest tests/unit/test_console_html_alarm.py::test_uji_plc_memberi_nama_bit -q`
Expected: FAIL (`namaBitPlc(` tidak ada).

- [ ] **Step 3: Implementasi**

KAMUS `id`, di baris yang memuat `diAktif:"Aktif", diMati:"Mati",` tambahkan di baris berikutnya:

```js
    diMotor:"MOTOR {n}", diEstop:"E-STOP", diKosong:"-",
```

KAMUS `en`, setelah `diAktif:"On", diMati:"Off",`:

```js
    diMotor:"MOTOR {n}", diEstop:"E-STOP", diKosong:"-",
```

Ganti `isiDiPlc`:

```js
// Nama bit mengikuti daftar pak Ocit 2026-09-23 (offset dalam blok
// PLC_DI_BASE): 0-10 motor 1-11, 11 E-stop, sisanya belum dialokasikan.
// Sengaja cermin dari domain/plc_alarm.py, bukan dikirim server: layar Uji
// PLC dipakai support saat commissioning, dan angka offset mentah tetap
// ditampilkan di depan nama supaya bisa dicocokkan ke GX Works.
function namaBitPlc(i) {
  if (i < 11) return t("diMotor").replace("{n}", String(i + 1));
  if (i === 11) return t("diEstop");
  return t("diKosong");
}

function isiDiPlc(inputs) {
  if (!inputs || !inputs.length) return `<span class="muted">${esc(t("plcMati"))}</span>`;
  return inputs.map((on, i) =>
    `<span class="plc-di-bit${on ? " aktif" : ""}">${i}: ${esc(namaBitPlc(i))} = ${on ? esc(t("diAktif")) : esc(t("diMati"))}</span>`
  ).join(" ");
}
```

Dan CSS, di dekat `.plc-di-bit { white-space:nowrap; }`:

```css
  .plc-di-bit.aktif { color:var(--danger-fg); font-weight:700; }
```

- [ ] **Step 4: Jalankan**

Run: `../../.venv/bin/python -m pytest tests/unit/test_console_html_alarm.py tests/unit/test_console_html.py tests/unit/test_dev_plc.py -q`
Expected: semua passed.

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/static/console.html tests/unit/test_console_html_alarm.py
git commit -m "feat(konsol): tab Uji PLC menamai tiap bit (MOTOR n / E-STOP)"
```

---

### Task 6: Dokumen dan skill

**Files:**
- Modify: `docs/plc-mc-handoff.md` bab 2.2 (tabel "PLC menulis, PC membaca") dan bab 5 (yang ditunggu)
- Modify: `.claude/skills/plc-mc-protocol/SKILL.md` — bagian "PC membaca"
- Modify: `docs/MANUAL.md` §5.9 (satu kalimat)
- Regenerate: `docs/plc-mc-handoff.pdf`, `docs/MANUAL.pdf`

- [ ] **Step 1: `plc-mc-handoff.md`**

Setelah kalimat "Bit yang kami baca dipakai untuk **tampilan dan diagnosa**, bukan untuk mengambil keputusan grading." tambahkan:

```markdown

Yang dilihat operator: begitu salah satu bit M1100–M1111 ON, layar konsol menampilkan
**pita merah besar** di atas kartu line — "MOTOR 3 FAULT", "E-STOP DITEKAN" — dan hilang
sendiri saat bitnya OFF. Grading **tidak dihentikan** oleh E-stop; kamera tetap menilai
(lihat bab 5, butir konfirmasi).

⚠️ **Polaritas diasumsikan bit ON = fault / ditekan.** Kalau ladder menulis kebalikannya
(ON = normal, OFF = fault, seperti kabel NC), mohon kabari — sisi aplikasi tinggal membalik
satu tempat.
```

Di tabel bab 5, tambah baris sebelum baris piston:

```markdown
| 4 | **Polaritas M1100–M1111: ON = fault/ditekan?** | Pita alarm operator dibaca dari bit ini apa adanya |
| 5 | **Saat E-stop, kamera ikut berhenti menilai?** Sekarang tidak — cuma pita. | Kalau harus berhenti, ada hasil grading yang tercatat selama line berhenti darurat |
```

dan ubah kalimat "Peta alamat **sudah selesai**" tetap; ubah "**Yang ditunggu dari sisi PLC:** tiga butir di bab 5." di bab 7 menjadi "lima butir di bab 5 (dua terakhir konfirmasi, bukan pekerjaan)". Naikkan `versi: "1.2"`, `tanggal: 23 September 2026`.

- [ ] **Step 2: Skill** — di `SKILL.md`, setelah tabel "PC membaca", tambah:

```markdown
Bit ini sampai ke operator lewat `domain/plc_alarm.py` → `/internal/status.alarms` →
`LineStatusWorker` → `/api/console/state` → `gambarPitaAlarm()` (satu pita global, bukan
per kartu — semua line membaca blok yang sama). E-stop = **tanda saja**, grading tidak
berhenti (keputusan 2026-09-23; menghentikan butuh konfirmasi Ocit). Polaritas
diasumsikan ON = fault — belum dikonfirmasi.
```

- [ ] **Step 3: MANUAL §5.9** — tambahkan kalimat terakhir: `Motor fault dan E-stop dari PLC tampil sebagai pita merah di atas kartu line.`

- [ ] **Step 4: PDF**

Run: `../../.venv/bin/python scripts/md_to_pdf.py docs/plc-mc-handoff.md && ../../.venv/bin/python scripts/md_to_pdf.py docs/MANUAL.md`
Expected: dua baris `PDF: ... (N halaman)`. Kalau timeout Chrome, ulang sekali.

- [ ] **Step 5: Test pengikat dokumen ↔ compose masih hijau**

Run: `../../.venv/bin/python -m pytest tests/unit/test_plc_docs_match_compose.py tests/unit/test_doc_links.py -q`
Expected: passed.

- [ ] **Step 6: Commit**

```bash
git add docs/plc-mc-handoff.md docs/plc-mc-handoff.pdf docs/MANUAL.md docs/MANUAL.pdf .claude/skills/plc-mc-protocol/SKILL.md
git commit -m "docs(plc): pita alarm operator, polaritas bit, dan E-stop = tanda saja"
```

---

### Task 7: Verifikasi penuh dan push

- [ ] **Step 1: Lint berkas yang disentuh**

Run: `../../.venv/bin/ruff check src/palmgrade/domain/plc_alarm.py src/palmgrade/controllers/internal_controller.py src/palmgrade/schemas/internal_schema.py src/palmgrade/workers/line_status_worker.py tests/unit/test_plc_alarm.py tests/unit/test_line_status_alarm.py tests/unit/test_console_html_alarm.py tests/e2e/test_internal_status_alarm.py`
Expected: `All checks passed!`

- [ ] **Step 2: Suite penuh**

Run: `../../.venv/bin/python -m pytest tests/unit tests/integration -q 2>&1 | tail -2` lalu `../../.venv/bin/python -m pytest tests/e2e -q 2>&1 | tail -2`
Expected: 0 failed. (`test_onboarding_pdf` bisa error kalau Chrome rebutan dengan pytest lain — jalankan sendirian untuk membuktikan lulus.)

- [ ] **Step 3: Push**

```bash
git push origin feat/plc-mc-protocol
```
