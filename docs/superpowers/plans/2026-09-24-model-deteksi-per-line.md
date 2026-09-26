# Model Deteksi per Line: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layar Support "Model Deteksi" di konsol untuk memilih berkas model YOLO per line, lengkap dengan daftar kelas tiap model, status engine TensorRT, dan modal konfirmasi sebelum line direstart.

**Architecture:** Menyalin pola Sumber Kamera persis. Pilihan disimpan sebagai `LINE_N_MODEL_FILE` di `media.env` (penulis tunggal: `MediaEnvService`), line membacanya sendiri di `Settings.__post_init__`, lalu konsol merestart line lewat `POST /internal/restart`. Kelas model dibaca konsol **tanpa torch**: `.pt` lewat unpickler tiruan yang cuma membaca `data.pkl` di dalam zip, `.engine` lewat header JSON yang ditulis ekspor Ultralytics.

**Tech Stack:** Python 3 / FastAPI / pickle + zipfile stdlib / console.html vanilla JS / pytest.

**Spec:** Percakapan 2026-09-24 dengan user, diringkas di memori `project_next_switch_model_dari_konsol`. Keputusan user:
1. Model **per line** (untuk development).
2. Boleh diganti **kapan pun**; ganti = restart line, jadi **modal info muncul sebelum restart**.
3. **Support saja.**
4. Tiap model menampilkan **kelas di dalamnya**.

## Global Constraints

- Konsol tidak boleh mengimpor `torch`, `ultralytics`, atau `cv2` di jalur baru. CI unit berjalan tanpa torch.
- Unpickler tidak boleh memanggil kelas asli apa pun selain `collections.OrderedDict`. Semua `find_class` lain memulangkan stub.
- `console.html` tetap nol referensi `https://`.
- `LINE_N_MODEL_FILE` kosong = pakai `MODEL_FILE` dari `.env` (bawaan PC). PC lama tanpa kunci itu tidak berubah perilaku.
- Nama berkas model: tanpa `/`, `\`, `..`, NUL, newline; berakhiran `.pt`; harus ada di `models/release/`.
- Model yang kelasnya bukan tepat `Ripe/Unripe/JK/TP` ditolak saat simpan (400), dan tampil tapi tidak bisa dipilih di dropdown.
- Simpan Sumber Kamera tidak boleh menghapus `LINE_N_MODEL_FILE`, dan sebaliknya.
- Hanya line yang pilihannya berubah yang direstart.
- Body PR dalam bahasa Inggris mengikuti `.github/pull_request_template.md`; commit boleh Indonesia; tanpa baris co-author.

## Review Focus

1. **Simpan Sumber Kamera sesudah memilih model**: model harus tetap tersimpan. Diuji di Task 3.
2. **`media.env` disunting tangan dengan `LINE_2_MODEL_FILE=../../etc/x.pt`**: line harus mengabaikannya dan memakai bawaan, bukan membuka path itu. Diuji di Task 4.
3. **`.pt` rusak / bukan zip / berkas 0 byte di `models/release`**: daftar tetap tampil, model itu `kelas: null`, tidak bisa dipilih, konsol tidak 500. Diuji di Task 2.
4. **Engine ada tapi lebih tua dari `.pt`-nya** (isi `best.pt` diganti, nama sama), tampil "engine basi". Diuji di Task 2.
5. **Line mati saat simpan**: berkas tetap tersimpan, respons menandai line itu tidak direstart. Diuji di Task 5.

---

### Task 1: Aturan domain: kelas model dan pilihan model

**Files:**
- Modify: `src/palmgrade/domain/grade_class.py` (tambah `periksa_kelas`)
- Create: `src/palmgrade/domain/pilihan_model.py`
- Test: `tests/unit/test_pilihan_model.py`

**Interfaces:**
- Produces: `periksa_kelas(names: Iterable[str]) -> tuple[list[str], list[str]]` = (tidak_dikenal, hilang), keduanya terurut.
- Produces: `class ModelTidakSah(ValueError)`; `bersihkan_pilihan_model(payload: dict) -> dict[str, str]` untuk kunci tepat `LINE_CODES`, nilai `""` atau nama `.pt` yang aman.

- [ ] **Step 1: Tulis tes gagal**

```python
from palmgrade.domain.grade_class import periksa_kelas
from palmgrade.domain.pilihan_model import ModelTidakSah, bersihkan_pilihan_model
import pytest

def test_periksa_kelas_empat_kelas_cocok_tanpa_peduli_huruf():
    assert periksa_kelas(["jk", "Ripe", "TP", "UNRIPE"]) == ([], [])

def test_periksa_kelas_model_lama():
    asing, hilang = periksa_kelas(["ACC", "Rej", "TP"])
    assert asing == ["ACC", "Rej"] and hilang == ["JK", "Ripe", "Unripe"]

def test_pilihan_sah_dan_bawaan():
    p = {"line-1": "best.pt", "line-2": "", "line-3": " coba.pt "}
    assert bersihkan_pilihan_model(p) == {"line-1": "best.pt", "line-2": "", "line-3": "coba.pt"}

@pytest.mark.parametrize("nama", ["../best.pt", "a/b.pt", "best.onnx", "x\n.pt", "..pt", 5])
def test_pilihan_berbahaya_ditolak(nama):
    with pytest.raises(ModelTidakSah):
        bersihkan_pilihan_model({"line-1": nama, "line-2": "", "line-3": ""})

def test_line_kurang_atau_asing_ditolak():
    with pytest.raises(ModelTidakSah):
        bersihkan_pilihan_model({"line-1": ""})
    with pytest.raises(ModelTidakSah):
        bersihkan_pilihan_model({"line-1": "", "line-2": "", "line-3": "", "line-9": ""})
```

- [ ] **Step 2: Jalankan, pastikan gagal**: `.venv/bin/pytest tests/unit/test_pilihan_model.py -q` → ImportError.

- [ ] **Step 3: Implementasi**

`grade_class.py`:
```python
def periksa_kelas(names) -> tuple[list[str], list[str]]:
    """(tidak dikenal, hilang) dari daftar nama kelas model. Dua-duanya kosong = cocok."""
    names = [str(n) for n in names]
    dikenal = {grade_class_or_none(n) for n in names}
    asing = sorted(n for n in names if grade_class_or_none(n) is None)
    hilang = sorted(c for c in GRADE_CLASSES if c not in dikenal)
    return asing, hilang
```

`pilihan_model.py`: `LINE_CODES` diimpor dari `services.media_env_service`? **Tidak**, domain tidak boleh bergantung pada service. Salin tuple `("line-1","line-2","line-3")` sebagai `LINE_MODEL`, dan tes di Task 3 memastikan sama dengan `LINE_CODES`.
```python
_BERBAHAYA = ("/", "\\", "..", "\x00", "\n", "\r")
class ModelTidakSah(ValueError): ...
def bersihkan_nama_model(nama) -> str:
    if not isinstance(nama, str): raise ModelTidakSah("nama model harus teks")
    nama = nama.strip()
    if not nama: return ""
    if any(b in nama for b in _BERBAHAYA): raise ModelTidakSah(f"nama model tidak sah: {nama!r}")
    if not nama.endswith(".pt") or nama == ".pt": raise ModelTidakSah(f"{nama}: harus berkas .pt")
    return nama
def bersihkan_pilihan_model(payload) -> dict[str, str]:
    # objek, kunci tepat LINE_MODEL, tiap nilai lewat bersihkan_nama_model
```

- [ ] **Step 4: Tes lulus**: perintah yang sama → PASS.
- [ ] **Step 5: Commit**: `feat(model): aturan domain pilihan model per line`

### Task 2: Pustaka model: baca kelas tanpa torch

**Files:**
- Create: `src/palmgrade/services/model_library.py`
- Test: `tests/unit/test_model_library.py`

**Interfaces:**
- Consumes: `periksa_kelas` (Task 1).
- Produces: `baca_kelas_pt(path: Path) -> list[str] | None`; `baca_meta_engine(path: Path) -> dict | None`; `ModelLibrary(release_dir: Path, engines_dir: Path)` dengan `daftar() -> list[dict]`, `cari(nama) -> dict | None`.
- Bentuk satu item `daftar()`:
  `{"berkas": "best.pt", "ukuran_mb": 49.6, "diubah": "2026-09-16T14:02:00", "kelas": ["JK","Ripe","TP","Unripe"] | None, "cocok": bool, "alasan": str, "engine": [{"berkas": "best.sm86.engine", "sm": "86", "kelas": [...] | None, "dibuat": iso | None, "basi": bool}]}`

- [ ] **Step 1: Tes gagal.** Fixture membuat `.pt` palsu yang bentuknya sama dengan checkpoint Ultralytics: zip berisi `arsip/data.pkl`, hasil `pickle.dumps` dari `{"model": obj, "train_args": {}}` di mana `obj` adalah instance kelas bernama `DetectionModel` dengan `__module__ = "ultralytics.nn.tasks"` dan atribut `names`. Kelas palsu itu didaftarkan di `sys.modules` hanya saat `dumps`, lalu dihapus, supaya tes membuktikan pembacaan tidak butuh modulnya.

```python
def test_baca_kelas_pt_palsu(tmp_path): assert baca_kelas_pt(buat_pt(tmp_path/"a.pt", {0:"JK",1:"Ripe"})) == ["JK","Ripe"]
def test_pt_rusak_none(tmp_path): (tmp_path/"r.pt").write_bytes(b"bukan zip"); assert baca_kelas_pt(tmp_path/"r.pt") is None
def test_pt_kosong_none(tmp_path): (tmp_path/"k.pt").touch(); assert baca_kelas_pt(tmp_path/"k.pt") is None
def test_unpickler_tidak_menjalankan_kelas_asli(tmp_path): # pickle berisi os.system -> tidak dipanggil, hasil None/stub
def test_meta_engine(tmp_path): # tulis 4 byte LE panjang + json {"names":{"0":"JK"},"date":...} + b"\0"*16
def test_meta_engine_sampah_none(tmp_path): # b"\xff\xff\xff\x7f..." -> None
def test_daftar_cocok_dan_tidak(tmp_path): # best.pt 4 kelas cocok, lama.pt ACC/Rej tidak cocok + alasan menyebut ACC
def test_engine_basi_kalau_pt_lebih_baru(tmp_path): # engine date < mtime pt -> basi True
def test_cache_tidak_membaca_ulang(tmp_path, monkeypatch): # hitung panggilan baca_kelas_pt
def test_model_asli_kalau_ada(): # skip kalau models/release/best.pt tidak ada; kelas == JK,Ripe,TP,Unripe
```

- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasi**: unpickler yang terbukti di prototipe 2026-09-24 (9 ms per model, dua model asli terbaca):

```python
class _Stub(dict):
    def __new__(cls, *a, **k): return dict.__new__(cls)
    def __init__(self, *a, **k): pass
    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) == 2:
            state = {**(state[0] or {}), **(state[1] or {})}
        if isinstance(state, dict): self.update(state)
    def append(self, _): pass
    def extend(self, _): pass

class _PembacaAman(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) == ("collections", "OrderedDict"): return collections.OrderedDict
        return _Stub
    def persistent_load(self, pid): return None
```
`baca_kelas_pt`: `zipfile.ZipFile`, entri yang berakhiran `/data.pkl` (batas 64 MB), `load()`, ambil `ckpt["model"]` lalu `ckpt["ema"]`, `names` dict → nilai terurut menurut kunci. Semua `Exception` → `None` + log WARNING sekali.
`baca_meta_engine`: baca 4 byte `int.from_bytes(..., "little", signed=True)`, tolak `<=0` atau `>1_000_000`, `json.loads`, `names` → list terurut kunci int.
`ModelLibrary.daftar()`: `*.pt` di `release_dir` terurut; cache per `(nama, st_size, st_mtime_ns)`; engine = `engines_dir.glob(f"{stem}.sm*.engine")`; `basi = dibuat < mtime pt` (engine tanpa `date` → pakai mtime engine).
- [ ] **Step 4: Tes lulus.**
- [ ] **Step 5: Commit**: `feat(model): baca kelas model .pt dan engine tanpa torch`

### Task 3: `media.env` memuat pilihan model

**Files:**
- Modify: `src/palmgrade/services/media_env_service.py`
- Modify: `media.env.example`
- Test: `tests/unit/test_media_env_service.py`

**Interfaces:**
- Produces: `MediaEnvService.baca_model() -> dict[str, str]`; `MediaEnvService.tulis_model(pilihan: dict[str, str]) -> None`. `tulis()` (kamera) sekarang mempertahankan model.

- [ ] **Step 1: Tes gagal**
```python
def test_tulis_model_mempertahankan_kamera(tmp_path): # tulis kamera video -> tulis_model -> baca() masih video
def test_tulis_kamera_mempertahankan_model(tmp_path): # Review Focus 1
def test_baca_model_bawaan_kosong(tmp_path): assert svc.baca_model() == {"line-1": "", "line-2": "", "line-3": ""}
def test_line_codes_domain_sama(): assert LINE_MODEL == LINE_CODES
```
- [ ] **Step 2: Gagal.**
- [ ] **Step 3: Implementasi**: pisahkan penulisan atomik yang sudah ada ke `_tulis_isi(kamera, model)`; blok per line ditambah `LINE_{n}_MODEL_FILE={model}`. `tulis(setelan)` = `_tulis_isi(setelan, self.baca_model())`; `tulis_model(p)` = `_tulis_isi(self.baca(), p)`. Kepala berkas menyebut "sumber kamera dan model deteksi". Perbaiki docstring usang ("lewat `env_file`" → `--env-file`). `media.env.example` tambah `LINE_N_MODEL_FILE=` dengan komentar "kosong = MODEL_FILE di .env".
- [ ] **Step 4: Lulus** (termasuk seluruh `test_media_env_service.py` lama).
- [ ] **Step 5: Commit**: `feat(model): media.env menyimpan model per line`

### Task 4: Line memuat model pilihannya dan melaporkannya

**Files:**
- Modify: `src/palmgrade/core/config.py` (field `model_file`, `__post_init__`, `ripeness_model_path`, `engine_path_for_gpu`)
- Modify: `src/palmgrade/pipelines/model_registry.py` (cek kelas untuk dua backend, `ringkasan()`)
- Modify: `src/palmgrade/schemas/common_schema.py`, `src/palmgrade/services/health_service.py`, `src/palmgrade/core/dependencies.py`
- Test: `tests/unit/test_line_baca_media_env.py`

**Interfaces:**
- Produces: `Settings.model_file: str`; `ModelRegistry.ringkasan() -> {"model_file", "model_backend", "model_kelas"}`; `HealthDetailSchema.model_file/model_backend: str | None`, `model_kelas: list[str]`.

- [ ] **Step 1: Tes gagal**
```python
def test_model_dari_media_env_menang(tmp_path, monkeypatch): # MODEL_FILE=best.pt, LINE_2_MODEL_FILE=coba.pt, MACHINE_ID line-2 -> model_file coba.pt, engine path coba.sm86.engine
def test_model_kosong_pakai_env(...)
def test_model_berbahaya_diabaikan(...)  # Review Focus 2: ../../x.pt -> tetap best.pt
def test_model_tetap_terbaca_tanpa_baris_kamera(...)  # berkas cuma berisi LINE_1_MODEL_FILE
```
- [ ] **Step 2: Gagal.**
- [ ] **Step 3: Implementasi**
  - Field: `model_file: str = field(default_factory=lambda: os.getenv("MODEL_FILE", "best.pt").strip() or "best.pt")`.
  - `__post_init__`: baca `LINE_N_MODEL_FILE` **sebelum** cek `CAMERA_TYPE`; berlaku kalau `bersihkan_nama_model` lolos dan tidak kosong, selain itu log WARNING dan abaikan. Import dari `domain.pilihan_model` (domain, bukan service: aturan `config.py`).
  - `ripeness_model_path` / `engine_path_for_gpu` memakai `self.model_file`.
  - `ModelRegistry.__init__`: `_warn_on_unexpected_classes(self.model, logger)` dipindah ke **sesudah warm-up**, sehingga jalan juga untuk engine. `_warn_on_unexpected_classes` memakai `periksa_kelas`. `ringkasan()` memulangkan `model_file`, `backend`, kelas terurut.
  - `HealthService` dapat field opsional `model: ModelRegistry | None = None`; `get_health_service()` mengisinya dengan `get_model_registry()`.
- [ ] **Step 4: Lulus**: `tests/unit/test_line_baca_media_env.py`, `test_grade_class_detection.py`, seluruh `tests/unit` yang menyentuh health.
- [ ] **Step 5: Commit**: `feat(model): line memuat model per line dan melaporkannya di health`

### Task 5: Service + route konsol

**Files:**
- Modify: `src/palmgrade/services/console_service.py`, `src/palmgrade/routes/console.py`, `src/palmgrade/core/config.py` (`models_release_dir`, `engines_dir` tetap dari `repo_root`)
- Test: `tests/unit/test_console_model_deteksi.py`, `tests/e2e/test_model_deteksi_lane.py`, `tests/unit/test_console_sumber_routes.py` (pola teks)

**Interfaces:**
- Produces: `GET /api/console/dev/model-deteksi` → `{"lines": {"line-1": "best.pt"|"" ...}, "model": [item Task 2]}`.
- Produces: `POST /api/console/dev/model-deteksi` body `{"line-1": "...", "line-2": "...", "line-3": "..."}` → `{"lines": [{"line_code", "berubah", "direstart", "alasan"?}], ...GET}`; 400 `ModelTidakSah`; 403 bukan support.

- [ ] **Step 1: Tes gagal**: `FakeLine` sama dengan tes Sumber Kamera; `svc` fixture menaruh `models/release` palsu di `tmp_path` dan `replace(Settings(), repo_root=tmp_path)`.
```python
def test_baca_daftar_dan_pilihan(svc)
def test_simpan_menulis_dan_merestart_yang_berubah(svc)
def test_tidak_berubah_tidak_restart(svc)
def test_model_tidak_ada_ditolak_tanpa_menulis(svc)
def test_model_kelas_asing_ditolak(svc)   # alasan menyebut kelasnya
def test_line_mati_tidak_membatalkan_simpan(svc)   # Review Focus 5
```
e2e: simpan lewat HTTP → berkas tertulis + restart; operator 403; model asing 400.
- [ ] **Step 2: Gagal.**
- [ ] **Step 3: Implementasi**: `_model_library()` → `ModelLibrary(settings.models_release_dir, settings.engines_dir)`; `simpan_model_deteksi(payload, diubah_oleh)`: bersihkan → tiap nama tak kosong wajib `cari()` ada + `cocok` → `sebelum = baca_model()` → `tulis_model` → WARNING siapa → restart yang berubah (salin loop Sumber Kamera). Route menyalin pasangan Sumber Kamera, `ModelTidakSah` → 400.
- [ ] **Step 4: Lulus.**
- [ ] **Step 5: Commit**: `feat(model): endpoint Support untuk memilih model per line`

### Task 6: Konsol di prod bisa melihat folder model

**Files:**
- Modify: `docker-compose.prod.yml` (volume konsol `./models:/app/models:ro`, `./engines:/app/engines:ro`), `docker-compose.yml` (sama, walau `.:/app` sudah mencakup, eksplisit supaya prod dan dev tidak bercabang diam-diam)
- Test: `tests/unit/test_compose_model_deteksi.py` (teks: blok volume konsol di dua berkas memuat kedua mount)

- [ ] Tes gagal → tambah mount → lulus → commit `feat(model): konsol me-mount models dan engines read-only`

### Task 7: Layar "Model Deteksi" + modal restart

**Files:**
- Modify: `src/palmgrade/static/console.html`
- Test: `tests/unit/test_console_html_model.py`

**Perilaku layar:**
- Tab Support `data-tab="model-deteksi" data-dev="1"`, masuk `TAB_SAH` dan `MUAT_TAB`.
- Satu kartu per line: baris "Sedang jalan" dari `/api/console/dev/diagnostik` (`model_file · model_backend`, atau "tidak menjawab"); `<select data-model="line-N">` berisi "Bawaan PC (.env)" + tiap model; model `cocok=false` → `<option disabled>` dengan alasan; di bawah select, chip kelas model terpilih + status engine (`sm86 ✓`, `belum ada engine — jalan di .pt, ±2x lebih lambat`, `engine basi — build ulang`).
- Tabel "Semua model di PC ini": berkas, ukuran, kelas, engine, cocok.
- Tombol "Simpan & Restart" → **`<dialog id="model-modal">`** (pola `foto-modal`) yang menyebut line yang berubah, "line akan restart ±10 detik, janjang yang lewat selama itu tidak dihitung", dan per line yang memegang truk (dari `/api/console/state` → `lines[].assignment.plate_number`) "sedang memproses truk {plat}: hasil truk ini akan campuran dua model". Tombol "Batal" dan "Ganti & Restart". Tidak ada yang berubah → toast "tidak ada yang berubah", tanpa modal.
- Sesudah POST: toast seperti Sumber Kamera (sukses / sebagian tidak menjawab), lalu muat ulang tab.
- i18n `KAMUS` id + en untuk semua teks baru.

- [ ] **Step 1: Tes teks gagal**: id elemen, endpoint dua-duanya, `TAB_SAH`/`MUAT_TAB`, `showModal`, nol `https://`.
- [ ] **Step 2-4: Implementasi, lulus.**
- [ ] **Step 5: Verifikasi di browser**: konsol native + tiga line palsu (pola verifikasi tab PLC 2026-09-24): login support, pilih `best_3class_v2.pt` harus disabled dengan alasan, pilih `best.pt` di line-2, modal muncul menyebut line-2, konfirmasi, `media.env` berisi `LINE_2_MODEL_FILE=best.pt`. Screenshot.
- [ ] **Step 6: Commit**: `feat(console): layar Model Deteksi per line dengan modal restart`

### Task 8: Dokumen

**Files:**
- Create: `docs/runbooks/2026-09-24-model-deteksi-per-line.md` (pakai, jebakan: engine per model harus dibuild per line `run ... ripe-line-N scripts/build_engine.py`; PC pabrik perlu mount `models`/`engines` di compose host)
- Modify: `.claude/skills/model-swap-eval/SKILL.md` (jalur layar sebagai cara utama), `docs/backend-overview.md` L520 (masih "3 kelas"), `docs/MANUAL.md` bagian Support.
- Commit `docs(model): layar Model Deteksi`

### Akhir

- `ruff check` pada berkas yang disentuh, `pytest tests/unit/ -q`, `pytest tests/e2e/ -q -rs`.
- PR ke `staging` (template, bahasa Inggris).
