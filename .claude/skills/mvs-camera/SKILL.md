---
name: mvs-camera
description: Navigate & tune kamera Hikrobot MV-CS050-10GC lewat MVS (Machine Vision Software) untuk autograde. Use when the user asks about MVS Feature Tree, setting kamera (exposure/gain/white balance/binning/fps), file .mfs, kamera GigE nggak kedetek / ACCESS_DENIED, fps kamera mentok, atau kalibrasi kamera di pabrik.
---

# MVS — Kamera Hikrobot MV-CS050-10GC (Palmgrade)

Sumber kebenaran nilai & topologi: `autograde/docs/camera-spec.md`.
Checklist kalibrasi lapangan: `../docs/camera-field-setup.md` (workspace `sawit`, bukan repo ini).
Skill ini = peta navigasi MVS + nilai live + jebakan. Jangan duplikat isi 2 dokumen itu.

## Hardware

3 unit MV-CS050-10GC (1 per line). 5 MP 2448×2048, Sony IMX264 global shutter,
color (Bayer), GigE Vision, **DC power — BUKAN PoE**. Serial contoh live: `DA9070001`, `DA7538184`.

## Aturan emas: `.mfs` MENANG atas `.env`

`hikrobot_camera.py:90` manggil `MV_CC_FeatureLoad(feature_file)` **tiap connect**,
sesudah `MV_CC_OpenDevice`, sebelum `StartGrabbing`. Gagal load = warning, **nggak fatal**
(lanjut pakai setting firmware).

Konsekuensi: `CAMERA_FPS` di `.env` cuma target loop capture, **bukan** fps kamera.
Yang nentuin fps/exposure/gain = `AcquisitionFrameRate` dst di
`autograde/config/camera/hikrobot.mfs`. Mau ubah fps → edit `.mfs`, bukan `.env`.

Cara bikin `.mfs`: MVS → connect kamera → toolbar **Save Feature** (ekspor semua node
ke XML). Load balik = **Load Feature**.

## Peta Feature Tree MVS (di mana setting-nya)

| Yang dicari | Lokasi di Feature Tree |
|---|---|
| Serial, model, User Set, firmware | **Device Control** |
| Width/Height, Binning, ReverseX/Y, PixelFormat, ROI/AOI | **Image Format Control** |
| Exposure, AcquisitionFrameRate(+Enable), Trigger Mode/Source | **Acquisition Control** |
| Gain, GainAuto, BlackLevel, Balance White Auto + Balance Ratio | **Analog Control** |
| Line Selector, Line Mode, Line Debouncer, Strobe | **Digital IO Control** |
| Packet Size, GevSCPD, Bandwidth Reserve, IP kamera, Heartbeat, CCP | **Transport Layer Control** |
| Auto Function AOI (jendela buat auto-exposure/auto-WB) | **Advanced Features → AOI** |
| Chunk Data, Event Control, CCM, Embedded Info | **Advanced Features** |
| Simpan setting ke firmware | **User Set Control** |

Shortcut MVS: panel **Common Features** (Basic / ISP / Transport) isinya node yang sama,
cuma dikurasi — cukup buat 90% tuning harian.

## Nilai live (terverifikasi di PC Lampung 2026-08-21, cocok 1:1 sama `hikrobot.mfs`)

```
Binning        Horizontal 2 × Vertical 2, BinningMode = Sum   → 1224×1024 (FOV tetap penuh)
PixelFormat    BayerRG8            (PayloadSize 1253376)
Exposure       ExposureTimeMode Standard, ExposureTime 22000 µs
               AutoExposure limit 15 – 8000 µs
Gain           0, GainAuto Off, limit 0 – 23.9812
BlackLevel     240 (enabled)
White balance  BalanceWhiteAuto = Continuous
Acquisition    Continuous, AcquisitionFrameRate 10 (Enable = 1)
Trigger        TriggerMode Off  (free-run; Line 0 debouncer 50 µs nganggur)
Reverse X / Y  off / off
Auto Fn AOI    1224 × 1024
GigE           GevSCPSPacketSize 8164 (jumbo), GevSCPD 400, BandwidthReserve 2,
               Heartbeat 3000 ms, Device Max Throughput 928156 Kbps
```

Binning 2×2 itu **bukan crop**: FOV penuh, tiap 4 piksel dijumlah jadi 1.
Efek samping: lebih terang (mode `Sum`) + bandwidth turun 4×.

## Bandwidth (kenapa binning + 10 fps wajib)

Full-res 2448×2048×8bit @10fps ≈ 401 Mbps/kamera × 3 = **1,2 Gbps** → lewat kapasitas 1 GigE uplink.
Binning 2×2 → ~100 Mbps/kamera ≈ **300 Mbps** total. Aman.

Jumbo frame `8164` cuma jalan kalau **MTU 9000 diset di switch DAN NIC host**.
MTU salah = frame putus / `MV_E_...` timeout. Cek: `ip link show <nic>` harus `mtu 9000`.

## Persistensi — 2 lapis, lapis 1 BELUM dipakai

1. **Firmware UserSet** (User Set Control → Save ke UserSet1 + set *User Set Default* = UserSet1).
   Live sekarang: `User Set Selector = Default`, `User Set Default = Default` → **belum disimpan**.
   Artinya setting cuma bertahan karena lapis 2.
2. **`.mfs` FeatureLoad** tiap connect (lihat aturan emas di atas). Ini yang aktif melindungi.

Kalau app pernah jalan tanpa `LINE_n_FEATURE_FILE`, kamera balik ke default firmware.
Simpan UserSet = jaring pengaman. Tes: simpan → cabut listrik kamera → nyalain → cek nilainya.

## Jebakan

- **Exclusive access.** App buka kamera dengan `MV_ACCESS_Exclusive`, dan MVS juga ambil
  kontrol (`GEV CCP = Control Access`). Dua-duanya nggak bisa barengan.
  MVS nampilin "NO VIDEO" / app `ACCESS_DENIED` → **disconnect MVS dulu**.
- **`MV_E_ACCESS_DENIED (0x80000203)`** waktu multi-kamera = urutan enumerasi GigE nggak
  deterministik, container rebutan kamera yang sama. Solusi (udah dipakai): pilih **by serial**
  lewat `LINE_n_CAMERA_SERIAL`, jangan `CAMERA_DEVICE_INDEX`.
- **fps kamera diatur `.mfs`, bukan `.env`.** `hikrobot.mfs` ngunci
  `AcquisitionFrameRate` (sekarang 15) dan di-load tiap connect, jadi `CAMERA_FPS`
  di `.env` cuma target loop capture. ⚠️ Nge-comment `LINE_n_FEATURE_FILE` **nggak**
  mematikan auto-load — default `:-` di `docker-compose.yml` tetap nyuntik
  `config/camera/hikrobot.mfs`. Plafon lain lihat `docs/camera-spec.md § 5.4`.
- **Jaringan di docs beda sama live.** Live Lampung: NIC `enp3s0` `192.168.0.10`,
  kamera `192.168.0.13`, gateway `192.168.0.254`, `GEV SCDA/MCDA = 192.168.0.10`.
  `camera-spec.md` nulis `192.168.100.x`, `camera-field-setup.md` nulis `192.168.X.20`.
  **Percaya kamera live**, dokumennya belum direkonsiliasi.
- **`camera-field-setup.md` sebagian basi**: masih klaim "kode capture TIDAK nge-set
  parameter kamera" (salah sejak FeatureLoad ada) dan nyaranin Binning off + full-res
  (bertentangan sama hitungan bandwidth). Prosedur kalibrasi WB-nya masih valid.

## Knob `.env` yang relevan

```
CAMERA_TYPE=hikrobot | opencv | photo     # photo/opencv = tes tanpa kamera fisik
LINE_1_CAMERA_SERIAL / LINE_2_ / LINE_3_  # pilih kamera by serial (WAJIB di pabrik)
LINE_1_FEATURE_FILE  / LINE_2_ / LINE_3_  # path .mfs → ini yang nentuin fps/exposure/gain
CAMERA_FPS                                # target loop capture, BUKAN fps kamera
STREAM_WIDTH/HEIGHT/FPS                   # preview MJPEG, nggak nyentuh kamera
ROI_X1/Y1/X2/Y2                           # zona deteksi di software (0,0,0,0 = full frame)
```
