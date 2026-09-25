# Danger Zone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kotak "Danger Zone" di tab Setelan (support saja) berisi lima aksi — restart semua line, logout paksa semua akun, hapus rekaman video, hapus data transaksi, hapus semua data — dengan pengaman di server.

**Architecture:** Logika keputusan (hambatan/peringatan, tabel per mode) murni di `domain/bahaya.py`. Line menghapus datanya sendiri **saat boot** lewat penanda `state/.hapus-data` (`services/hapus_data_line.py`, tanpa torch), lewat router internal baru yang dirakit dengan fungsi pabrik supaya bisa diuji di CI tanpa torch. Konsol menghapus miliknya di tempat (`DELETE` dalam transaksi) lewat `BahayaService`.

**Tech Stack:** Python 3.11, FastAPI, SQLite, httpx; `console.html` vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-25-danger-zone-design.md`

## Global Constraints

- Konfirmasi hapus: teks persis `HAPUS` (spasi di tepi dibuang, huruf besar-kecil dibedakan). Diperiksa di server.
- Semua rute konsol baru lewat `require_support`; rute line baru lewat `x-internal-secret`.
- `license.db*` line dan kunci `sync_state` berawalan `setelan_` **tidak pernah** dihapus.
- Tidak ada `confirm()`/`prompt()` browser; konfirmasi inline, tombol Batal lebih dulu.
- Tiap aksi meninggalkan satu `logger.warning` berisi email yang menekan (masuk `event_log` lewat `SqliteLogHandler`).
- Modul yang diuji di CI tidak boleh mengimpor `core.dependencies`, `routes/internal.py`, torch, atau cv2.
- Komentar kode & docs boleh Indonesia; PR bahasa Inggris ikut template.

## Review Focus

1. **Tabel baru di `console.db` yang belum digolongkan** — harus membuat test merah, bukan diam-diam tertinggal/ikut terhapus. → Task 1 (`test_semua_tabel_konsol_digolongkan`).
2. **Boot terputus di tengah hapus** (listrik mati) — penanda tetap ada, boot berikutnya mengulang; berkas yang gagal dihapus tidak menghapus penanda. → Task 2.
3. **`line-1` menghapus rekaman `line-10`** (glob awalan) — tidak boleh. → Task 2.
4. **Kondisi berubah antara panel dibuka dan tombol ditekan** (truk baru dipasang) — server menolak 409 walau layar bilang aman. → Task 5/6.
5. **Janjang yang lewat di detik terakhir sebelum line mati** masuk ke DB konsol sesudah dikosongkan — konsol menunggu line mati dulu. → Task 5 (`test_menunggu_line_mati_sebelum_menghapus_konsol`).

---

### Task 1: Aturan murni — `domain/bahaya.py`

**Files:** Create `src/palmgrade/domain/bahaya.py`; Test `tests/unit/test_bahaya_domain.py`

**Interfaces — Produces:**
- `KONFIRMASI_HAPUS = "HAPUS"`, `MODE_TRANSAKSI = "transaksi"`, `MODE_SEMUA = "semua"`, `MODE_HAPUS = (MODE_TRANSAKSI, MODE_SEMUA)`
- `konfirmasi_sah(teks: str | None) -> bool`
- `@dataclass(frozen=True) KeadaanLine(line_code: str, terjangkau: bool, truk_terpasang: bool = False, outbox_pending: int | None = None, merekam: bool = False, rekaman_berkas: int = 0, rekaman_bytes: int = 0)`
- `@dataclass(frozen=True) KeadaanKonsol(erp_aktif: bool, erp_pending: int = 0, erp_gagal: int = 0)`
- `hambatan_hapus_data(lines, konsol) -> list[dict]` — kode `line_mati`, `truk_terpasang`, `antrean_line`, `antrean_erp`; tiap item `{"kode", "line"?, "jumlah"?}`
- `peringatan_hapus_data(lines, konsol, mode) -> list[dict]` — `foto_belum_r2` (selalu), `kiriman_gagal`, `erp_mati`, `semua_keluar` (mode semua)
- `peringatan_restart(lines) -> list[dict]` — `line_mati`, `truk_terpasang`, `line_merekam`
- `peringatan_hapus_rekaman(lines) -> list[dict]` — `line_mati`, `line_merekam`
- `GOLONGAN_TABEL_KONSOL: dict[str, str]` — tiap tabel `console.db` → `"transaksi" | "semua" | "sebagian"`
- `tabel_dihapus(mode) -> tuple[str, ...]`, `kunci_state_dihapus(kunci, mode) -> bool`

- [ ] Test: konfirmasi (`HAPUS`, ` HAPUS `, `hapus`, `""`, `None`); tiap kode hambatan muncul untuk keadaan yang tepat dan tidak untuk line sehat; `antrean_erp` hanya kalau `erp_aktif`; `erp_mati` peringatan saat `erp_aktif=False` dan ada baris; `tabel_dihapus` per mode; `kunci_state_dihapus` (`setelan_grading` tidak pernah, `erp_cursor_truck` hanya mode semua, `erp_visit_resend_day` selalu); **`test_semua_tabel_konsol_digolongkan`**: `sqlite_master` dari `ConsoleStore` baru == kunci `GOLONGAN_TABEL_KONSOL`.
- [ ] Jalankan → merah (modul belum ada). Implementasi. Jalankan → hijau. Commit.

### Task 2: Hapus sisi line — `services/hapus_data_line.py`

**Files:** Create `src/palmgrade/services/hapus_data_line.py`; Test `tests/unit/test_hapus_data_line.py`

**Interfaces — Produces:**
- `PENANDA = ".hapus-data"`
- `tulis_penanda(state_dir: Path, *, mode: str, diminta_oleh: str, now: float) -> Path`
- `hapus_kalau_diminta(artifacts_dir: Path, state_dir: Path) -> dict | None` → `{"mode", "diminta_oleh", "dihapus": int, "gagal": int}`; `None` tanpa penanda
- `ringkas_rekaman(rekaman_dir: Path, line_code: str) -> dict` → `{"berkas", "bytes"}`
- `hapus_rekaman(rekaman_dir: Path, line_code: str) -> dict` → `{"berkas", "bytes"}`

Inti:

```python
_SIMPAN_ARTIFACTS = "license.db"   # license.db, -wal, -shm, -journal

def hapus_kalau_diminta(artifacts_dir, state_dir):
    penanda = state_dir / PENANDA
    if not penanda.exists():
        return None
    info = _baca_penanda(penanda)          # rusak -> {"mode": "?", "diminta_oleh": "?"}
    dihapus = gagal = 0
    for anak in _isi(artifacts_dir):
        if anak.name.startswith(_SIMPAN_ARTIFACTS):
            continue
        ok, n = _hapus(anak); dihapus += n; gagal += 0 if ok else 1
    for anak in _isi(state_dir):
        if anak.name == PENANDA:
            continue
        ok, n = _hapus(anak); dihapus += n; gagal += 0 if ok else 1
    if gagal == 0:
        penanda.unlink()                   # PALING AKHIR
    return {**info, "dihapus": dihapus, "gagal": gagal}
```

Rekaman: cocokkan `f"{line_code}_"` + akhiran `.mp4` — `line-1_…` tidak cocok dengan `line-10_…`.

- [ ] Test: tanpa penanda → `None`, tidak ada yang tersentuh; dengan penanda → isi `artifacts/` (results bersarang, `outbox.db`, `-wal`) hilang, `license.db`/`license.db-wal` tetap, isi `state/` hilang, penanda hilang; berkas yang gagal dihapus (monkeypatch `_hapus`) → penanda **tetap**, panggilan kedua menghapus; penanda JSON rusak tetap diproses; folder tidak ada → tidak error; rekaman: hanya milik line itu (`line-1_…mp4`, `line-1_…-2.mp4`) terhapus, `line-10_…`, `line-2_…`, `.txt` tetap; ringkasan menjumlah byte.
- [ ] Merah → implementasi → hijau → commit.

### Task 3: Router internal line tanpa torch — `routes/internal_bahaya.py` + `main.py`

**Files:** Create `src/palmgrade/routes/internal_bahaya.py`; Modify `src/palmgrade/main.py` (awal lifespan + include router); Test `tests/unit/test_internal_bahaya_routes.py`, `tests/e2e/test_internal_bahaya_lane.py`

**Interfaces — Consumes:** Task 2. **Produces:**
- `buat_router(*, settings: Callable[[], Settings], state: Callable[[], RuntimeState], keluar: Callable[[float], None]) -> APIRouter` (prefix `/internal`)
- `POST /internal/hapus-data` body `{"mode", "diminta_oleh"}` → 200 `{"status": "menghapus", "jeda_detik": 1.0}`; 409 `{"detail": {"kode": "truk_terpasang"}}` bila `state.current_assignment_id`; 400 mode asing
- `POST /internal/rekam/hapus` → 200 `{"line_code", "berkas", "bytes"}`; 409 `{"detail": {"kode": "sedang_merekam"}}`
- `GET /internal/rekam/berkas` → `{"line_code", "berkas", "bytes", "merekam"}`

`main.py`: baris pertama lifespan `hasil = hapus_kalau_diminta(settings.artifacts_dir, settings.state_dir)` + `logger.warning` kalau ada; `app.include_router(buat_router_bahaya(settings=get_settings, state=get_runtime_state, keluar=_jadwalkan_keluar), dependencies=[Depends(_verify_internal_secret)])`.

- [ ] Test unit (app FastAPI kosong + router pabrik, `keluar` palsu yang mencatat): 409 saat truk terpasang dan penanda TIDAK ditulis; 200 menulis penanda + memanggil `keluar(1.0)`; mode asing 400; rekam hapus 409 saat merekam; berkas dihitung. E2E: `Settings()` + `RuntimeState()` sungguhan dari env `ARTIFACTS_DIR`/`REKAMAN_DIR`, lalu `hapus_kalau_diminta` sungguhan membersihkan folder sesudah perintah.
- [ ] Merah → implementasi → hijau → commit.

### Task 4: Klien line + store konsol

**Files:** Modify `integrations/notifications/line_client.py`, `repositories/console_repository.py`, `integrations/erp/outbox_store.py`, `repositories/log_repository.py`; Test `tests/unit/test_line_client_bahaya.py`, `tests/unit/test_console_store_hapus.py`

**Produces:**
- `LineClient.hapus_data(line, *, mode, diminta_oleh) -> dict` (409 → `LinePlcTolak`), `rekam_hapus(line) -> dict`, `rekam_berkas(line) -> dict`, `hidup(line) -> bool` (GET `/health`, timeout 0,5 dtk, `False` untuk galat apa pun)
- `ConsoleStore.hapus_data(mode) -> dict[str, int]`, `hapus_semua_sesi() -> int`, `ringkas_data(*, now) -> dict` (`janjang`, `tiket`, `truk`, `akun`, `akun_lokal`, `sesi_aktif`)
- `ErpOutboxStore.hapus_semua() -> int`, `LogStore.hapus_semua() -> int`

- [ ] Test: klien lewat `httpx.MockTransport` (URL, secret, 409 → `LinePlcTolak`, putus → `LineUnavailable`, `hidup` False saat putus); store: mode transaksi menghapus janjang/tiket/penugasan, menyisakan truk/akun/sesi/`setelan_*`/`erp_cursor_*`; mode semua menyisakan hanya `setelan_*`; hitungan per tabel dikembalikan; `hapus_semua_sesi` menghitung.
- [ ] Merah → implementasi → hijau → commit.

### Task 5: `services/bahaya_service.py`

**Files:** Create `src/palmgrade/services/bahaya_service.py`; Test `tests/unit/test_bahaya_service.py`

**Produces:** `BahayaService(store, log_store, line_client, lines, erp_outbox, manifest_outbox, *, erp_aktif, hash_bawaan, hash_support, tarik_master=None, tunggu_mati_s=5.0, jeda_cek_s=0.25)` dengan `ringkasan()`, `restart_semua(oleh=)`, `logout_semua(oleh=)`, `hapus_rekaman(konfirmasi=, oleh=)`, `hapus_data(mode=, konfirmasi=, oleh=)`; galat `BahayaTidakSah` (400: `konfirmasi_salah`, `mode_asing`) dan `BahayaDitolak` (409: `bahaya_ditolak`, param `hambatan`).

- [ ] Test (store sungguhan + klien line palsu): ringkasan membawa hambatan per aksi; konfirmasi salah → `BahayaTidakSah`, **tidak ada line yang dipanggil**; hambatan → `BahayaDitolak`, tidak ada yang terhapus; sukses → tiap line dipanggil, konsol dikosongkan sesuai mode, `setelan_*` selamat, jejak jadi baris pertama log (handler terpasang); mode semua → akun bawaan dibuat ulang + `tarik_master` dipanggil (gagalnya tidak menggagalkan reset); line gagal di tengah → konsol tetap dikosongkan, line itu disebut; **`test_menunggu_line_mati_sebelum_menghapus_konsol`**; restart/logout/rekaman per line.
- [ ] Merah → implementasi → hijau → commit.

### Task 6: Rute konsol

**Files:** Modify `src/palmgrade/routes/console.py`; Test `tests/unit/test_bahaya_routes.py`, `tests/e2e/test_bahaya_lane.py`

**Produces:** `get_bahaya_service()`; `GET /api/console/dev/bahaya`; `POST .../bahaya/restart-line`, `.../logout-semua`, `.../hapus-rekaman` `{konfirmasi}`, `.../hapus-data` `{mode, konfirmasi}`.

- [ ] Test: 401 tanpa sesi, 403 operator, 400 konfirmasi salah, 409 dengan `code=bahaya_ditolak`, 200; e2e: login sungguhan → hapus data semua → sesi yang menekan ikut mati (401 berikutnya) dan akun bawaan ada lagi.
- [ ] Merah → implementasi → hijau → commit.

### Task 7: Layar — kotak Danger Zone di tab Setelan

**Files:** Modify `src/palmgrade/static/console.html`; Test `tests/unit/test_console_html_bahaya.py`

- [ ] `<details id="bahaya">` tertutup di bawah `#set-lines`; lima baris urut; satu panel per baris; `hapusSah(teks)`; render `panelBahaya(aksi, ringkasan)` (murni, diuji lewat node); kunci i18n `bahaya*`, `hambatan_*`, `peringatan_*`, `err_bahaya_ditolak`, `err_konfirmasi_salah`, `err_mode_asing` di dua bahasa.
- [ ] Test: posisi & tertutup, urutan aksi, Batal lebih dulu, tombol eksekusi mati sampai `HAPUS`, tiap kode hambatan/peringatan punya terjemahan di dua bahasa, tidak ada `confirm(`, endpoint dipanggil dengan `JSON.stringify`.
- [ ] Merah → implementasi → hijau → cek di browser (konsol native + line palsu) → commit.

### Task 8: Integrasi + dokumen

**Files:** Create `tests/integration/test_danger_zone_integrasi.py`; Modify `.github/workflows/ci.yml` (langkah `pytest tests/integration/ -rs`), `CLAUDE.md`, `README.md`, `docs/MANUAL.md`, `docs/backend-overview.md`, `.claude/skills/panduan-autograde/SKILL.md`

- [ ] Integrasi: `BahayaService` + store sungguhan + tiga app line sungguhan (router Task 3 + `/health`) di-dispatch lewat transport ASGI per port → hapus data → penanda di folder tiap line → `hapus_kalau_diminta` (simulasi boot) → folder bersih kecuali `license.db`, konsol bersih sesuai mode; jalur ditolak tidak menyentuh apa pun.
- [ ] Dokumen: tabel HTTP + aturan kritis baru di `CLAUDE.md`, README (`make reset-data` menyebut Danger Zone), MANUAL §3.7, backend-overview, skill.
- [ ] Suite penuh + ruff + cek merge dengan #171/#172 (`git merge-tree`) → commit → PR.
