# Spesifikasi Kamera: Palmgrade Vision

Dokumen ini merangkum spesifikasi kamera yang dipakai Palmgrade Vision, setting
runtime yang aktif, dan alasan di balik setiap keputusan. Untuk langkah instalasi
dari nol, lihat [SETUP.md](SETUP.md).

Sumber kebenaran setting kamera adalah [`config/camera/hikrobot.mfs`](../config/camera/hikrobot.mfs)
file itu di-load ke kamera saat connect, jadi nilainya menang atas ekspektasi
apa pun di `.env`.

---

## 1. Hardware

Palmgrade memakai **3 unit Hikrobot MV-CS050-10GC**, satu kamera per camera line.

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
2448 × 2048 × 1 byte (BayerRG8) × 10 fps ≈ 401 Mbps per kamera
401 Mbps × 3 kamera                      ≈ 1.2 Gbps
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
([hikrobot_camera.py:106-118](../src/palmgrade/integrations/camera/hikrobot_camera.py#L106-L118)).

Operasi ini **non-fatal**: kalau load gagal, line tetap jalan memakai setting
firmware yang tersimpan di kamera, dan kegagalan hanya tercatat sebagai warning.

> **Implikasi penting:** karena `.mfs` di-load setiap connect,
> **`AcquisitionFrameRate = 15` di file inilah** yang menentukan fps runtime,
> bukan `CAMERA_FPS` di `.env`. Untuk mengubah frame rate secara permanen, edit
> `.mfs` (atau simpan ulang dari MVS), jangan hanya `.env`.

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
CAMERA_TYPE=hikrobot      # hikrobot (produksi) | opencv (dev) | photo (testing)
CAMERA_WIDTH=2448
CAMERA_HEIGHT=2048
CAMERA_FPS=15

LINE_1_CAMERA_SERIAL=
LINE_2_CAMERA_SERIAL=
LINE_3_CAMERA_SERIAL=
```

`CAMERA_TYPE` memberi dua opsi pengembangan tanpa hardware: `opencv` (webcam atau
file video) dan `photo` (gambar statis).

> **Peringatan konsistensi:** `.env.example` dan `docker-compose.yml` memakai
> default `CAMERA_WIDTH=2448` / `CAMERA_HEIGHT=2048` (resolusi native), sedangkan
> kamera sebenarnya mengirim **1224×1024** karena binning 2×2 di `.mfs`. Nilai
> yang menang saat runtime adalah yang dari kamera. Jangan pakai `CAMERA_WIDTH`
> sebagai acuan ukuran frame yang sesungguhnya.

### 6.3 Deployment

Tiga container Docker, satu per line, di port **8001** / **8002** / **8003**,
dengan `network_mode: host` (diperlukan agar GigE discovery bisa menjangkau
subnet kamera) dan GPU passthrough.

---

## 7. Catatan GPU

Perbedaan hardware antara dev dan produksi memengaruhi kamera secara tidak langsung:

| Environment | GPU | VRAM |
|---|---|---|
| Laptop dev | RTX 4050 Laptop | 6 GB |
| PC produksi | GTX 1650 | 4 GB |

Frame rate 10 fps bukan hanya soal bandwidth jaringan, angka itu juga hasil
tuning terhadap kemampuan **GTX 1650** memproses tiga stream secara bersamaan
dalam 4 GB VRAM.

Engine TensorRT **terkunci per hardware GPU** dan tidak di-commit ke repo. Engine
yang di-build di laptop tidak bisa dipakai di PC produksi, harus
`make build-engine` ulang di mesin produksi. Runtime akan fallback ke `.pt` kalau
engine belum tersedia.

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
