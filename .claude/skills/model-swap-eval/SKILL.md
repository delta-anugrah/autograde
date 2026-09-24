---
name: model-swap-eval
description: Evaluasi, ganti, dan rollback model deteksi YOLO di autograde — pilih kandidat dari hasil training, pasang ke models/release/, pilih per line dari layar Support > Model Deteksi, rebuild TensorRT engine, verifikasi. Pakai kalau ada model baru dari tim AI, mau bandingin model, ganti model satu line, ganti MODEL_FILE, deteksi tiba-tiba meleset, atau rebuild engine setelah ganti GPU.
---

# Ganti & Evaluasi Model

## Yang lagi jalan

**Sejak 2026-09-24 model dipilih PER LINE dari konsol**: login support → tab
**Model Deteksi**. Pilihan disimpan sebagai `LINE_N_MODEL_FILE` di `media.env`;
kosong = **bawaan PC** = `MODEL_FILE` di `.env` (default `best.pt`). Keduanya
dibaca `Settings.model_file` → `ripeness_model_path` → **selalu dari
`models/release/`**, bukan `models/`. Cara pakai, prasyarat PC pabrik (mount
`models`/`engines` ke konsol di compose host), dan jebakannya:
`docs/runbooks/2026-09-24-model-deteksi-per-line.md`.

Layar yang sama menunjukkan **kelas tiap model** (dibaca tanpa torch),
**status engine** per GPU, dan model yang **sedang jalan** menurut line sendiri
(`/health/detail` → `model_file`, `model_backend`, `model_kelas`,
`model_kelas_cocok`). Kartu line menulis merah kalau kelas yang **jalan** bukan
empat kelas di bawah — satu-satunya tanda engine lama bernama sama yang dimuat.
Model yang kelasnya bukan tepat empat kelas itu tampil tapi tidak bisa dipilih.

**4 kelas** sejak 2026-09-16: `Ripe` / `Unripe` / `JK` / `TP`. Diverifikasi
langsung dari checkpoint, bukan dari dokumen:

| | `best.pt` (terpasang) | `best_3class_v2.pt` (lama, disimpan) |
|---|---|---|
| Kelas | `{0: JK, 1: Ripe, 2: TP, 3: Unripe}` | `{0: ACC, 1: Rej, 2: TP}` |
| Backbone | yolov8m | yolov8x |
| Parameter | 25,9 juta | 68,2 juta |
| Ukuran | 52,0 MB (52.040.274 byte, md5 `2dc72ada…`) | 130,4 MB |
| mAP50 | 0,982 | 0,981 |
| mAP50-95 | 0,813 | 0,846 |
| Precision / Recall | 0,967 / 0,981 | 0,965 / 0,974 |
| Dataset val | `nxt-pg-001-v1i` (Roboflow) | `sawit-dataset3class_v2` |
| Tanggal | 2026-09-16 | 2025-09-21 |

⚠️ **mAP dua baris itu TIDAK bisa dibandingkan** — val set-nya beda dan jumlah
kelasnya beda, jadi angka model lama yang terlihat lebih tinggi 0,033 itu
membandingkan dua ujian yang soalnya beda. Yang membuat model 4 kelas tetap
pilihan benar bukan mAP-nya, tapi: dia bisa memisahkan `Unripe` dari `JK`
(model lama cuma bisa bilang "Rej"), dan 2,6x lebih ringan — kerasa langsung di
FPS RTX 3060 yang menarik 3 line sekaligus.

Kalau memang perlu perbandingan jujur: siapkan satu val set 4 kelas, ukur
dua-duanya di situ, model lama dipetakan `Rej` = `Unripe` + `JK`. Dataset lama
sudah tidak ada di repo maupun MacBook.

`submit_grading()` cuma memetakan `acc` → coil OK dan `rej` → coil NG
(`plc/worker.py::_coil_for`); status lain diabaikan diam-diam. Kelas → verdict
diputuskan di `domain/grade_class.py`: `Ripe` → ACC, `Unripe` dan `JK` → REJ,
`TP` → tanpa verdict (tidak pernah ke PLC). **Ganti nama kelas = putusin sinyal
PLC.** Cek `plc-coil-map` sebelum ngutak-ngatik nama kelas.

⚠️ Pencocokan nama kelas **case-insensitive** (`grade_class.py:_BY_LOWER`).
Ini disengaja: model lama mengirim `{ACC, Rej, TP}` — tiga gaya kapital di tiga
kelas. Mengunci kapital persis adalah cara retrain berikutnya mematikan grading
tanpa satu pun error: semua janjang gagal dicocokkan dan tidak ada yang dihitung.

## Layout folder

| Folder | Isi | Mount |
|---|---|---|
| `models/release/` | model yang boleh dipakai runtime | `:ro` (read-only) |
| `models/experiments/` | kandidat, belum dipakai | — |
| `engines/` | cache TensorRT, **per-GPU** | writable |

## Baca hasil training kandidat

Tiap run training ninggalin `results.csv` + `confusion_matrix.png`. Urutan bacanya:

1. **`confusion_matrix.png` dulu, bukan mAP.** mAP satu angka; confusion matrix
   ngasih tau *jenis* errornya. Bedanya menentukan obatnya:
   - **Antar kelas** (ACC diprediksi Rej) → beneran masalah model, perlu retrain
   - **Background → kelas** (false positive) → obatnya **ROI + `CONF_THRESHOLD`**, bukan model baru
   - **Difoto di saat yang salah** (kekecilan, kepotong, janjang belum utuh) → itu **bukan**
     soal model maupun ambang: **geser `GARIS_CAPTURE`**. Sejak 2026-09-18 yang menentukan
     kapan janjang difoto adalah garis capture, bukan pusat kotak masuk ROI
   - **Kelas → background** (kelewat) → turunin `CONF_THRESHOLD`, atau memang objeknya kekecil di imgsz 640
2. `results.csv` kolom `metrics/mAP50-95(B)` di baris terakhir — buat bandingin antar run.
3. **Cek jumlah objek di confusion matrix.** Val set ratusan objek = angkanya
   berisik. Jangan ambil keputusan dari selisih mAP 0,01 di val set kecil.

⚠️ mAP antar run **cuma bisa dibandingin kalau val set-nya sama**. Nambah dataset
= angka lama dan baru beda semesta, bukan perbaikan.

## Prosedur ganti model

### 1. Taruh & tunjuk

```bash
cp <kandidat>.pt models/release/
```

Lalu pilih di konsol: Support → **Model Deteksi** → line yang mau dicoba →
Simpan & Restart → konfirmasi di modal. Cuma line itu yang restart.

Cara lama tetap sah untuk mengganti bawaan ketiga line sekaligus:
`MODEL_FILE=<kandidat>.pt` di `.env`, lalu `autograde restart`. Pilihan per
line di `media.env` **menang** atas `.env` untuk line yang memilikinya.

### 2. Rebuild TensorRT engine

Nama engine diturunin dari **stem nama model**
(`best.pt` → `best.sm75.engine`, lihat `engine_path_for_gpu`).
Jadi begitu model ganti, engine lama otomatis nggak kepilih dan runtime
**diam-diam turun ke `.pt`** — jalan, tapi ±2x lebih lambat. Nggak ada error.
Layar Model Deteksi menulisnya kuning ("Belum ada engine TensorRT").

`build_engine.py` membangun engine untuk model milik **service line yang
menjalankannya** (pilihan `media.env` line itu ikut terbaca). Model yang cuma
dipakai line 2 → jalankan lewat `ripe-line-2`, bukan `ripe-line-1`.

Dev / laptop:
```bash
make build-engine
```

**PC pabrik — `make build-engine` NGGAK BISA** (target Makefile nge-build dari
source yang nggak ada di situ). Folder service-nya `autograde/` sejak 2026-09-18
(dulu `vision/`), dan launchernya `autograde`, bukan `palmgrade`. Matikan line
dulu supaya build nggak berebut VRAM dengan 3 line yang lagi jalan:
```bash
cd /opt/palmgrade
autograde stop
F=(-f autograde/docker-compose.yml -f autograde/docker-compose.prod.yml)
[ -f autograde/docker-compose.factory.yml ] && F+=(-f autograde/docker-compose.factory.yml)
docker compose --project-directory autograde "${F[@]}" \
  run --rm --no-deps --entrypoint python ripe-line-1 scripts/build_engine.py
ls -la autograde/engines/        # harus muncul <stem>.sm86.engine (RTX 3060)
autograde
```
Terbukti di Lampung 2026-09-23: `best.sm86.engine` 45 MB jadi dalam ±4 menit.
File `prod` itu yang bawa mount `./engines:/app/engines`. Tanpa dia, engine
ditulis ke container sekali-pakai dan **hilang** begitu perintah selesai.

±5–15 menit sekali per GPU, sesudahnya instan (auto-skip kalau udah ada).

### 3. Verifikasi

```bash
docker logs ripe_line_1 2>&1 | grep backend=      # harus backend=tensorrt
ls -lh engines/                                   # ±180 MB
```

Masih `backend=pytorch` → engine nggak kebaca. Sistem tetap jalan, cuma lebih
lambat; `model_registry.py` sengaja fallback, bukan mati.

### 4. Rollback

Per line: pilih **Bawaan PC** (atau model lama) di layar Model Deteksi, simpan.
Bawaan: balikin `MODEL_FILE` ke nilai lama, restart. Engine lama masih di
`engines/` (nama beda), jadi langsung kepakai lagi — nggak perlu rebuild.

## Jebakan

- **Engine terkunci ke compute capability GPU.** Jangan pernah nyalin isi
  `engines/` antar mesin. Ganti VGA = rebuild.
- **`IMGSZ = 640` di-hardcode dua tempat**: `scripts/build_engine.py` dan default
  ultralytics di `realtime_inspection_pipeline.py::track_ripeness` (yang nggak
  ngoper `imgsz` sama sekali). **Kalau salah satu dinaikin, satunya wajib ikut,
  dan semua engine wajib di-rebuild** — kalau nggak, engine-nya beda resolusi
  sama yang diminta runtime.
- **Salah folder = container mati.** `models/release/`, bukan `models/`.
- `models/` di-mount `:ro`. Makanya `build_engine.py` nyalin `.pt` ke `engines/`
  dulu baru export — jangan "dirapikan" jadi export in-place.
- Engine itu FP16 dan runtime juga udah `.half()` — **hasil deteksinya setara**,
  bukan trade-off akurasi.
- **Model 130 MB itu ukuran yolov8x.** Kandidat 83 MB (yolov8l) bukan cuma "lebih
  kecil" — beda arsitektur, angkanya nggak sebanding langsung.

## Knob tanpa retrain

Coba ini dulu sebelum minta model baru — tiga-tiganya lebih murah dan bisa dibalikin:

| Knob | Default | Buat apa |
|---|---|---|
| `CONF_THRESHOLD` | `0.75` | Naik = false positive turun, kelewat naik. Turun = sebaliknya |
| `ROI_X1/Y1/X2/Y2` | `0` (mati) | Crop area kerja. Ini yang **matiin FP background secara struktural**, bukan nebak threshold |
| `GARIS_CAPTURE` | `0` (mati) | Titik janjang difoto (px, ruang stream). Ini knob buat "kefoto kecepetan/kelambatan", **bukan** `CONF_THRESHOLD`. Diatur dari tab Setelan konsol, tanpa restart |
| `SUMBU_GARIS` | `tegak` | Arah conveyor: `tegak` (px dari kiri) / `mendatar` (px dari atas) |
| `MODE_DEV` | `false` | Nyalain buat lihat **angka confidence di kotak janjang** — satu-satunya cara melihatnya di layar sejak angkanya dibuang dari label. Wajib dinyalain waktu nyetel `CONF_THRESHOLD` |
| `DEBUG_MODEL_OUTPUT` | kosong | Nyalain buat lihat output mentah per frame di log |

## Provenance

Model produksi datang dari tim AI, **bukan dari repo ini** — nggak ada kode
training maupun dataset di sini. Arsip kandidat + `results.csv` +
`confusion_matrix.png` ada di workspace (`Model baru/`), di luar git dan cuma di
laptop developer. Kalau butuh reproduksi training, itu ke tim AI.

## Gejala model salah pasang (terbukti Lampung 2026-09-23)

`MODEL_FILE` di `.env` PC Lampung masih `best_3class_v2.pt` selama seminggu
sesudah kode pindah ke 4 kelas (PR #100), karena **berkas model nggak ikut image**
(`.dockerignore`) dan `autograde pull` nggak pernah menyentuh `models/`. Tiga
gejala, satu penyebab:

- label bbox `ACC` / `Rej` (nama kelas model lama), bukan `Ripe/Unripe/JK/TP`
- `Rej` berwarna **hijau**: warna ikut verdict kelas yang dikenal, kelas asing
  verdict-nya kosong dan jatuh ke warna PASS (`realtime_inspection_pipeline.draw_boxes`)
- janjang lewat garis capture **nggak dihitung, nggak ke PLC** — kelas asing
  dianggap bukan buah (`frame_processing_worker._grade_class_or_none`), dan
  log `ERROR Kelas model tidak dikenal` cuma keluar **sekali per label per line**

Cara buktiin, semuanya read-only:
```bash
grep MODEL_FILE /opt/palmgrade/autograde/.env
docker logs ripe_line_2 2>&1 | grep -i "kelas model"      # terverifikasi vs tidak dikenal
docker exec ripe_line_1 python -c "from ultralytics import YOLO; print(YOLO('/app/models/release/best.pt').names)"
```
Yang benar: `{0: 'JK', 1: 'Ripe', 2: 'TP', 3: 'Unripe'}`.

⚠️ `best.pt` yang terpasang di Lampung (40.526.060 byte, md5 `9423c4c4…`,
berkas 18 Sep) **bukan** berkas yang sama dengan di MacBook (52.040.274 byte,
md5 `2dc72ada…`, 16 Sep). Kelasnya identik dan jalan; asalnya belum tercatat.
Kalau membandingkan hasil dua mesin, cek md5 dulu.

⚠️ `model_registry` memilih engine **cuma dari nama berkas** (`<stem>.sm<cc>.engine`
ada atau nggak). Mengganti isi `best.pt` tanpa ganti nama = engine lama tetap
dipakai, tanpa error. Ganti nama berkas atau hapus engine-nya. Sejak 2026-09-24
layar Model Deteksi menandai engine **basi** kalau lebih tua dari `.pt`-nya atau
kelasnya beda — tapi berkas baru berkelas sama yang disalin `cp -p` (mtime lama)
tetap lolos. Dan kelas model sekarang diperiksa saat boot untuk **dua** backend
(dulu cuma jalur `.pt`, jadi engine model lama dimuat tanpa ERROR).

