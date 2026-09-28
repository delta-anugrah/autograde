# AutoGrade: Setup Host dan Kamera

Menyiapkan PC Linux dan kamera Hikrobot: NVIDIA Container Toolkit, MVS, jaringan kamera,
setelan kamera, dan firewall. Urutan pasang PC pabrik yang lengkap (`.env`, image,
launcher, AutoERP, PLC) ada di [MANUAL.md](MANUAL.md) §5; laptop developer di
[README](../README.md).

---

## Daftar Isi

1. [Prerequisites](#1-prerequisites)
2. [Install NVIDIA Container Toolkit](#2-install-nvidia-container-toolkit)
3. [Install Hikrobot MVS SDK](#3-install-hikrobot-mvs-sdk)
4. [Koneksi Fisik Kamera](#4-koneksi-fisik-kamera)
5. [Setup IP di PC (NIC Wired)](#5-setup-ip-di-pc-nic-wired)
6. [Konfigurasi Kamera di MVS](#6-konfigurasi-kamera-di-mvs)
7. [Project dan `.env`](#7-project-dan-env)
8. [Menyalakan](#8-menyalakan)
9. [Verifikasi](#9-verifikasi)
10. [Network Hardening (Firewall)](#10-network-hardening-firewall)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

### Hardware
- PC dengan NVIDIA GPU (CUDA-capable)
- Kamera **Hikrobot MV-CS050-10GC** (GigE, 5MP, global shutter)
- Kabel **CAT6** (1 per kamera)
- **Gigabit switch** (wajib support Jumbo Frame / MTU 9000) untuk 3 kamera; 1 kamera boleh langsung ke NIC tanpa switch

### Software
- Ubuntu 22.04 LTS atau turunannya (PC Lampung: Linux Mint 22)
- Docker + Docker Compose
- NVIDIA Driver (>= 525)
- Hikrobot MVS Software (terpasang di `/opt/MVS/`)
- `make` (GNU Make), hanya untuk mesin yang build dari source

### File yang dibutuhkan
- YOLO model: `best.pt` → taruh di `models/release/`
- `.env` → copy dari `.env.example`

---

## 2. Install NVIDIA Container Toolkit

Wajib untuk GPU passthrough ke Docker. Tanpa ini YOLO jalan di CPU (10× lebih lambat).

```bash
# Tambah repo NVIDIA
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verifikasi:
```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
# Harus muncul tabel GPU. Kalau error: cek driver NVIDIA di host
```

---

## 3. Install Hikrobot MVS SDK

### Download

| Software | Platform |
|---|---|
| Machine Vision Software MVS V5.0.0 | Linux x86_64 |
| Machine Vision Industrial Camera SDK V4.7.0 Runtime Package | Linux x86_64 |

Download dari [Hikrobot Download Center](https://www.hikrobotics.com/en/machinevision/service/download): pilih **Type: All**, **System: Linux**.

### Persyaratan Sistem

- OS: Ubuntu 18.04 / 20.04 / 22.04 (x86_64)
  > Ubuntu 24.04 tetap bisa digunakan meski muncul warning `Unsupported distribution`
- Arsitektur: x86_64
- Akses `sudo`

### Langkah Instalasi

**1. Install via dpkg**

```bash
sudo dpkg -i MVS-5.0.0_x86_64_20260421.deb
```

Proses instalasi otomatis:
- Setup SDK environment
- Tambah udev rules untuk USB dan virtual serial device
- Buat dynamic library links
- Set konfigurasi network (socket buffer, rp_filter)
- Buat shortcut desktop `~/Desktop/MVS.desktop`

**2. Reload environment**

```bash
source /etc/profile
```

**3. Jalankan MVS**

```bash
/opt/MVS/bin/MVS.sh
# atau klik shortcut MVS di Desktop
```

### Struktur Instalasi

```
/opt/MVS/
├── bin/       # Executable MVS & SDK tools
├── lib/       # Dynamic libraries
├── include/   # Header files
└── Samples/   # Contoh kode (C/C++/Python)
```

### Troubleshooting Instalasi

| Warning/Error | Keterangan |
|---|---|
| `Unsupported distribution.` | Ubuntu 24.04 belum officially supported, MVS tetap berjalan normal |
| `cp: cannot stat '/opt/MVS/bin/fonts/*'` | Minor warning, tidak mempengaruhi fungsi |
| Kamera tidak terdeteksi (USB) | `sudo udevadm control --reload-rules && sudo udevadm trigger` |

### Verifikasi SDK

```bash
ls /opt/MVS/lib/64/libMvCameraControl.so*
# Harus muncul: libMvCameraControl.so  libMvCameraControl.so.X.X.X.X
```

> SDK sudah ikut di image (`sdk/` dilacak git). MVS di host dipakai untuk menyetel kamera
> dan membaca serial. Build dari source (`make up`) menyalin ulang `/opt/MVS/lib/64` ke
> `sdk/` lewat `make sync-sdk`.

---

## 4. Koneksi Fisik Kamera

### 1 kamera (direct ke NIC)
```
[Hikrobot Camera] ──CAT6──► [PC NIC / port LAN]
```

### 3 kamera (via switch)
```
[Camera 1] ──CAT6──┐
[Camera 2] ──CAT6──┤──► [Gigabit Switch] ──CAT6──► [PC NIC / port LAN]
[Camera 3] ──CAT6──┘
```

> Switch **wajib** support Jumbo Frame (MTU 9000). Switch murah umumnya tidak support, cek spesifikasi.

Setelah kabel terpasang, LED di NIC PC dan di kamera harus menyala (link aktif 1000 Mb/s).

---

## 5. Setup IP di PC (NIC Wired)

Koneksi direct kamera-ke-PC tidak punya DHCP server, jadi NIC perlu IP statis agar bisa berkomunikasi dengan kamera.

> Alamat `192.168.100.x` di bawah adalah **contoh template**. PC Lampung memakai segmen
> `192.168.0.x`: NIC kamera `enp3s0` = `192.168.0.10/24`, PLC `192.168.0.14` di switch yang
> sama. Rinciannya: [camera-spec.md](camera-spec.md) §4.

### Cara via GUI (GNOME Network Manager)

1. Buka **Settings → Network**
2. Pilih **Wired** → klik ikon gear ⚙️
3. Pilih tab **IPv4**
4. Ubah dari **Automatic (DHCP)** ke **Manual**
5. Isi:

| Field   | Value             |
|---------|-------------------|
| Address | `192.168.100.100` |
| Netmask | `255.255.255.0`   |
| Gateway | *(kosongkan)*     |

6. Scroll ke bawah, centang **"Use this connection only for resources on its network"**
7. Klik **Apply**

> **Wajib centang opsi ini.** Tanpa opsi ini, interface kamera ikut jadi default route sehingga Docker tidak bisa resolve DNS saat build, menyebabkan error `getaddrinfo EAI_AGAIN` atau `Temporary failure in name resolution`.

### Cara via Terminal (langsung aktif, tidak persist setelah reboot)

```bash
sudo ip addr add 192.168.100.100/24 dev enp55s0
sudo ip link set enp55s0 up
```

> Ganti `enp55s0` dengan nama interface NIC yang terhubung ke kamera (Lampung: `enp3s0`). Cek dengan `ip link show`.

### Set Jumbo Frame (opsional tapi direkomendasikan untuk 3 kamera)

```bash
sudo ip link set enp55s0 mtu 9000
```

---

## 6. Konfigurasi Kamera di MVS

### 6.1 Set IP Kamera

1. Buka **MVS**
2. Di panel kiri, refresh device list (**F5** atau klik ikon refresh 🔄)
3. Kamera muncul di bawah `GigE → enp55s0[192.168.100.100]`
   - Jika kamera baru pertama kali, IP-nya akan `169.254.x.x` atau `192.168.26.x` (dari pabrik)
   - MVS biasanya langsung pop-up **"Modify IP Address"**
4. Set IP statis per kamera, satu per satu, di segmen yang sama dengan NIC (§5):

| Kamera | IP Address (contoh) | Subnet Mask     | Gateway           |
|--------|---------------------|-----------------|-------------------|
| Line 1 | `192.168.100.10`    | `255.255.255.0` | `192.168.100.254` |
| Line 2 | `192.168.100.11`    | `255.255.255.0` | `192.168.100.254` |
| Line 3 | `192.168.100.12`    | `255.255.255.0` | `192.168.100.254` |

5. Klik **OK**: kamera reboot sebentar lalu muncul kembali dengan IP baru

> Jika tidak otomatis pop-up: klik kanan nama kamera → **Modify IP Address**

### 6.2 Connect & Preview

1. Klik kanan kamera → **Open Device** (atau double-click)
2. Klik tombol **▶ Play** (Start Live) di toolbar atas
3. Pastikan feed kamera tampil: cek tidak ada error di status bar bawah

### 6.3 Samakan setelan dengan `.mfs`

Line memuat [`config/camera/hikrobot.mfs`](../config/camera/hikrobot.mfs) ke kamera setiap kali
connect, jadi nilai di berkas itu yang berlaku saat produksi. Di MVS cukup samakan, supaya uji di
MVS dan isi UserSet (§6.4) tidak berbeda dari produksi:

1. **Acquisition Control** → **Acquisition Frame Rate Enable** → **True**
2. **Acquisition Frame Rate** → `15`
3. **Exposure Time (us)**: `.mfs` memakai `22000`. Ruangan terang `5000`–`10000`, gelap / conveyor `20000`–`30000`
4. **Image Format Control** → **Pixel Format** `BayerRG8`, binning 2×2 (`Sum`)

Kenapa 15 fps dan binning 2×2 (bandwidth tiga kamera di satu uplink GigE): [camera-spec.md](camera-spec.md) §2–3.
Mengubah fps secara permanen berarti mengubah `.mfs`. `CAMERA_FPS` di `.env` cuma cadangan
untuk sumber yang tidak bisa melaporkan lajunya sendiri (webcam, berkas video).

### 6.4 Simpan ke Kamera (UserSet1)

Agar setting bertahan setelah kamera restart:

1. Di Feature Tree → **User Set Control**
2. **User Set Selector** → pilih `UserSet1`
3. **User Set Save** → klik **Execute**
4. **User Set Default** → set ke `UserSet1`

Ulangi 6.2–6.4 untuk setiap kamera.

---

## 7. Project dan `.env`

- **PC pabrik** tidak memakai checkout: yang jalan image GHCR `ghcr.io/delta-anugrah/autograde`
  dengan compose + `.env` di `/opt/palmgrade/autograde/`. Isi `.env` dan urutannya:
  [MANUAL.md](MANUAL.md) §5.
- **Mesin yang build dari source**: `cp .env.example .env`, lalu taruh `best.pt` di
  `models/release/`. Arti tiap variabel: `.env.example` dan
  [backend-overview.md](backend-overview.md) §Environment Variables.

Yang paling sering salah:

- `BACKEND_URL` menunjuk **konsol** di mesin yang sama (`http://localhost:8100` di PC pabrik),
  bukan palmgrade-api yang sudah pensiun.
- `LINE_N_CAMERA_SERIAL` wajib diisi di pabrik, supaya tiap line selalu membuka kamera fisik
  yang sama ([camera-spec.md](camera-spec.md) §6.1).
- `LINE_N_MACHINE_ID` unik per line dan tidak pernah berubah. Compose sudah membawa bawaan;
  tiga line dengan id sama menumpuk di kartu line-1 di konsol.
- Sumber kamera per line (Hikrobot, video, foto) tidak diatur di `.env`, tapi di `media.env`
  lewat konsol tab **Line → Sumber Kamera**
  ([runbook](runbooks/2026-09-21-sumber-kamera-per-line.md)).

---

## 8. Menyalakan

Tutup MVS dulu. SDK hanya bisa membuka kamera dari satu proses, jadi MVS dan line tidak bisa
memegang kamera yang sama bersamaan.

- **PC pabrik** tidak menjalankan `make up`. Launcher host `autograde` menyalakan tiga line +
  konsol; `autograde pull` atau `autograde use vX.Y.Z` memasang versi; `autograde restart`
  membuat ulang container sesudah `.env` diubah (reboot saja tidak cukup). Engine TensorRT
  dibangun sekali per GPU:
  [runbook Model Deteksi](runbooks/2026-09-24-model-deteksi-per-line.md) §Engine TensorRT per model.
- **Build dari source:** `make up` (salin SDK, build image GPU, build engine TensorRT, start
  semua). Build pertama ±15–30 menit (unduh PyTorch CUDA ±2,4 GB). Sesudahnya `make start` /
  `make down` / `make restart`, per line `make up-1` / `make logs-1`. Daftar lengkap:
  [README](../README.md).

Line memakai `network_mode: host`: discovery GigE Vision memakai UDP broadcast yang diblok
bridge network Docker.

---

## 9. Verifikasi

```bash
curl http://localhost:8001/health/detail     # line 1; line 2 dan 3 di 8002 / 8003
```

Yang harus terlihat: `camera_connected: true`, `gpu_available: true`, `model_backend:
"tensorrt"` (sesudah engine dibangun), dan **`capture_save_dropped` serta `tp_telat` NOL**.
Arti tiap field: [backend-overview.md](backend-overview.md) §`GET /health/detail`.

Stream langsung: `http://localhost:8001/api/video_feed`. Ringkasan ketiga line ada di konsol
(`http://localhost:8100/console`, akun support) tab **Status**, bagian Diagnostik.

---

## 10. Network Hardening (Firewall)

Line dan konsol jalan dengan `network_mode: host`, jadi port `8001/8002/8003` (line) dan `8100`
(konsol) **terbuka di semua interface** PC. Selama PC cuma punya NIC ke switch kamera (LAN
tertutup), ini aman. Begitu PC dapat NIC internet, port itu ikut terekspos.

Endpoint line yang masih tanpa auth tinggal satu: `/api/video_feed`. `/api/set_truck` (#122) dan
`/api/capture_reject` (#123) sudah dihapus 2026-09-20 karena nol pemanggil; tolak manual tetap
ada lewat `/internal/manual-reject`, yang meminta secret.

`/api/video_feed` **tidak bisa** diberi auth semudah itu: `<img src>` di `console.html` tidak
mengirim header, dan gambarnya harus tetap muncul saat internet putus. Jadi firewall yang
menjaganya, bukan kode.

⚠️ `video_feed` dimuat **browser yang membuka konsol**, bukan server. Batasi ke subnet
operator, bukan ke satu IP server, atau gambar di konsol mati.

```bash
# <SUBNET_OPERATOR> = subnet tempat browser operator berada.
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <SUBNET_OPERATOR> to any port 8001,8002,8003,8100 proto tcp
# SSH kalau remote (jangan sampai kekunci):
sudo ufw allow from <SUBNET_ADMIN> to any port 22 proto tcp
sudo ufw enable
sudo ufw status verbose
```

Catatan:
- Endpoint `/internal/*` di line sudah dilindungi `x-internal-secret`, tapi firewall tetap
  lapisan pertama (defense-in-depth).
- Kalau konsol hanya dibuka di PC itu sendiri (kiosk), cukup blok akses dari interface
  internet dan izinkan `127.0.0.1` / interface LAN kamera.
- Verifikasi dari host lain: `curl http://<IP_PROD>:8001/health` harus **timeout/refused**
  dari luar allowlist, tapi jalan dari IP yang diizinkan.

---

## 11. Troubleshooting

### Kamera tidak muncul di MVS setelah colok

1. Pastikan NIC PC sudah punya IP statis (§5): cek di **Settings → Network → Wired**
2. Cek LED di kamera dan NIC, harus menyala (link aktif)
3. Tekan **F5** di MVS untuk refresh
4. `ping <IP kamera>` dari terminal: tidak ada balasan = masalah di koneksi fisik atau IP

### `gpu_available: false` di health check

1. Cek NVIDIA Container Toolkit terinstall: `nvidia-smi` harus jalan
2. Cek docker restart setelah install: `sudo systemctl restart docker`
3. Verifikasi: `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi`

### Kamera terconnect di MVS tapi tidak muncul di line

- Pastikan sumber line itu **Kamera Hikrobot** (konsol tab Line → Sumber Kamera; tersimpan sebagai `LINE_N_CAMERA_TYPE=hikrobot` di `media.env`)
- Container jalan dengan `network_mode: host`, cek `docker-compose.yml`
- Pastikan MVS sudah di-close (SDK hanya bisa diakses 1 proses sekaligus)

### Bandwidth terlalu tinggi (packet lost)

- Pastikan **Acquisition Frame Rate Enable = True** di MVS sebelum save UserSet1
- Cek **Resulting Frame Rate** di MVS, harus sekitar 15 fps (nilai `.mfs`)
- Set Jumbo Frame di NIC: `sudo ip link set enp55s0 mtu 9000`

### Gambar gelap

- Naikkan **Exposure Time** di MVS → **Acquisition Control** → **Exposure Time (us)**
- Mulai dari `20000`, sesuaikan sampai gambar cukup terang
- Simpan ulang ke **UserSet1**, dan samakan `ExposureTime` di `.mfs`: berkas itu dimuat ulang tiap connect

### `camera_connected: false` setelah line menyala

Normal terjadi jika kamera belum terhubung atau MVS masih buka. App tetap jalan dan workers aktif, `FrameCaptureWorker` otomatis retry setiap beberapa detik. Begitu kamera terhubung, `camera_connected` berubah jadi `true` tanpa restart.

Jika `camera_connected` tetap `false` meski kamera sudah terhubung:
1. Pastikan MVS sudah di-close (hanya 1 proses yang bisa akses kamera)
2. Cek koneksi fisik + LED
3. `curl http://localhost:8001/health/detail`: cek `workers[capture].alive`.
   Cek juga `workers[capture_save].alive`: penulis bukti yang mati itu **senyap**, grading
   jalan, PLC menyortir, angka di layar naik, dan nol gambar tersimpan.

### `MvImport SDK tidak ditemukan` saat container start (build dari source)

Image dibuild tanpa SDK (`WITH_SDK=false`). Terjadi jika `make up` gagal di tengah jalan atau image lama dipakai. Fix:

```bash
make down
make up   # rebuild dengan WITH_SDK=true
```

### Error DNS saat `make up` (`getaddrinfo EAI_AGAIN` / `name resolution`)

Terjadi karena interface NIC kamera ikut jadi default route Docker. Dua solusi:

**Solusi permanen** (lakukan di step 5): centang **"Use this connection only for resources on its network"** di pengaturan IPv4 NIC Wired.

**Solusi cepat** (jika sudah terlanjur build):
```bash
sudo bash -c 'echo "{\"dns\": [\"8.8.8.8\", \"8.8.4.4\"]}" > /etc/docker/daemon.json'
sudo systemctl restart docker
make down && make up
```

### Kamera tertukar line (Line 1 menampilkan feed kamera fisik Line 2)

Line memilih kamera lewat serial, bukan urutan enumerasi. Isi atau tukar `LINE_N_CAMERA_SERIAL`
di `.env` untuk line yang tertukar ([camera-spec.md](camera-spec.md) §6.1), lalu buat ulang
container: `autograde restart` di PC pabrik, `make start` di mesin build.
