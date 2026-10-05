# Spesifikasi Kamera: AutoGrade

Dokumen ini merangkum spesifikasi kamera yang dipakai AutoGrade, setting runtime
yang aktif, dan alasan di balik setiap keputusan. Untuk langkah instalasi host dan
kamera, lihat [SETUP.md](SETUP.md).

Sumber kebenaran setting kamera adalah [`config/camera/hikrobot.mfs`](../config/camera/hikrobot.mfs):
file itu di-load ke kamera saat connect, jadi nilainya menang atas ekspektasi
apa pun di `.env`.

---

## 1. Hardware

AutoGrade memakai **3 unit Hikrobot MV-CS050-10GC**, satu kamera per camera line.

| Item | Nilai |
|---|---|
| Model | Hikrobot MV-CS050-10GC |
| Resolusi native | 5 MP: 2448 × 2048 |
| Sensor | Sony IMX264, global shutter |
| Tipe | Color (Bayer) |
| Interface | GigE Vision (1000BASE-T) |
| Power | Adaptor DC via I/O connector, **bukan PoE** |

Global shutter penting karena objek bergerak di conveyor: rolling shutter akan
menghasilkan distorsi geometri (skew) pada objek bergerak.

> **Catatan power:** kamera ini tidak menarik daya dari kabel ethernet. Setiap
> unit butuh adaptor sendiri. Switch PoE tidak menggantikan kebutuhan ini.

---

## 2. Setting Kamera Aktif

Nilai berikut dibaca langsung dari `config/camera/hikrobot.mfs` (hasil
*Feature Save* dari MVS).

### 2.1 Image Format

| Parameter | Nilai | Keterangan |
|---|---|---|
| `Width` | `1224` | hasil binning, bukan crop |
| `Height` | `1024` | hasil binning, bukan crop |
| `OffsetX` / `OffsetY` | `0` | FOV penuh |
| `PixelFormat` | `BayerRG8` | 8-bit, 1 byte/pixel di kabel |
| `BinningHorizontal` | `2` | |
| `BinningVertical` | `2` | |
| `BinningMode` | `Sum` | |
| `ReverseX` / `ReverseY` | `0` | tanpa mirroring |

**Binning 2×2 mempertahankan field of view penuh.** Sensor menggabungkan blok
2×2 piksel jadi satu, sehingga resolusi turun dari 2448×2048 ke 1224×1024 tanpa
memotong area pandang. Ini berbeda dari ROI/crop, yang akan menyempitkan FOV.

`BinningMode = Sum` menjumlahkan nilai keempat piksel, jadi sinyal (dan efektifnya
sensitivitas cahaya) naik. Kalau kondisi pencahayaan berubah dan gambar jadi
over-exposed, ganti ke `Average`.

### 2.2 Acquisition & Exposure

| Parameter | Nilai | Keterangan |
|---|---|---|
| `AcquisitionMode` | `Continuous` | free-run, bukan trigger |
| `AcquisitionFrameRate` | `15` | fps: lihat § 3.1 kenapa 15, bukan 24 |
| `AcquisitionFrameRateEnable` | `1` | limiter aktif |
| `TriggerMode` | `Off` | tidak ada hardware trigger |
| `ExposureMode` | `Timed` | |
| `ExposureTime` | `22000` | µs (22 ms): tuning conveyor |
| `ExposureAuto` | `Off` | tetap, agar frame konsisten |
| `Gain` | `0` | |
| `GainAuto` | `Off` | |
| `BlackLevel` | `240` (enabled) | |
| `BalanceWhiteAuto` | `Continuous` | auto white balance |

Exposure dan gain di-set **manual**, sementara white balance dibiarkan otomatis.
Auto-exposure membuat brightness berubah antar frame, dan kondisi pencahayaan yang
konsisten lebih menguntungkan untuk inference.

`TriggerMode Off` + `AcquisitionMode Continuous` berarti pipeline memakai
*continuous grabbing* (`MV_CC_StartGrabbing`), bukan mode trigger per objek.

### 2.3 Network Tuning (GigE)

| Parameter | Nilai | Keterangan |
|---|---|---|
| `GevSCPSPacketSize` | `8164` | jumbo frame: butuh MTU 9000 |
| `GevSCPD` | `400` | inter-packet delay |
| `BandwidthReserve` | `2` | % |
| `GevHeartbeatTimeout` | `3000` | ms |

**Jumbo frame wajib.** Packet size 8164 byte melebihi MTU standar 1500. Switch
**dan** NIC PC harus di-set MTU 9000, kalau tidak stream akan drop frame atau
gagal total.

`GevSCPD` (inter-packet delay) menahan laju burst tiap kamera supaya tiga stream
tidak saling tabrakan di uplink yang sama.

---

## 3. Kalkulasi Bandwidth

Ini kendala desain utama dari keseluruhan setup kamera.

**Tanpa mitigasi: tidak muat:**

```
2448 × 2048 × 1 byte (BayerRG8) × 15 fps ≈ 602 Mbps per kamera
602 Mbps × 3 kamera                      ≈ 1.8 Gbps
```

Uplink GigE hanya 1 Gbps. Konfigurasi ini **melebihi kapasitas** dan menghasilkan
frame drop serta disconnect.

**Dengan binning 2×2: muat:**

```
1224 × 1024 × 1 byte × 15 fps ≈ 150 Mbps per kamera
150 Mbps × 3 kamera           ≈ 451 Mbps
```

Sekitar 45% dari kapasitas uplink, masih lega, termasuk untuk overhead protokol.
Model ini terverifikasi di lapangan: di 10 fps rumusnya memprediksi 301 Mbps dan
`enp3s0` terukur 302 Mbps.

Dua pengaman bekerja berdampingan: **binning 2×2** menurunkan byte per frame, dan
**frame rate limiter** di `.mfs` menahan jumlah frame per detik. Keduanya diperlukan.

### 3.1 Tiga plafon fps: jangan ketuker jadi satu

Naikin fps kena tiga batas yang beda sifatnya. Per 2026-09-13, dengan RTX 3060 12GB
dan TensorRT engine `sm86`:

| Plafon | Batas | Kena di fps berapa |
|---|---|---|
| GPU | ~82–116 inferensi/detik untuk 3 line | 28–38 fps per line |
| Bandwidth 1 port GigE, 3 kamera | ~900 Mbps efektif | 20 fps = 602 Mbps, 24 fps = 722 Mbps (mepet) |
| PLC | **2,5 sinyal/detik per line** | tidak ikut naik |

Plafon PLC itu per **keputusan grading**, bukan per frame: satu pulse per tandan
yang di-track, jadi menaikkan fps tidak menambah tekanan ke PLC
(lihat `plc-integration.md § Throughput ceiling`).

**Kenapa 15 dan bukan 24:** jumlah keputusan grading dibatasi jumlah tandan di
belt, bukan fps. Yang didapat dari fps lebih tinggi adalah **lebih banyak frame per
tandan**: ByteTrack lebih stabil megang ID, vote klasifikasi lebih banyak. 15 fps
memberi +50% frame per tandan dibanding 10 sambil menyisakan setengah kapasitas GPU
dan setengah bandwidth sebagai margin. Naik ke 24 menghabiskan margin itu tanpa
menambah keputusan grading.

⚠️ **Motion blur tidak diatur fps, tapi `ExposureTime`** (22 ms). Naikin fps tidak
membuat frame lebih tajam. Kalau blur jadi masalah, turunkan exposure dan tambah
cahaya: tapi ingat exposure 22 ms masih muat di periode 15 fps (66,7 ms), jadi fps
bukan penghalangnya.

⚠️ Kalau habis naik fps muncul frame tidak lengkap atau reconnect, knob-nya
**`GevSCPD`** (§ 2.3): dinaikkan untuk memberi jeda antar paket, bukan diturunkan.

**Kenapa 1224×1024 tidak merugikan akurasi:** pipeline inference beroperasi di
bawah resolusi itu, dan 1224×1024 masih di atas 720p. Detail yang tersedia untuk
YOLO tidak berkurang akibat binning.

---

## 4. Topologi Jaringan

Contoh template, sama dengan [SETUP.md](SETUP.md) §5–6:

```
Kamera 1 (192.168.100.10) ─┐
Kamera 2 (192.168.100.11) ─┼─→ Gigabit Switch ─→ NIC PC (192.168.100.100)
Kamera 3 (192.168.100.12) ─┘      (MTU 9000)         enp55s0
```

| Item | Nilai |
|---|---|
| Subnet | `192.168.100.0/24` |
| IP kamera | `.10`, `.11`, `.12` (statik/Persistent) |
| IP PC (NIC) | `192.168.100.100` |
| Gateway | `192.168.100.254` |
| MTU | `9000` (switch + NIC) |
| Kabel | Cat5e/Cat6 pure copper minimum |

**PC Lampung memakai segmen lain.** Angka di bawah diukur di mesinnya (skill
`spek-pc-pabrik` dan `mvs-camera`), bukan dari template:

| Item | Lampung |
|---|---|
| NIC kamera | `enp3s0`, `192.168.0.10/24` |
| Kamera | segmen `192.168.0.x`; satu kamera terbaca `192.168.0.13`, IP ketiganya belum tercatat |
| Gateway kamera | `192.168.0.254` |
| PLC Mitsubishi | `192.168.0.14`, dicolok ke switch kamera yang sama; jangan dipakai kamera |
| Internet | NIC terpisah (USB ethernet, DHCP) |

**Assign IP satu per satu** sebelum menggabungkan semua kamera ke switch. Kamera
keluar dari pabrik dengan IP default yang sama, jadi menghubungkan semuanya
sekaligus menyebabkan konflik IP.

### Wajib switch: bukan splitter

Pernah terjadi gejala "kamera 2 LAN disconnect / drop ke 100 Mbps". Akar
masalahnya adalah pemakaian **RJ45 splitter pasif**. Splitter membagi 8 kawat
menjadi 4 kawat per cabang, yang membatasi tiap cabang ke maksimal 100 Mbps dan
menimbulkan konflik multi-device. Mengganti ke switch gigabit sungguhan langsung
menyelesaikan masalah.

**Splitter ≠ switch.** Jangan pakai splitter.

Hindari juga kabel CCA (copper-clad aluminium): pakai pure copper.

---

## 5. Persistensi Setting

Setting kamera bertahan lewat **dua lapis**, dan keduanya perlu ada.

### 5.1 UserSet di firmware kamera

Di MVS: **User Set Control** → `UserSet1` → **User Set Save** → Execute, lalu
**User Set Default** = `UserSet1`. Ulangi untuk setiap kamera. Tanpa ini, setting
hilang saat kamera restart.

### 5.2 Auto-load `.mfs` saat connect

Aplikasi me-load [`config/camera/hikrobot.mfs`](../config/camera/hikrobot.mfs) ke
kamera lewat `MV_CC_FeatureLoad` setiap kali connect
([hikrobot_camera.py:105-126](../src/palmgrade/integrations/camera/hikrobot_camera.py#L105-L126)).

Operasi ini **non-fatal**: kalau load gagal, line tetap jalan memakai setting
firmware yang tersimpan di kamera, dan kegagalan hanya tercatat sebagai warning.

> **Implikasi penting:** karena `.mfs` di-load setiap connect,
> **`AcquisitionFrameRate = 15` di file inilah** yang menentukan fps runtime,
> bukan `CAMERA_FPS` di `.env`. Line membaca balik laju itu dari kamera
> (`HikrobotCamera.get_fps`); `CAMERA_FPS` hanya cadangan kalau sumbernya tidak
> bisa melapor. Untuk mengubah frame rate secara permanen, edit `.mfs` (atau simpan
> ulang dari MVS), jangan `.env`.

> ⚠️ **Nge-comment `LINE_<n>_FEATURE_FILE` tidak mematikan auto-load.**
> `docker-compose.yml` memakai `${LINE_1_FEATURE_FILE:-config/camera/hikrobot.mfs}`,
> dan `:-` berlaku untuk *unset maupun kosong*, jadi meng-comment variabel itu
> justru **mengaktifkan default**. Akibatnya nilai yang di-set manual lewat MVS
> ditiban dalam hitungan detik setelah container connect. Untuk memakai `.mfs`
> lain, isi variabelnya dengan path file itu; untuk benar-benar melewati auto-load,
> arahkan ke path yang tidak ada (loader mencatat warning lalu lanjut).

---

## 6. Konfigurasi Aplikasi

### 6.1 Pemilihan kamera: by serial, bukan index

Setiap line memilih kamera fisiknya lewat **serial number**:

```env
LINE_1_CAMERA_SERIAL=<serial-kamera-1>
LINE_2_CAMERA_SERIAL=<serial-kamera-2>
LINE_3_CAMERA_SERIAL=<serial-kamera-3>
```

Sebelumnya line memakai `CAMERA_DEVICE_INDEX` (= posisi di array hasil enumerate).
Urutan enumerasi GigE **tidak deterministik**, bergantung timing balasan discovery
jaringan. Saat 3 container start bersamaan, mereka bisa saling rebut kamera dan
line yang kalah mendapat `MV_E_ACCESS_DENIED` (`0x80000203`) karena device sudah
dibuka exclusive oleh line lain. Gejalanya: Line 3 kosong.

Selektor by-serial membuat tiap line **selalu** memilih kamera fisik yang sama.
Lihat [device_selector.py](../src/palmgrade/integrations/camera/device_selector.py).

`CAMERA_DEVICE_INDEX` masih ada sebagai fallback, tapi jangan dipakai untuk
produksi multi-line.

Cara mendapatkan serial: buka MVS, atau baca log startup, aplikasi mencatat
`Camera selected by serial <serial> (enum index N)`.

### 6.2 Variabel `.env` terkait kamera

```env
LINE_1_CAMERA_SERIAL=     # wajib di pabrik, lihat §6.1
LINE_2_CAMERA_SERIAL=
LINE_3_CAMERA_SERIAL=
LINE_1_FEATURE_FILE=      # kosong = config/camera/hikrobot.mfs (lihat §5.2)
LINE_2_FEATURE_FILE=
LINE_3_FEATURE_FILE=
CAMERA_FPS=20             # cadangan, lihat §5.2
```

Jenis sumber per line (`hikrobot` untuk produksi, `opencv` untuk webcam atau
berkas video, `photo` untuk gambar statis) tidak lagi di `.env`: ada di
`media.env` sebagai `LINE_N_CAMERA_TYPE`, diatur dari konsol tab **Line → Sumber
Kamera** ([runbook](runbooks/2026-09-21-sumber-kamera-per-line.md)).

> `CAMERA_WIDTH` / `CAMERA_HEIGHT` hanya dipakai sumber OpenCV dan pemanasan model.
> Kamera Hikrobot mengirim ukuran dari `.mfs`, yaitu **1224×1024** karena binning
> 2×2. Jangan pakai `CAMERA_WIDTH` sebagai acuan ukuran frame yang sesungguhnya.

### 6.3 Deployment

Tiga container line di port **8001** / **8002** / **8003** (plus konsol operator
tanpa kamera di 8100), dengan `network_mode: host` (diperlukan agar GigE discovery
bisa menjangkau subnet kamera) dan GPU passthrough.

### 6.4 Suhu kamera

Kartu Diagnostik (tab **Status**, support) menampilkan suhu badan tiap kamera dalam °C.

- Sumbernya node `DeviceTemperature`, dibaca thread capture tiap **10 detik** selama gambar
  mengalir, di bawah kunci kamera yang sama dengan `grab_frame()` (aturan 3). Nilainya ikut
  `/health/detail` sebagai `suhu_kamera_c`.
- Bacaan yang lebih tua dari **60 detik** dilaporkan `null` (kartu menampilkan `-`): kamera
  yang dicabut tidak meninggalkan angka lama di layar.
- Kamera yang menolak menjawab: satu WARNING `Camera did not report DeviceTemperature (<kode SDK>)`
  di tab Log, sesudahnya diam; line tetap jalan. Webcam, video, dan foto selalu `-`.
- **Belum ada batas aman dan warna.** Batasnya diputuskan nanti dari datasheet dan beberapa hari
  bacaan Lampung.
- **Kamera Lampung tidak punya sensor suhu** (MV-CS050-10GC firmware V4.0.43, dicek 2026-10-05:
  `DeviceTemperature` dan `DeviceTemperatureSelector` akses NI). Line menanyakannya sekali per
  sambung lalu berhenti, dan kartu menulis "tidak didukung kamera". Penggantinya baris laju,
  frame hilang, dan putus-nyambung di kartu yang sama (aturan 35, `docs/rules.md`).
- Cek manual di MVS: Feature Tree mode **Expert** atau **Guru**, **Device Control**,
  **Device Temperature**. Line harus dimatikan dulu, karena kamera dibuka eksklusif (§8,
  `MV_E_ACCESS_DENIED`).

---

## 7. Catatan GPU

PC pabrik Lampung memakai **RTX 3060 12 GB** (compute capability sm86); spek
terukurnya di skill `spek-pc-pabrik`. Plafon GPU untuk 3 line ada di §3.1: GPU
bukan penentu 15 fps.

Engine TensorRT **terkunci per hardware GPU** dan tidak di-commit ke repo. Engine
yang di-build di laptop tidak bisa dipakai di PC produksi: bangun ulang di mesin
itu (perintahnya di [runbook Model Deteksi](runbooks/2026-09-24-model-deteksi-per-line.md)).
Runtime akan fallback ke `.pt` kalau engine belum tersedia.

---

## 8. Troubleshooting Cepat

| Gejala | Kemungkinan penyebab |
|---|---|
| Line kosong, `MV_E_ACCESS_DENIED` (0x80000203) | serial belum di-set → line rebutan kamera (§6.1) |
| Drop frame / stream gagal | MTU bukan 9000 di switch atau NIC (§2.3) |
| Link turun ke 100 Mbps, disconnect | RJ45 splitter pasif dipakai, bukan switch (§4) |
| Setting hilang setelah restart kamera | UserSet belum disimpan ke firmware (§5.1) |
| fps tidak sesuai `.env` | `.mfs` menang: `AcquisitionFrameRate` (§5.2) |
| Gambar over-exposed | `BinningMode Sum` → ganti `Average` (§2.1) |
| Konflik IP saat pertama pasang | kamera di-assign bersamaan, bukan satu per satu (§4) |

---

## Referensi

- [SETUP.md](SETUP.md): panduan instalasi lengkap
- [`config/camera/hikrobot.mfs`](../config/camera/hikrobot.mfs): sumber kebenaran setting
- [hikrobot_camera.py](../src/palmgrade/integrations/camera/hikrobot_camera.py): driver
- [device_selector.py](../src/palmgrade/integrations/camera/device_selector.py): pemilihan by-serial
