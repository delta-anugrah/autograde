# Biaya encode rekam video terhadap fps deteksi

**2026-09-22.** Diukur sebelum fitur Rekam Video masuk pabrik, karena satu
pertanyaan harus dijawab angka dan bukan dugaan: **apakah merekam memperlambat
grading?**

Kalau iya, fitur ini tidak boleh dipasang — janjang yang terlewat karena fps
turun adalah tonase yang salah dibayar, dan itu jauh lebih mahal daripada tidak
punya video.

## Jawabannya: tidak, +0,1%

Diukur di MacBook (CPU-only), line memakai `sample_sawit_video.avi` sebagai
sumber, rekaman 1280x1024 @ 5 fps dan 640x480 @ 8 fps, 8 jendela rekaman.

| | Sampel | fps rata-rata | Terendah | Tertinggi |
|---|---|---|---|---|
| **Tanpa** rekaman | 187 | **7,44** | 6,8 | 7,8 |
| **Saat** merekam | 15 | **7,45** | 7,3 | 7,6 |

Selisih **+0,1%** — di dalam derau pengukuran. `frame_dibuang` **nol** di setiap
rekaman.

Angka itu memang yang diharapkan dari rancangannya: encode jalan di thread
sendiri, dan `tulis()` cuma menaruh frame ke antrean yang membuang kalau penuh.
Thread deteksi tidak pernah menunggu encoder. Yang diukur di sini adalah bahwa
rancangan itu benar-benar terpasang, bukan bahwa niatnya baik.

## Ukuran berkas

Diukur pada resolusi target, bukan diekstrapolasi dari resolusi lain:

| Codec | 10 detik | Per jam per line |
|---|---|---|
| **`avc1` (H.264)** | 1,34 MB | **0,48 GB** |
| `mp4v` | 6,68 MB | 2,40 GB |

**`avc1` 5x lebih kecil**, dan itu yang dipakai (`mp4v` cuma cadangan kalau
build OpenCV di suatu PC tidak punya H.264 — lihat `_CODEC` di
`services/video_recorder.py`).

⚠️ Angka di atas dari **noise acak**, yang merupakan kasus **terburuk** untuk
H.264. Rekaman conveyor sungguhan jauh lebih kecil: berkas 55 frame dari video
sampel keluar 3,4 MB, setara ~0,25 GB/jam.

Disk PC Lampung sisa ~232 GB, jadi satu line bisa merekam berhari-hari. Tetap
ada rem: rekaman berhenti sendiri di bawah `UPLOAD_DISK_MIN_FREE_GB` (20 GB).

## Cara mengulang pengukuran ini

Di PC pabrik, dengan line sungguhan:

1. Biarkan line jalan ~2 menit tanpa merekam, catat `[FPS] capture=` dari log.
2. Nyalakan rekaman dari konsol (tab **Rekam Video**), biarkan ~2 menit.
3. Bandingkan `[FPS]`, dan periksa `frame_dibuang` di layar (harus **0**).

```bash
docker logs ripe_line_1 2>&1 | grep '\[FPS\]' | tail -40
```

`frame_dibuang` di atas nol berarti encoder tidak mengejar laju kamera —
videonya bolong, tapi **grading tetap utuh**. Turunkan fps atau resolusi dari
layar; jangan memperdalam antrean.

## Yang BELUM diukur

⚠️ **PC Lampung belum diuji.** MacBook ini CPU-only dan jauh lebih lambat dari
RTX 3060 di pabrik, jadi angka di atas **batas bawah**, bukan ramalan. Yang
belum terjawab:

- **Tiga line merekam bersamaan.** Di sini cuma satu line yang diuji. Tiga
  encoder berebut CPU/GPU dengan tiga inference adalah kasus yang sebenarnya.
- **Kamera Hikrobot 20 fps.** Sumber di sini video sampel ~7 fps; kamera
  sungguhan menyerahkan frame tiga kali lebih sering.

Keduanya harus diukur sekali di Lampung sebelum fitur ini dianggap aman untuk
tiga line sekaligus. Merekam **satu** line di sana sudah aman berdasarkan
pengukuran ini.

Terkait: `docs/superpowers/plans/2026-09-22-rekam-video-per-line.md`.
