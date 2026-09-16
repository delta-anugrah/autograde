# Menu Developer Konsol AutoGrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lima layar khusus akun support di konsol AutoGrade — Log, Diagnostik, Antrean ERP, Versi & Lisensi, Uji PLC — supaya sesi AnyDesk tidak lagi berakhir di `docker logs` yang sudah terhapus restart.

**Architecture:** Satu kolom `peran` di `operators` memisahkan operator pabrik dari support; backend yang menjaga (dependency FastAPI → 403), tampilan hanya merapikan. Empat dari lima layar membungkus data yang sudah dicatat hari ini (`/health/detail`, `outbox_events`, settings); satu-satunya data baru adalah tabel `log_kejadian` yang diisi logging handler.

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL, `synchronous=FULL`), vanilla JS satu berkas (`console.html`, tanpa build step, tanpa CDN), pytest, ruff. Sisi ERP: Frappe DocType JSON + patch.

**Spec:** `docs/superpowers/specs/2026-09-15-menu-developer-konsol-design.md`

## Global Constraints

- **Konsol harus tetap jalan offline.** `console.html` nol referensi `https://`; tidak ada menu baru yang memanggil ke luar. Dijaga `tests/unit/test_console_html.py`.
- **Layer rule konsol:** `route → service → repository / integration`. Tanpa controller (pengecualian sadar, lihat CLAUDE.md).
- **Ruff:** seluruh modul konsol sudah masuk scope `ruff check`. Berkas baru di `routes/`, `services/`, `repositories/`, `domain/` wajib lolos.
- **Test HTTP merakit app sendiri** dengan dependensi di-override — **bukan** `create_console_app()`, yang menyentuh `state/console.db` milik developer.
- **Test tanpa torch/cv2/SDK.** CI runner ringan. `asyncio.run`, bukan pytest-asyncio.
- **Judul & isi PR bahasa Inggris**; pesan commit boleh Indonesia. **Tanpa** baris `Co-Authored-By: Claude`.
- **Branch dari `staging`**, PR squash merge ke `staging`.
- **Frappe membalas 417** untuk satu field asing di `/api/resource` → PR 0 (autoerp) wajib merge duluan.
- Retensi log **180 hari**; jendela penggabungan **60 detik**; hanya level **ERROR** dan **WARNING** yang ditulis.
- `ERP_ALLOWED_ROLES` bawaan `support`.
- **Setelan baru di `Settings` WAJIB ikut ditambahkan ke `docker-compose.yml` service
  `console` dan ke `.env.example`, di commit yang sama.**
  `tests/unit/test_console_compose_env.py` membaca keduanya satu sama lain dan akan
  gagal kalau tidak. Tes itu ada karena `ERP_COMPANY` pernah rilis tak terjangkau:
  setelan yang tidak diteruskan compose diam-diam jatuh ke default di dalam container.
- Dua peran saja: `operator`, `support`.

---

## File Structure

**Repo `autoerp` (PR 0):**
- Modify: `erpnext/palm_mill/doctype/autograde_operator/autograde_operator.json` — field `peran` (Select)
- Create: `erpnext/patches/v17_0/palm_mill_operator_peran.py` — isi baris lama
- Modify: `erpnext/patches.txt` — daftarkan patch
- Modify: `erpnext/palm_mill/doctype/autograde_operator/test_autograde_operator.py`

**Repo `autograde` (PR 1–4):**

| Berkas | Tanggung jawab |
|---|---|
| `domain/peran.py` | Aturan murni: peran sah, penyaring daftar izin. Tanpa I/O. |
| `repositories/console_repository.py` | Kolom `peran` + migrasi; `log_kejadian` (tulis/baca/buang) |
| `repositories/log_repository.py` | **Baru.** Store `log_kejadian` sendiri — `ConsoleStore` sudah 700+ baris |
| `core/log_sink.py` | **Baru.** `logging.Handler` → `LogStore`, plus penyaring rahasia |
| `domain/log_redaksi.py` | **Baru.** Aturan murni penyaring rahasia. Tanpa I/O. |
| `services/dev_service.py` | **Baru.** Flow lima layar developer |
| `routes/console.py` | `require_support`, endpoint `/api/console/dev/*` |
| `static/console.html` | Lima tab, dirender hanya kalau `peran === "support"` |
| `core/config.py` | `ERP_ALLOWED_ROLES`, `LOG_RETENSI_HARI` |

---

## Task 1: Field `peran` di DocType (repo autoerp)

**Files:**
- Modify: `erpnext/palm_mill/doctype/autograde_operator/autograde_operator.json`
- Create: `erpnext/patches/v17_0/palm_mill_operator_peran.py`
- Modify: `erpnext/patches.txt`
- Test: `erpnext/palm_mill/doctype/autograde_operator/test_autograde_operator.py`

**Interfaces:**
- Consumes: —
- Produces: field `peran` pada DocType `AutoGrade Operator`, nilai `"operator"` / `"support"`, default `"operator"`. Dipakai Task 5 (`master_data_worker` memintanya).

- [ ] **Step 1: Branch dari staging**

```bash
cd /Users/nexiomacbookpro/Desktop/Projects/sawit/autoerp
git checkout staging && git pull
git checkout -b feat/operator-peran
```

- [ ] **Step 2: Tulis tes yang gagal**

Tambahkan ke `test_autograde_operator.py`:

```python
def test_peran_default_operator(self):
    """A new account is an operator until someone says otherwise."""
    doc = frappe.get_doc({
        "doctype": "AutoGrade Operator",
        "email": "peran-default@example.com",
        "full_name": "Peran Default",
    }).insert(ignore_permissions=True)
    self.assertEqual(doc.peran, "operator")

def test_peran_support_tersimpan(self):
    """`support` is a value the field accepts, not just free text."""
    doc = frappe.get_doc({
        "doctype": "AutoGrade Operator",
        "email": "peran-support@example.com",
        "full_name": "Peran Support",
        "peran": "support",
    }).insert(ignore_permissions=True)
    self.assertEqual(
        frappe.db.get_value("AutoGrade Operator", doc.name, "peran"), "support"
    )
```

- [ ] **Step 3: Jalankan tes, pastikan gagal**

Run: `cd autoerp && bench --site pks.localhost run-tests --module erpnext.palm_mill.doctype.autograde_operator.test_autograde_operator`
Expected: FAIL — atribut `peran` tidak ada.

⚠️ Catatan: `bench run-tests` diketahui bermasalah di MacBook ini (memori `project_field_tidak_dipakai_autoerp`). Kalau gagal karena lingkungan, verifikasi manual: `bench --site pks.localhost console` lalu `frappe.get_meta("AutoGrade Operator").get_field("peran")` — harus `None` sebelum Step 4, dan terisi sesudahnya.

- [ ] **Step 4: Tambah field ke DocType JSON**

Di `autograde_operator.json`, tambahkan `"peran"` ke array `field_order` (setelah `"active"`), dan objek ini ke array `fields`:

```json
{
 "default": "operator",
 "fieldname": "peran",
 "fieldtype": "Select",
 "in_list_view": 1,
 "label": "Peran",
 "options": "operator\nsupport",
 "reqd": 1,
 "description": "support membuka menu diagnostik di konsol AutoGrade (log, antrean ERP, uji PLC). Naikkan hanya untuk orang yang memang menangani gangguan pabrik."
}
```

- [ ] **Step 5: Tulis patch untuk baris lama**

Create `erpnext/patches/v17_0/palm_mill_operator_peran.py`:

```python
"""Isi `peran` untuk akun yang dibuat sebelum field ini ada.

Semuanya jadi `operator`. Menaikkan seseorang jadi `support` adalah keputusan
sadar per orang, bukan efek samping sebuah migrasi.
"""

import frappe


def execute():
    frappe.reload_doc("palm_mill", "doctype", "autograde_operator")
    frappe.db.sql(
        """UPDATE `tabAutoGrade Operator`
           SET peran = 'operator'
           WHERE peran IS NULL OR peran = ''"""
    )
```

- [ ] **Step 6: Daftarkan patch**

Tambahkan satu baris di akhir `erpnext/patches.txt`:

```
erpnext.patches.v17_0.palm_mill_operator_peran
```

- [ ] **Step 7: Jalankan migrasi dan tes**

```bash
cd autoerp && bench --site pks.localhost migrate
bench --site pks.localhost run-tests --module erpnext.palm_mill.doctype.autograde_operator.test_autograde_operator
```

Expected: migrate sukses, tes PASS.

⚠️ **Jangan `bench migrate` di checkout yang tidak punya `erpnext/palm_mill`** — Frappe menghapus DocType yang tidak bisa diimpor beserta tabelnya (CLAUDE.md).

- [ ] **Step 8: Commit dan PR**

```bash
git add erpnext/palm_mill/doctype/autograde_operator/ erpnext/patches/v17_0/palm_mill_operator_peran.py erpnext/patches.txt
git commit -m "feat(palm_mill): field peran di AutoGrade Operator"
git push -u origin feat/operator-peran
gh pr create --base staging --title "feat(palm_mill): add a role field to AutoGrade Operator" --body "Adds \`peran\` (operator/support) so AutoGrade can tell a mill operator from someone who handles faults. A patch fills existing rows with \`operator\` — raising someone is a per-person decision, never a migration side effect.

Prerequisite for the AutoGrade console developer menus: Frappe answers 417 for one unknown field, so the field has to exist before AutoGrade asks for it."
```

---

## Task 2: Aturan peran (domain murni)

**Files:**
- Create: `src/palmgrade/domain/peran.py`
- Test: `tests/unit/test_peran.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `PERAN_OPERATOR: str = "operator"`, `PERAN_SUPPORT: str = "support"`
  - `peran_sah(nilai: object) -> str` — normalisasi ke peran yang dikenal, selain itu `"operator"`
  - `saring_peran_erp(nilai: object, diizinkan: frozenset[str]) -> str` — peran dari ERP setelah daftar izin
  - `parse_daftar_izin(mentah: str) -> frozenset[str]` — `.env` → himpunan

- [ ] **Step 1: Branch dari staging**

```bash
cd /Users/nexiomacbookpro/Desktop/Projects/sawit/autograde
git checkout staging && git pull
git checkout -b feat/konsol-peran-support
```

- [ ] **Step 2: Tulis tes yang gagal**

Create `tests/unit/test_peran.py`:

```python
from palmgrade.domain.peran import (
    PERAN_OPERATOR,
    PERAN_SUPPORT,
    parse_daftar_izin,
    peran_sah,
    saring_peran_erp,
)


def test_peran_dikenal_lolos_apa_adanya():
    assert peran_sah("support") == PERAN_SUPPORT
    assert peran_sah("operator") == PERAN_OPERATOR


def test_peran_asing_jatuh_ke_operator():
    """Sebuah nilai yang tidak dikenal tidak boleh membuka apa pun."""
    for nilai in ("admin", "", None, 7, "developer"):
        assert peran_sah(nilai) == PERAN_OPERATOR


def test_peran_dibaca_tanpa_peduli_besar_kecil_huruf():
    assert peran_sah("Support") == PERAN_SUPPORT


def test_spasi_pinggir_ditoleransi():
    """Nilai peran datang dari env dan dari kolom yang bisa diketik orang.

    Menolak karena satu spasi akan menurunkan akun support jadi operator tanpa
    jejak apa pun — gagal diam-diam, yang paling mahal di layar pabrik.
    """
    assert peran_sah("  support  ") == PERAN_SUPPORT
    assert peran_sah("SUPPORT ") == PERAN_SUPPORT


def test_daftar_izin_dibaca_dari_env():
    assert parse_daftar_izin("support") == frozenset({"support"})
    assert parse_daftar_izin("support, operator") == frozenset({"support", "operator"})
    assert parse_daftar_izin("") == frozenset()
    assert parse_daftar_izin("   ") == frozenset()


def test_peran_erp_di_luar_daftar_izin_jatuh_ke_operator():
    """Rem dari sisi pabrik: kosongkan .env dan ERP tidak bisa menaikkan siapa pun."""
    assert saring_peran_erp("support", frozenset()) == PERAN_OPERATOR
    assert saring_peran_erp("support", frozenset({"support"})) == PERAN_SUPPORT


def test_peran_erp_asing_tetap_jatuh_walau_daftar_izin_luas():
    assert saring_peran_erp("admin", frozenset({"admin"})) == PERAN_OPERATOR
```

- [ ] **Step 3: Jalankan tes, pastikan gagal**

Run: `cd autograde && pytest tests/unit/test_peran.py -v`
Expected: FAIL — `ModuleNotFoundError: palmgrade.domain.peran`

- [ ] **Step 4: Tulis implementasi minimal**

Create `src/palmgrade/domain/peran.py`:

```python
"""Dua peran akun konsol, dan penyaring untuk peran yang datang dari AutoERP.

Murni aturan, tanpa I/O — yang menyimpannya `console_repository`, yang menegakkannya
`routes/console.py`.

Sengaja hanya dua: dari lima layar developer tidak ada satu pun yang masuk akal
dibuka untuk yang satu tapi ditutup untuk yang lain. Peran ketiga akan jadi nama
kedua untuk hal yang sama, dan satu tempat lagi untuk salah setel.
"""

from __future__ import annotations

PERAN_OPERATOR = "operator"
PERAN_SUPPORT = "support"

_DIKENAL = frozenset({PERAN_OPERATOR, PERAN_SUPPORT})


def peran_sah(nilai: object) -> str:
    """Peran yang dikenal, atau `operator`.

    Apa pun yang aneh jatuh ke peran paling sempit, tidak pernah melempar: baris
    yang rusak harus tetap bisa login sebagai operator biasa, bukan mengunci
    layar pabrik.
    """
    if not isinstance(nilai, str):
        return PERAN_OPERATOR
    bersih = nilai.strip().lower()
    return bersih if bersih in _DIKENAL else PERAN_OPERATOR


def parse_daftar_izin(mentah: str) -> frozenset[str]:
    """`ERP_ALLOWED_ROLES` jadi himpunan peran yang boleh datang dari ERP."""
    if not mentah:
        return frozenset()
    return frozenset(
        bagian.strip().lower() for bagian in mentah.split(",") if bagian.strip()
    )


def saring_peran_erp(nilai: object, diizinkan: frozenset[str]) -> str:
    """Peran dari AutoERP, tapi hanya kalau PC ini mengizinkannya.

    Satu-satunya rem yang bisa ditarik dari sisi pabrik: kosongkan setelan, restart,
    dan tidak ada akun ERP yang bisa membuka layar developer — tanpa menunggu ERP
    dibereskan lebih dulu.
    """
    peran = peran_sah(nilai)
    return peran if peran in diizinkan else PERAN_OPERATOR
```

- [ ] **Step 5: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_peran.py -v && ruff check src/palmgrade/domain/peran.py tests/unit/test_peran.py`
Expected: 7 PASS, ruff bersih.

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/domain/peran.py tests/unit/test_peran.py
git commit -m "feat(konsol): aturan peran operator/support dan penyaring peran dari ERP"
```

---

## Task 3: Kolom `peran` di store

**Files:**
- Modify: `src/palmgrade/repositories/console_repository.py`
- Test: `tests/unit/test_console_store.py`

**Interfaces:**
- Consumes: `domain.peran.peran_sah`, `PERAN_OPERATOR`
- Produces:
  - Kolom `operators.peran TEXT NOT NULL DEFAULT 'operator'`
  - `ConsoleStore.operator_by_email()` dan `.session()` mengembalikan `peran`
  - `ConsoleStore.set_peran(operator_id: str, peran: str) -> None`

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan ke `tests/unit/test_console_store.py`:

```python
def test_operator_baru_default_operator(tmp_path):
    """Tidak ada akun yang naik hak karena migrasi."""
    store = ConsoleStore(tmp_path / "c.db")
    store.upsert_operator_lokal(
        {"email": "a@b.c", "nama": "A", "password_hash": "scrypt$x"}
    )
    assert store.operator_by_email("a@b.c")["peran"] == "operator"


def test_peran_ikut_di_baris_sesi(tmp_path):
    """Penjaga route membaca peran dari sesi, jadi sesi harus membawanya."""
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_lokal(
        {"email": "s@b.c", "nama": "S", "password_hash": "scrypt$x"}
    )
    store.set_peran(oid, "support")
    store.create_session("tok", oid, now=1000.0, ttl_s=3600)
    assert store.session("tok", now=1001.0)["peran"] == "support"


def test_migrasi_menambah_peran_ke_db_lama(tmp_path):
    """PC pabrik yang sudah jalan punya tabel tanpa kolom ini."""
    import sqlite3

    db_path = tmp_path / "lama.db"
    db = sqlite3.connect(str(db_path))
    db.execute(
        """CREATE TABLE operators (
               id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, nama TEXT NOT NULL,
               password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
               asal TEXT NOT NULL DEFAULT 'lokal', erp_name TEXT,
               dibuat_at REAL NOT NULL, gagal_count INTEGER NOT NULL DEFAULT 0,
               gagal_terakhir REAL)"""
    )
    db.execute(
        "INSERT INTO operators (id, email, nama, password_hash, dibuat_at)"
        " VALUES ('i1', 'lama@b.c', 'Lama', 'scrypt$x', 1.0)"
    )
    db.commit()
    db.close()

    store = ConsoleStore(db_path)
    assert store.operator_by_email("lama@b.c")["peran"] == "operator"


def test_set_peran_menolak_nilai_asing(tmp_path):
    """Nilai asing tidak boleh mengendap di kolom yang menjaga akses."""
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_lokal(
        {"email": "x@b.c", "nama": "X", "password_hash": "scrypt$x"}
    )
    store.set_peran(oid, "admin")
    assert store.operator_by_email("x@b.c")["peran"] == "operator"
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_console_store.py -k peran -v`
Expected: FAIL — `no such column: peran` / `AttributeError: set_peran`

- [ ] **Step 3: Tambah kolom ke skema**

Di `_CREATE_SQL`, dalam `CREATE TABLE IF NOT EXISTS operators`, sesudah baris `erp_name TEXT,`:

```sql
    -- `operator` atau `support`. Yang menegakkan ini route, bukan kolomnya:
    -- sengaja tanpa CHECK, supaya peran ketiga nanti tidak butuh migrasi tabel.
    peran          TEXT NOT NULL DEFAULT 'operator',
```

- [ ] **Step 4: Tambah pass migrasi**

Di `_migrate()`, sesudah loop `for table, column in (...)`, sebelum `self._db.executescript(_MIGRATE_SQL)`:

```python
        # Sendiri, bukan lewat loop di atas: loop itu hanya bisa `ADD COLUMN ... TEXT`
        # polos, sementara kolom ini butuh NOT NULL + DEFAULT supaya baris lama langsung
        # terisi `operator` alih-alih NULL yang harus ditebak pembacanya.
        kolom_operator = {r["name"] for r in self._db.execute("PRAGMA table_info(operators)")}
        if "peran" not in kolom_operator:
            self._db.execute(
                "ALTER TABLE operators ADD COLUMN peran TEXT NOT NULL DEFAULT 'operator'"
            )
```

- [ ] **Step 5: Sertakan `peran` di query pembaca**

Tambahkan `peran` ke daftar kolom `SELECT` pada `operator_by_email()`, `operator()`, dan `session()`. Untuk `session()`, kolomnya diambil dari join ke `operators` — tambahkan `o.peran`.

- [ ] **Step 6: Tulis `set_peran`**

Tambahkan method di `ConsoleStore`:

```python
    def set_peran(self, operator_id: str, peran: str) -> None:
        """Setel peran satu akun. Nilai asing disimpan sebagai `operator`.

        Disaring di sini, bukan dipercaya dari pemanggil: kolom ini yang menentukan
        siapa boleh membuka layar yang menggerakkan piston.
        """
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET peran = ? WHERE id = ?",
                (peran_sah(peran), operator_id),
            )
```

Tambahkan import di atas berkas: `from ..domain.peran import peran_sah`

- [ ] **Step 7: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_console_store.py -v && ruff check src/palmgrade/repositories/console_repository.py`
Expected: semua PASS, ruff bersih.

- [ ] **Step 8: Commit**

```bash
git add src/palmgrade/repositories/console_repository.py tests/unit/test_console_store.py
git commit -m "feat(konsol): kolom peran di operators, dengan migrasi untuk DB lama"
```

---

## Task 4: Seed akun support dengan peran

**Files:**
- Modify: `src/palmgrade/services/akun_bawaan.py`
- Test: `tests/unit/test_akun_bawaan.py`

**Interfaces:**
- Consumes: `ConsoleStore.set_peran`, `domain.peran.PERAN_SUPPORT`
- Produces: `support@autograde.local` selalu ber-`peran='support'`, termasuk di PC yang akunnya sudah ada sebelum kolom ini lahir.

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan ke `tests/unit/test_akun_bawaan.py`:

```python
def test_akun_support_dibuat_dengan_peran_support(tmp_path):
    store = ConsoleStore(tmp_path / "c.db")
    seed_akun_bawaan(store, hash_bawaan="scrypt$a", hash_support="scrypt$b")
    assert store.operator_by_email(EMAIL_SUPPORT)["peran"] == "support"
    assert store.operator_by_email(EMAIL_BAWAAN)["peran"] == "operator"


def test_akun_support_lama_dinaikkan_tanpa_menyentuh_sandi(tmp_path):
    """PC pabrik sudah punya akun support dari image sebelum kolom peran ada.

    Perannya harus naik, tapi sandinya tidak boleh kembali ke bawaan pabrik —
    aturan yang sama dengan alasan seed tidak pernah menimpa akun yang ada.
    """
    store = ConsoleStore(tmp_path / "c.db")
    store.upsert_operator_lokal(
        {"email": EMAIL_SUPPORT, "nama": "Support", "password_hash": "scrypt$sandi-mill"}
    )
    seed_akun_bawaan(store, hash_bawaan="scrypt$a", hash_support="scrypt$b")
    row = store.operator_by_email(EMAIL_SUPPORT)
    assert row["peran"] == "support"
    assert row["password_hash"] == "scrypt$sandi-mill"
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_akun_bawaan.py -v`
Expected: FAIL — peran masih `operator`.

- [ ] **Step 3: Tulis implementasi**

Di `akun_bawaan.py`, ubah `seed_akun_bawaan` supaya menaikkan peran terpisah dari pembuatan:

```python
def seed_akun_bawaan(
    store: ConsoleStore, *, hash_bawaan: str, hash_support: str
) -> list[str]:
    """Create whichever of the two accounts is missing. Returns the emails created.

    Never touches an account that already exists — not its password, not its status.
    A container restarts for all sorts of reasons, and a restart that quietly restored
    the factory password would undo every password the mill had changed, on exactly the
    accounts whose passwords are identical across images.
    """
    dibuat = []
    for email, nama, hash_sandi in (
        (EMAIL_BAWAAN, _NAMA_BAWAAN, hash_bawaan),
        (EMAIL_SUPPORT, _NAMA_SUPPORT, hash_support),
    ):
        if _buat_kalau_belum_ada(store, email, nama, hash_sandi):
            dibuat.append(email)
    _pastikan_peran_support(store)
    return dibuat


def _pastikan_peran_support(store: ConsoleStore) -> None:
    """Naikkan akun support, juga di PC yang sudah punya akun itu sejak sebelum
    kolom `peran` ada.

    Terpisah dari pembuatan dan hanya menyentuh `peran`: akun yang sudah ada tidak
    boleh kehilangan sandi yang sudah diganti pabrik — alasan yang sama dengan
    kenapa seed tidak pernah meng-upsert ulang.
    """
    row = store.operator_by_email(EMAIL_SUPPORT)
    if row is not None and row["peran"] != PERAN_SUPPORT:
        store.set_peran(row["id"], PERAN_SUPPORT)
```

Tambahkan import: `from ..domain.peran import PERAN_SUPPORT`

- [ ] **Step 4: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_akun_bawaan.py -v && ruff check src/palmgrade/services/akun_bawaan.py`
Expected: PASS, ruff bersih.

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/services/akun_bawaan.py tests/unit/test_akun_bawaan.py
git commit -m "feat(konsol): akun support bawaan selalu berperan support"
```

---

## Task 5: Tarik peran dari AutoERP, disaring daftar izin

**Files:**
- Modify: `src/palmgrade/core/config.py`
- Modify: `src/palmgrade/domain/erp_master.py:32-55` (`operator_row`)
- Modify: `src/palmgrade/workers/master_data_worker.py:66-70`
- Modify: `src/palmgrade/repositories/console_repository.py` (`_upsert_operator`)
- Test: `tests/unit/test_erp_master_data.py`, `tests/unit/test_console_store.py`

**Interfaces:**
- Consumes: `domain.peran.saring_peran_erp`, `parse_daftar_izin`
- Produces:
  - `Settings.erp_allowed_roles: str` (bawaan `"support"`)
  - `operator_row()` mengembalikan kunci `peran`
  - `upsert_operator_erp` menulis peran; akun `asal='lokal'` tidak tersentuh

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan ke `tests/unit/test_erp_master_data.py`:

```python
def test_operator_row_membawa_peran():
    row = operator_row(
        {"name": "a@b.c", "email": "a@b.c", "full_name": "A",
         "password_hash": "x", "active": 1, "peran": "support"}
    )
    assert row["peran"] == "support"


def test_operator_row_tanpa_peran_jadi_operator():
    """ERP lama, atau dokumen yang field-nya belum terisi."""
    row = operator_row({"name": "a@b.c", "email": "a@b.c", "full_name": "A"})
    assert row["peran"] == "operator"
```

Tambahkan ke `tests/unit/test_console_store.py`:

```python
def test_tarikan_erp_menulis_peran_yang_diizinkan(tmp_path):
    store = ConsoleStore(tmp_path / "c.db", erp_allowed_roles=frozenset({"support"}))
    store.upsert_operator_erp(
        {"email": "s@erp.c", "nama": "S", "password_hash": "x",
         "erp_name": "s@erp.c", "active": 1, "peran": "support"}
    )
    assert store.operator_by_email("s@erp.c")["peran"] == "support"


def test_daftar_izin_kosong_membuang_peran_dari_erp(tmp_path):
    """Rem sisi pabrik: kosongkan .env, restart, tidak ada akun ERP yang naik."""
    store = ConsoleStore(tmp_path / "c.db", erp_allowed_roles=frozenset())
    store.upsert_operator_erp(
        {"email": "s@erp.c", "nama": "S", "password_hash": "x",
         "erp_name": "s@erp.c", "active": 1, "peran": "support"}
    )
    assert store.operator_by_email("s@erp.c")["peran"] == "operator"


def test_tarikan_erp_tidak_menurunkan_peran_akun_lokal(tmp_path):
    """Akun lokal adalah jalan masuk saat internet mati; ERP tidak boleh menyentuhnya."""
    store = ConsoleStore(tmp_path / "c.db", erp_allowed_roles=frozenset({"support"}))
    oid = store.upsert_operator_lokal(
        {"email": "support@autograde.local", "nama": "S", "password_hash": "scrypt$x"}
    )
    store.set_peran(oid, "support")
    store.upsert_operator_erp(
        {"email": "support@autograde.local", "nama": "S", "password_hash": "y",
         "erp_name": "s", "active": 1, "peran": "operator"}
    )
    assert store.operator_by_email("support@autograde.local")["peran"] == "support"
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_erp_master_data.py tests/unit/test_console_store.py -k peran -v`
Expected: FAIL — `KeyError: 'peran'` / `TypeError: unexpected keyword 'erp_allowed_roles'`

- [ ] **Step 3: Tambah setelan**

Di `core/config.py`, dalam kelas `Settings`:

```python
    # Peran mana yang boleh datang dari AutoERP. Kosongkan untuk menolak semuanya —
    # satu-satunya rem yang bisa ditarik dari sisi pabrik kalau akun ERP bermasalah,
    # tanpa menunggu ERP dibereskan lebih dulu.
    erp_allowed_roles: str = "support"
```

Teruskan juga di `docker-compose.yml`, service `console`, di dekat blok `ERP_*`
(pola yang sama dengan `ERP_COMPANY` di baris ~396):

```yaml
      - ERP_ALLOWED_ROLES=${ERP_ALLOWED_ROLES:-support}
```

dan tambahkan barisnya ke `.env.example`. Tanpa ini
`tests/unit/test_console_compose_env.py` gagal.

- [ ] **Step 4: `operator_row` membawa peran**

Di `domain/erp_master.py`, pada dict yang dikembalikan `operator_row`, sebelum baris `"active"`:

```python
        # Mentah dari ERP; store yang menyaringnya lewat daftar izin PC ini.
        "peran": doc.get("peran") or "",
```

- [ ] **Step 5: Minta field-nya saat menarik**

Di `workers/master_data_worker.py` baris 67, tambahkan `"peran"` ke tuple `fields`:

```python
        fields=("name", "email", "full_name", "active", "password_hash", "peran", "modified"),
```

⚠️ Ini yang membuat PR 0 wajib merge duluan — Frappe membalas 417 untuk field asing.

- [ ] **Step 6: Store menyaring dan menulis peran**

Di `ConsoleStore.__init__`, tambah parameter:

```python
    def __init__(
        self,
        db_path: Path,
        *,
        erp_allowed_roles: frozenset[str] | None = None,
    ) -> None:
```

dan simpan: `self._erp_allowed_roles = erp_allowed_roles or frozenset()`

Di `_upsert_operator`, saat `asal == "erp"`, hitung peran lewat `saring_peran_erp(row.get("peran"), self._erp_allowed_roles)` dan sertakan di `INSERT`. Pada cabang `UPDATE` untuk baris yang sudah ada, peran **hanya** ditimpa kalau baris target `asal='erp'` — baris `lokal` tidak tersentuh, sejalan dengan `overwrite_asal` yang sudah ada.

Di `routes/console.py` `get_console_service()`, teruskan setelan:

```python
    store = ConsoleStore(
        settings.console_db_path,
        erp_allowed_roles=parse_daftar_izin(settings.erp_allowed_roles),
    )
```

- [ ] **Step 7: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/ -v && ruff check src/palmgrade/`
Expected: semua PASS, ruff bersih.

- [ ] **Step 8: Commit**

```bash
git add src/palmgrade/core/config.py src/palmgrade/domain/erp_master.py \
        src/palmgrade/workers/master_data_worker.py \
        src/palmgrade/repositories/console_repository.py \
        src/palmgrade/routes/console.py tests/unit/
git commit -m "feat(konsol): tarik peran dari AutoERP, disaring daftar izin PC"
```

---

## Task 6: Penjaga route `require_support` + `me` membawa peran

**Files:**
- Modify: `src/palmgrade/routes/console.py:60-75`
- Modify: `src/palmgrade/domain/operator_error.py`
- Test: `tests/unit/test_console_routes_auth.py`

**Interfaces:**
- Consumes: `require_operator`, `domain.peran.PERAN_SUPPORT`
- Produces:
  - `require_support(operator: Operator) -> dict` — 403 `bukan_support` kalau bukan
  - `Support = Annotated[dict, Depends(require_support)]` — dipakai Task 8, 11, 12, 13
  - `/api/console/me` mengembalikan `peran`

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan ke `tests/unit/test_console_routes_auth.py`:

```python
def test_lane_support_menolak_operator_biasa():
    """Yang menjaga backend, bukan tab yang disembunyikan."""
    app, store = _app_dengan_store()
    oid = store.upsert_operator_lokal(
        {"email": "o@b.c", "nama": "O", "password_hash": "scrypt$x"}
    )
    store.create_session("tok-op", oid, now=time.time(), ttl_s=3600)
    client = TestClient(app)
    client.cookies.set("konsol_sesi", "tok-op")
    assert client.get("/api/console/dev/ping").status_code == 403


def test_lane_support_menerima_akun_support():
    app, store = _app_dengan_store()
    oid = store.upsert_operator_lokal(
        {"email": "s@b.c", "nama": "S", "password_hash": "scrypt$x"}
    )
    store.set_peran(oid, "support")
    store.create_session("tok-sup", oid, now=time.time(), ttl_s=3600)
    client = TestClient(app)
    client.cookies.set("konsol_sesi", "tok-sup")
    assert client.get("/api/console/dev/ping").status_code == 200


def test_lane_support_tanpa_sesi_tetap_401():
    """Belum masuk dijawab 401, bukan 403 — bedanya kelihatan di layar."""
    app, _ = _app_dengan_store()
    assert TestClient(app).get("/api/console/dev/ping").status_code == 401


def test_me_membawa_peran():
    app, store = _app_dengan_store()
    oid = store.upsert_operator_lokal(
        {"email": "s@b.c", "nama": "S", "password_hash": "scrypt$x"}
    )
    store.set_peran(oid, "support")
    store.create_session("tok", oid, now=time.time(), ttl_s=3600)
    client = TestClient(app)
    client.cookies.set("konsol_sesi", "tok")
    assert client.get("/api/console/me").json()["operator"]["peran"] == "support"
```

Kalau helper `_app_dengan_store()` belum ada di berkas itu, tulis satu yang merakit `APIRouter` konsol dengan `get_auth_service`/`get_console_service` di-override ke store `tmp_path` — **bukan** `create_console_app()`.

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_console_routes_auth.py -v`
Expected: FAIL — 404 (route `dev/ping` belum ada).

- [ ] **Step 3: Tambah kode galat**

Di `domain/operator_error.py`, sebelah `BELUM_MASUK`:

```python
BUKAN_SUPPORT = "bukan_support"
```

⚠️ **Tambahkan juga ke tuple `CODES` di berkas yang sama, dan ke KAMUS `id` dan `en`
di `console.html`** (`err_bukan_support:"..."`). `tests/unit/test_console_html.py::
test_setiap_kode_error_operator_diterjemahkan_di_kedua_bahasa` memaksa tiap kode
punya terjemahan di kedua bahasa; pesan galat dirangkai di layar dari kodenya, jadi
kode tanpa terjemahan muncul sebagai teks mentah di depan operator.

- [ ] **Step 4: Tulis penjaga dan route ping**

Di `routes/console.py`, sesudah `Operator = Annotated[...]`:

```python
def require_support(operator: Operator) -> dict:
    """Akun support, atau 403.

    Ini yang menjaga layar developer — menyembunyikan tabnya di `console.html` cuma
    merapikan layar operator yang dibaca dari beberapa meter, bukan pengaman. Semua
    lane `/api/console/dev/*` lewat sini, satu tempat, supaya tidak ada yang lupa.
    """
    if operator.get("peran") != PERAN_SUPPORT:
        raise _operator_error(
            403, OperatorError(BUKAN_SUPPORT, "menu ini untuk akun support")
        )
    return operator


Support = Annotated[dict, Depends(require_support)]
```

Tambahkan route paling bawah, di grup lane developer:

```python
@router.get("/api/console/dev/ping")
async def dev_ping(operator: Support) -> dict:
    """Lane developer paling ringan — dipakai layar untuk memastikan aksesnya hidup."""
    return {"status": "ok"}
```

Import: `from ..domain.peran import PERAN_SUPPORT` dan tambahkan `BUKAN_SUPPORT` ke import `operator_error`.

- [ ] **Step 5: `me` membawa peran**

Di `console_me`, tambahkan `"peran": operator["peran"],` ke dict `operator` yang dikembalikan.

- [ ] **Step 6: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_console_routes_auth.py -v && ruff check src/palmgrade/routes/console.py`
Expected: PASS, ruff bersih.

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/routes/console.py src/palmgrade/domain/operator_error.py tests/unit/
git commit -m "feat(konsol): penjaga lane support 403 dan peran di /me"
```

---

## Task 7: Kerangka tab developer di layar

**Files:**
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/unit/test_console_html.py`

**Interfaces:**
- Consumes: `/api/console/me` → `operator.peran`
- Produces: elemen `<nav id="tabs">` menumbuhkan tab ber-`data-dev="1"`, dirender hanya kalau peran `support`.

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan ke `tests/unit/test_console_html.py`:

```python
def test_tab_developer_ditandai_data_dev():
    html = _console_html()
    assert 'data-dev="1"' in html


def test_tab_developer_disembunyikan_default():
    """Tanpa peran support, tab developer tidak boleh ada di layar operator."""
    html = _console_html()
    assert "hapusTabDeveloper" in html or "renderTabDeveloper" in html


def test_konsol_tetap_tanpa_referensi_https():
    """Invarian lama: konsol harus jalan saat internet putus."""
    assert "https://" not in _console_html()
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_console_html.py -v`
Expected: FAIL pada dua tes pertama.

- [ ] **Step 3: Tambah tab ke nav**

Di `console.html` baris ~534, sesudah tab `rekap`:

```html
  <button data-tab="log" data-dev="1" data-t="judulLog">Log</button>
  <button data-tab="diagnostik" data-dev="1" data-t="judulDiagnostik">Diagnostik</button>
  <button data-tab="antrean" data-dev="1" data-t="judulAntrean">Antrean ERP</button>
  <button data-tab="versi" data-dev="1" data-t="judulVersi">Versi</button>
  <button data-tab="plc" data-dev="1" data-t="judulPlc">Uji PLC</button>
```

Tambahkan lima kunci itu ke objek terjemahan (baris ~676): `judulLog:"Log"`, `judulDiagnostik:"Diagnostik"`, `judulAntrean:"Antrean ERP"`, `judulVersi:"Versi"`, `judulPlc:"Uji PLC"`.

- [ ] **Step 4: Hapus tab kalau bukan support**

Di tempat `/api/console/me` dibaca (baris ~1602, `tutupGerbang`):

```js
function hapusTabDeveloper(peran) {
  // Dibuang dari DOM, bukan disembunyikan: layar operator dibaca dari beberapa
  // meter di luar ruangan, dan tab mati cuma mempersempit yang dipakai. Yang
  // menjaga aksesnya tetap backend — ini kerapian, bukan pengaman.
  if (peran === "support") return;
  document.querySelectorAll('[data-dev="1"]').forEach((el) => el.remove());
}
```

Panggil `hapusTabDeveloper(operator.peran)` sesudah `tutupGerbang(...)`.

- [ ] **Step 5: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_console_html.py -v`
Expected: PASS.

- [ ] **Step 6: Periksa dengan mata**

```bash
make console    # 127.0.0.1:8100
```

⚠️ `make console` memakai `WEBHOOK_SECRET=devsecret` dan **tanpa `--reload`** — ubah HTML lalu jalankan ulang, jangan menunggu auto-reload.

Masuk sebagai `operator@autograde.local` → lima tab **tidak** terlihat. Masuk sebagai `support@autograde.local` → lima tab terlihat.

- [ ] **Step 7: Commit dan PR 1**

```bash
git add src/palmgrade/static/console.html tests/unit/test_console_html.py
git commit -m "feat(konsol): kerangka tab developer, dibuang untuk akun operator"
git push -u origin feat/konsol-peran-support
gh pr create --base staging --title "feat(console): add a support role and the developer tab scaffold" \
  --body "Splits mill operators from whoever handles faults, so the diagnostic screens that follow have something to hang on.

- \`operators.peran\` (operator/support), migrated for factory databases that predate it
- \`require_support\` → 403; the hidden tabs are tidiness, the guard is the backend
- roles pulled from AutoERP, filtered by \`ERP_ALLOWED_ROLES\` (default \`support\`) — the one brake that can be pulled from the mill side
- local accounts are never touched by a pull, so a mill with no internet keeps its way in

Needs delta-anugrah/autoerp#<N> merged first: Frappe answers 417 for one unknown field."
```

---

## Task 8: Penyaring rahasia untuk log (domain murni)

**Files:**
- Create: `src/palmgrade/domain/log_redaksi.py`
- Test: `tests/unit/test_log_redaksi.py`

**Interfaces:**
- Consumes: —
- Produces: `redaksi(teks: str) -> str` — menutup nilai di dekat kata kunci rahasia.

- [ ] **Step 1: Branch dari staging**

```bash
git checkout staging && git pull
git checkout -b feat/konsol-log-kejadian
```

- [ ] **Step 2: Tulis tes yang gagal**

Create `tests/unit/test_log_redaksi.py`:

```python
from palmgrade.domain.log_redaksi import redaksi


def test_sandi_ditutup():
    assert "rahasia123" not in redaksi("login gagal: password=rahasia123")


def test_token_ditutup_dalam_json():
    keluar = redaksi('{"token": "abc.def.ghi", "line": "line-1"}')
    assert "abc.def.ghi" not in keluar
    assert "line-1" in keluar, "yang bukan rahasia harus tetap kebaca"


def test_hash_sandi_ditutup():
    assert "$pbkdf2-sha256$29000$xyz" not in redaksi(
        "hash mismatch for password_hash=$pbkdf2-sha256$29000$xyz"
    )


def test_header_authorization_ditutup():
    assert "Bearer eyJhbGci" not in redaksi("Authorization: Bearer eyJhbGci")


def test_pesan_biasa_tidak_berubah():
    """Penyaring yang terlalu rakus bikin log tidak berguna."""
    pesan = "kamera line-2 putus setelah 43 detik, retry 3"
    assert redaksi(pesan) == pesan


def test_teks_kosong_aman():
    assert redaksi("") == ""
```

- [ ] **Step 3: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_log_redaksi.py -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 4: Tulis implementasi**

Create `src/palmgrade/domain/log_redaksi.py`:

```python
"""Menutup rahasia sebelum sebuah baris log mengendap 180 hari di disk.

Pesan galat sering memuat potongan payload, dan log ini dibaca lewat AnyDesk di PC
yang dipegang banyak orang. Murni teks masuk teks keluar — tidak tahu apa-apa soal
SQLite maupun logging.
"""

from __future__ import annotations

import re

_KUNCI = "password|sandi|password_hash|token|secret|authorization|api_key|x-webhook-secret"

# `kunci=nilai`, `kunci: nilai`, dan bentuk JSON `"kunci": "nilai"`. Nilainya
# berhenti di pemisah supaya sisa barisnya tetap terbaca — log yang seluruhnya
# ditutup sama tidak bergunanya dengan log yang membocorkan.
_POLA = re.compile(
    rf'(?i)(["\']?(?:{_KUNCI})["\']?\s*[:=]\s*)(["\']?)([^\s,;}}\'"]+)(\2)'
)

_TUTUP = "«ditutup»"


def redaksi(teks: str) -> str:
    """Kembalikan `teks` dengan nilai rahasia diganti penanda."""
    if not teks:
        return teks
    return _POLA.sub(rf"\1\2{_TUTUP}\4", teks)
```

- [ ] **Step 5: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_log_redaksi.py -v && ruff check src/palmgrade/domain/log_redaksi.py`
Expected: 6 PASS, ruff bersih.

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/domain/log_redaksi.py tests/unit/test_log_redaksi.py
git commit -m "feat(konsol): penyaring rahasia untuk baris log"
```

---

## Task 9: Store `log_kejadian`

**Files:**
- Create: `src/palmgrade/repositories/log_repository.py`
- Test: `tests/unit/test_log_store.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `LogStore(db_path: Path, *, retensi_hari: int = 180)`
  - `.tulis(level: str, sumber: str, pesan: str, detail: str | None, now: float) -> None`
  - `.baca(level: str | None, cari: str | None, limit: int, offset: int) -> dict` → `{"items": [...], "total": int}`
  - `.buang_kedaluwarsa(now: float) -> int`

- [ ] **Step 1: Tulis tes yang gagal**

Create `tests/unit/test_log_store.py`:

```python
from palmgrade.repositories.log_repository import LogStore

SEJAM = 3600.0


def test_baris_tersimpan_dan_terbaca(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.tulis("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    hasil = store.baca(level=None, cari=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["pesan"] == "line-2 putus"
    assert hasil["items"][0]["jumlah"] == 1


def test_pesan_kembar_digabung_bukan_ditumpuk(tmp_path):
    """Kabel kamera putus bikin error tiap detik; 347 baris identik tidak kebaca."""
    store = LogStore(tmp_path / "log.db")
    for i in range(5):
        store.tulis("ERROR", "kamera", "line-2 putus", None, now=1000.0 + i)
    hasil = store.baca(level=None, cari=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["jumlah"] == 5
    assert hasil["items"][0]["terakhir_at"] == 1004.0


def test_kembar_di_luar_jendela_jadi_baris_baru(tmp_path):
    """Kejadian yang sama besok bukan kejadian yang sama."""
    store = LogStore(tmp_path / "log.db")
    store.tulis("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    store.tulis("ERROR", "kamera", "line-2 putus", None, now=1000.0 + 61)
    assert store.baca(level=None, cari=None, limit=10, offset=0)["total"] == 2


def test_sumber_berbeda_tidak_digabung(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.tulis("ERROR", "kamera", "putus", None, now=1000.0)
    store.tulis("ERROR", "plc", "putus", None, now=1001.0)
    assert store.baca(level=None, cari=None, limit=10, offset=0)["total"] == 2


def test_saring_level(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.tulis("ERROR", "a", "satu", None, now=1000.0)
    store.tulis("WARNING", "b", "dua", None, now=1001.0)
    assert store.baca(level="ERROR", cari=None, limit=10, offset=0)["total"] == 1


def test_cari_di_pesan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.tulis("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    store.tulis("ERROR", "plc", "modbus timeout", None, now=1001.0)
    hasil = store.baca(level=None, cari="modbus", limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["sumber"] == "plc"


def test_total_hitungan_seluruh_kecocokan_bukan_sepanjang_halaman(tmp_path):
    """Jebakan yang sama dengan pagination grading: total datang dari SQL."""
    store = LogStore(tmp_path / "log.db")
    for i in range(25):
        store.tulis("ERROR", f"s{i}", f"pesan {i}", None, now=1000.0 + i * 100)
    hasil = store.baca(level=None, cari=None, limit=10, offset=0)
    assert hasil["total"] == 25
    assert len(hasil["items"]) == 10


def test_terbaru_di_atas(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.tulis("ERROR", "a", "lama", None, now=1000.0)
    store.tulis("ERROR", "b", "baru", None, now=2000.0)
    assert store.baca(level=None, cari=None, limit=10, offset=0)["items"][0]["pesan"] == "baru"


def test_baris_lewat_retensi_dibuang(tmp_path):
    store = LogStore(tmp_path / "log.db", retensi_hari=180)
    lama = 1000.0
    store.tulis("ERROR", "a", "lama", None, now=lama)
    sekarang = lama + 181 * 24 * SEJAM
    store.tulis("ERROR", "b", "baru", None, now=sekarang)
    assert store.buang_kedaluwarsa(now=sekarang) == 1
    hasil = store.baca(level=None, cari=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["pesan"] == "baru"


def test_baris_dalam_retensi_tidak_dibuang(tmp_path):
    store = LogStore(tmp_path / "log.db", retensi_hari=180)
    store.tulis("ERROR", "a", "masih muda", None, now=1000.0)
    assert store.buang_kedaluwarsa(now=1000.0 + 179 * 24 * SEJAM) == 0
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_log_store.py -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Tulis implementasi**

Create `src/palmgrade/repositories/log_repository.py`:

```python
"""Riwayat ERROR/WARNING yang tahan restart, untuk layar Log support.

Berkas SQLite sendiri, bukan tabel di `console.db`: yang menulisnya sebuah logging
handler yang bisa dipanggil dari thread mana pun, dan menaruhnya di satu lock dengan
query yang melayani layar operator berarti sebuah banjir error ikut memperlambat
layar itu. Konvensinya tetap sama dengan store lain — WAL, `synchronous=FULL`, satu
lock.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS log_kejadian (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    waktu       REAL NOT NULL,
    level       TEXT NOT NULL,
    sumber      TEXT NOT NULL,
    pesan       TEXT NOT NULL,
    detail      TEXT,
    sidik       TEXT NOT NULL,
    jumlah      INTEGER NOT NULL DEFAULT 1,
    terakhir_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_waktu ON log_kejadian (waktu DESC);
CREATE INDEX IF NOT EXISTS idx_log_sidik ON log_kejadian (sidik, terakhir_at DESC);
"""

# Sejendela ini pesan identik dihitung, bukan ditumpuk. Cukup panjang untuk
# meredam banjir error per detik, cukup pendek supaya kejadian besok tetap
# terbaca sebagai kejadian tersendiri.
JENDELA_GABUNG_S = 60.0

_SEHARI_S = 86400.0


class LogStore:
    def __init__(self, db_path: Path, *, retensi_hari: int = 180) -> None:
        self._retensi_s = retensi_hari * _SEHARI_S
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)

    def tulis(
        self, level: str, sumber: str, pesan: str, detail: str | None, *, now: float
    ) -> None:
        """Catat satu kejadian, atau naikkan penghitung kalau ia kembar yang baru saja lewat."""
        sidik = _sidik(level, sumber, pesan)
        with self._lock, self._db:
            baris = self._db.execute(
                "SELECT id FROM log_kejadian"
                " WHERE sidik = ? AND terakhir_at >= ?"
                " ORDER BY terakhir_at DESC LIMIT 1",
                (sidik, now - JENDELA_GABUNG_S),
            ).fetchone()
            if baris is not None:
                self._db.execute(
                    "UPDATE log_kejadian SET jumlah = jumlah + 1, terakhir_at = ?"
                    " WHERE id = ?",
                    (now, baris["id"]),
                )
                return
            self._db.execute(
                "INSERT INTO log_kejadian"
                " (waktu, level, sumber, pesan, detail, sidik, jumlah, terakhir_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (now, level, sumber, pesan, detail, sidik, now),
            )

    def baca(
        self, *, level: str | None, cari: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        """Satu halaman, terbaru di atas, plus `total` seluruh yang cocok filter.

        `total` datang dari SQL sendiri, bukan `len(items)`: halaman terakhir akan
        melaporkan jumlah yang salah dan layar berhenti di tengah riwayat.
        """
        syarat, args = [], []
        if level:
            syarat.append("level = ?")
            args.append(level)
        if cari:
            syarat.append("(pesan LIKE ? OR sumber LIKE ?)")
            args.extend([f"%{cari}%", f"%{cari}%"])
        where = f" WHERE {' AND '.join(syarat)}" if syarat else ""

        with self._lock:
            total = self._db.execute(
                f"SELECT COUNT(*) AS n FROM log_kejadian{where}", args
            ).fetchone()["n"]
            rows = self._db.execute(
                f"SELECT * FROM log_kejadian{where}"
                " ORDER BY terakhir_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    def buang_kedaluwarsa(self, *, now: float) -> int:
        """Buang baris yang lewat masa simpan. Kembalikan berapa yang terbuang.

        Batas waktu, bukan batas jumlah baris: batas jumlah membuang justru log lama
        yang penting persis saat error sedang membanjir.
        """
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM log_kejadian WHERE terakhir_at < ?", (now - self._retensi_s,)
            )
            return cur.rowcount


def _sidik(level: str, sumber: str, pesan: str) -> str:
    return hashlib.sha256(f"{level}|{sumber}|{pesan}".encode()).hexdigest()[:32]
```

- [ ] **Step 4: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_log_store.py -v && ruff check src/palmgrade/repositories/log_repository.py`
Expected: 10 PASS, ruff bersih.

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/repositories/log_repository.py tests/unit/test_log_store.py
git commit -m "feat(konsol): store log_kejadian dengan penggabungan dan retensi"
```

---

## Task 10: Logging handler → LogStore

**Files:**
- Create: `src/palmgrade/core/log_sink.py`
- Modify: `src/palmgrade/core/config.py`
- Modify: `src/palmgrade/console_main.py`
- Test: `tests/unit/test_log_sink.py`

**Interfaces:**
- Consumes: `LogStore`, `domain.log_redaksi.redaksi`
- Produces:
  - `SqliteLogHandler(store: LogStore, now=time.time)` — `logging.Handler`
  - `pasang_log_sink(store: LogStore) -> SqliteLogHandler`
  - `Settings.log_retensi_hari: int = 180`

- [ ] **Step 1: Tulis tes yang gagal**

Create `tests/unit/test_log_sink.py`:

```python
import logging

from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.repositories.log_repository import LogStore


def _logger_dengan_handler(store, nama):
    log = logging.getLogger(nama)
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.addHandler(SqliteLogHandler(store))
    log.propagate = False
    return log


def test_error_tersimpan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_dengan_handler(store, "t.error").error("kamera putus")
    hasil = store.baca(level=None, cari=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["level"] == "ERROR"


def test_warning_tersimpan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_dengan_handler(store, "t.warn").warning("antrean menumpuk")
    assert store.baca(level="WARNING", cari=None, limit=10, offset=0)["total"] == 1


def test_info_tidak_tersimpan(tmp_path):
    """INFO terlalu berisik; log yang penuh INFO menenggelamkan sebab."""
    store = LogStore(tmp_path / "log.db")
    log = _logger_dengan_handler(store, "t.info")
    log.info("frame diproses")
    log.debug("detail")
    assert store.baca(level=None, cari=None, limit=10, offset=0)["total"] == 0


def test_sandi_tidak_pernah_mendarat_di_disk(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_dengan_handler(store, "t.rahasia").error("gagal: password=rahasia123")
    items = store.baca(level=None, cari=None, limit=10, offset=0)["items"]
    assert "rahasia123" not in items[0]["pesan"]


def test_traceback_masuk_detail(tmp_path):
    store = LogStore(tmp_path / "log.db")
    log = _logger_dengan_handler(store, "t.exc")
    try:
        raise ValueError("pecah")
    except ValueError:
        log.exception("worker jatuh")
    items = store.baca(level=None, cari=None, limit=10, offset=0)["items"]
    assert "ValueError" in items[0]["detail"]


def test_store_yang_gagal_tidak_menjatuhkan_pemanggil(tmp_path):
    """Log itu alat bantu; ia tidak boleh jadi sebab baru matinya line."""

    class StoreRusak:
        def tulis(self, *a, **k):
            raise RuntimeError("disk penuh")

    log = logging.getLogger("t.rusak")
    log.handlers.clear()
    log.addHandler(SqliteLogHandler(StoreRusak()))
    log.propagate = False
    log.error("tetap harus balik dengan selamat")  # tidak boleh melempar
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_log_sink.py -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Tulis implementasi**

Create `src/palmgrade/core/log_sink.py`:

```python
"""Jembatan `logging` → `log_kejadian`, supaya sebuah galat bertahan melewati restart.

Yang paling sering terjadi di pabrik adalah "tadi error, saya restart, sekarang
normal" — dan persis di situ `docker logs` sudah kosong. Handler ini yang membuat
jejaknya masih ada saat seseorang akhirnya masuk lewat AnyDesk.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from ..domain.log_redaksi import redaksi

_LEVEL_DISIMPAN = frozenset({"ERROR", "CRITICAL", "WARNING"})


class SqliteLogHandler(logging.Handler):
    """Tulis ERROR/WARNING ke `LogStore`. Tidak pernah melempar ke pemanggil."""

    def __init__(self, store: Any, *, now=time.time) -> None:
        super().__init__(level=logging.WARNING)
        self._store = store
        self._now = now
        self._sudah_mengeluh = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelname not in _LEVEL_DISIMPAN:
            return
        try:
            detail = (
                self.format_exception(record) if record.exc_info else None
            )
            self._store.tulis(
                "ERROR" if record.levelname == "CRITICAL" else record.levelname,
                record.name,
                redaksi(record.getMessage()),
                redaksi(detail) if detail else None,
                now=self._now(),
            )
        except Exception:
            # Sengaja ditelan: line tidak boleh mati karena alat bantunya gagal.
            # Dikeluhkan sekali ke stderr supaya kegagalan permanen tetap terlihat
            # di `docker logs`, bukan senyap selamanya.
            if not self._sudah_mengeluh:
                self._sudah_mengeluh = True
                print(
                    "log_kejadian tidak bisa ditulis; layar Log akan kosong",
                    file=sys.stderr,
                )

    @staticmethod
    def format_exception(record: logging.LogRecord) -> str:
        import traceback

        return "".join(traceback.format_exception(*record.exc_info))


def pasang_log_sink(store: Any) -> SqliteLogHandler:
    """Pasang handler di root logger. Kembalikan handler-nya supaya bisa dilepas tes."""
    handler = SqliteLogHandler(store)
    logging.getLogger().addHandler(handler)
    return handler
```

Di `core/config.py`, tambahkan:

```python
    # Berapa lama riwayat galat disimpan untuk layar Log. Batas waktu, bukan batas
    # jumlah baris: batas jumlah membuang log lama yang penting persis saat error
    # sedang membanjir. ±300 byte/baris, jadi 180 hari ≈ 10 MB.
    log_retensi_hari: int = 180
```

Tambahkan juga `log_db_path` mengikuti pola `console_db_path` yang sudah ada.

Teruskan setelan yang dibaca dari env di `docker-compose.yml` service `console`
dan `.env.example`, di commit yang sama:

```yaml
      - LOG_RETENSI_HARI=${LOG_RETENSI_HARI:-180}
```

Tanpa ini `tests/unit/test_console_compose_env.py` gagal.

Di `console_main.py`, dalam lifespan, sesudah store konsol dibuat:

```python
    log_store = LogStore(settings.log_db_path, retensi_hari=settings.log_retensi_hari)
    pasang_log_sink(log_store)
```

- [ ] **Step 4: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/test_log_sink.py -v && ruff check src/palmgrade/core/log_sink.py`
Expected: 6 PASS, ruff bersih.

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/core/log_sink.py src/palmgrade/core/config.py \
        src/palmgrade/console_main.py tests/unit/test_log_sink.py
git commit -m "feat(konsol): logging handler menulis ERROR/WARNING ke log_kejadian"
```

---

## Task 11: Endpoint + layar Log

**Files:**
- Create: `src/palmgrade/services/dev_service.py`
- Modify: `src/palmgrade/routes/console.py`
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/unit/test_dev_routes.py`

**Interfaces:**
- Consumes: `LogStore`, `Support`
- Produces:
  - `DevService(log_store: LogStore, ...)` — ditumbuhkan Task 12 & 13
  - `DevService.log(level, cari, limit, offset) -> dict`
  - `GET /api/console/dev/log?level=&cari=&limit=&offset=`

- [ ] **Step 1: Tulis tes yang gagal**

Create `tests/unit/test_dev_routes.py`:

```python
def test_log_butuh_peran_support():
    app, store, _ = _app_dev()
    oid = store.upsert_operator_lokal(
        {"email": "o@b.c", "nama": "O", "password_hash": "scrypt$x"}
    )
    store.create_session("tok", oid, now=time.time(), ttl_s=3600)
    client = TestClient(app)
    client.cookies.set("konsol_sesi", "tok")
    assert client.get("/api/console/dev/log").status_code == 403


def test_log_mengembalikan_halaman_dan_total():
    app, store, log_store = _app_dev()
    for i in range(25):
        log_store.tulis("ERROR", f"s{i}", f"pesan {i}", None, now=1000.0 + i * 100)
    client = _client_support(app, store)
    data = client.get("/api/console/dev/log?limit=10").json()
    assert data["total"] == 25
    assert len(data["items"]) == 10


def test_log_saring_level():
    app, store, log_store = _app_dev()
    log_store.tulis("ERROR", "a", "satu", None, now=1000.0)
    log_store.tulis("WARNING", "b", "dua", None, now=1001.0)
    client = _client_support(app, store)
    assert client.get("/api/console/dev/log?level=ERROR").json()["total"] == 1


def test_log_limit_dibatasi_atas():
    """Satu permintaan tidak boleh menarik 180 hari riwayat sekaligus."""
    app, store, _ = _app_dev()
    client = _client_support(app, store)
    assert client.get("/api/console/dev/log?limit=99999").status_code == 422
```

Helper `_app_dev()` merakit router dengan `get_log_store` di-override ke `LogStore(tmp)`; `_client_support()` membuat akun ber-peran support dan memasang cookie-nya.

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_dev_routes.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Tulis service**

Create `src/palmgrade/services/dev_service.py`:

```python
"""Flow di balik lima layar developer.

Empat dari lima cuma membungkus apa yang sudah dicatat hari ini — `/health/detail`,
`outbox_events`, settings. Yang membuatnya berguna bukan data barunya, melainkan
bahwa datanya akhirnya punya layar, alih-alih hanya terbaca lewat `curl`.
"""

from __future__ import annotations

import time
from typing import Any

from ..repositories.log_repository import LogStore


class DevService:
    def __init__(self, log_store: LogStore) -> None:
        self._log = log_store
        self._buang_terakhir = 0.0

    def log(
        self, *, level: str | None, cari: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        self._buang_berkala()
        return self._log.baca(level=level, cari=cari, limit=limit, offset=offset)

    def _buang_berkala(self, *, now: float | None = None) -> None:
        """Buang baris kedaluwarsa, paling sering sekali sejam.

        Ditempel di pembacaan, bukan worker sendiri: satu thread lagi di PC pabrik
        harus membayar dirinya, dan pembuangan sekali sejam sudah lebih dari cukup
        untuk tabel yang tumbuh beberapa ratus baris sehari.
        """
        sekarang = now if now is not None else time.time()
        if sekarang - self._buang_terakhir < 3600:
            return
        self._buang_terakhir = sekarang
        self._log.buang_kedaluwarsa(now=sekarang)
```

- [ ] **Step 4: Tulis route**

Di `routes/console.py`, tambahkan dependency dan route:

```python
@lru_cache
def get_dev_service() -> DevService:
    """Store log-nya berkas sendiri, bukan `console.db`: sebuah banjir galat tidak
    boleh ikut memperlambat query yang melayani layar operator."""
    settings = Settings()
    return DevService(
        LogStore(settings.log_db_path, retensi_hari=settings.log_retensi_hari)
    )


Dev = Annotated[DevService, Depends(get_dev_service)]


@router.get("/api/console/dev/log")
async def dev_log(
    dev: Dev,
    operator: Support,
    level: Annotated[str | None, Query()] = None,
    cari: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return dev.log(level=level, cari=cari, limit=limit, offset=offset)
```

- [ ] **Step 5: Tulis layar**

Di `console.html`, tambahkan panel `<section data-panel="log">` berisi: dua tombol saring level (Semua / ERROR / WARNING), satu kotak cari, tabel (waktu, level, sumber, pesan, `×jumlah`), dan tombol halaman berikut/sebelumnya memakai `total` dari respons.

⚠️ Total halaman **wajib** dari `total` respons, bukan `items.length` — jebakan yang sama dengan pagination grading (memori `project_konsol_login_operator`).

⚠️ **Tambahkan tes pemetaan tab ↔ panel** di `tests/unit/test_console_html.py`: tiap
`data-tab="x"` yang punya panel harus punya `id="sec-x"` yang cocok. Task 7 memasang
penjaga null di `terapkanTab()` (perlu, karena lima tab dev belum punya panel) —
konsekuensinya `data-tab` salah ketik sekarang diam-diam tidak melakukan apa-apa
alih-alih melempar. Panel dev pertama lahir di task ini, jadi di sinilah tesnya mulai
punya sesuatu untuk dijaga.

- [ ] **Step 6: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/ -v && ruff check src/palmgrade/`
Expected: semua PASS, ruff bersih.

- [ ] **Step 7: Periksa dengan mata**

```bash
make console
```

Masuk sebagai support → tab Log. Picu galat (misal matikan `ERP_URL` ke host yang tidak ada) dan pastikan barisnya muncul, penggabungan `×N` jalan, dan sandi tidak pernah kelihatan.

- [ ] **Step 8: Commit dan PR 2**

```bash
git add src/palmgrade/services/dev_service.py src/palmgrade/routes/console.py \
        src/palmgrade/static/console.html tests/unit/test_dev_routes.py
git commit -m "feat(konsol): endpoint dan layar Log"
git push -u origin feat/konsol-log-kejadian
gh pr create --base staging --title "feat(console): a fault log that survives a restart" \
  --body "Today a fault leaves its only trace in \`docker logs\`, and the most common thing that happens at a mill is 'it errored, I restarted, it's fine now' — which is exactly when that trace is gone.

- \`log_kejadian\`: ERROR/WARNING only, kept 180 days (~10 MB at 200/day)
- identical messages inside 60s are counted, not stacked — a cut camera cable used to emit one per second
- secrets are redacted before anything reaches disk; the log is read over AnyDesk and outlives the incident by months
- a failing handler never reaches the caller: the log is a tool, not a new way for a line to stop"
```

---

## Task 12: Diagnostik, Antrean ERP, Versi & Lisensi

**Files:**
- Modify: `src/palmgrade/services/dev_service.py`
- Modify: `src/palmgrade/routes/console.py`
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/unit/test_dev_routes.py`

**Interfaces:**
- Consumes: `LineClient`, `ErpOutboxStore`, `Settings`
- Produces:
  - `DevService.diagnostik() -> dict` — `/health/detail` tiap line
  - `DevService.antrean() -> dict`, `.kirim_ulang() -> dict`
  - `DevService.versi() -> dict`
  - `GET /api/console/dev/diagnostik`, `GET|POST /api/console/dev/antrean`, `GET /api/console/dev/versi`

- [ ] **Step 1: Branch dari staging**

```bash
git checkout staging && git pull
git checkout -b feat/konsol-diagnostik
```

- [ ] **Step 2: Tulis tes yang gagal**

```python
def test_diagnostik_mengumpulkan_tiap_line():
    app, store, _ = _app_dev(line_client=_LineClientPalsu({"line-1": {"status": "ok"}}))
    data = _client_support(app, store).get("/api/console/dev/diagnostik").json()
    assert data["lines"]["line-1"]["status"] == "ok"


def test_line_mati_dilaporkan_bukan_menjatuhkan_layar():
    """Satu line mati justru yang perlu dilihat; ia tidak boleh mengosongkan layar."""
    app, store, _ = _app_dev(line_client=_LineClientMati())
    data = _client_support(app, store).get("/api/console/dev/diagnostik").json()
    assert data["lines"]["line-1"]["terjangkau"] is False


def test_antrean_menampilkan_sebab_gagal():
    app, store, _ = _app_dev()
    _isi_outbox_gagal(app, pesan="417 unknown field")
    data = _client_support(app, store).get("/api/console/dev/antrean").json()
    assert "417" in data["items"][0]["last_error"]


def test_kirim_ulang_memindahkan_gagal_jadi_pending():
    app, store, _ = _app_dev()
    _isi_outbox_gagal(app, pesan="timeout")
    client = _client_support(app, store)
    assert client.post("/api/console/dev/antrean/kirim-ulang").json()["dikirim_ulang"] == 1
    assert client.get("/api/console/dev/antrean").json()["gagal"] == 0


def test_versi_membawa_machine_id_dan_lisensi():
    app, store, _ = _app_dev()
    data = _client_support(app, store).get("/api/console/dev/versi").json()
    assert data["machine_id"]
    assert "lisensi" in data


def test_semua_lane_dev_menolak_operator_biasa():
    """Satu tes untuk ketiganya: penjaganya satu, jadi lupa memasangnya kelihatan."""
    app, store, _ = _app_dev()
    client = _client_operator(app, store)
    for jalur in ("diagnostik", "antrean", "versi"):
        assert client.get(f"/api/console/dev/{jalur}").status_code == 403
```

- [ ] **Step 3: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_dev_routes.py -v`
Expected: FAIL — 404.

- [ ] **Step 4: Tumbuhkan service**

Tambahkan ke `DevService`:

```python
    async def diagnostik(self) -> dict[str, Any]:
        """`/health/detail` tiap line, digabung jadi satu layar.

        Line yang tidak menjawab dilaporkan `terjangkau: False`, bukan melempar:
        line yang mati justru yang paling perlu dilihat di layar ini.
        """
        lines = {}
        for line in self._lines:
            try:
                lines[line] = {"terjangkau": True, **await self._line_client.health(line)}
            except LineUnavailable as exc:
                lines[line] = {"terjangkau": False, "sebab": str(exc)}
        return {"lines": lines}

    def antrean(self) -> dict[str, Any]:
        return {
            "pending": self._erp_outbox.pending_count(),
            "gagal": self._erp_outbox.failed_count(),
            "items": self._erp_outbox.daftar_gagal(limit=50),
        }

    def kirim_ulang(self) -> dict[str, Any]:
        return {"dikirim_ulang": self._erp_outbox.requeue_failed()}

    def versi(self) -> dict[str, Any]:
        return {
            "versi": self._settings.app_version,
            "machine_id": self._settings.machine_id,
            "environment": self._settings.environment,
            "lisensi": self._ringkas_lisensi(),
        }
```

Kalau `ErpOutboxStore` belum punya `daftar_gagal`, tambahkan — `SELECT` baris `status='failed'` beserta `last_error`, `retry_count`, `next_retry_at`, urut terbaru.

- [ ] **Step 5: Tulis route**

Tiga route, semuanya memakai `operator: Support`:

```python
@router.get("/api/console/dev/diagnostik")
async def dev_diagnostik(dev: Dev, operator: Support) -> dict:
    return await dev.diagnostik()


@router.get("/api/console/dev/antrean")
async def dev_antrean(dev: Dev, operator: Support) -> dict:
    return dev.antrean()


@router.post("/api/console/dev/antrean/kirim-ulang")
async def dev_kirim_ulang(dev: Dev, operator: Support) -> dict:
    return dev.kirim_ulang()


@router.get("/api/console/dev/versi")
async def dev_versi(dev: Dev, operator: Support) -> dict:
    return dev.versi()
```

- [ ] **Step 6: Tulis tiga panel**

Di `console.html`: panel Diagnostik (kartu per line — worker, kamera, fps, GPU, PLC; menyegar tiap 5 detik), panel Antrean (jumlah + tabel sebab + tombol Kirim Ulang), panel Versi (daftar definisi).

- [ ] **Step 7: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/ -v && ruff check src/palmgrade/`
Expected: semua PASS, ruff bersih.

- [ ] **Step 8: Periksa dengan mata**

```bash
make console
```

Tiga tab terisi. Matikan satu line → kartunya jadi "tidak terjangkau", layar tetap hidup.

- [ ] **Step 9: Commit dan PR 3**

```bash
git add src/palmgrade/services/dev_service.py src/palmgrade/routes/console.py \
        src/palmgrade/static/console.html src/palmgrade/integrations/erp/outbox_store.py \
        tests/unit/test_dev_routes.py
git commit -m "feat(konsol): layar diagnostik, antrean ERP, dan versi"
git push -u origin feat/konsol-diagnostik
gh pr create --base staging --title "feat(console): diagnostics, ERP queue and version screens" \
  --body "Three screens over data the console already records but has never shown — until now it was only reachable with \`curl\` over AnyDesk.

- Diagnostics: per-line workers, camera, fps, GPU, PLC. An unreachable line is reported as such rather than emptying the screen — that line is the thing worth seeing.
- ERP queue: what is stuck, why (\`last_error\`), and a Resend button over the existing \`requeue_failed()\`. Turns 'my data never reached ERP' into one click.
- Version & licence: version, machine id, licence state. Removes the question every support session starts with."
```

---

## Task 13: Uji PLC

**Files:**
- Modify: `src/palmgrade/plc/worker.py` (method `picu_coil`)
- Modify: `src/palmgrade/plc/__init__.py` (fungsi modul + `__all__`)
- Modify: `src/palmgrade/services/dev_service.py`
- Modify: `src/palmgrade/routes/console.py`
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/unit/test_dev_plc.py`

**Interfaces:**
- Consumes: `plc.inputs()`, `plc.diagnostics()`, `RuntimeState.current_assignment_id`, `LogStore`
- Produces:
  - `plc.picu_coil(coil: int) -> bool` — fungsi modul baru, masuk `__all__`
  - `DevService.plc_baca() -> dict`
  - `DevService.plc_picu(coil: int, operator_email: str) -> dict` — `PlcSibuk` kalau line jalan
  - `GET /api/console/dev/plc`, `POST /api/console/dev/plc/coil`

- [ ] **Step 1: Branch dari staging**

```bash
git checkout staging && git pull
git checkout -b feat/konsol-uji-plc
```

- [ ] **Step 2: Tulis tes yang gagal**

Create `tests/unit/test_dev_plc.py`:

```python
def test_baca_di_tidak_menyentuh_coil():
    """Membaca harus aman; layar ini boleh dibuka kapan saja."""
    app, store, plc = _app_plc(inputs=[True, False, True])
    data = _client_support(app, store).get("/api/console/dev/plc").json()
    assert data["inputs"] == [True, False, True]
    assert plc.coil_ditulis == []


def test_picu_coil_ditolak_saat_line_memproses_truk():
    """Piston bergerak saat janjang lewat itu bahaya, bukan cuma berantakan."""
    app, store, plc = _app_plc(assignment_id="a-1")
    r = _client_support(app, store).post(
        "/api/console/dev/plc/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 409
    assert plc.coil_ditulis == []


def test_picu_coil_ditolak_tanpa_konfirmasi_ketik():
    """Klik bisa kesenggol; ketikan tidak."""
    app, store, plc = _app_plc()
    r = _client_support(app, store).post(
        "/api/console/dev/plc/coil", json={"coil": 11, "konfirmasi": ""}
    )
    assert r.status_code == 400
    assert plc.coil_ditulis == []


def test_picu_coil_jalan_saat_line_menganggur():
    app, store, plc = _app_plc(assignment_id=None)
    r = _client_support(app, store).post(
        "/api/console/dev/plc/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    assert r.status_code == 200
    assert plc.coil_ditulis == [11]


def test_penekanan_meninggalkan_jejak_di_log():
    """Kalau ada kejadian di pabrik, ketahuan siapa menekan apa dan kapan."""
    app, store, plc, log_store = _app_plc_dengan_log()
    _client_support(app, store, email="s@b.c").post(
        "/api/console/dev/plc/coil", json={"coil": 11, "konfirmasi": "UJI"}
    )
    items = log_store.baca(level="WARNING", cari="coil", limit=10, offset=0)["items"]
    assert len(items) == 1
    assert "s@b.c" in items[0]["pesan"]
    assert "11" in items[0]["pesan"]


def test_coil_di_luar_daftar_ditolak():
    """Hanya coil yang memang dipetakan; nomor asing tidak boleh sampai ke PLC."""
    app, store, plc = _app_plc()
    r = _client_support(app, store).post(
        "/api/console/dev/plc/coil", json={"coil": 999, "konfirmasi": "UJI"}
    )
    assert r.status_code == 422
    assert plc.coil_ditulis == []


def test_uji_plc_menolak_operator_biasa():
    app, store, _ = _app_plc()
    assert _client_operator(app, store).get("/api/console/dev/plc").status_code == 403
```

- [ ] **Step 3: Jalankan tes, pastikan gagal**

Run: `pytest tests/unit/test_dev_plc.py -v`
Expected: FAIL — 404.

- [ ] **Step 4: Tambah `picu_coil` ke public surface PLC**

Modul `plc/` sengaja menutup dirinya di lima fungsi (`start_plc_worker`,
`shutdown_plc_worker`, `submit_grading`, `inputs`, `diagnostics` — plus
`request_piston`/`piston_state`), dan `_write_coil` adalah method privat worker.
Layar uji butuh jalan masuk yang sah, bukan menembus lewat `_write_coil`.

Di `plc/worker.py`, tambahkan method publik:

```python
    def picu_coil(self, coil: int) -> None:
        """Nyalakan satu coil sesaat, untuk uji kabel saat pemasangan.

        Jalan masuk sah untuk layar Uji PLC — `_write_coil` privat karena
        pemanggil di luar tidak boleh memilih level sendiri dan meninggalkan
        coil menyala. Di sini pulse-nya ditutup oleh tick yang sama dengan
        grading, jadi tidak ada keadaan yang perlu dibersihkan pemanggil.
        """
        with self._lock:
            self._pulse.mulai(coil)
```

Di `plc/__init__.py`, tambahkan fungsi modul yang meneruskannya (mengikuti
pola `request_piston`), dan masukkan namanya ke `__all__`:

```python
def picu_coil(coil: int) -> bool:
    """Picu satu coil untuk uji kabel. False kalau worker PLC tidak hidup."""
    worker = _worker
    if worker is None:
        return False
    worker.picu_coil(coil)
    return True
```

⚠️ Sesuaikan nama `self._pulse.mulai(...)` dengan API `plc/pulse.py` yang
sebenarnya — baca berkas itu dulu; kalau namanya beda, ikuti yang ada di kode,
jangan tambah API baru di `pulse.py`.

- [ ] **Step 5: Tulis service**

```python
    def plc_baca(self) -> dict[str, Any]:
        """Keadaan DI apa adanya. Hanya membaca — tidak menyentuh satu coil pun."""
        return {"inputs": self._plc.inputs(), "diagnostics": self._plc.diagnostics()}

    def plc_picu(self, *, coil: int, konfirmasi: str, operator_email: str) -> dict[str, Any]:
        """Picu satu coil untuk memisahkan kabel rusak dari program salah.

        Satu-satunya layar yang menulis ke barang sungguhan, jadi tiga pengaman:
        ditolak saat sebuah line sedang memproses truk, butuh konfirmasi yang
        diketik, dan tiap penekanan meninggalkan baris di `log_kejadian`.
        """
        if not konfirmasi.strip():
            raise KonfirmasiKurang("ketik konfirmasi sebelum memicu coil")
        if self._state.current_assignment_id is not None:
            raise PlcSibuk("line sedang memproses truk")

        logger.warning(
            "UJI PLC: %s memicu coil %s", operator_email, coil
        )
        self._plc.picu_coil(coil)
        return {"status": "ok", "coil": coil}
```

Nomor coil divalidasi di route lewat `Query`/model dengan daftar coil yang dipetakan di `plc/` — bukan bilangan bebas.

- [ ] **Step 6: Tulis route**

```python
@router.get("/api/console/dev/plc")
async def dev_plc(dev: Dev, operator: Support) -> dict:
    return dev.plc_baca()


@router.post("/api/console/dev/plc/coil")
async def dev_plc_coil(
    dev: Dev, operator: Support, payload: Annotated[UjiCoilRequest, Body()]
) -> dict:
    try:
        return dev.plc_picu(
            coil=payload.coil,
            konfirmasi=payload.konfirmasi,
            operator_email=operator["email"],
        )
    except PlcSibuk as exc:
        raise _operator_error(409, exc) from exc
    except KonfirmasiKurang as exc:
        raise _operator_error(400, exc) from exc
```

`UjiCoilRequest` di `schemas/` dengan `coil: int` divalidasi terhadap daftar coil yang dipetakan, dan `konfirmasi: str`.

- [ ] **Step 7: Tulis layar**

Panel dengan dua bagian: daftar DI (hijau/abu, menyegar tiap 2 detik) dan tombol per coil. Saat ada penugasan aktif, tombol **disabled** dengan penjelasan terbaca. Menekan tombol membuka dialog yang meminta ketikan `UJI`.

⚠️ Dropdown/dialog harus dicek tidak keluar layar — jebakan yang sudah pernah kena (memori `project_konsol_login_operator`).

- [ ] **Step 8: Jalankan tes, pastikan lolos**

Run: `pytest tests/unit/ -v && ruff check src/palmgrade/`
Expected: semua PASS, ruff bersih.

- [ ] **Step 9: Periksa dengan mata**

```bash
make console
```

Tanpa PLC (`PLC_ENABLED=false`), layar harus tetap membuka dan mengatakan PLC mati — bukan error.

- [ ] **Step 10: Commit dan PR 4**

```bash
git add src/palmgrade/services/dev_service.py src/palmgrade/routes/console.py \
        src/palmgrade/schemas/ src/palmgrade/static/console.html tests/unit/test_dev_plc.py
git commit -m "feat(konsol): layar uji PLC dengan tiga pengaman"
git push -u origin feat/konsol-uji-plc
gh pr create --base staging --title "feat(console): a manual PLC test screen for commissioning" \
  --body "Answers the question that costs the most time at a new mill: when a piston does not move, is it the wiring or the program? Firing one coil from a screen settles it in seconds.

The only screen here that writes to something physical, so three guards:
- refused while a line is processing a truck — a piston moving under a passing bunch is dangerous, not just untidy
- typed confirmation, not a click, which can be brushed
- every press leaves a WARNING row naming who fired which coil, so an incident has a trail"
```

---

## Task 14: Dokumentasi

**Files:**
- Modify: `CLAUDE.md` (autograde)
- Modify: `docs/backend-overview.md`
- Modify: `.env.example`

- [ ] **Step 1: Catat lane baru di CLAUDE.md**

Tambahkan lima baris ke tabel surface konsol, dan satu aturan bernomor di Critical Rules yang merangkum: peran menjaga di backend, log 180 hari dengan penggabungan, uji PLC tiga pengaman.

- [ ] **Step 2: Catat env baru**

Di `.env.example`, dengan komentarnya:

```bash
# Peran mana yang boleh datang dari AutoERP. Kosongkan untuk menolak semuanya —
# rem sisi pabrik kalau akun ERP bermasalah.
ERP_ALLOWED_ROLES=support

# Berapa lama riwayat galat disimpan untuk layar Log support.
LOG_RETENSI_HARI=180
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/backend-overview.md .env.example
git commit -m "docs: catat lane developer konsol dan dua setelan barunya"
```

---

## Catatan Eksekusi

**Urutan wajib:** Task 1 (autoerp) merge lebih dulu. Frappe membalas 417 untuk satu field asing, jadi Task 5 akan mematahkan tarikan master data kalau field `peran` belum ada di ERP.

**Jebakan yang sudah pernah kena di repo ini** (jangan diwarisi lagi):
- `make console` memakai `WEBHOOK_SECRET=devsecret` dan **tanpa `--reload`** — jalankan ulang setelah mengubah HTML.
- Total halaman **wajib** dari `total` di respons, bukan `items.length`.
- Dropdown/dialog bisa keluar layar; periksa dengan mata, bukan hanya `overflow`.
- Ringkasan pytest kadang terpendam di output panjang — baca ekornya.
- `bench run-tests` bermasalah di MacBook ini; Task 1 punya jalur verifikasi manual.
