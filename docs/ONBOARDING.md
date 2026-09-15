---
judul: Panduan Onboarding AutoGrade
subjudul: Gambaran sistem, alur data, struktur repositori, dan aturan kerja bagi anggota tim baru — manusia maupun AI agent.
label: Internal · Tim Engineering
versi: "1.1"
tanggal: 15 September 2026
klasifikasi: Internal — tidak untuk dibagikan ke pihak luar
pemilik: Tim Engineering AutoGrade
sorotan: Sistem = Kamera · AI · Konsol operator; Integrasi = AutoERP · PLC · Timbangan; Pembaca = Developer · AI / Vision · IoT
---

# Panduan Onboarding AutoGrade

Dokumen ini ditujukan bagi anggota tim yang baru pertama kali bekerja dengan repositori
`autograde`. Setelah membacanya — sekitar 20 menit — pembaca diharapkan memahami apa yang
dikerjakan sistem ini, di mana setiap bagian kodenya berada, dan aturan mana yang tidak boleh
dilanggar.

> **Catatan untuk AI agent (Codex, Claude).** Dokumen ini adalah titik masuk. `CLAUDE.md` berisi
> ringkasan aturan yang lebih padat, dan `docs/overview.md` berisi rincian teknis. Dokumen ini
> memberi konteks yang menghubungkan keduanya.

## 1. Gambaran Umum

AutoGrade adalah sistem penilaian mutu tandan buah segar (TBS) kelapa sawit berbasis kamera dan
kecerdasan buatan, yang dipasang di pabrik kelapa sawit (PKS).

Truk pemasok membawa buah sawit — disebut **janjang** atau tandan — ke pabrik. Buah dituang ke
conveyor dan melintas di bawah kamera. Kamera dan model AI menilai setiap janjang: layak diterima
(**ACC**) atau ditolak (**REJ**). Hasil penilaian ini menjadi dasar pembayaran kepada pemasok.

Sebelumnya penilaian dilakukan secara manual oleh petugas sortasi, sehingga hasilnya bergantung
pada orang, jam kerja, dan tingkat kelelahan. AutoGrade membuat penilaian konsisten dan
terdokumentasi, lengkap dengan foto setiap janjang sebagai bukti bila ada keberatan dari pemasok.

**Tiga fungsi utama AutoGrade:**

1. Menilai setiap janjang di tiga conveyor (disebut **line**), masing-masing dengan satu kamera.
2. Menyediakan layar operator: truk yang sedang dibongkar di tiap line, jumlah janjang, dan berat
   timbangan.
3. Mengirim **rekap per kunjungan truk** ke AutoERP, sistem yang mengelola pembukuan dan pembayaran.

**Di luar cakupan AutoGrade:** harga, potongan, pembayaran, dan faktur. Seluruhnya dikelola
AutoERP. AutoGrade berperan sebagai sensor dan layar operasional.

## 2. Arsitektur: Dua Sistem Terpisah

```diagram:arsitektur Pembagian peran AutoGrade di pabrik dan AutoERP di cloud
┌─ PC pabrik (dapat beroperasi offline) ─┐      ┌─ Server cloud ──────────┐
│  AutoGrade  ← repositori ini           │      │  AutoERP (fork ERPNext) │
│  Python · FastAPI · YOLO · SQLite      │─────▶│  Frappe · MariaDB       │
│  3 kamera · PLC · layar operator       │      │  Layar backoffice       │
└────────────────────────────────────────┘      └─────────────────────────┘
   data per janjang + foto tetap di pabrik        hanya menerima rekap per truk
```

Pemisahan ini disengaja, dengan dua alasan:

- **Koneksi internet di pabrik tidak dapat diandalkan.** Seluruh kebutuhan operator harus tetap
  berfungsi ketika internet terputus, sehingga semuanya berjalan di PC pabrik.
- **ERP adalah buku besar, bukan penyimpan kejadian.** Mengirim ribuan data janjang per hari ke
  ERP membebaninya tanpa manfaat. ERP cukup menerima ringkasan per truk: berat dan persentase buah
  yang ditolak. Foto dan data per janjang tetap di pabrik sebagai bukti.

**Arah komunikasi hanya satu: pabrik → ERP.** ERP tidak pernah menghubungi pabrik, karena PC
pabrik tidak menerima koneksi masuk dari internet.

## 3. Komponen yang Berjalan

Satu image Docker dijalankan empat kali dengan peran berbeda:

| Container | Port | Fungsi | Dampak bila berhenti |
|---|---|---|---|
| `ripe_line_1` | 8001 | kamera dan AI line 1 | line 1 berhenti menilai; line lain tetap berjalan |
| `ripe_line_2` | 8002 | kamera dan AI line 2 | sama seperti di atas |
| `ripe_line_3` | 8003 | kamera dan AI line 3 | sama seperti di atas |
| `palmgrade_console` | 8000 | layar operator (`/console`) | layar operator mati; line tetap menilai dan menyimpan |

Line dan konsol memakai **modul aplikasi yang berbeda**: `main.py` untuk line (memuat torch,
OpenCV, dan driver kamera) dan `console_main.py` untuk konsol, yang **tidak boleh** mengimpor
torch maupun OpenCV. Tujuannya satu: gangguan pada kamera tidak boleh mematikan layar operator.

**Layar operator terkunci.** Sampai ada yang masuk dengan **email dan sandi**, seluruh layar
tertutup gerbang dan seluruh API konsol menjawab 401. Akun datang dari dua tempat: dibuat di
AutoERP (DocType `AutoGrade Operator`, ikut turun bareng master data) atau dibuat lokal di PC itu
dengan `make operator` — akun bawaan dan akun support, supaya pabrik yang belum pernah dapat
internet tetap bisa dibuka. Keduanya diperiksa di pabrik, jadi login tetap jalan saat internet
mati: yang ikut turun itu hash sandinya, bukan sandinya. Tidak ada halaman web untuk membuat akun.

## 4. Alur Data: Satu Janjang

Bagian ini adalah inti sistem.

```diagram:alur-janjang Perjalanan data satu janjang, dari kamera sampai AutoERP
kamera → FrameCaptureWorker → antrean → FrameProcessingWorker → disk + outbox.db
                                                                     │
                                   DisplayWorker → MJPEG             ▼
                                   (layar langsung)          OutboxRetryWorker
                                                                     │
                                                                     ▼
                                                    konsol (SQLite console.db)
                                                                     │
                                            rekap per truk ──────────┘──▶ AutoERP
```

1. **Pengambilan frame.** `FrameCaptureWorker` mengambil frame dari kamera dengan laju tetap. Laju
   itu ditentukan oleh kamera sendiri (lihat bagian 8). Frame masuk ke antrean yang **membuang
   frame terlama** saat penuh, sehingga model selalu memproses gambar terbaru.
2. **Penilaian.** `FrameProcessingWorker` menjalankan YOLO dan ByteTrack. ByteTrack memastikan satu
   janjang yang terlihat di banyak frame berturut-turut **dihitung satu kali**. Janjang dihitung
   ketika memasuki area ROI di tengah conveyor.
3. **Simpan ke disk sebelum mengirim.** Ini aturan terpenting di repositori ini. Worker penilaian
   **tidak pernah** berkomunikasi lewat jaringan: ia menulis gambar WebP dan JSON ke
   `artifacts/results/`, lalu menambahkan satu baris ke `outbox.db`.
4. **Pengiriman lewat antrean.** `OutboxRetryWorker` memeriksa `outbox.db` setiap detik dan
   mengirimnya ke konsol. Bila konsol sedang tidak aktif, data menunggu di antrean tanpa hilang.
5. **Pencatatan di konsol.** Konsol menyimpan data ke `state/console.db` (SQLite). Layar operator
   membaca dari indeks ini dan **tidak pernah** memindai folder, karena pemindaian berkala akan
   menyita I/O yang dibutuhkan proses penilaian.
6. **Unggah berkala ke cloud.** `BatchUploadWorker` mengunggah foto ke Cloudflare R2 dan datanya ke
   API cloud setiap jam. Jalur ini terpisah dari langkah 4 dan boleh tertunda.

Rancangan ini mengikuti kondisi pabrik: listrik padam, internet terputus, dan container dimulai
ulang adalah kejadian rutin. Karena data selalu tersimpan di disk lebih dulu, gangguan hanya
menyebabkan keterlambatan, bukan kehilangan data.

## 5. Alur Kunjungan Truk

Data per janjang adalah rincian. Yang masuk ke pembukuan adalah **kunjungan truk**:

| # | Kejadian | Proses di sistem |
|---|---|---|
| 1 | Truk bermuatan naik timbangan | timbangan → konsol → AutoERP, tahap `gate`: berat bruto dan jam masuk |
| 2 | Operator memasang truk ke line | konsol memberi tahu line: janjang berikutnya dicatat atas nama truk ini |
| 3 | Buah dituang dan dinilai | data janjang tersimpan di `console.db`; AutoERP belum menerima apa pun |
| 4 | Operator melepas truk dari line | konsol → AutoERP, tahap `grading`: total, ACC, REJ, dan persentasenya |
| 5 | Truk kosong naik timbangan | konsol → AutoERP, tahap `departed`: berat tara dan jam keluar |
| 6 | AutoERP memproses | neto = bruto − tara, potongan, harga, lalu Purchase Receipt |

**Satu kunjungan dikirim sebagai satu pesan `upsert_visit`, sebanyak tiga kali** sesuai tahapannya.
Setiap kiriman **menggantikan** bagian yang dibawanya. Karena itu bagian yang belum tersedia **tidak
dikirim sama sekali** — bagian kosong akan menghapus data yang sudah ada di AutoERP.

Janjang yang ditolak dinaikkan kembali ke truk dan ikut ditimbang saat truk keluar. Beratnya masuk
ke tara, sehingga otomatis tidak ikut dibayar.

## 6. Struktur Repositori

### Folder utama

| Folder | Isi | Kapan dibuka |
|---|---|---|
| `src/palmgrade/` | seluruh kode Python | setiap perubahan perilaku |
| `tests/` | unit, e2e, integration | setiap perubahan perilaku — test ditulis **lebih dulu** |
| `docs/` | dokumen teknis, termasuk dokumen ini | saat membutuhkan rincian |
| `scripts/` | kiosk, data contoh, build engine, smoke test, pembuat PDF | sesekali |
| `config/camera/` | `hikrobot.mfs` — setelan kamera, termasuk **fps** | saat mengubah fps atau exposure |
| `sdk/` | SDK kamera Hikrobot (MVS), disertakan agar build Docker tidak butuh internet | hampir tidak pernah |
| `models/release/` | berkas model YOLO (`.pt`) | saat mengganti model |
| `engines/` | engine TensorRT hasil build per GPU | tidak diubah manual; diisi `make build-engine` |
| `images/` | `sample_sawit.jpg`, gambar contoh untuk `CAMERA_TYPE=photo` | saat menguji tanpa kamera |
| `artifacts/` | hasil runtime: foto, JSON, dan `outbox.db` | saat memeriksa bukti penilaian |
| `state/` | `console.db`, `erp_outbox.db`, `upload_manifest.db` | saat memeriksa isi antrean |

Isi `models/`, `engines/`, `artifacts/`, dan `state/` **tidak disimpan di git**: ukurannya besar,
berbeda di tiap mesin, dan sebagian bersifat rahasia.

### Isi folder src/palmgrade

Kode disusun berlapis, dan urutan lapisannya **tidak boleh dilompati**:
`routes → controllers → services → repositories / pipelines / integrations`.

| Folder | Tanggung jawab | Contoh isi |
|---|---|---|
| `core/` | setelan dan perakitan dependensi | `config.py` (seluruh env var), `dependencies.py`, `constants.py` |
| `routes/` | daftar endpoint HTTP saja | `console.py`, `internal.py`, `health.py` |
| `controllers/` | menerima request dan meneruskannya ke service | `capture_controller.py` |
| `services/` | alur bisnis | `console_service.py`, `erp_queue.py` |
| `repositories/` | baca-tulis disk dan SQLite | `console_repository.py`, `capture_repository.py` |
| `pipelines/` | inferensi YOLO | `model_registry.py`, `realtime_inspection_pipeline.py` |
| `workers/` | proses latar yang berjalan terus | capture, processing, display, outbox, batch upload, worker ERP |
| `integrations/` | sistem luar | `camera/`, `erp/`, `notifications/`, `storage/`, `upload/`, `outbox/`, `scheduler/` |
| `domain/` | aturan murni tanpa I/O | `working_day.py`, `ffb_source.py`, `vision_event.py`, `plate.py` |
| `schemas/` | bentuk request dan response (Pydantic) | `internal_schema.py` |
| `plc/` | Modbus-TCP ke PLC; berdiri sendiri, nonaktif secara bawaan | — |
| `license/` | penjaga langganan (Ed25519), opsional | `manager.py`, `guard.py` |
| `static/` | `console.html` — layar operator dalam **satu berkas**, tanpa build dan tanpa CDN | — |

Dua folder yang sering disalahpahami:

- **`domain/` berisi aturan yang harus benar tanpa bergantung pada apa pun.** Isinya fungsi murni:
  menerima nilai dan mengembalikan nilai, tanpa akses disk maupun HTTP. Bagian ini paling mudah
  diuji sekaligus paling mahal bila keliru — contohnya `working_day.py`, yang menentukan satu shift
  malam masuk ke tanggal kerja yang mana.
- **`console.html` sengaja dibuat satu berkas tanpa framework.** Layar ini harus tetap berfungsi
  saat internet terputus; halaman yang memuat library dari CDN akan kosong tepat pada saat paling
  dibutuhkan.

### Berkas di akar repositori

| Berkas | Fungsi |
|---|---|
| `Makefile` | **seluruh perintah dijalankan lewat sini** — `make up`, `make restart`, `make logs-1`, `make console` |
| `Dockerfile` | resep image (torch CPU untuk pengembangan, CUDA untuk pabrik) |
| `docker-compose.yml` | empat service: tiga line dan konsol |
| `docker-compose.override.yml` | penyesuaian khusus satu mesin; dibaca compose **otomatis** dan tidak masuk git |
| `.env.example` | contoh seluruh setelan; `.env` yang sebenarnya tidak masuk git |
| `requirements.txt` | dependency Python dengan versi terkunci |
| `CLAUDE.md` | ringkasan aturan untuk AI agent |
| `README.md` | cara memasang dan menjalankan secara lengkap |

## 7. Menjalankan Sistem

### Di Mac — pengembangan konsol

```bash
cd autograde
make operator         # sekali: akun lokal (tanya email + nama + sandi)
make console          # http://127.0.0.1:8100/console
```

Konsol berjalan native, tanpa Docker, di port 8100 — port 8000 dipakai AutoERP lokal. Target
`make up` dan `make up-dev` **tidak** dipakai di Mac karena membutuhkan SDK kamera dan GPU NVIDIA.

Menjalankan test:

```bash
.venv/bin/pytest tests/unit        # jangan tambahkan -q; pyproject.toml sudah memasangnya
.venv/bin/ruff check <daftar berkas di .github/workflows/ci.yml>
```

### Di PC pabrik — Linux dengan GPU

```bash
make up              # build image, bangun engine TensorRT, jalankan tiga line dan konsol
make operator-docker # sekali: akun operator untuk login konsol (di dalam container)
make ps          # status container
make logs-1      # log line 1
make restart     # setelah mengubah kode (kode di-bind-mount, tanpa rebuild)
make start       # setelah mengubah .env atau docker-compose.override.yml
```

Pedoman singkat: **ubah kode → `make restart`; ubah setelan → `make start`; ubah dependency atau
Dockerfile → `make up`.**

## 8. Hal yang Wajib Diwaspadai

Setiap butir berikut pernah menyebabkan kehilangan waktu berjam-jam.

1. **Laju frame kamera hanya diatur di satu tempat: `config/camera/hikrobot.mfs`.** Berkas ini
   dikirim ke kamera setiap kali terhubung, lalu lajunya dibaca kembali dari kamera. `CAMERA_FPS`
   di `.env` hanya cadangan untuk sumber yang tidak dapat melaporkan lajunya (webcam, berkas video).
2. **Port 8000 di Mac adalah AutoERP, bukan konsol.** Konsol di Mac selalu di port 8100. Di PC
   pabrik, konsol di dalam Docker memang di port 8000.
3. **`BACKEND_URL` wajib menunjuk API lokal.** Pernah diarahkan ke API cloud, dan produksi menerima
   sekitar 1.098 event uji dalam sehari.
4. **Label produksi adalah `ACC` dan `REJ`**, bukan `MATANG` atau `MENTAH`. Nilai lain ditolak
   dengan status 400 saat diterima, karena angka ini menentukan pembayaran.
5. **`neto_kg` selalu dihitung ulang, tidak pernah diterima apa adanya.** Neto yang berbeda lebih
   dari 1 kg dari bruto − tara ditolak. Dua sumber angka yang diam-diam berbeda adalah cara paling
   mudah untuk salah bayar berbulan-bulan.
6. **Tanggal kerja dihitung saat data diterima, lalu disimpan.** Pabrik beroperasi sekitar 20 jam
   sehari dan melewati tengah malam; menghitung tanggal dari waktu pembacaan akan memecah satu shift
   menjadi dua hari.
7. **Nama image GHCR tetap `palmgrade-vision`** walaupun repositori sudah bernama `autograde`.
   Mengganti nama image membuat PC pabrik terus meminta nama lama, dan pembaruan berhenti tanpa
   pesan error. Ketentuan ini dijaga oleh test.
8. **Berkas `.mfs` di PC pabrik dilacak git.** Jalankan `git checkout config/camera/hikrobot.mfs`
   sebelum `git pull` bila berkas itu sempat diubah untuk pengujian.

## 9. Aturan Kerja Tim

- **Setiap perubahan melalui pull request.** Branch baru → PR *squash* ke `staging` → PR *merge
  commit* ke `main`. Tidak ada commit langsung ke `staging`.
- **Judul dan isi PR ditulis dalam bahasa Inggris.** Pesan commit boleh berbahasa Indonesia.
- **Test ditulis sebelum kode.** Pastikan test gagal dengan alasan yang benar, baru perbaiki
  kodenya. Test yang tidak pernah gagal tidak membuktikan apa pun.
- **Unit test tidak boleh memuat torch, OpenCV, atau hardware.** CI berjalan tanpa GPU; pengujian
  yang membutuhkan komponen berat ditempatkan di `tests/e2e/`.
- **Komentar kode ditulis dalam bahasa Inggris, singkat, dan menjelaskan alasan** — bukan mengulang
  apa yang sudah terbaca dari kodenya.
- **Commit tidak mencantumkan `Co-Authored-By` atau referensi AI apa pun.**
- **Selama Opsi B berjalan tidak ada deploy dan tidak ada tag rilis `vX.Y.Z`.**

## 10. Rujukan Dokumen

| Kebutuhan | Dokumen |
|---|---|
| Ringkasan aturan untuk AI agent | `CLAUDE.md` |
| Alur rinci, diagram, dan seluruh invariant beserta alasannya | `docs/overview.md` |
| Batas antar lapisan kode | `docs/architecture.md` |
| Daftar endpoint, event, dan variabel lingkungan | `docs/backend-overview.md` |
| Pemasangan dari nol di PC pabrik | `docs/SETUP.md` |
| Spesifikasi dan setelan kamera | `docs/camera-spec.md` |
| Integrasi PLC / ODOT dan urutan commissioning | `docs/plc-integration.md` |
| Kontrak integrasi dengan AutoERP | `../autoerp/docs/autograde-integration.md` |
| Status pekerjaan terkini | `../docs/PROGRESS-AUTOGRADE-AUTOERP.md` |
| Membuat ulang PDF dokumen ini | `scripts/md_to_pdf.py` |

## 11. Glosarium

| Istilah | Arti |
|---|---|
| **TBS** | Tandan Buah Segar — buah sawit yang baru dipanen |
| **Janjang / tandan** | satu buah sawit utuh; satuan yang dinilai kamera |
| **PKS** | Pabrik Kelapa Sawit |
| **ACC / REJ** | diterima / ditolak; hasil penilaian AI |
| **Tangkai panjang** | buah diterima tetapi tangkainya terlalu panjang — menambah berat tanpa menambah minyak |
| **Mentah** | buah belum matang dengan kandungan minyak rendah |
| **Brondolan** | buah lepasan yang rontok dari tandan |
| **Line** | satu conveyor dengan satu kamera; terdapat tiga line |
| **Bruto / tara / neto** | berat truk bermuatan / truk kosong / selisihnya, yaitu berat yang diterima pabrik |
| **Sortasi** | proses penilaian mutu buah |
| **Potongan** | pengurangan nilai pembayaran karena mutu buah |
| **Sumber TBS** | Internal (kebun sendiri) atau External (pembelian dari pemasok) |
| **Kunjungan** | satu siklus truk: masuk, bongkar, keluar |
| **Outbox** | antrean di disk untuk data yang belum berhasil terkirim |

## 12. Langkah Pertama

1. Baca bagian **Critical Rules** di `CLAUDE.md`.
2. Buat operator dengan `make operator`, jalankan `make console`, lalu masuk dengan email dan
   sandi itu dan coba layar operator.
3. Buka `src/palmgrade/workers/frame_processing_worker.py` — di sinilah janjang diubah menjadi angka.
4. Buka `src/palmgrade/domain/working_day.py` — contoh aturan murni yang ringkas di `domain/`.
5. Jalankan `.venv/bin/pytest tests/unit` dan pastikan seluruhnya lolos sebelum mulai mengubah kode.

Bila menemukan hal yang membingungkan atau tampak keliru, **catat sebagai temuan** — jangan
dianggap "memang begitu".

## Riwayat Revisi

| Versi | Tanggal | Perubahan |
|---|---|---|
| 1.2 | 15 September 2026 | Login email + sandi: akun dari AutoERP (`AutoGrade Operator`) atau lokal, diverifikasi offline |
| 1.1 | 15 September 2026 | Login konsol (Fase 4): gerbang PIN, akun lokal lewat `make operator` |
| 1.0 | 14 September 2026 | Rilis pertama |
