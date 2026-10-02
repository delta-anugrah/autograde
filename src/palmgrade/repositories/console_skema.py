"""Skema `state/console.db`: tabel, indeks, dan migrasi untuk database dari build lama.

Dipisah dari `console_repository.py` (batch 2, 2026-09-28) karena berkas itu lewat
1.000 baris. SQL-nya pindah apa adanya; empat method migrasi jadi fungsi yang
menerima koneksi (`self._db` jadi `db`), urutannya tidak berubah. Pintu masuknya satu,
`siapkan_skema()`, dipanggil `ConsoleStore.__init__` di bawah lock-nya. Koneksinya
harus memakai `sqlite3.Row`: kolom `PRAGMA table_info` dibaca lewat nama.
"""
from __future__ import annotations

import sqlite3

#: Nomor skema `console.db` (`PRAGMA user_version`). Naikkan SATU setiap kali
#: `_CREATE_SQL` atau `_migrate` berubah. Ini penanda, bukan pengatur: migrasi tetap
#: berbasis `PRAGMA table_info` (aturan B5), dan angkanya tidak pernah diturunkan,
#: jadi image lama yang membuka berkas dari image lebih baru tidak mengubahnya
#: (rollback lewat `autograde use`).
#:
#: 1 = batch 4.5 (PR #213). 2 = `visit_assignments` + `idx_weighings_truck` (PR #208).
VERSI_SKEMA = 2

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS inspections (
    event_id            TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    line_code           TEXT NOT NULL,
    work_date           TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    ripeness_status     TEXT NOT NULL,
    ripeness_confidence REAL,
    capture_type        TEXT NOT NULL,
    image_path          TEXT,
    truck_id            TEXT,
    assignment_id       TEXT,
    received_at         REAL NOT NULL,
    -- Stored as sent by the line, NOT re-derived from `ripeness_status`: ERP
    -- requires `prediction`, and deriving it in two repos means two rules that
    -- can drift apart with nobody noticing.
    prediction          TEXT,
    -- Kelas model yang sebenarnya (Ripe/Unripe/JK/TP), di samping verdict biner
    -- di `ripeness_status`. Dua kolom, bukan satu, karena piston dan buku besar
    -- AutoERP cuma mengenal ACC/REJ (`domain/grade_class.py`). NULL untuk baris
    -- yang ditulis sebelum kolom ini ada, dan untuk capture manual — yang itu
    -- tidak pernah lewat model, jadi kelasnya memang tidak diketahui.
    grade_class         TEXT,
    tp_status           TEXT,
    tp_confidence       REAL,
    -- Unused since the per-bunch push was dropped: AutoERP takes one message
    -- per truck visit. Kept so factory databases need no table rebuild.
    erp_state           TEXT
);
CREATE INDEX IF NOT EXISTS idx_inspections_hari ON inspections (work_date, line_code);
CREATE INDEX IF NOT EXISTS idx_inspections_urut ON inspections (work_date, timestamp DESC);

CREATE TABLE IF NOT EXISTS suppliers (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    source_group TEXT,
    status       TEXT,
    -- The AutoERP document name, this row's id on the other side. NULL until a
    -- pull matches it; unique, so two local rows can never claim one supplier.
    erp_name TEXT
);

CREATE TABLE IF NOT EXISTS trucks (
    id           TEXT PRIMARY KEY,
    plate_number TEXT,
    supplier_id  TEXT,
    capacity     REAL,
    status       TEXT,
    erp_name     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trucks_plat ON trucks (plate_number);

CREATE TABLE IF NOT EXISTS assignments (
    line_code     TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    truck_id      TEXT,
    started_at    REAL NOT NULL
);

-- Line yang dilepas OLEH TIMBANG KELUAR, bukan oleh operator (G5). Dicatat
-- supaya pelepasannya terlihat: operator yang menimbang keluar terlalu cepat
-- (antrean jembatan timbang, bongkar belum habis) harus tahu line-nya baru saja
-- lepas, supaya bisa meng-assign ulang. Pelepasan senyap hanya menukar satu
-- kegagalan diam dengan kegagalan diam yang lain.
CREATE TABLE IF NOT EXISTS auto_releases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    line_code     TEXT NOT NULL,
    truck_id      TEXT NOT NULL,
    plate_number  TEXT,
    assignment_id TEXT,
    released_at   REAL NOT NULL
);

-- Weighbridge (§3.5c). Filled by the scale program via
-- POST /internal/scale/weighing; its format is unknown (X1), so the lane is
-- built in OUR shape and only an adapter is added later.
-- `net_kg` never arrives from outside as-is — it is computed in the service.
CREATE TABLE IF NOT EXISTS weighings (
    id            TEXT PRIMARY KEY,
    ref           TEXT,
    plate_number  TEXT,
    plate_norm    TEXT,
    truck_id      TEXT,
    work_date     TEXT NOT NULL,
    gross_kg      REAL,
    tare_kg       REAL,
    net_kg        REAL,
    entered_at    TEXT,
    exited_at     TEXT,
    received_at   REAL NOT NULL,
    -- The line assignment this visit's bunches belong to, written when the truck
    -- leaves the line. Without it a second ticket the same day would inherit the
    -- first one's grading.
    assignment_id TEXT,
    -- What AutoERP answered for this visit: the Weighbridge Ticket it made, that
    -- ticket's status, and the note it sends only when a human is needed — a
    -- finalised ticket whose grading changed, or a cancelled one it ignored.
    erp_ticket    TEXT,
    erp_status    TEXT,
    erp_note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_weighings_hari ON weighings (work_date, entered_at DESC);
CREATE INDEX IF NOT EXISTS idx_weighings_plat ON weighings (plate_norm);

-- One visit, every line that unloaded it (2026-10-01). A truck on three lines has three
-- assignments, and `weighings.assignment_id` holds one: the AutoERP recap counted the
-- line released last. That column is still written (an older image reads it); this
-- table is what the recap sums. Written when a line lets the truck go.
CREATE TABLE IF NOT EXISTS visit_assignments (
    assignment_id TEXT PRIMARY KEY,
    weighing_id   TEXT NOT NULL,
    line_code     TEXT,
    linked_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visit_assignments_tiket ON visit_assignments (weighing_id);
-- The unloading queue and the busy check read open tickets of the last hours, every 2 s.
CREATE INDEX IF NOT EXISTS idx_weighings_terbuka ON weighings (received_at)
    WHERE tare_kg IS NULL;

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Operator accounts for the console login (Fase 4). Two sources, and the row says
-- which: `erp` is pulled from AutoERP's `AutoGrade Operator` (§4.A), `lokal` is written
-- on this PC by `make operator` — the built-in and support accounts, which are how a
-- mill that has never reached the internet gets opened. Neither may overwrite the
-- other. The hash is verified here, offline; nothing is asked of AutoERP at sign-in.
CREATE TABLE IF NOT EXISTS operators (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    origin         TEXT NOT NULL DEFAULT 'lokal',
    erp_name       TEXT,
    -- `operator` or `support`. No CHECK on purpose: a third role later should
    -- not need a table migration; the route is what enforces this column.
    role           TEXT NOT NULL DEFAULT 'operator',
    created_at     REAL NOT NULL,
    -- Wrong-password counter, on disk so reloading the page cannot reset the lockout.
    fail_count     INTEGER NOT NULL DEFAULT 0,
    last_failed_at REAL
);

CREATE TABLE IF NOT EXISTS sesi (
    token          TEXT PRIMARY KEY,
    operator_id    TEXT NOT NULL,
    created_at     REAL NOT NULL,
    expires_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sesi_kedaluwarsa ON sesi (expires_at);

-- Impor grading dari CSV Per janjang (tab Riwayat, support saja). Satu baris per
-- impor; janjangnya di `inspections` dengan `import_batch` = `id` di sini, jadi satu
-- impor bisa dibatalkan utuh tanpa menyentuh janjang asli pabrik.
-- `status`: running (sedang ditulis) / done / interrupted (konsol mati di tengah) /
-- undone (dibatalkan).
CREATE TABLE IF NOT EXISTS grading_imports (
    id               TEXT PRIMARY KEY,
    file_name        TEXT,
    fingerprint      TEXT NOT NULL,
    imported_by      TEXT NOT NULL,
    started_at       REAL NOT NULL,
    finished_at      REAL,
    status           TEXT NOT NULL DEFAULT 'running',
    rows_total       INTEGER NOT NULL DEFAULT 0,
    added            INTEGER NOT NULL DEFAULT 0,
    skipped_existing INTEGER NOT NULL DEFAULT 0,
    skipped_today    INTEGER NOT NULL DEFAULT 0,
    duplicates       INTEGER NOT NULL DEFAULT 0,
    date_from        TEXT,
    date_to          TEXT,
    new_trucks       INTEGER NOT NULL DEFAULT 0,
    undone_at        REAL,
    undone_by        TEXT,
    removed          INTEGER NOT NULL DEFAULT 0
);
"""


# Runs after the ALTERs above, never inside `_CREATE_SQL`: on a database that
# predates the column, an index over it cannot be created yet. NULLs are exempt
# from a SQLite unique index, so unmatched rows stay allowed.
_MIGRATE_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_erp ON suppliers (erp_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trucks_erp ON trucks (erp_name);
-- Served only the dropped per-bunch push; it cost a write on every event.
DROP INDEX IF EXISTS idx_inspections_erp;
-- Batal impor menghapus per batch. Parsial: janjang asli (NULL) tidak ikut diindeks,
-- jadi ingest dari line tidak membayar apa pun untuk indeks ini.
CREATE INDEX IF NOT EXISTS idx_inspections_impor ON inspections (import_batch)
    WHERE import_batch IS NOT NULL;
-- Batch 2.5. Rekap satu penugasan (`grading_counts`, `grading_counts_for_visit`, `bunches_for_visit`) dulu
-- memindai seluruh `inspections` sambil memegang lock konsol (63 ms di 558 ribu baris).
-- Parsial: janjang tanpa penugasan dan janjang impor tidak ikut diindeks. `timestamp`
-- di belakang supaya daftar janjang manifest keluar berurutan tanpa sortir.
CREATE INDEX IF NOT EXISTS idx_inspections_assignment ON inspections (assignment_id, timestamp)
    WHERE assignment_id IS NOT NULL;
-- Janjang susulan (batch 2.3) mencari tiket yang ditautkan ke penugasannya, tiap janjang.
CREATE INDEX IF NOT EXISTS idx_weighings_assignment ON weighings (assignment_id)
    WHERE assignment_id IS NOT NULL;
-- `/api/console/state` tiap 2 detik membaca pelepasan otomatis sejam terakhir; tabelnya
-- tidak pernah dibersihkan.
CREATE INDEX IF NOT EXISTS idx_auto_releases_waktu ON auto_releases (released_at);
-- Lepas truk mencari tiket truk itu dalam jendela 12 jam (`latest_weighing_for_truck_since`),
-- bukan lagi lewat hari kerja yang berindeks.
CREATE INDEX IF NOT EXISTS idx_weighings_truck ON weighings (truck_id, received_at);
-- Visits linked before `visit_assignments` existed. Safe to repeat on every boot: the
-- assignment is the primary key, so a second run inserts nothing.
INSERT OR IGNORE INTO visit_assignments (assignment_id, weighing_id, line_code, linked_at)
    SELECT assignment_id, id, NULL, received_at FROM weighings
    WHERE assignment_id IS NOT NULL AND assignment_id != '';
"""

# Columns renamed to English after the schema had already been created on
# developer machines. `CREATE TABLE IF NOT EXISTS` leaves an existing table
# alone, so without this pass every read hits a column that is not there.
_RENAMED_COLUMNS = (
    ("inspections", (("tanggal_kerja", "work_date"),)),
    ("suppliers", (("sumber", "source_group"),)),
    (
        "weighings",
        (
            ("tanggal_kerja", "work_date"),
            ("bruto_kg", "gross_kg"),
            ("tara_kg", "tare_kg"),
            ("neto_kg", "net_kg"),
            ("waktu_masuk", "entered_at"),
            ("waktu_keluar", "exited_at"),
        ),
    ),
    ("sesi", (("dibuat_at", "created_at"), ("kedaluwarsa_at", "expires_at"))),
    (
        "operators",
        (
            ("nama", "full_name"),
            ("asal", "origin"),
            ("dibuat_at", "created_at"),
            ("gagal_count", "fail_count"),
            ("gagal_terakhir", "last_failed_at"),
        ),
    ),
)


def siapkan_skema(db: sqlite3.Connection) -> None:
    """Rename kolom lama, buat yang belum ada, migrasi, lalu tandai nomor skema.

    Aman diulang tiap boot.

    Rename lebih dulu: indeks di `_CREATE_SQL` menyebut nama kolom berbahasa Inggris,
    jadi di database dari sebelum rename indeks itu akan dibuat pada kolom yang belum ada.
    """
    _rename_indonesian_columns(db)
    db.executescript(_CREATE_SQL)
    _migrate(db)
    _tandai_versi(db)


def _tandai_versi(db: sqlite3.Connection) -> None:
    """Naikkan `user_version` ke `VERSI_SKEMA`, tidak pernah menurunkannya."""
    sekarang = db.execute("PRAGMA user_version").fetchone()[0]
    if sekarang < VERSI_SKEMA:
        # PRAGMA tidak menerima parameter terikat; angkanya konstanta kode (B5).
        db.execute(f"PRAGMA user_version = {VERSI_SKEMA}")
        db.commit()


def _migrate(db: sqlite3.Connection) -> None:
    """Add what a console older than this build has not got.

    `CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it is, so a new
    column never reaches a factory database through the schema above: it needs its own
    pass, and the index that depends on it has to wait until the column exists.
    """
    _drop_pin_era_operators(db)
    for table, column in (
        # Batch 2.5: the index on it below. Every real console database already has this
        # column; this only guards a hand-made or very old table
        # (tests/unit/test_console_store.py builds one without it).
        ("inspections", "assignment_id"),
        ("suppliers", "erp_name"),
        ("trucks", "erp_name"),
        ("weighings", "assignment_id"),
        ("weighings", "erp_ticket"),
        ("weighings", "erp_status"),
        ("weighings", "erp_note"),
        # "Lewati" on the unloading queue (2026-10-01). NULL = still eligible.
        ("weighings", "unloading_queue_skipped_at"),
        # Konsol pabrik yang sudah jalan punya tabel `inspections` tanpa kolom ini;
        # `CREATE TABLE IF NOT EXISTS` di atas tidak akan menambahkannya. Baris lama
        # tetap NULL, sengaja: kelas aslinya memang tidak pernah direkam, dan
        # menebaknya dari `ripeness_status` akan mengarang (REJ bisa Unripe atau JK).
        ("inspections", "grade_class"),
        # Batch impor CSV (support). NULL untuk semua janjang dari line.
        ("inspections", "import_batch"),
    ):
        columns = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
    # Separate from the loop above: that loop can only do a plain `ADD COLUMN ... TEXT`,
    # but this column needs NOT NULL + DEFAULT so old rows land on `operator` instead
    # of a NULL readers have to guess at.
    operator_columns = {r["name"] for r in db.execute("PRAGMA table_info(operators)")}
    if "role" not in operator_columns:
        db.execute("ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'")
    db.executescript(_MIGRATE_SQL)


def _rename_indonesian_columns(db: sqlite3.Connection) -> None:
    """Carry a database written before the columns were renamed to English.

    The rename shipped without this pass, on the reasoning that no factory PC had ever
    run that schema. True for factory PCs, false for every machine that already had a
    console database: there the old names stayed and every read missed.

    `peran` is the sharp one: `_migrate` adds `role` as a *new* column defaulting to
    `operator`, so a database that still had `peran` came out with both, every support
    account silently demoted while keeping its name. The value is carried over before
    that runs, and `peran` dropped only once `role` holds it.
    """
    for table, pairs in _RENAMED_COLUMNS:
        columns = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if not columns:
            continue
        for old, new in pairs:
            if old in columns and new not in columns:
                db.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    _rename_operator_role(db)


def _rename_operator_role(db: sqlite3.Connection) -> None:
    """`peran` → `role`, keeping the value even when both columns exist."""
    columns = {r["name"] for r in db.execute("PRAGMA table_info(operators)")}
    if "peran" not in columns:
        return
    if "role" in columns:
        db.execute("UPDATE operators SET role = peran")
        db.execute("ALTER TABLE operators DROP COLUMN peran")
    else:
        db.execute("ALTER TABLE operators RENAME COLUMN peran TO role")


def _drop_pin_era_operators(db: sqlite3.Connection) -> None:
    """Rebuild `operators` if it still carries the six-digit-PIN shape.

    Dropped rather than migrated, deliberately. The PIN table keyed accounts by
    `full_name` with no email anywhere, and an email cannot be invented for a row: a
    guessed one would be a sign-in that silently belongs to nobody. The accounts are
    re-made by `make operator` or arrive with the next AutoERP pull, so the cost is one
    command on a dev database. No factory PC ran the PIN build: it never left that
    branch, and the sessions go with the table so nobody stays signed in against an
    account that no longer exists.
    """
    columns = {r["name"] for r in db.execute("PRAGMA table_info(operators)")}
    if columns and "pin_hash" in columns:
        db.execute("DROP TABLE IF EXISTS sesi")
        db.execute("DROP TABLE operators")
        db.executescript(_CREATE_SQL)
