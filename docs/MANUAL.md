---
judul: Manual AutoGrade
subjudul: Cara pakai, daftar fitur, pemasangan dari nol, operasional harian, dan penanganan masalah — untuk orang yang ikut memegang AutoGrade.
label: Internal · Tim Engineering
versi: "1.0"
tanggal: 17 September 2026
klasifikasi: Internal — tidak untuk dibagikan ke pihak luar
pemilik: Tim Engineering AutoGrade
sorotan: Isi = Fitur · Setup · Operasional · Troubleshooting; Pembaca = Pemegang baru AutoGrade; Bentuk = Ringkas, tabel, perintah siap tempel
---

# Manual AutoGrade

Dokumen ini untuk orang yang baru ikut memegang AutoGrade: bisa memakainya, memasangnya dari
nol, menjaganya sehari-hari, dan tahu ke mana harus melihat saat ada masalah. Sengaja ringkas.
Rincian yang lebih dalam selalu ditunjuk ke berkas di repositori, bukan disalin ke sini.

> **Untuk AI agent** (Claude Code, Codex): repositori ini punya `CLAUDE.md` (peta aturan,
> `AGENTS.md` menunjuk ke berkas yang sama) dan skill `.claude/skills/panduan-autograde/`.
> Dokumen ini adalah versi manusianya.

## 1. AutoGrade Itu Apa

AutoGrade adalah sistem penilaian mutu tandan buah segar (TBS) kelapa sawit di pabrik kelapa
sawit (PKS). Truk pemasok menuang buah ke conveyor; kamera industri dan model AI menilai setiap
tandan (disebut **janjang**): diterima (**ACC**) atau ditolak (**REJ**). Hasilnya jadi dasar
potongan dan pembayaran ke pemasok, lengkap dengan foto tiap janjang sebagai bukti.

Tiga hal yang dikerjakan AutoGrade:

1. **Menilai janjang** di tiga conveyor (**line**), masing-masing satu kamera Hikrobot dan satu
   proses AI. Hasil REJ boleh memicu piston PLC untuk membuang buah.
2. **Layar operator** (konsol): truk yang sedang dibongkar per line, jumlah janjang, tiket
   timbangan, rekap harian. Jalan **tanpa internet**.
3. **Mengirim rekap per truk** ke AutoERP (ERPNext) di server: berat masuk/keluar dan hitungan
   ACC/REJ. Yang per janjang **tidak** dikirim; foto tetap di pabrik sebagai bukti.

```diagram:arsitektur Pembagian peran: AutoGrade di PC pabrik, AutoERP di server
PC pabrik (boleh offline)                 Server
┌──────────────────────────┐   rekap    ┌────────────────────┐
│ 3 line kamera + konsol   │ ─────────▶ │ AutoERP (ERPNext)  │
│ SQLite + foto di disk    │ per truk   │ tiket → stok → bayar│
└──────────────────────────┘            └────────────────────┘
```

Yang **bukan** urusan AutoGrade: harga TBS, potongan, faktur, pembayaran. Semua itu di AutoERP.
Rancangannya "dua kotak": PC pabrik memegang bukti per janjang, server memegang buku besar.

## 2. Komponen yang Berjalan

Satu image Docker dijalankan **empat kali** dengan peran berbeda:

| Container | Port | Peran | Kalau mati |
|---|---|---|---|
| `ripe_line_1` | 8001 | kamera + AI line 1 | line 1 berhenti menilai, line lain jalan |
| `ripe_line_2` | 8002 | kamera + AI line 2 | sama |
| `ripe_line_3` | 8003 | kamera + AI line 3 | sama |
| `palmgrade_console` | 8000 | layar operator `/console` | layar mati; line tetap menilai dan menyimpan, kiriman menunggu di antrean |

Line memakai `main.py` (memuat torch, OpenCV, driver kamera). Konsol memakai `console_main.py`
yang **tidak** memuat keduanya, supaya gangguan kamera tidak mematikan layar operator.

**Model AI** `models/release/best.pt` mengenali 4 kelas: `Ripe`, `Unripe`, `JK` (janjang kosong),
`TP` (tangkai panjang). Verdict diturunkan dari kelas: `Ripe` → ACC; `Unripe` dan `JK` → REJ;
`TP` cuma penanda, bukan verdict. Objek lebih kecil dari `MINIMUM_SIZE` piksel² otomatis REJ.
Dua buah bertumpuk dalam ROI di satu frame → semuanya REJ.

**Kapan janjang difoto.** Saat kotaknya **menyentuh garis capture** — garis biru bertanda
`CAPTURE` di layar line, diatur dari tab Setelan. ROI menjawab *di mana* (bagian gambar yang
dianggap conveyor), garis menjawab *kapan*. Janjang difoto apa adanya, ada tangkai panjang atau
tidak. Tangkai panjang dipasangkan ke janjang **terdekat**; tangkai yang baru muncul sesudah
janjangnya difoto tidak ikut, dan jumlahnya terbaca di tab Diagnostik sebagai `tp_telat`.
Garis `0` = tanpa garis, janjang difoto begitu masuk ROI (perilaku sebelum September 2026).

```diagram:alur-janjang Perjalanan satu janjang dari kamera sampai AutoERP
kamera → FrameCaptureWorker → antrean → FrameProcessingWorker → CaptureSaveWorker
                                                                   (disk + outbox.db)
                                                                     │
                                   DisplayWorker → MJPEG             ▼
                                   (layar langsung)          OutboxRetryWorker
                                                                     │
                                                                     ▼
                                                    konsol (SQLite console.db)
                                                                     │
                                            rekap per truk ──────────┘──▶ AutoERP
```

Urutan yang penting dipahami:

1. Kamera → frame → YOLO + ByteTrack (satu janjang dihitung **sekali** walau terlihat di banyak frame),
   dan difoto saat kotaknya **menyentuh garis capture**.
2. Hasil ditulis ke **disk dulu** (`artifacts/line-N/results/`: WebP + JSON), lalu satu baris ke
   `outbox.db`. Penulisannya dikerjakan `CaptureSaveWorker` di thread terpisah supaya penilaian
   tidak berhenti menunggu disk — satu janjang memakan sekitar setengah detik untuk disimpan.
3. `OutboxRetryWorker` mengirim ke konsol tiap detik. Konsol mati = data menunggu, tidak hilang.
4. Konsol menyimpan ke `state/console.db`. Layar membaca dari sini, **tidak pernah memindai folder**.
5. Tiap jam `BatchUploadWorker` mengunggah foto ke Cloudflare R2 (kalau `R2_BUCKET` diisi).
6. Saat truk dilepas dari line, konsol mengirim rekap kunjungan ke AutoERP lewat antrean sendiri.

Listrik padam, internet putus, container restart: semuanya cuma bikin **terlambat**, bukan hilang.

## 3. Cara Pakai Konsol Operator

Layar: `http://localhost:8000/console` di PC pabrik (`:8100` di laptop developer). Satu berkas
HTML tanpa CDN dan tanpa webfont, jadi tetap terbuka saat internet mati. Dwibahasa ID/EN, tema
terang/gelap, pilihan tersimpan di browser.

### 3.1 Masuk

Layar terkunci sampai ada yang masuk dengan **email + sandi**. Tombol nama di gerbang cuma
mengisi kolom email; sandi tetap wajib. Sesi 12 jam, tidak diperpanjang otomatis.

| Sumber akun | Dibuat di | Reset sandi |
|---|---|---|
| AutoERP (DocType `AutoGrade Operator`) | ERP Desk, ikut turun bareng master data | di AutoERP |
| Lokal PC ini | `make operator` (atau `make operator-docker` di pabrik) | `make operator` lagi dengan email sama |

Dua akun bawaan ada di tiap PC: `operator@autograde.local` (pabrik) dan `support@autograde.local`
(kita, lewat AnyDesk). Sandinya beda tiap PKS, dibuat saat pasang PC (§5.5). Login tetap jalan
tanpa internet karena hash sandi tersimpan lokal.

Dua peran: **operator** (4 tab) dan **support** (12 tab, lihat §3.5). Yang menjaga adalah backend:
endpoint support dijawab 403 untuk operator, dan 401 untuk yang belum masuk.

### 3.2 Layar utama

- **Strip total hari kerja**: total janjang, ACC, REJ, rasio Ripe.
- **Tiga kartu line**, satu per kamera, dengan stream langsung, status **ONLINE / OFFLINE** di
  judul, tombol **Tugaskan** (pilih truk), **Lepas** (truk pergi), dan **Reject Manual**.
- **Reject manual tanpa mouse**: tahan `Spasi` lalu tekan `1` / `2` / `3` sesuai line.
- **Piston manual** per line (Buka / Tutup) kalau PLC aktif. Ada konfirmasi karena ini
  menggerakkan besi sungguhan.
- Sumber TBS **Internal** ditandai "REJ tidak dibuang": buah kebun sendiri tetap dinilai, tapi
  piston tidak membuangnya.
- Dua kolom scan di baris alat: **Truk masuk** dan **Truk keluar** (§3.3).

### 3.3 Alur satu kunjungan truk

```diagram:kunjungan-truk Perjalanan satu truk, dari gerbang masuk sampai pemasok dibayar
1 timbang masuk → 2 buah dituang, kamera menilai → 3 timbang keluar → 4 AutoERP hitung → 5 bayar
```

| # | Kejadian | Yang dilakukan di konsol | Yang dikirim ke AutoERP |
|---|---|---|---|
| 1 | Truk tiba | Scan kartu QR di kolom **Truk masuk**, atau ketik plat. Truk belum dikenal → **Daftar truk manual** di tab Truk (cukup plat) | truk baru (`upsert_truck`) |
| 2 | Timbang masuk | Tab **Timbangan** → **Timbang masuk**: plat + bruto (kg). Berat di bawah 1.000 kg ditolak | tahap `gate`: bruto + jam masuk |
| 3 | Bongkar | Kartu line → **Tugaskan** → pilih truk. Janjang berikutnya dicatat atas nama truk itu | — |
| 4 | Selesai bongkar | **Lepas** di kartu line | tahap `grading`: total, ACC, REJ, persen |
| 5 | Timbang keluar | Scan QR di kolom **Truk keluar** → isi tara. Dua tiket terbuka → konsol menolak menebak, pilih di tabel | tahap `departed`: tara + jam keluar |
| 6 | AutoERP | — | neto = bruto − tara, potongan, harga, Purchase Receipt |

Tabel Timbangan memakai kolom **Lama**: berapa lama truk itu diproses, dihitung
dari jam timbang masuk ke jam timbang keluar (`25 mnt`, `1 j 45 mnt`). Tiket
yang belum timbang keluar tampil `-`, bukan nol — truknya masih di pabrik. Angka
ini tidak disimpan di mana pun, selalu dihitung ulang dari dua jam timbangan,
supaya tidak pernah ada dua angka yang bisa berbeda kalau salah satu jam
dikoreksi.

Aturan angka yang dijaga konsol:

- **Neto dihitung, tidak pernah dipercaya** dari pengirim. Beda lebih dari 1 kg → ditolak.
- Desimal boleh titik atau koma (`14820,5`). Pemisah ribuan (`14.820`) **ditolak** oleh lantai
  1.000 kg pada bruto dan tara, karena terbaca 14,82 kg.
- **Tanggal kerja** dihitung saat data masuk dengan `FACTORY_TZ`. Pabrik jalan ±20 jam lewat
  tengah malam; ini yang mencegah satu shift terbelah jadi dua hari.
- Buah REJ dinaikkan lagi ke truk dan ikut ditimbang saat keluar, jadi otomatis tidak dibayar.

### 3.4 Empat tab operator

| Tab | Isi | Yang bisa dilakukan |
|---|---|---|
| **Grading** | riwayat janjang: waktu, line, truk, sumber, hasil, kelas, confidence, foto | filter per line/truk, pagination, klik foto → tampilan besar |

> Angka keyakinan ada di tabel Grading, tapi **tidak** digambar di kotak janjang pada layar
> line — dari beberapa meter "54%" terbaca seperti "54% matang". Saklar **Mode dev** di tab
> Setelan mengembalikannya, untuk yang sedang menyetel ambang.

| **Truk** | master truk + supplier + asal data (ERP / manual) | **Daftar truk manual**, **Cetak QR truk** (kartu QR berisi plat, dibuat di server) |
| **Timbangan** | tiket hari kerja: masuk, keluar, bruto, tara, neto | **Timbang masuk**, isi tara lewat scan keluar |
| **Rekap** | satu baris per truk per hari kerja: janjang, ACC, REJ, rasio, neto | ini yang diserahkan ke supplier; baris **Tanpa truk** = janjang ter-grading sebelum truk ditugaskan |

Rekap menyandingkan dua sumber terpisah (grading dan timbangan). Neto dijumlah per truk; satu
truk boleh punya lebih dari satu tiket sehari.

### 3.5 Delapan tab support

Muncul hanya untuk akun berperan `support`. Tujuannya: memeriksa PC pabrik dari layar, tanpa
`docker logs` yang hilang tiap restart.

| Tab | Isi |
|---|---|
| **Log** | ERROR/WARNING 180 hari terakhir, selamat dari restart; pesan berulang digabung `×N`; sandi/token tertulis `«ditutup»` |
| **Diagnostik** | tiga kartu line: kamera, GPU, PLC, antrean lokal, lalu worker satu per baris (✓ hijau hidup, ✗ merah mati; judulnya memberi hitungan, mis. `5/6`). Line mati tetap tampil dengan sebabnya. ⚠️ `capture_save_dropped` dan `tp_telat` **harus nol** — di atas nol berarti ada janjang yang tidak tersimpan, atau tangkai panjang yang tidak tercatat |
| **Antrean ERP** | pesan yang belum sampai ke AutoERP: sebab gagal, percobaan, jadwal berikutnya; tombol **Kirim Ulang**. Plus antrean manifest R2 |
| **Versi** | versi, environment, status lisensi (tanpa token). Machine ID disembunyikan sejak 2026-09-25. Lisensi **Mati — token ada, tapi LICENSE_ENABLED tidak menyala** berarti tokennya sampai ke konsol tapi saklarnya tidak: periksa blok konsol di compose host, bukan tokennya |
| **Uji PLC** | tombol uji coil per line (OK hijau, NG merah, Error kuning, alamat M di tiap tombol) + kartu peta alamat PLC di bawahnya. Mati saat line memproses truk; konfirmasi tombol Jalankan/Batal; heartbeat (M1009) sengaja tidak ada |
| **Sumber Kamera** | pilih sumber gambar tiap line: kamera Hikrobot, webcam, berkas video, atau foto diam. Menyimpan **merestart** line yang berubah (~10 detik) |
| **Model Deteksi** | pilih model YOLO tiap line dari berkas di `models/release/`. Tiap model menampilkan **kelasnya** dan status engine TensorRT; model yang kelasnya bukan `Ripe/Unripe/JK/TP` tampil tapi tidak bisa dipilih. Kartu line menunjukkan model yang **sedang jalan** menurut line itu sendiri, beserta kelasnya — **merah** kalau bukan empat kelas itu, artinya line tidak menghitung janjang. Simpan membuka **modal konfirmasi** yang menyebut line yang akan restart (~10 detik) dan truk yang sedang diproses di situ. Bawaan PC = `MODEL_FILE` di `.env`. Runbook: `docs/runbooks/2026-09-24-model-deteksi-per-line.md` |
| **Rekam Video** | rekam gambar kamera ke MP4, satu tombol per line, jalan sampai ditekan Stop. Gambarnya **polos tanpa kotak deteksi** (diambil sebelum model jalan). Resolusi (lebar × tinggi) diatur di tab ini juga, dan berlaku untuk rekaman **berikutnya** — mengubahnya di tengah rekaman menghasilkan berkas rusak. ⚠️ **FPS mengikuti sumbernya, tidak diatur dari layar** (kolom FPS dan Bitrate dicabut 2026-09-25 — dua-duanya tidak pernah sampai ke berkas): berkas video memakai laju aslinya, kamera Hikrobot memakai `CAMERA_FPS`. Itu yang membuat durasi rekaman sama dengan lama menekan Record. ⚠️ **Rekaman tidak pernah dihapus otomatis**: hapus sendiri dari folder yang tertulis di kaki layar (`Disimpan di …`, di PC pabrik `/opt/palmgrade/autograde/videos/`). Sesudah menekan Stop, jalur lengkap berkasnya juga muncul sekali di notifikasi hijau. Berhenti sendiri kalau sisa disk di bawah 20 GB, supaya grading tidak pernah kehabisan tempat menulis |
| **Setelan** | ambang keyakinan (0–1), ukuran minimum (piksel), **arah conveyor**, **garis capture** (piksel), dan saklar **Mode dev**. Tersimpan dan langsung dikirim ke tiga line, menang atas `.env`. Tab paling kanan |

### 3.6 Layar penuh di PC pabrik

`make kiosk` membuka Chrome mode kiosk (keluar dengan `Alt+F4`). Untuk jalan otomatis saat login
pasang `scripts/palmgrade-console.desktop`. Skrip itu menunggu konsol menjawab dulu, karena
setelah listrik padam desktop sering login sebelum Docker siap.

## 4. Setup dari Nol: Laptop Developer

Untuk mengembangkan atau mencoba konsol **tanpa kamera dan tanpa GPU**. Jalan di Mac atau Linux.
Butuh Python 3.12 dan akses ke repositori `delta-anugrah/autograde`.

```bash
git clone git@github.com:delta-anugrah/autograde.git
cd autograde
cp .env.example .env

python3.12 -m venv .venv
.venv/bin/pip install "fastapi==0.115.12" "uvicorn[standard]==0.34.0" "python-dotenv==1.1.0" \
  "httpx==0.28.1" "pydantic==2.11.3" "segno==1.6.6" \
  pytest ruff cryptography aiosqlite psutil boto3 pyyaml

make operator          # akun lokal: email + nama + sandi (min. 8 karakter)
make demo              # opsional: 10 truk, seminggu riwayat, akun operator@/support@demo.autoerp.test sandi sawit2026
make demo-reset        # hapus data demo lalu isi ulang bersih
make demo-off          # sesudah demo: hapus data demo, berhenti di situ (data sungguhan tidak disentuh)
make console           # http://127.0.0.1:8100/console  (Ctrl-C untuk berhenti)
.venv/bin/pytest tests/unit
```

Yang perlu diketahui:

- Venv ini **sengaja tanpa torch / ultralytics / OpenCV**. Konsol tidak memakainya.
- **Sesudah showcase, jalankan `make demo-off` sebelum uji coba sungguhan.** Data demo
  kalau dibiarkan akan menutupi baris yang baru digrading — janjangnya berstempel sampai
  mendekati jam sekarang, dan tab Grading + tabel Timbangan urut waktu terbaru, jadi baris
  demo selalu di atas. Layarnya terlihat "beku" padahal real-time-nya jalan. `make demo-off`
  cuma menghapus sepuluh plat demo; truk, timbangan, dan janjang sungguhan tidak disentuh.
- Port **8100**, bukan 8000: di laptop, 8000 biasanya dipegang AutoERP lokal.
- Tiga kartu kamera tampil **OFFLINE**. Itu benar, tidak ada line di laptop.
- `make console` jalan **tanpa auto-reload**: ubah Python → jalankan ulang. Ubah `console.html`
  → cukup refresh browser.
- `make up` / `make up-prod` berhenti di `Hikrobot MVS SDK not found`. Memang seharusnya; target
  Docker adalah jalur Linux + GPU.
- Satu line kamera **native** dari file video: `make line` (port 8001, `CAMERA_TYPE=opencv`,
  `CAMERA_VIDEO_PATH=/path/video.mp4`, `CAMERA_FPS=` kosong supaya laju mengikuti berkas). Ini
  butuh venv penuh dari `requirements.txt` (torch, ultralytics, OpenCV). `make line N=2` untuk
  line kedua; port dan `MACHINE_ID` ikut berubah bersama.
- Menyambung ke AutoERP lokal: dari repo `autoerp` jalankan `make up` lalu `make key-show`, tempel
  `ERP_URL=http://pks.localhost:8000`, `ERP_API_KEY`, `ERP_API_SECRET` ke `.env`, dan pastikan
  `CONSOLE_LINE_HOST=http://127.0.0.1` (di macOS `localhost` menunjuk IPv6 dulu).

## 5. Setup dari Nol: PC Pabrik

Linux (dipakai Linux Mint 22 di Lampung), GPU NVIDIA, tiga kamera Hikrobot GigE. Panduan panjang
dengan tangkapan layar MVS ada di `docs/SETUP.md`; ini urutan ringkasnya.

### 5.1 Bawa sebelum berangkat

- [ ] PC dengan GPU NVIDIA; `nvidia-smi` sudah keluar tabel. Disk sisa ≥ 30 GB.
- [ ] **Dua NIC**: satu untuk kamera (switch gigabit khusus), satu untuk internet (USB ethernet boleh).
- [ ] Switch gigabit yang mendukung jumbo frame (MTU 9000). **Splitter bukan switch.**
- [ ] Berkas model `best.pt` 4 kelas (±50 MB; yang 130 MB itu model lama 3 kelas, tidak dikenali kode). **Tidak ada di repositori.**
- [ ] Serial tiga kamera Hikrobot.
- [ ] Empat nilai `R2_*` Cloudflare kalau foto mau diarsipkan ke cloud.
- [ ] Kunci integrasi AutoERP (`ERP_API_KEY`/`ERP_API_SECRET`) kalau langsung disambung. Boleh belakangan.
- [ ] Akses `git clone` repositori (SSH key atau PAT).

### 5.2 Jaringan kamera

NIC kamera diberi IP statis, tanpa gateway, dan **centang "Use this connection only for
resources on its network"**. Tanpa centang itu, NIC kamera jadi default route dan Docker gagal
resolve DNS saat build.

| Perangkat | IP |
|---|---|
| NIC PC (kamera) | `192.168.100.100/24` |
| Kamera line 1 / 2 / 3 | `192.168.100.10` / `.11` / `.12` |
| PLC Mitsubishi (kalau ada) | `192.168.0.14` — satu segmen dengan NIC kamera PC (`192.168.0.10`), dicolok ke switch kamera |

Minta IT pabrik mengunci IP NIC internet di DHCP reservation, supaya alamat konsol tidak
berpindah.

### 5.3 MVS: set kamera, simpan `.mfs`

Pasang MVS client di host untuk **membaca serial dan menyetel kamera**. SDK-nya sendiri ikut di
dalam image; `make up` menyalin `/opt/MVS/lib/64/` ke `sdk/` saat build.

1. MVS → refresh → tiap kamera: **Modify IP Address** sesuai tabel di atas.
2. Open Device → Play → pastikan gambar keluar.
3. Acquisition Frame Rate Enable = True, Frame Rate 15–20, Exposure sesuai cahaya, Pixel Format `BayerRG8`.
4. User Set Control → simpan ke `UserSet1`, jadikan default.
5. Simpan feature ke berkas `.mfs`. Bawaan repositori: `config/camera/hikrobot.mfs`; per line bisa
   dibedakan lewat `LINE_N_FEATURE_FILE`.

⚠️ **Laju frame diatur oleh `.mfs`, bukan `CAMERA_FPS`.** Untuk Hikrobot, `CAMERA_FPS` diabaikan.
Tutup MVS sebelum menjalankan line; kamera GigE hanya bisa dibuka satu proses.

### 5.4 Docker, NVIDIA Container Toolkit, repositori

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin make git
sudo usermod -aG docker "$USER"      # lalu LOGOUT dan login lagi; newgrp saja tidak cukup

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker

docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi   # HARUS keluar tabel GPU
```

⚠️ Berhenti kalau baris terakhir tidak mengeluarkan tabel GPU. Tanpa itu YOLO jalan di CPU,
sepuluh kali lebih lambat, dan semua langkah berikutnya cuma menumpuk masalah.

```bash
git clone git@github.com:delta-anugrah/autograde.git ~/autograde
cd ~/autograde
mkdir -p models/release artifacts/line-{1,2,3} state/line-{1,2,3} state/console engines
cp /media/usb/best.pt models/release/          # wajib di models/release/, bukan models/
cp .env.example .env
```

Folder `engines/` biarkan kosong. Engine TensorRT terkunci ke GPU tertentu; jangan disalin dari
mesin lain.

### 5.5 Isi `.env` produksi

Baris yang wajib disentuh. Sisanya biarkan bawaan.

| Kunci | Nilai | Catatan |
|---|---|---|
| `APP_ENV` | `production` | fail-fast kalau secret masih bawaan |
| `CAMERA_TYPE` | `hikrobot` | |
| `LINE_1_CAMERA_SERIAL` … `LINE_3` | serial dari MVS | pilih kamera by-serial; tanpa ini urutan kamera bisa tertukar |
| `BACKEND_URL` | `http://localhost:8000` | tiga line mengirim ke **konsol lokal**. Jangan pernah ke API cloud |
| `WEBHOOK_SECRET` | `openssl rand -hex 32` | dipakai line ↔ konsol di PC ini |
| `FACTORY_TZ` | `Asia/Jakarta` (sesuaikan) | batas tanggal kerja |
| `CONSOLE_DEFAULT_HASH`, `CONSOLE_SUPPORT_HASH` | keluaran `make hash-sandi` | dua sandi **berbeda**, catat di catatan internal. Tulis `$$` untuk tiap `$` (compose memakan `$`) |
| `CONF_THRESHOLD`, `MINIMUM_SIZE`, `ROI_*` | nilai pabrik | Lampung: 0.5, 3000, ROI 100/100/1180/620. Bisa diubah dari tab Setelan |
| `GARIS_CAPTURE`, `SUMBU_GARIS`, `MODE_DEV` | `300`, `tegak`, `false` | **nilai awal saja** — yang dipakai sehari-hari diatur dari tab Setelan, berlaku tanpa restart. Garis `0` = tanpa garis |
| `BORDER_THICKNESS`, `FONT_SCALE`, `FONT_THICKNESS` | 8, 2.5, 5 | frame 2448×2048 butuh angka besar |
| `R2_ACCOUNT_ID` … `R2_PUBLIC_URL` | dari Cloudflare, atau kosong | kosong = foto tidak diunggah, tidak ada `detail_url` di tiket ERP |
| `UPLOAD_API_URL`, `UPLOAD_API_SECRET` | **kosong** | penerima teks per janjang sudah pensiun |
| `UPLOAD_RETENTION_DAYS`, `UPLOAD_DISK_MIN_FREE_GB` | 180, 20 | penjaga disk membuang arsip `done` tertua saat disk tinggal 20 GB |
| `ERP_URL`, `ERP_API_KEY`, `ERP_API_SECRET` | kosong dulu | isi di §5.8 |
| `PLC_ENABLED` | `false` dulu | nyalakan saat commissioning PLC (§5.9) |
| `LICENSE_ENABLED` | `false` | lihat §5.10 |

`make hash-sandi` menanyakan dua sandi secara interaktif dan mencetak dua baris hash. Sandi
mentah tidak pernah masuk ke `.env` maupun image.

### 5.6 Nyalakan

```bash
make up          # salin SDK, build image GPU (unduh torch ±2,4 GB, ±30 menit), build engine TensorRT, start 4 container
make ps
curl -s localhost:8001/health/detail | grep -E 'camera_connected|gpu_available'   # keduanya true
docker logs ripe_line_1 2>&1 | grep backend=       # backend=tensorrt
```

Buka `http://localhost:8000/console`, masuk dengan `support@autograde.local`, cek tab
**Diagnostik**: tiga kartu line harus hijau dengan fps terbaca.

`make up` menjalankan container dengan kode di-bind-mount (`.:/app`), jadi perubahan kode cukup
`make restart`. Kalau mau image immutable (yang jalan = image yang dibuild, `git pull` tidak
mengubah service yang sedang jalan): `make up-prod`, lalu `make build-engine` sekali, lalu
`make restart`. Engine tidak ada → runtime otomatis memakai `.pt` (akurasi sama, lebih lambat).

### 5.7 Kiosk dan autostart

```bash
make kiosk                                              # coba dulu
cp scripts/palmgrade-console.desktop ~/.config/autostart/   # jalan sendiri saat login
```

Pastikan autologin aktif di login manager, supaya PC yang reboot setelah listrik padam kembali
menampilkan konsol tanpa disentuh.

### 5.8 Sambung ke AutoERP

⚠️ **PC yang sudah punya data truk dari palmgrade-api (stack lama)** wajib menjalankan
rekonsiliasi truk **sebelum** `ERP_URL` diisi: `make rekonsiliasi-truk-docker` (lihat dulu), lalu
`TULIS=1`. Tanpa ini tarikan pertama membelah tonase satu truk jadi dua baris tanpa pesan apa
pun. Checklist lengkap: `sawit/docs/runbooks/2026-09-15-checklist-ops2-rekonsiliasi-truk-lampung.md`.
PC baru (database kosong) tidak perlu.

Kunci integrasi dibuat di server AutoERP (menjalankannya ulang **merotasi** secret):

```bash
bench --site <site> execute erpnext.palm_mill.setup.create_integration_user \
  --kwargs '{"email": "autograde@<site>", "full_name": "AutoGrade"}'
```

Kalau kuncinya sudah pernah dibuat, minta nilainya ke pemegang server; di bench lokal ada
`make key-show` di repo `autoerp`. Isi `ERP_URL`, `ERP_API_KEY`, `ERP_API_SECRET`, `ERP_COMPANY`
(kosong = company bawaan site) di `.env`, lalu `make up-console` (bukan `restart`: `docker
compose restart` tidak membaca ulang `.env`, `up -d` membuat ulang container yang setelannya
berubah). Tunggu satu siklus tarikan (`CONSOLE_SYNC_INTERVAL_S`, 5 menit): tab Truk terisi truk
dan supplier dari ERP, tab Antrean ERP kosong.

Konsol yang memanggil AutoERP, tidak pernah sebaliknya. PC pabrik nol inbound. Akun dari ERP
hanya diterima untuk peran di `ERP_ALLOWED_ROLES` (bawaan `support`).

### 5.9 PLC (Mitsubishi Q03UDECPU, MC Protocol)

`PLC_ENABLED=true`, `PLC_HOST=192.168.0.14`, lalu `make start` (port per line 1025/1026/1027 sudah
dipatok di compose — satu Open Setting PLC per koneksi). PC bicara langsung ke port
Ethernet bawaan CPU (coupler ODOT dibatalkan 2026-09-21). Alamat M per line dipatok di
`docker-compose.yml` mengikuti daftar pak Ocit: camera 1 = M1000–M1002 + heartbeat M1009,
camera 2 = M1003–M1005, camera 3 = M1006–M1008; yang dibaca M1100–M1115 (motor fault, E-stop
M1111). Piston manual **belum dialokasikan** — fiturnya mati sampai panel memberi bitnya.
Dokumen tim PLC: `docs/plc-mc-handoff.pdf`; referensi teknis: `docs/plc-integration.md`. Uji
dari tab **Uji PLC**: tombol per coil bernama ("Kamera 1 OK / M1000") dan peta alamat
lengkap di bawahnya. Motor fault dan E-stop dari PLC tampil sebagai pita merah di atas
kartu line (bukan di tab Uji PLC); E-stop tidak menghentikan grading.

### 5.10 Lisensi

Bawaan mati. Kalau dinyalakan (`LICENSE_ENABLED=true`, `LICENSE_TOKEN=<token dari cloud>`),
lisensi kedaluwarsa menghentikan inferensi dan menjatuhkan heartbeat PLC, jadi terlihat di lantai
pabrik. Kunci publik sudah tertanam di image; `LICENSE_PRIVATE_KEY` **tidak boleh** ada di PC
pabrik. Status terlihat di tab Versi.

### 5.11 Catatan PC Lampung (per 17 September 2026)

PC Lampung masih menjalankan stack lama (`palmgrade-api` + frontend + vision) lewat skrip
`palmgrade`, dan AutoGrade diuji dari checkout `~/autograde-test` lewat `make`. Keduanya memakai
nama container yang sama dan berebut kamera: **jangan jalankan `palmgrade` selagi AutoGrade
jalan**. Spek terukur (disk, GPU, NIC) ada di skill `.claude/skills/spek-pc-pabrik/`. Akses
hanya lewat AnyDesk, tidak ada SSH masuk.

## 6. Operasional Harian

### 6.1 Perintah `make`

| Perintah | Kapan |
|---|---|
| `make start` / `make down` | nyalakan / matikan 4 container tanpa rebuild |
| `make restart` | setelah ubah **kode** (kode di-bind-mount). **Tidak** membaca ulang `.env` |
| `make start` | setelah ubah **`.env`** atau `docker-compose.override.yml` (`up -d` membuat ulang container yang setelannya berubah; reboot PC juga tidak menerapkan `.env` baru) |
| `make up` | setelah ubah `requirements.txt`, `Dockerfile`, atau SDK |
| `make ps` | status container |
| `make logs` / `make logs-1` / `make logs-console` | tail log semua / satu line / konsol |
| `make up-console` / `make restart-console` | konsol saja; `restart-console` wajib setelah ubah Python konsol |
| `make up-1` / `up-2` / `up-3` | satu line saja |
| `make operator-docker AKSI=daftar\|tambah\|matikan\|role ROLE=support` | akun lokal konsol di pabrik (`make operator` di laptop) |
| `make hash-sandi` | hash dua akun bawaan saat pasang PC |
| `make build-engine` | engine TensorRT, sekali per GPU (auto-skip kalau sudah ada) |
| `make kiosk` | konsol layar penuh |
| `make rekonsiliasi-truk-docker [TULIS=1]` | OPS-2, sekali saat pasang di PC ber-data lama |
| `make demo [HARI=3]` | data contoh. **Hanya laptop/demo, jangan pernah di PC pabrik** |
| `make demo-reset` | hapus data demo lama lalu isi ulang bersih (`AKSI=reset` juga masih jalan) |
| `make demo-off` | hapus data demo, berhenti di situ (tidak mengisi ulang seperti `demo-reset`). Data sungguhan tidak disentuh — jalankan sesudah showcase, sebelum uji coba. AutoERP punya tiga perintah nama sama |
| `make rebuild-clean` | build ulang tanpa cache, hanya kalau cache dicurigai rusak |

### 6.2 Memperbarui kode di pabrik

```bash
cd ~/autograde
git checkout config/camera/hikrobot.mfs   # kalau .mfs sempat diubah untuk uji; berkas ini dilacak git
git pull
make restart                              # atau make up kalau dependency berubah
```

**Rilis lewat tag dibuka lagi 2026-09-18.** Tag `vX.Y.Z` menerbitkan image ke GHCR; PC pabrik
menariknya sendiri (`palmgrade pull vision`) — tidak ada deploy otomatis, karena PC pabrik tidak
punya alamat publik.

Nama image sekarang **`ghcr.io/delta-anugrah/autograde`** — satu nama, nama lama
`palmgrade-vision` sudah dicabut.

⚠️ **Sebelum tag rilis pertama, `.env` PC pabrik harus diedit dulu.** Di
`/opt/palmgrade/vision/.env`, ubah `PALMGRADE_VISION_IMAGE` ke nama baru. Kalau tag diterbitkan
lebih dulu, `palmgrade pull vision` menjawab "sudah terbaru" selamanya dan PC itu berhenti menerima
pembaruan **tanpa satu pun pesan error** — baru ketahuan saat ada yang bertanya kenapa versinya
tidak naik-naik.

### 6.3 Cek kesehatan

| Cara | Yang dilihat |
|---|---|
| tab **Diagnostik** (support) | worker, kamera, fps, GPU, PLC per line |
| `curl localhost:8001/health/detail` | `camera_connected`, `gpu_available`, `current_assignment_id`, `outbox_pending`, dan **`capture_save_dropped` + `tp_telat` yang harus NOL** |
| tab **Antrean ERP** | pesan yang belum sampai ke AutoERP dan sebabnya |
| tab **Log** | ERROR/WARNING 180 hari, bertahan lewat restart |
| `docker logs ripe_line_1 \| grep 'Batch tick'` | progres unggah ke R2 (tidak ada di `/health`) |

`outbox_pending` naik terus = konsol tidak menjawab (cek `BACKEND_URL`). Angka itu **tidak**
menggambarkan unggahan ke cloud.

### 6.4 Disk dan arsip

`artifacts/line-N/results/<tanggal>/` berisi JSON per janjang (datar) dan folder per kunjungan
truk `HHMMSS_plat_assign8/` dengan `bbox/` (bergambar kotak, naik ke R2), `clean/` (polos, untuk
latih ulang model, tidak diunggah), dan `thumb/` (400 px, naik ke R2). Retensi menghapus
ketiganya setelah item `done` lewat `UPLOAD_RETENTION_DAYS`, dan lebih awal kalau sisa disk di
bawah `UPLOAD_DISK_MIN_FREE_GB`. **Arsip lokal bukan arsip permanen**; R2 yang permanen.
Angka kapasitas terukur (±178 KB per gambar, tiga line satu disk): skill `spek-pc-pabrik`.

## 7. Kalau Ada Masalah

| Gejala | Sebab yang biasa | Tindakan |
|---|---|---|
| Kartu line "Kamera tidak tersambung" padahal line jalan | tulisan itu muncul kalau **browser** gagal memuat stream `http://<host konsol>:800N/api/video_feed`; sebabnya line di port lain, stream mati, atau port line tidak terjangkau dari PC yang membuka konsol | buka `http://<host>:800N/health/detail` dari browser yang sama; `make line N=…` (bukan port bebas); tab Diagnostik untuk status kamera sesungguhnya |
| Janjang line 2 mendarat di kartu line 1 | konsol mencocokkan event lewat `machine_id`, bukan port; `MACHINE_ID` kembar | cek `LINE_N_MACHINE_ID` berbeda per line (`make line N=2` sudah mengaturnya) |
| Layar nol, log line "Outbox delivery failed … HTTP 404" | `BACKEND_URL` menunjuk port yang salah (8000 vs 8100) | betulkan `.env`, `make start` |
| Line `OFFLINE`, `camera_connected: false` | MVS masih membuka kamera; kabel/switch; IP kamera bukan `.10/.11/.12` | tutup MVS; cek LED link; `ip -br addr`; kamera dicoba ulang otomatis tanpa restart |
| Frame hitam di malam hari | gelap, `Gain 0`, bukan bug | pencahayaan; jangan ubah kode |
| fps tidak berubah walau `CAMERA_FPS` diganti | Hikrobot membaca laju dari `.mfs` | ubah `config/camera/hikrobot.mfs`, `make restart` |
| `backend=pt` di log, bukan `tensorrt` | engine belum dibangun / GPU beda | `make build-engine` lalu `make restart` |
| `gpu_available: false` | NVIDIA Container Toolkit belum benar | ulangi §5.4, tes `nvidia-smi` di container |
| Login 401 "belum masuk" | sesi 12 jam habis | masuk lagi |
| 403 "menu ini untuk akun support" | akun berperan operator membuka tab support | `make operator-docker AKSI=role ROLE=support` |
| Log konsol: "Tidak ada akun dengan peran support" | `.env` dibuat sebelum fitur peran ada | perintah yang sama di atas |
| Akun bawaan ditolak saat start | hash di `.env` terpotong karena `$` | tulis `$$` untuk tiap `$` |
| Tab Antrean ERP menumpuk, sebab 4xx | pesan **ditolak** ERP (field tidak dikenal, versi ERP lama, 417) | betulkan di ERP, lalu **Kirim Ulang** |
| Tab Antrean ERP menumpuk, sebab jaringan/5xx | ERP **tidak terjangkau**; backoff 30 dtk → 1 jam | tunggu, atau Kirim Ulang setelah ERP pulih |
| Plat yang sama muncul dua baris di tab Truk | `ERP_URL` diisi sebelum OPS-2 | jalankan checklist OPS-2 (§5.8) |
| Unggah ke R2 berhenti tanpa error | `R2_BUCKET` kosong, atau JSON sidecar dipindah ke subfolder | isi R2; JSON wajib datar di folder tanggal |
| Disk penuh, grading berhenti tersimpan | penjaga disk mati (`UPLOAD_DISK_MIN_FREE_GB=0`) atau Docker menumpuk image lama | `docker system prune`; kembalikan penjaga ke 20 |
| Laptop: `make console` terasa memakai kode lama | port 8100 masih dipegang proses lama | cari pid-nya dengan `lsof -ti:8100`, matikan, jalankan ulang |
| Laptop: `make up` gagal "MVS SDK not found" | memang, target Docker untuk Linux + GPU | pakai `make console` / `make line` |
| Kamera "tidak terjawab" saat E2E di macOS | `CONSOLE_LINE_HOST=http://localhost` → IPv6 | ganti `http://127.0.0.1` |

Dua jebakan umum di balik "setelan `.env` tidak berlaku": **env var proses menang atas
`.env`** (`load_dotenv(override=False)`; cek `/health/detail`), dan `.env` yang diubah baru
berlaku setelah `make start`, bukan `make restart` atau reboot.

Kalau gejalanya tidak ada di tabel: tab Log dulu, lalu `make logs-<line>`, lalu `CLAUDE.md`
§ Critical Rules untuk memahami aturan yang mungkin tersentuh.

## 8. Aturan yang Tidak Boleh Dilanggar

1. **Disk dulu, baru jaringan.** Worker penilaian tidak pernah POST; antrean yang bicara.
2. **`BACKEND_URL` selalu konsol lokal.** Pernah diarahkan ke cloud dan produksi menerima 1.098 event uji.
3. **Label ACC / REJ**, bukan MATANG/MENTAH. Nilai lain ditolak 400. Angka ini menentukan pembayaran.
4. **Neto dihitung, tidak dipercaya.** Tanggal kerja dihitung saat masuk dengan `FACTORY_TZ`.
5. **Konsol tidak memindai folder.** Semua yang di layar berasal dari `console.db`.
6. **`console.html` nol referensi `https://`**, tanpa CDN, tanpa build step. Harus terbuka saat internet mati.
7. **Per janjang tetap di pabrik.** Yang ke AutoERP hanya rekap per kunjungan; tautan detail (`detail_url`) boleh, foto ribuan tidak.
8. **`make demo` jangan pernah di PC pabrik.** Dia menulis ke database yang sama dengan milik operator.
9. **Nama image GHCR tetap `palmgrade-vision`.** Mengganti nama membuat PC pabrik berhenti update tanpa pesan.
10. **`.mfs` dilacak git.** `git checkout config/camera/hikrobot.mfs` sebelum `git pull`.
11. **Unit test tidak boleh memuat torch, OpenCV, atau hardware.** CI jalan tanpa GPU.
12. **Alur kode:** branch baru → PR squash ke `staging` → PR merge commit ke `main`. Judul dan isi PR bahasa Inggris; commit boleh Indonesia; tanpa `Co-Authored-By`. Tidak ada tag rilis selama Opsi B.

## 9. Peta Repositori dan Dokumen

| Butuh | Lihat |
|---|---|
| Peta aturan padat untuk AI agent | `CLAUDE.md` (= `AGENTS.md`) |
| Pengantar 20 menit untuk orang baru | `docs/ONBOARDING.md` (+ PDF) |
| Alur rinci, worker, invariant beserta alasannya | `docs/overview.md` |
| Batas antar lapisan kode | `docs/architecture.md` |
| Daftar endpoint, event, variabel lingkungan | `docs/backend-overview.md`, `README.md` |
| Pasang PC pabrik, langkah panjang dengan MVS | `docs/SETUP.md` |
| Spesifikasi dan setelan kamera, kenapa `.mfs` menang | `docs/camera-spec.md` |
| PLC: alamat M, heartbeat, commissioning | `docs/plc-mc-handoff.pdf`, `docs/plc-integration.md`, skill `plc-mc-protocol` |
| Spek terukur PC Lampung | skill `spek-pc-pabrik` |
| Kontrak dengan AutoERP (yang harus dicocokkan dulu) | `../autoerp/docs/autograde-integration.md` |
| Rekonsiliasi truk OPS-2, checklist PC pabrik | `../docs/runbooks/` di workspace `sawit` |
| Sisa pekerjaan | `../docs/TODO-AUTOGRADE-AUTOERP.md` |

Struktur kode di `src/palmgrade/`: `routes/` (HTTP) → `controllers/` → `services/` (logika) →
`repositories/` (I/O berkas dan SQLite); `domain/` aturan murni tanpa I/O; `pipelines/` YOLO;
`workers/` thread dan task latar; `integrations/` kamera, R2, ERP, outbox; `plc/` MC Protocol/Modbus;
`license/`; `static/console.html` layar operator.

## 10. Glosarium

| Istilah | Arti |
|---|---|
| **Janjang / TBS** | satu tandan buah sawit; TBS = tandan buah segar |
| **ACC / REJ** | diterima / ditolak; verdict biner yang dibayar dan yang memicu piston |
| **JK / TP** | janjang kosong (→ REJ) / tangkai panjang (penanda, bukan verdict) |
| **Line** | satu conveyor + satu kamera + satu container |
| **Assignment** | penugasan truk ke line; janjang di antara Tugaskan dan Lepas milik truk itu |
| **Kunjungan (visit)** | satu truk dari timbang masuk sampai timbang keluar; satu tiket timbangan |
| **Bruto / tara / neto** | berat masuk / berat keluar / selisih yang dibayar |
| **Hari kerja (`work_date`)** | tanggal operasional menurut `FACTORY_TZ`, dihitung saat data masuk |
| **Outbox** | antrean SQLite di disk untuk kiriman yang belum sampai (ke konsol, ke ERP, ke R2) |
| **`.mfs`** | berkas setelan kamera Hikrobot (fps, exposure, gain); dikirim ke kamera saat tersambung |
| **Engine TensorRT** | model yang dikompilasi untuk satu GPU; opsional, hanya mempercepat |
| **OPS-2** | rekonsiliasi truk kembar saat memasang di PC yang punya data stack lama |
| **Opsi B** | arsitektur dua kotak: AutoGrade di pabrik, AutoERP di server; tanpa `palmgrade-api` |

## Riwayat Revisi

| Versi | Tanggal | Perubahan |
|---|---|---|
| 1.0 | 17 September 2026 | Terbitan pertama. Dicocokkan dengan kode `staging` (`a559427`): konsol dengan login email+sandi, lima tab support, scan QR dua gerbang, Setelan grading, seeder demo, detail grading via R2. |
