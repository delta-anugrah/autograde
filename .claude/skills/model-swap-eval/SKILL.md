---
name: model-swap-eval
description: Evaluasi, ganti, dan rollback model deteksi YOLO di palmgrade-vision — pilih kandidat dari hasil training, pasang ke models/release/, rebuild TensorRT engine, verifikasi. Pakai kalau ada model baru dari tim AI, mau bandingin model, ganti MODEL_FILE, deteksi tiba-tiba meleset, atau rebuild engine setelah ganti GPU.
---

# Ganti & Evaluasi Model

## Yang lagi jalan

`MODEL_FILE` di `.env` (default `best_3class_v2.pt`) → dibaca
`Settings.ripeness_model_path` → **selalu dari `models/release/`**, bukan `models/`.

3 kelas: `ACC` / `Rej` / `TP`. `submit_grading()` cuma memetakan `acc` → coil OK
dan `rej` → coil NG (`plc/worker.py::_coil_for`); status lain diabaikan diam-diam.
**Ganti nama kelas = putusin sinyal PLC.** Cek `plc-coil-map` sebelum ngutak-ngatik nama kelas.

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
# .env:  MODEL_FILE=<kandidat>.pt
```

### 2. Rebuild TensorRT engine

Nama engine diturunin dari **stem nama model**
(`best_3class_v2.pt` → `best_3class_v2.sm75.engine`, lihat `engine_path_for_gpu`).
Jadi begitu `MODEL_FILE` ganti, engine lama otomatis nggak kepilih dan runtime
**diam-diam turun ke `.pt`** — jalan, tapi ±2x lebih lambat. Nggak ada error.

Dev / laptop:
```bash
make build-engine
```

**PC pabrik — `make build-engine` NGGAK BISA** (target Makefile nge-build dari
source yang nggak ada di situ). Wajib tiga `-f`:
```bash
cd /opt/palmgrade
docker compose --project-directory vision \
  -f vision/docker-compose.yml \
  -f vision/docker-compose.prod.yml \
  -f vision/docker-compose.factory.yml \
  run --rm --entrypoint python ripe-line-1 scripts/build_engine.py
palmgrade restart
```
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

Balikin `MODEL_FILE` ke nilai lama, restart. Engine lama masih di `engines/`
(nama beda), jadi langsung kepakai lagi — nggak perlu rebuild.

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
| `DEBUG_MODEL_OUTPUT` | kosong | Nyalain buat lihat output mentah per frame di log |

## Provenance

Model produksi datang dari tim AI, **bukan dari repo ini** — nggak ada kode
training maupun dataset di sini. Arsip kandidat + `results.csv` +
`confusion_matrix.png` ada di workspace (`Model baru/`), di luar git dan cuma di
laptop developer. Kalau butuh reproduksi training, itu ke tim AI.
