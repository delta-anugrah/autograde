# Auto-load `.mfs` camera features on connect

**Date:** 2026-07-07
**Branch:** `fix/camera-select-by-serial`

## Problem

Kamera Hikrobot dikonfigurasi (framerate, exposure, gain, dll) manual lewat MVS
client (Feature → Feature Load `.mfs`). Kalau kamera baru / factory reset / EEPROM
belum di-set, kamera jalan di firmware default — mis. `capture=10.0` FPS konsisten
karena `AcquisitionFrameRate` kamera = 10. Kode `connect()` saat ini **nol
parameter**: tidak memuat `.mfs` sama sekali. Akibatnya setiap kamera baru butuh
setup MVS manual, dan config tidak ke-version di git.

Investigasi (2026-07-07, di laptop dev RTX 4050): container **BISA** pakai GPU
(`torch.cuda.is_available()=True`), `.pt` jalan di GPU — jadi 10 FPS **bukan**
bottleneck inference/CPU, tapi karena kamera hanya menghasilkan 10 frame/detik
(`config/camera/hikrobot.mfs` berisi `AcquisitionFrameRate=10`). `CAMERA_FPS` env
hanya cap atas software, tidak bisa memaksa kamera keluar lebih banyak frame.

**Target prod = GTX 1650** (bukan RTX 4050 laptop dev). Angka framerate final harus
diukur & dituning di 1650, bukan ditebak.

## Goal

Setiap container start, kamera Hikrobot **otomatis** apply setting dari file `.mfs`
via `MV_CC_FeatureLoad`, tanpa MVS manual. Config ke-version di git.

## Non-goals

- Mengubah nilai framerate di `hikrobot.mfs` (tetap 10; tuning nanti di GTX 1650).
- Menyentuh by-serial selection (sudah jalan di branch ini).
- Mengubah kontrak API / webhook / FE.

## Design

### Decisions (dari brainstorming)

1. **Fail behavior**: kalau `MV_CC_FeatureLoad` gagal (file tidak ada / korup /
   SDK menolak) → **log WARNING dan LANJUT** grabbing pakai setting firmware/EEPROM.
   Line tidak mati hanya karena `.mfs` bermasalah (production-safe).
2. **Path**: env per-line dengan default file bersama —
   `CAMERA_FEATURE_FILE=${LINE_N_FEATURE_FILE:-config/camera/hikrobot.mfs}`.
   Semua line default ke file yang sama; bisa override per line via `.env`.
3. **Framerate `.mfs`**: **tidak diubah** (tetap 10).

### Perubahan

1. **`core/config.py`** — field baru:
   ```python
   camera_feature_file: str | None = field(
       default_factory=lambda: (os.getenv("CAMERA_FEATURE_FILE", "").strip() or None)
   )
   ```

2. **`integrations/camera/hikrobot_camera.py` `connect()`** — tambah param
   `feature_file: str | None = None`. Setelah `OpenDevice` sukses & **sebelum**
   `StartGrabbing`, kalau `feature_file` di-set:
   - Cek `os.path.exists(feature_file)` dulu; kalau tidak ada → warning + skip.
   - Panggil `self.cam.MV_CC_FeatureLoad(feature_file)`.
   - ret == 0 → `logger.info("Loaded camera features from %s", feature_file)`.
   - ret != 0 → `logger.warning("MV_CC_FeatureLoad(%s) gagal: %s — lanjut pakai
     setting firmware", feature_file, format_mvs_ret(ret))`. **Tidak** raise.

3. **`base.py` / `opencv_camera.py` / `photo_camera.py`** — signature `connect()`
   terima `feature_file: str | None = None`, di-ignore selain hikrobot (sama pola
   dengan `serial`).

4. **`main.py`** — `camera.connect(..., feature_file=settings.camera_feature_file)`
   dan teruskan ke `FrameCaptureWorker(feature_file=...)`.

5. **`workers/frame_capture_worker.py`** — `__init__` terima `feature_file`, simpan
   `self._feature_file`, pakai di `_try_reconnect` → `connect(..., feature_file=...)`.

6. **`docker-compose.yml`** — tiap line tambah:
   ```yaml
   - CAMERA_FEATURE_FILE=${LINE_N_FEATURE_FILE:-config/camera/hikrobot.mfs}
   ```

7. **`.env`** — dokumentasi `LINE_N_FEATURE_FILE` (opsional; default sudah aktif).

## Testing

- **Unit**: `MV_CC_FeatureLoad` butuh SDK + kamera fisik → tidak bisa di-unit-test
  di host (tanpa python/torch/SDK). Signature-passthrough di worker/main dijaga
  konsisten dengan pola `serial` yang sudah ada.
- **Runtime (laptop dev RTX 4050)**: start 1 container, verifikasi log
  `"Loaded camera features from config/camera/hikrobot.mfs"` muncul, tidak ada
  ACCESS_DENIED, `capture` FPS sesuai `.mfs` (10). Uji juga path salah → muncul
  WARNING + kamera tetap grabbing.
- **Prod (GTX 1650)**: setelah tuning framerate `.mfs`, verifikasi FPS naik &
  inference sanggup (drop-oldest sudah menjaga latency).

## Risks

- Kalau `.mfs` berisi setting yang tidak kompatibel dengan model kamera lain →
  `MV_CC_FeatureLoad` sebagian gagal. Mitigasi: warn + lanjut (tidak fatal).
- File `.mfs` harus ikut ter-mount di container. Path `config/camera/hikrobot.mfs`
  relatif ke workdir `/app` (bind-mount `.:/app`) → sudah tersedia di container.
