---
name: panduan-autograde
description: Use when working on or operating AutoGrade (repo autograde) as someone new to it — setting up the console on a laptop, installing or updating the factory PC, answering "how do I use / what does this screen do / which make command", diagnosing a console or camera-line symptom, connecting to AutoERP, or before running anything on a factory PC. Also use when the user asks what AutoGrade is, how a truck visit flows, or where a topic is documented.
---

# Panduan AutoGrade — peta untuk pemegang baru

Sumber utama: **`docs/MANUAL.md`** (Bahasa Indonesia, ±20 halaman; PDF di sampingnya).
Baca bagian yang relevan dari situ dulu, bukan menyusun ulang dari kode. Skill ini
cuma peta: ke mana melihat, apa yang tidak boleh, dan jawaban cepat yang paling sering
ditanya.

## Ke mana melihat

| Pertanyaan | Baca |
|---|---|
| Sistem ini apa, alur janjang, alur kunjungan truk | `docs/MANUAL.md` §1–§3 |
| Cara pakai konsol, tab operator vs support | `docs/MANUAL.md` §3 |
| Setup laptop (tanpa kamera) / setup PC pabrik dari nol | `docs/MANUAL.md` §4 / §5, rinci di `docs/SETUP.md` |
| Perintah `make`, update kode, cek kesehatan, disk | `docs/MANUAL.md` §6, `Makefile` (komentarnya lengkap) |
| Gejala → sebab → tindakan | `docs/MANUAL.md` §7 |
| Aturan yang tidak boleh dilanggar dan alasannya | `CLAUDE.md` § Critical Rules, `docs/overview.md` |
| Variabel `.env` | `.env.example` (tiap baris berkomentar) |
| Kontrak ke AutoERP (cocokkan ini dulu sebelum menulis kode integrasi) | `../autoerp/docs/autograde-integration.md` |
| PLC / coil, spek PC Lampung | skill `plc-coil-map`, skill `spek-pc-pabrik` |
| Rekonsiliasi truk OPS-2, checklist pasang PC | `../docs/runbooks/` di workspace `sawit` |

## Jawaban cepat

- **Laptop (Mac/Linux, tanpa kamera):** `cp .env.example .env` → venv Python 3.12
  *tanpa* torch (daftar pip di README Quick Start) → `make operator` → `make console`
  → `http://127.0.0.1:8100/console`. Port **8100**, bukan 8000. Kartu kamera OFFLINE
  itu normal. `make up` gagal "MVS SDK not found" di Mac itu normal.
- **PC pabrik (Linux + GPU):** `make up` menjalankan 4 container: line di 8001–8003,
  konsol di **8000**. Ubah kode → `make restart` (konsol saja: `make restart-console`);
  ubah `.env` → `make start` (satu service saja: `make up-N` / `make up-console`) —
  `restart` dan reboot **tidak** membaca ulang `.env`; ubah deps/Dockerfile → `make up`.
  Setelan "tidak berlaku" padahal `.env` benar → env var proses menang atas `.env`
  (`load_dotenv(override=False)`), lihat nilai efektifnya di `/health/detail`.
- **Akun konsol:** email + sandi, sesi 12 jam. Lokal: `make operator`
  (`make operator-docker` di pabrik; `AKSI=daftar|matikan|role ROLE=support`).
  Akun dari AutoERP direset di AutoERP. Bawaan: `operator@autograde.local`,
  `support@autograde.local`, sandi beda per PKS (`make hash-sandi`, tulis `$$`).
- **Tab support** (Log, Diagnostik, Antrean ERP, Versi, Uji PLC, Sumber Kamera,
  Rekam Video, Setelan) hanya untuk peran `support`; 403 untuk operator, 401 kalau
  belum masuk.
- **Rekam video** (v1.13.x): satu tombol per line, jalan sampai ditekan Stop. Yang
  terekam frame **clean tanpa bbox** — disadap di `FrameCaptureWorker`, sebelum
  inference. Berkasnya di `videos/` (jalurnya tertulis di kaki layar), **tidak pernah
  dihapus otomatis** dan berhenti sendiri di bawah `UPLOAD_DISK_MIN_FREE_GB`.
  ⚠️ **Laju video mengikuti SUMBERNYA, bukan angka FPS di layar**: berkas video
  memakai laju aslinya, kamera yang tidak bisa melapor memakai `CAMERA_FPS`. Angka
  di layar cuma berlaku kalau tidak ada keduanya. Kalau durasi berkas tidak sama
  dengan lama menekan Record, baca `Rekam video MULAI` di log line — ia menyebut laju
  yang benar-benar dipakai encoder.
  ⚠️ **~2 GB/jam per line** pada 20 fps; disk pabrik 232 GB ≈ 4 hari rekam terus.
- **Kartu "Kamera tidak tersambung" padahal container jalan:** itu teks fallback saat
  **browser** gagal memuat `http://<host konsol>:800N/api/video_feed` — port line
  harus terjangkau dari PC yang membuka konsol. Status kamera sesungguhnya ada di tab
  Diagnostik / `:800N/health/detail` (`camera_connected`). Janjang nyasar ke kartu
  lain = `LINE_N_MACHINE_ID` kembar (konsol mencocokkan lewat `machine_id`, bukan port).
- **Layar nol + log "Outbox delivery failed HTTP 404":** `BACKEND_URL` salah port.
- **Janjang difoto di titik mana:** saat kotaknya **menyentuh garis capture** — garis biru
  bertanda `CAPTURE`, diatur dari tab **Setelan** (piksel, ruang stream; `0` = tanpa garis,
  janjang difoto begitu masuk ROI). ROI menjawab *di mana*, garis menjawab *kapan*. Arah
  conveyor (`tegak`/`mendatar`) menentukan garisnya tegak atau melintang. Berlaku tanpa
  restart. "Capture terlalu cepat" → **geser garisnya**, jangan sentuh `CONF_THRESHOLD`.
- **Angka keyakinan hilang dari kotak janjang:** disengaja — dari beberapa meter "54%"
  terbaca seperti "54% matang". Saklar **Mode dev** di tab Setelan mengembalikannya.
  Nilainya tetap tersimpan di sidecar dan tabel Grading.
- **`capture_save_dropped` / `tp_telat` di `/health/detail` harus NOL.** Yang pertama =
  janjang sudah dipulse PLC tapi tidak punya gambar maupun sidecar (disk/CPU kalah cepat);
  yang kedua = tangkai panjang muncul sesudah janjangnya difoto, jadi tidak tercatat.
- **Banner langganan / kamera berhenti tanpa sebab:** cek banner di atas layar konsol.
  Kuning = habis N hari lagi; oranye = sudah lewat tanggal tapi masih masa tenggang
  (grading **tetap jalan**); merah = tenggang habis dan **grading dihentikan**. Tanggal
  lengkapnya di tab **Versi** (support). Token baru diterbitkan di **AutoERP** oleh
  Administrator, lalu dipasang `autograde licence <token>` di PC pabrik — token baru
  cuma berlaku setelah container dibuat ulang, **reboot saja tidak cukup**. Data grading
  dan antrean ERP **tidak hilang** selama lisensi mati.
- **fps:** untuk Hikrobot diatur `config/camera/hikrobot.mfs`, `CAMERA_FPS` diabaikan.
- **Berat:** neto dihitung konsol, bruto/tara < 1.000 kg ditolak, `14.820` terbaca 14,82.

## Jangan — hentikan dan sebutkan alasannya

- **`make demo` di PC pabrik.** Menulis ke database operator; hanya laptop/demo. Skripnya
  menolak DB berisi data sungguhan, tapi `PAKSA=1` melewatinya — penolakan itu jaring, bukan izin.
- **Mengisi `ERP_URL` di PC yang punya data truk lama** sebelum OPS-2
  (`make rekonsiliasi-truk[-docker]`, lihat dulu tanpa `TULIS=1`). Tonase terbelah dua tanpa pesan.
- **Menjalankan ulang `create_integration_user` di AutoERP** hanya untuk melihat kunci:
  itu merotasi secret. Kunci yang sedang dipakai ada di `.env` PC pabrik; bench lokal
  punya `make key-show` di repo `autoerp`; server → minta ke pemegangnya.
- **`BACKEND_URL` ke API cloud.** Selalu konsol lokal.
- **Mengganti nama image `palmgrade-vision`**, label selain ACC/REJ, memindai folder
  dari konsol, referensi `https://` di `console.html`, torch/cv2 di unit test.
- **Mengirim data per janjang ke AutoERP.** Hanya rekap per kunjungan.
- **Menjalankan `palmgrade` (stack lama) bersamaan AutoGrade** di PC Lampung: rebutan kamera dan nama container.
- **Deploy / tag `vX.Y.Z`** selama Opsi B. Update pabrik = `git pull` manual
  (`git checkout config/camera/hikrobot.mfs` dulu).
- **Menyimpan sandi mentah atau `LICENSE_PRIVATE_KEY`** di `.env`/image.

## Mode kerja di PC pabrik

Kamu tidak memegang PC-nya; aksesnya AnyDesk, tanpa SSH. Beri **satu blok perintah**,
minta hasilnya ditempel, baru lanjut. Gerbang keras saat pasang: `docker run --gpus all
… nvidia-smi` harus keluar tabel GPU sebelum langkah lain.

## Alur kode

Branch baru → PR **squash** ke `staging` → PR **merge commit** ke `main`. Judul + isi PR
bahasa Inggris, commit boleh Indonesia, tanpa `Co-Authored-By`. Test dulu
(`.venv/bin/pytest tests/unit`), murni logic tanpa hardware.
