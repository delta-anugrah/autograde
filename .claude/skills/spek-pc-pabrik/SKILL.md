---
name: spek-pc-pabrik
description: Spek terukur PC pabrik Palmgrade/AutoGrade (Lampung) — disk, CPU, RAM, GPU, jaringan kamera, docker. Pakai kalau lagi menghitung kapasitas penyimpanan/retensi, menaksir apakah fitur baru muat, memilih target TensorRT/model, mendiagnosis "disk penuh"/"GPU nggak kuat"/"kamera nggak kebaca", menyiapkan PC pabrik baru, atau butuh angka spek apa pun — JANGAN menebak dan JANGAN tanya user duluan, baca ini dulu.
---

# Spek PC Pabrik — Lampung

Angka di sini **hasil ukur langsung di mesinnya**, bukan taksiran. Dipakai untuk
menjawab "muat nggak", "aman nggak", "sanggup nggak" tanpa menebak dan tanpa
membebani user dengan pertanyaan yang jawabannya sudah ada.

> **Diukur: 2026-09-16 10:09 WIB** (`admin-pc`, Linux Mint 22)
> Cara ukur ulang ada di bagian terakhir. **Kalau tanggal di atas lebih dari ~3
> bulan, sebut umurnya saat memakai angka disk** — disk terisi terus, angka
> "sisa" paling cepat basi.

## Ringkas

| | |
|---|---|
| Hostname | `admin-pc` (desktop, bukan server) |
| OS | Linux Mint 22 |
| CPU | Intel i5-12400F — 6 core / 12 thread |
| RAM | 31 GB (+2 GB swap) |
| Disk | **468 GB** T-FORCE SSD (NVMe/SSD, `ROTA=0`), **sisa 232 GB** |
| GPU | **RTX 3060 12 GB** (sm86), driver 575.64.03, CUDA 12.9 |
| Line kamera | **3** (line-1/2/3) |
| Akses | AnyDesk + Tailscale (`100.124.34.49`). **Tidak ada SSH masuk.** |

## ⚠️ Disk — yang paling sering ditanya

```
/dev/sda2  468G  213G terpakai  232G sisa  (48%)
```

**Satu disk untuk semuanya**: OS, docker, dan ketiga line. `docker-compose.prod.yml`
me-mount `./artifacts/line-1|2|3` dari host yang sama, jadi **kapasitas penyimpanan
gambar dihitung untuk 3 line digabung, bukan per line.**

Yang memakan 213 GB sekarang **bukan gambar** — artifacts cuma ~2,7 MB total
(908K + 872K + 924K; pabrik belum produksi penuh). Yang gemuk:

| | |
|---|---|
| Docker images | **71,2 GB** (14 image, 14,9 GB bisa dibuang) |
| Build cache | **20,1 GB** (1,6 GB reclaimable) |
| Volume lokal | 446 MB |
| `/opt/palmgrade/vision` | 449 MB (kode + model, bukan gambar) |

➡️ **Ruang aman untuk gambar ≈ 232 GB sisa − 20 GB lantai penjaga disk ≈ 210 GB.**
Bisa ditambah ~35 GB gratis dengan `docker system prune` (image lama + build cache).

### Kapasitas gambar, dihitung

Ukuran nyata **178 KB/gambar** (WebP q65, kamera 2448×2048). Untuk **3 line
digabung**, dengan asumsi 20 jam operasi/hari:

| janjang/jam/line | per hari (3 line) | muat berapa hari di 210 GB |
|---|---|---|
| 300 | 3,1 GB | **~68 hari** |
| 500 | 5,1 GB | **~41 hari** |
| 1000 | 10,2 GB | **~21 hari** |

⚠️ **`UPLOAD_RETENTION_DAYS=180` di pabrik TIDAK akan pernah tercapai** pada
throughput manapun di atas — penjaga disk (`UPLOAD_DISK_MIN_FREE_GB=20`) akan
membuang item `done` jauh lebih dulu. Itu **perilaku benar, bukan bug**: arsip
sesungguhnya ada di R2/cloud, lokal cuma cadangan. Jangan "membetulkan"
retensi karena melihat foto lama hilang.

⚠️ **Menyimpan gambar versi kedua (mis. clean tanpa bounding box) = semua angka
di atas dibagi dua.** Di 500 janjang/jam/line, 41 hari jadi ~20 hari.

## GPU

RTX 3060 12 GB, **compute capability sm86**. Engine TensorRT hardware-locked per
GPU: `engines/best.sm86.engine`, sekali bangun ~208 detik.

Saat idle: 196 MiB / 12288 MiB terpakai (cuma Xorg + cinnamon). VRAM bukan
kendala — 3 line jalan di ~1,5 GB total. Yang jadi kendala fps itu CPU/kamera,
bukan GPU.

## Jaringan — dua NIC, jangan tertukar

| Interface | IP | Gunanya |
|---|---|---|
| `enp3s0` | `192.168.0.10/24` | **Jaringan kamera** (switch gigabit khusus) |
| `enx00e04c680881` | `192.168.1.103/24` | **Internet** (USB ethernet) |
| `tailscale0` | `100.124.34.49` | Akses jarak jauh |

Kamera Hikrobot GigE ada di segmen `192.168.0.x`. Internet lewat NIC terpisah —
ini disengaja, jangan digabung (lihat `project_prod_internet_network`).

⚠️ IP `192.168.1.103` itu **DHCP** — bisa berubah sendiri. Ada ranjau CORS yang
mencocokkan IP persis huruf-per-huruf; lihat `project_factory_pc_lampung`.

## Container

4 container jalan: `palmgrade_api`, `palmgrade_frontend`, `palmgrade_postgres`,
`palmgrade_mongo`, plus `ripe_line_1|2|3` untuk vision. Nama pakai **underscore**,
tidak sama dengan compose dev. Selalu `docker ps --format '{{.Names}}'` sebelum
`docker exec` — file compose prod ada di host, tidak ada di repo.

## Cara ukur ulang

Jalankan di PC Lampung lewat AnyDesk (semuanya baca saja, tidak mengubah apa pun),
lalu paste hasilnya ke sesi dan minta skill ini diperbarui:

```bash
{
echo "=== TANGGAL ==="; date
echo; echo "=== MESIN ==="; hostnamectl 2>/dev/null | head -6
echo; echo "=== CPU ==="; lscpu | grep -E "Model name|^CPU\(s\)|Thread|Core"
echo; echo "=== RAM ==="; free -h
echo; echo "=== DISK ==="; df -h; echo "--- fisik ---"; lsblk -d -o NAME,SIZE,ROTA,MODEL
echo; echo "=== PALMGRADE MAKAN BERAPA ==="; sudo du -sh /opt/palmgrade/* 2>/dev/null
echo; echo "=== ARTIFACTS PER LINE ==="; sudo du -sh /opt/palmgrade/vision/artifacts/* 2>/dev/null
echo; echo "=== GPU ==="; nvidia-smi
echo; echo "=== DOCKER ==="; docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'; docker system df
echo; echo "=== KAMERA ==="; ip -br addr
} 2>&1 | tee ~/spek-pc-lampung.txt
```

Throughput nyata (janjang/jam) — tidak ada di spek mesin, hitung dari file yang ada:

```bash
sudo find /opt/palmgrade/vision/artifacts -name "*_ripeness.json" | \
  sed 's/.*\///; s/_[0-9]*_auto.*//' | cut -c1-13 | sort | uniq -c | tail -30
```

## Yang MASIH belum terukur

Jujur sebutkan ini kalau relevan, jangan ditambal dengan tebakan:

- **Throughput produksi nyata.** Per 2026-09-16 pabrik belum giling penuh
  (artifacts cuma ~2,7 MB), jadi angka janjang/jam masih asumsi. Semua hitungan
  "muat berapa hari" di atas bergantung pada ini.
- **Site selain Lampung.** Skill ini khusus `admin-pc`. PC pabrik lain punya
  spek sendiri — ukur ulang, jangan pakai angka ini.

## Kalau dipakai untuk memutuskan

1. Baca angka di sini dulu — **jangan tanya user spek apa pun yang sudah ada di atas**.
2. Sebut umur pengukuran kalau menyangkut disk ("per 16 Sep sisa 232 GB").
3. Yang ada di "belum terukur" → itu baru boleh ditanyakan ke user.
4. Kalau usul fitur menambah tulisan ke disk, hitung pakai tabel kapasitas di
   atas dan sebutkan dampaknya ke retensi — jangan cuma bilang "aman".
