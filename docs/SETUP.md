# Palmgrade Vision — Setup Guide

Panduan instalasi lengkap dari nol sampai sistem berjalan. Ikuti urutan ini — setiap section bergantung pada section sebelumnya.

---

## Daftar Isi

1. [Prerequisites](#1-prerequisites)
2. [Install NVIDIA Container Toolkit](#2-install-nvidia-container-toolkit)
3. [Install Hikrobot MVS SDK](#3-install-hikrobot-mvs-sdk)
4. [Koneksi Fisik Kamera](#4-koneksi-fisik-kamera)
5. [Setup IP di PC (NIC Wired)](#5-setup-ip-di-pc-nic-wired)
6. [Konfigurasi Kamera di MVS](#6-konfigurasi-kamera-di-mvs)
7. [Siapkan Project](#7-siapkan-project)
8. [Build & Run Docker](#8-build--run-docker)
9. [Verifikasi](#9-verifikasi)
10. [Network Hardening (Firewall)](#10-network-hardening-firewall)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

### Hardware
- PC dengan NVIDIA GPU (CUDA-capable)
- Kamera **Hikrobot MV-CS050-10GC** (GigE, 5MP, global shutter)
- Kabel **CAT6** (1 per kamera)
- **Gigabit switch** (wajib support Jumbo Frame / MTU 9000) untuk 3 kamera — untuk 1 kamera, bisa langsung ke NIC tanpa switch

### Software
- Ubuntu 22.04 LTS
- Docker + Docker Compose
- NVIDIA Driver (>= 525)
- Hikrobot MVS Software (sudah terinstall di `/opt/MVS/`)
- `make` (GNU Make)

### File yang dibutuhkan
- YOLO model: `best_3class_v2.pt` → taruh di `models/release/`
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
sudo systemctl restart docker
```

Verifikasi:
```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
# Harus muncul tabel GPU info — kalau error, cek driver NVIDIA di host
```

---

## 3. Install Hikrobot MVS SDK

### Download

| Software | Platform |
|---|---|
| Machine Vision Software MVS V5.0.0 | Linux x86_64 |
| Machine Vision Industrial Camera SDK V4.7.0 Runtime Package | Linux x86_64 |

Download dari [Hikrobot Download Center](https://www.hikrobotics.com/en/machinevision/service/download) — pilih **Type: All**, **System: Linux**.

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

> `make up` otomatis copy SDK dari `/opt/MVS/` ke `sdk/` dan include ke Docker image. Tidak perlu copy manual.

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

> Switch **wajib** support Jumbo Frame (MTU 9000). Switch murah umumnya tidak support — cek spesifikasi.

Setelah kabel terpasang, LED di NIC PC dan di kamera harus menyala (link aktif 1000 Mb/s).

---

## 5. Setup IP di PC (NIC Wired)

Koneksi direct kamera-ke-PC tidak punya DHCP server, jadi NIC perlu IP statis agar bisa berkomunikasi dengan kamera.

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

> **Wajib centang opsi ini.** Tanpa opsi ini, interface kamera ikut jadi default route sehingga Docker tidak bisa resolve DNS saat build — menyebabkan error `getaddrinfo EAI_AGAIN` atau `Temporary failure in name resolution`.

### Cara via Terminal (langsung aktif, tidak persist setelah reboot)

```bash
sudo ip addr add 192.168.100.100/24 dev enp55s0
sudo ip link set enp55s0 up
```

> Ganti `enp55s0` dengan nama interface NIC yang terhubung ke kamera. Cek dengan `ip link show`.

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
4. Set IP statis per kamera:

| Kamera | IP Address        | Subnet Mask     | Gateway           |
|--------|-------------------|-----------------|-------------------|
| Line 1 | `192.168.100.10`  | `255.255.255.0` | `192.168.100.254` |
| Line 2 | `192.168.100.11`  | `255.255.255.0` | `192.168.100.254` |
| Line 3 | `192.168.100.12`  | `255.255.255.0` | `192.168.100.254` |

5. Klik **OK** — kamera reboot sebentar lalu muncul kembali dengan IP baru

> Jika tidak otomatis pop-up: klik kanan nama kamera → **Modify IP Address**

### 6.2 Connect & Preview

1. Klik kanan kamera → **Open Device** (atau double-click)
2. Klik tombol **▶ Play** (Start Live) di toolbar atas
3. Pastikan feed kamera tampil — cek tidak ada error di status bar bawah

### 6.3 Set Frame Rate & Pixel Format

Di panel **Feature Tree** (kanan):

1. **Acquisition Control** → **Acquisition Frame Rate Enable** → **True** (toggle ON)
2. **Acquisition Frame Rate** → set `10`
3. **Acquisition Control** → **Exposure Time (us)** → sesuaikan dengan kondisi cahaya:
   - Ruangan terang: `5000`–`10000`
   - Ruangan gelap / conveyor: `20000`–`30000`
4. **Image Format Control** → **Pixel Format** → pilih `BayerRG8`

> **Mengapa 10 fps?** Kamera 5MP di full resolution (2448×2048) mengonsumsi ~400 Mbps per kamera. Dengan 3 kamera, total ~1.2 Gbps melebihi kapasitas uplink GigE (1 Gbps). Dengan 10 fps, total bandwidth ~400 Mbps — aman untuk 1 uplink.

### 6.4 Simpan ke Kamera (UserSet1)

Agar setting bertahan setelah kamera restart:

1. Di Feature Tree → **User Set Control**
2. **User Set Selector** → pilih `UserSet1`
3. **User Set Save** → klik **Execute**
4. **User Set Default** → set ke `UserSet1`

Ulangi 6.2–6.4 untuk setiap kamera.

---

## 7. Siapkan Project

### 7.1 Clone & env

```bash
git clone git@github.com:delta-anugrah/palmgrade-vision.git
cd palmgrade-vision
cp .env.example .env
```

### 7.2 Taruh model

```bash
mkdir -p models/release
# copy best_3class_v2.pt ke models/release/
```

### 7.3 Edit `.env`

Bagian yang **wajib** diisi:

```env
# ── Kamera ───────────────────────────────────────────────────
CAMERA_TYPE=hikrobot
CAMERA_DEVICE_INDEX=0       # 0 = kamera pertama yang ditemukan
CAMERA_VIDEO_PATH=          # kosongkan untuk hikrobot
CAMERA_WIDTH=2448
CAMERA_HEIGHT=2048
CAMERA_FPS=10

# ── Backend ──────────────────────────────────────────────────
BACKEND_URL=http://localhost:2500        # atau IP server palmgrade-api
WEBHOOK_SECRET=your-webhook-secret      # harus sama dengan palmgrade-api

# ── Machine UUIDs ────────────────────────────────────────────
# UUID dari tabel machines di PostgreSQL (palmgrade-api)
LINE_1_MACHINE_ID=<uuid-dari-db>
LINE_2_MACHINE_ID=<uuid-dari-db>
LINE_3_MACHINE_ID=<uuid-dari-db>

# ── Model ────────────────────────────────────────────────────
MODEL_FILE=best_3class_v2.pt
CONF_THRESHOLD=0.75
MINIMUM_SIZE=460000
```

> **LINE_X_MACHINE_ID** — ambil dari tabel `machines` di database PostgreSQL palmgrade-api. Setiap line harus punya UUID yang unik dan terdaftar di DB.

---

## 8. Build & Run Docker

### 8.1 Tutup MVS sebelum build

MVS dan Docker **tidak bisa connect ke kamera yang sama bersamaan** — SDK hanya bisa diakses 1 proses sekaligus. Pastikan MVS sudah di-close sebelum lanjut.

### 8.2 Build pertama kali

```bash
make down   # pastikan tidak ada container lama yang jalan
make up     # copy SDK + build GPU image + start semua line
```

Build pertama membutuhkan waktu **~15–30 menit** (download PyTorch CUDA ~2.4 GB).

> **Jika error `getaddrinfo EAI_AGAIN` atau `name resolution` saat build:**
> Opsi "Use this connection only for resources on its network" di step 5 belum aktif, atau perlu tambah DNS manual ke Docker:
> ```bash
> sudo bash -c 'echo "{\"dns\": [\"8.8.8.8\", \"8.8.4.4\"]}" > /etc/docker/daemon.json'
> sudo systemctl restart docker
> make down && make up
> ```

### 8.3 Penggunaan sehari-hari (setelah build selesai)

```bash
make start      # start semua line (tanpa rebuild)
make down       # stop semua
make restart    # restart semua container tanpa rebuild
```

### 8.4 Per-line

```bash
make up-1       # start line-1 saja
make up-2       # start line-2 saja
make up-3       # start line-3 saja
make logs-1     # tail logs line-1
make logs-2     # tail logs line-2
make logs-3     # tail logs line-3
make logs       # tail logs semua line
```

> **`make up` vs `make start`:**
> - `make up` — rebuild image lalu start. Gunakan saat: setup pertama, setelah update kode, atau setelah `make clean`.
> - `make start` — start tanpa rebuild. Gunakan untuk restart harian.

> **Kenapa `network_mode: host`?** Kamera Hikrobot (GigE Vision) menggunakan UDP broadcast untuk discovery. Docker bridge network memblok UDP broadcast ini sehingga kamera tidak terdeteksi di dalam container. `network_mode: host` membuat container langsung pakai network stack host — kamera langsung terjangkau.

---

## 9. Verifikasi

```bash
# Health check dasar
curl http://localhost:8001/health

# Detail: GPU, kamera, worker status
curl http://localhost:8001/health/detail
```

Response yang diharapkan:
```json
{
  "status": "ok",
  "camera_connected": true,
  "gpu_available": true,
  "workers_running": true,
  "outbox_pending": 0
}
```

Cek live stream di browser:
```
http://localhost:8001/api/video_feed
```

---

## 10. Network Hardening (Firewall)

Vision jalan dengan `network_mode: host`, jadi port `8001/8002/8003` **terbuka di
semua interface** PC. Selama PC prod cuma punya NIC ke switch kamera (LAN tertutup),
ini aman. Tapi begitu PC prod dapat akses internet (mis. NIC#2 / USB-Ethernet buat
kirim data), port itu jadi ter-ekspos — dan beberapa endpoint (`/api/set_truck`,
`/api/capture_reject`, `/api/video_feed`) **tidak** punya auth (dipakai langsung
oleh frontend di LAN).

**Jangan matikan endpoint-nya** (frontend masih pakai). Batasi lewat firewall:
izinkan port vision **hanya dari IP frontend/api**, tolak dari mana pun.

```bash
# Ganti <IP_FRONTEND_API> dengan IP host yang menjalankan palmgrade-frontend + api
# (biasanya sama dengan PC ini atau 1 host di LAN internal).
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <IP_FRONTEND_API> to any port 8001,8002,8003 proto tcp
# SSH kalau remote (jangan sampai kekunci):
sudo ufw allow from <SUBNET_ADMIN> to any port 22 proto tcp
sudo ufw enable
sudo ufw status verbose
```

Catatan:
- Endpoint internal (`/internal/*`) sudah dilindungi `x-internal-secret`, tapi
  firewall tetap lapisan pertama (defense-in-depth).
- Kalau frontend/api jalan di **PC yang sama**, cukup blok akses dari interface
  internet dan izinkan `127.0.0.1` / interface LAN kamera.
- Verifikasi dari host lain: `curl http://<IP_PROD>:8001/health` harus **timeout/refused**
  dari luar allowlist, tapi jalan dari IP yang diizinkan.

---

## 11. Troubleshooting

### Kamera tidak muncul di MVS setelah colok

1. Pastikan NIC PC sudah punya IP statis (`192.168.100.100`) — cek di **Settings → Network → Wired**
2. Cek LED di kamera dan NIC — harus menyala (link aktif)
3. Tekan **F5** di MVS untuk refresh
4. Coba `ping 192.168.100.10` dari terminal — jika tidak reply, masalah di koneksi fisik atau IP

### `gpu_available: false` di health check

1. Cek NVIDIA Container Toolkit terinstall: `nvidia-smi` harus jalan
2. Cek docker restart setelah install: `sudo systemctl restart docker`
3. Verifikasi: `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi`

### Kamera terconnect di MVS tapi tidak muncul di Docker

- Pastikan `CAMERA_TYPE=hikrobot` di `.env`
- Container jalan dengan `network_mode: host` — cek `docker-compose.yml`
- Pastikan MVS sudah di-close saat Docker jalan (SDK hanya bisa diakses 1 proses sekaligus — MVS dan Docker tidak bisa connect ke kamera yang sama bersamaan)

### Bandwidth terlalu tinggi (packet lost)

- Pastikan **Acquisition Frame Rate Enable = True** di MVS sebelum save UserSet1
- Cek **Resulting Frame Rate** di MVS — harus sekitar 10 fps, bukan 23 fps
- Set Jumbo Frame di NIC: `sudo ip link set enp55s0 mtu 9000`

### Gambar gelap

- Naikkan **Exposure Time** di MVS → **Acquisition Control** → **Exposure Time (us)**
- Mulai dari `20000`, sesuaikan sampai gambar cukup terang
- Jangan lupa save ulang ke **UserSet1** setelah ubah exposure

### `camera_connected: false` setelah `make start`

Normal terjadi jika kamera belum terhubung atau MVS masih buka. App tetap jalan dan workers aktif — `FrameCaptureWorker` otomatis retry setiap beberapa detik. Begitu kamera terhubung, `camera_connected` berubah jadi `true` tanpa restart.

Jika `camera_connected` tetap `false` meski kamera sudah terhubung:
1. Pastikan MVS sudah di-close (hanya 1 proses yang bisa akses kamera)
2. Cek koneksi fisik + LED
3. `curl http://localhost:8001/health/detail` — cek `workers[capture].alive`

### `MvImport SDK tidak ditemukan` saat container start

Image dibuilid tanpa SDK (`WITH_SDK=false`). Terjadi jika `make up` gagal di tengah jalan atau image lama dipakai. Fix:

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

Urutan kamera di `CAMERA_DEVICE_INDEX` bergantung pada urutan enumeration SDK. Jika tertukar:
1. Matikan semua container: `make down`
2. Tukar nilai `CAMERA_DEVICE_INDEX` di `docker-compose.yml` untuk line yang tertukar
3. `make start`
