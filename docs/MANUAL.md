---
judul: Manual AutoGrade
subjudul: Cara pakai, daftar fitur, pemasangan dari nol, operasional harian, dan penanganan masalah, untuk orang yang ikut memegang AutoGrade.
label: Internal · Tim Engineering
versi: "2.1"
tanggal: 1 Oktober 2026
klasifikasi: Internal, tidak untuk dibagikan ke pihak luar
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
| konsol (`palmgrade_console`; di Lampung `autograde-console-1`) | 8100 image produksi, 8000 kalau dipasang dari source (`make up`) | layar operator `/console` | layar mati; line tetap menilai dan menyimpan, kiriman menunggu di antrean |

Line memakai `main.py` (memuat torch, OpenCV, driver kamera). Konsol memakai `console_main.py`
yang **tidak** memuat keduanya, supaya gangguan kamera tidak mematikan layar operator.

**Model AI** `models/release/best.pt` mengenali 4 kelas: `Ripe`, `Unripe`, `JK` (janjang kosong),
`TP` (tangkai panjang). Verdict diturunkan dari kelas: `Ripe` → ACC; `Unripe` dan `JK` → REJ;
`TP` cuma penanda, bukan verdict. Objek lebih kecil dari `MINIMUM_SIZE` piksel² otomatis REJ.
Dua buah bertumpuk dalam ROI di satu frame → semuanya REJ.

**Kapan janjang difoto.** Saat kotaknya **menyentuh garis capture**, garis biru bertanda
`CAPTURE` di layar line, diatur dari tab Setelan. ROI menjawab *di mana* (bagian gambar yang
dianggap conveyor), garis menjawab *kapan*. Janjang difoto apa adanya, ada tangkai panjang atau
tidak. Tangkai panjang dipasangkan ke janjang **terdekat**; tangkai yang baru muncul sesudah
janjangnya difoto tidak ikut, dan jumlahnya terbaca di tab Status (bagian Diagnostik) sebagai `tp_telat`.
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
   tidak berhenti menunggu disk: satu janjang memakan sekitar setengah detik untuk disimpan.
3. `OutboxRetryWorker` mengirim ke konsol tiap detik. Konsol mati = data menunggu, tidak hilang.
4. Konsol menyimpan ke `state/console.db`. Layar membaca dari sini, **tidak pernah memindai folder**.
5. Tiap jam `BatchUploadWorker` mengunggah foto ke Cloudflare R2 (kalau `R2_BUCKET` diisi).
6. Saat truk dilepas dari line, konsol mengirim rekap kunjungan ke AutoERP lewat antrean sendiri.

Listrik padam, internet putus, container restart: semuanya cuma bikin **terlambat**, bukan hilang.

## 3. Cara Pakai Konsol Operator

Layar: `http://localhost:8100/console` di PC pabrik yang memakai image produksi (Lampung) dan di laptop developer (`make console`); `:8000` kalau PC dipasang dari source dengan `make up`. Satu berkas
HTML tanpa CDN dan tanpa webfont, jadi tetap terbuka saat internet mati. Dwibahasa ID/EN, tema
terang/gelap, pilihan tersimpan di browser.

### 3.1 Masuk

Layar terkunci sampai ada yang masuk dengan **email + sandi**. Tombol nama di gerbang cuma
mengisi kolom email; sandi tetap wajib. Sesi 12 jam, tidak diperpanjang otomatis.

| Sumber akun | Dibuat di | Reset sandi |
|---|---|---|
| AutoERP (DocType `AutoGrade Operator`) | ERP Desk, ikut turun bareng master data | di AutoERP |
| Lokal PC ini | tab **Akun** → **Tambah akun** (support), atau `make operator` (`make operator-docker` di pabrik) | tombol **Ganti sandi** di tab Akun, atau `make operator` lagi dengan email sama |

Dua akun bawaan ada di tiap PC: `operator@autograde.local` (pabrik) dan `support@autograde.local`
(kita, lewat AnyDesk). Sandinya beda tiap PKS, dibuat saat pasang PC (§5.5). Login tetap jalan
tanpa internet karena hash sandi tersimpan lokal.

Dua peran: **operator** (4 tab) dan **support** (9 tab: empat tab operator + lima tab support, lihat §3.5). Yang menjaga adalah backend:
endpoint support dijawab 403 untuk operator, dan 401 untuk yang belum masuk.

### 3.2 Layar utama

- **Di bawah tulisan AUTOGRADE** (semua akun): versi dan sampai kapan lisensi PC ini berlaku,
  misalnya `v1.18.0 · Lisensi s/d 30 Sep 2027`. Kuning saat langganan tinggal sebentar, merah
  saat masa tenggang atau habis. Klik untuk melihat perusahaan, tanggal aktif, dan masa
  tenggang. PC tanpa lisensi cuma menampilkan versinya.
- **Strip "Hari ini"**: jumlah janjang per kelas (Ripe, Unripe, JK, TP) dan total, rasio Ripe,
  **Data timbangan** (neto hari ini dan jumlah tiket), dan **Last Sync**.
- **Last Sync**: dua baris, **AutoERP** dan **Cloud Photo** (foto di R2). Jamnya = kapan data
  terakhir masuk ke sana; `-` berarti belum pernah ada yang masuk. Titik **hijau** = tersambung; titik **kuning** = terputus, dengan
  keterangan seperti "Terputus sejak 13.40 · 5 menunggu". Foto naik tiap jam, jadi jam Cloud
  Photo yang tertinggal sampai satu jam itu normal selama titiknya hijau. Arahkan kursor ke
  baris untuk rinciannya (Cloud Photo: jam upload tiap line). Selama terputus tidak ada data
  yang hilang: semuanya menunggu di antrean dan terkirim sendiri begitu sambungan pulih.
- **Tiga kartu line**, satu per kamera, dengan stream langsung, status **ONLINE / OFFLINE** di
  judul, tombol **Tugaskan** (pilih truk), **Lepas** (truk pergi), dan **Reject Manual**.
- Kartu berbingkai **merah** dengan pita **AI berhenti memproses** (jam mulai, tindakan) =
  kamera jalan tapi tidak ada yang digrading: tahan umpan buah ke line itu dan panggil teknisi.
  Pita hilang sendiri begitu line memproses lagi.
- Kartu berbingkai **merah** dengan pita **kamera berhenti mengirim gambar** (jam mulai,
  tindakan) = kamera tersambung tapi tidak ada gambar masuk lebih dari 30 detik: tahan umpan
  buah, periksa kabel data dan switch kamera, restart line. Video uji tanpa
  ulang yang selesai diputar TIDAK memunculkan pita ini. Hilang sendiri begitu gambar datang lagi.
- Pita **Disk PC hampir penuh** (kuning berdenyut pelan, sisa di bawah 15 GB) atau **Disk PC hampir habis**
  (merah berdenyut, di bawah 5 GB) di atas semua kartu,
  satu pita untuk seluruh PC: menyebut jam mulai, line yang melaporkan, dan sisa GB. Langkah
  pengosongannya untuk teknisi, ada di tabel masalah di bawah. Pita kuning bisa ditutup dengan
  tombol ×, lalu muncul lagi 24 jam kemudian kalau disk masih penuh; pita merah tidak bisa ditutup.
  Muncul dengan atau tanpa R2, dan hilang sendiri begitu disk lega lagi.
- Kotak kamera bertuliskan **Line N sedang dinyalakan ulang** dengan spinner dan bar berjalan
  = line itu sedang restart karena support menyimpan Sumber Kamera atau Model Deteksi, atau
  menekan Restart / Hapus data di Danger Zone. Selama itu tulisan "Kamera tidak tersambung"
  tidak ikut tampil, dan tidak ada hitungan detik: bar berjalan cukup menandai masih diproses. Hilang sendiri begitu gambar kamera muncul lagi,
  tanpa memuat ulang halaman. Lewat 60 detik berganti jadi kotak merah **Line N belum kembali**
  (jam restart diminta): cek tab Log dan terminal line itu. Hapus data
  menulis **Line N sedang menghapus data lalu dinyalakan ulang** dan menunggu sampai 10 menit
  sebelum kotak merah, karena line menghapus fotonya dulu sebelum menyala. Tanda ini tampil di
  layar tempat tombolnya ditekan (biasanya PC pabrik lewat AnyDesk); layar lain cuma melihat
  kartu OFFLINE lalu ONLINE lagi.
- **Notifikasi di pojok kanan bawah** menutup sendiri: hijau dan kuning 5 detik, merah dan hasil
  Danger Zone yang perlu dibaca 10 detik. Selama kursor di atasnya hitungannya berhenti, jadi
  kalimat panjang bisa dibaca sampai habis, tapi tidak ada yang bertahan lebih dari 30 detik;
  tombol × menutupnya kapan saja.
- **Reject manual tanpa mouse**: tahan `Spasi` lalu tekan `1` / `2` / `3` sesuai line.
- **Piston manual** per line (Buka / Tutup) kalau PLC aktif. Ada konfirmasi karena ini
  menggerakkan besi sungguhan.
- Sumber TBS **Internal** ditandai "REJ tidak dibuang": buah kebun sendiri tetap dinilai, tapi
  piston tidak membuangnya.
- Kolom scan QR **Truk masuk** dan **Truk keluar** di baris alat tab Timbangan baru muncul
  sesudah scanner barcode dipasang; sampai saat itu keduanya disembunyikan. Plat dipilih dari
  daftar **Pilih Truk**, dan timbang keluar lewat tombol **Timbang keluar** di baris tiket (§3.3).

### 3.3 Alur satu kunjungan truk

```diagram:kunjungan-truk Perjalanan satu truk, dari gerbang masuk sampai pemasok dibayar
1 timbang masuk → 2 buah dituang, kamera menilai → 3 timbang keluar → 4 AutoERP hitung → 5 bayar
```

| # | Kejadian | Yang dilakukan di konsol | Yang dikirim ke AutoERP |
|---|---|---|---|
| 1 | Truk tiba | Pilih plat di daftar **Pilih Truk** (sesudah scanner dipasang: scan kartu QR di kolom **Truk masuk**). Truk belum dikenal → **Daftar truk manual** di tab Truk (cukup plat) | truk baru (`upsert_truck`) |
| 2 | Timbang masuk | Tab **Timbangan** → **Timbang masuk**: plat + bruto (kg). Berat di bawah 1.000 kg ditolak | tahap `gate`: bruto + jam masuk |
| 3 | Bongkar | Kartu line → **Tugaskan** → pilih truk. Janjang berikutnya dicatat atas nama truk itu | - |
| 4 | Selesai bongkar | **Lepas** di kartu line | tahap `grading`: total, ACC, REJ, persen |
| 5 | Timbang keluar | Tombol **Timbang keluar** di baris tiket truk itu → isi tara (sesudah scanner dipasang: scan QR di kolom **Truk keluar**; dua tiket terbuka → konsol menolak menebak, pilih di tabel) | tahap `departed`: tara + jam keluar |
| 6 | AutoERP | - | neto = bruto − tara, potongan, harga, Purchase Receipt |

Tabel Timbangan memakai kolom **Lama**: berapa lama truk itu diproses, dihitung
dari jam timbang masuk ke jam timbang keluar (`25 mnt`, `1 j 45 mnt`). Tiket
yang belum timbang keluar tampil `-`, bukan nol, truknya masih di pabrik. Angka
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
| **Truk** | master truk + supplier + asal data (ERP / manual) | **Daftar truk manual**, **Cetak QR truk** (kartu QR berisi plat, dibuat di server) |
| **Timbangan** | tiket hari kerja: masuk, keluar, bruto, tara, neto | **Timbang masuk**, isi tara lewat **Timbang keluar** di baris tiket |
| **Rekap** | grading per truk dan per hari, untuk hari ini atau hari-hari sebelumnya (paling panjang 31 hari). Dibuka di **Hari ini, Per truk**: satu baris per truk, ini yang diserahkan ke supplier | ganti tanggal untuk hari sebelumnya, **Unduh CSV**, **Impor CSV** untuk akun support; rinciannya di bawah |

> Angka keyakinan ada di tabel Grading, tapi **tidak** digambar di kotak janjang pada layar
> line: dari beberapa meter "54%" terbaca seperti "54% matang". Saklar **Mode dev** di tab
> Setelan mengembalikannya, untuk yang sedang menyetel ambang.

**Rekap** (sejak 2026-09-28 Rekap dan Riwayat jadi satu tab) dibuka di **Hari ini, Per truk**,
sama seperti tab Rekap dulu, dan menyegarkan diri tiap 15 detik selama rentangnya memuat hari ini.
Ganti tanggal untuk melihat hari-hari sebelumnya. Rekap menyandingkan dua sumber terpisah (grading
dan timbangan): neto dijumlah per truk, dan satu truk boleh punya lebih dari satu tiket sehari.
Baris **Tanpa truk** = janjang ter-grading sebelum truk ditugaskan.

| Bagian | Isi |
|---|---|
| Saringan | **Dari / Sampai** (tanggal kerja, paling panjang 31 hari), tombol cepat **Hari ini / Kemarin / 7 hari / Bulan ini / Bulan lalu** (yang sedang dipakai menyala hijau), **Line**, **Plat** (cukup sebagian, mis. `1234`), lalu **Tampilkan** |
| Ringkasan | janjang, Ripe, Unripe, JK, TP, rasio Ripe, jumlah truk, jumlah hari, dan neto periode itu. Neto tidak dihitung kalau disaring per line (neto itu berat truk) |
| Tiga tampilan | **Per hari** (satu baris per hari kerja, tombol **Lihat truk**), **Per truk** (tampilan bawaan: satu baris per truk per hari, tombol **Lihat janjang**), **Per janjang** (seperti tab Grading, dengan foto dan saringan **Hasil**: Ripe/Unripe/JK/TP) |
| **Unduh CSV** | semua baris tampilan dan saringan yang sedang aktif, bukan cuma halaman yang terlihat; kepala kolom mengikuti bahasa layar, jam dalam jam pabrik. Dibuka langsung di Excel/LibreOffice. Kalau Excel dengan setelan wilayah Indonesia menaruh semuanya di satu kolom, buka lewat **Data → From Text/CSV** dan pilih pemisah koma |

Foto yang lebih tua dari masa simpan PC (180 hari di Lampung) sudah terhapus dari PC; barisnya
tetap ada, fotonya tertulis "Foto sudah terhapus dari PC".

**Impor CSV** (akun support saja, sejak 2026-09-27) memasukkan kembali CSV **Per janjang** hasil
Unduh CSV, dari PC ini atau PC lain. Dipakai untuk memindahkan riwayat ke PC baru, atau memulihkan
hari-hari yang terhapus.

1. Tab Rekap, **Impor CSV**, pilih berkasnya, **Periksa**. Belum ada yang disimpan: layar menulis
   berapa janjang baru, berapa yang sudah ada (dilewati), berapa yang jatuh hari ini atau sesudahnya
   (tidak diimpor, datanya masih berjalan), dan baris yang salah beserta nomornya.
2. Kalau tidak ada baris salah, tekan **Impor N janjang**. Satu baris salah menolak seluruh berkas:
   perbaiki, atau unduh ulang dari tab Rekap.
3. Salah impor? Di daftar **Impor sebelumnya**, **Batalkan** (dua kali klik) menghapus janjang
   impor itu saja. Truk yang ditambahkannya tetap ada.

Pakai berkas asli hasil Unduh CSV. Berkas yang disimpan ulang dari Excel ditolak: Excel mengganti
pemisah dan format tanggal, dan membuang detik. Janjang hasil impor diberi label **IMPOR** di
tampilan Per janjang, dan tidak pernah dikirim ke AutoERP.

### 3.5 Lima tab support

Muncul hanya untuk akun berperan `support`. Tujuannya: memeriksa PC pabrik dari layar, tanpa
`docker logs` yang hilang tiap restart.

Sejak 2026-09-28 tab-tabnya digabung (dulu sepuluh). Nama lama yang mungkin masih tertulis di
runbook: **Diagnostik, Antrean ERP, Versi** → tab **Status**; **Sumber Kamera, Model Deteksi,
Uji PLC, Rekam Video** → tab **Line** (empat tombol pilihan di atasnya); **Riwayat** → tab
**Rekap** (operator). Tab lama yang masih diingat browser dibuka di tempat barunya.

| Tab | Isi |
|---|---|
| **Log** | galat dan peringatan konsol DAN ketiga line (kolom Sumber menyebut line-1/2/3 atau konsol), jam pertama muncul untuk baris gabungan, traceback bisa dibuka per baris; kalimat di atas tabel menyebut keadaan lapor ke Discord. 180 hari terakhir, selamat dari restart; pesan berulang digabung `×N`; sandi/token tertulis `«ditutup»` |
| **Status**, bagian Versi | versi, environment, status lisensi (tanpa token; versi dan tanggal lisensi juga tampil di bawah tulisan AUTOGRADE untuk semua akun). Machine ID disembunyikan sejak 2026-09-25. Lisensi **Mati. Token ada, tapi saklar lisensi di konsol belum menyala** berarti tokennya sampai ke konsol tapi saklarnya (`LICENSE_ENABLED`) tidak: periksa blok konsol di compose host, bukan tokennya |
| **Status**, bagian Diagnostik | tiga kartu line: kamera, FPS kamera / deteksi (terukur, 0 kalau gambar berhenti), umur gambar terakhir (merah kalau kamera berhenti mengirim), GPU, PLC (✓ **hanya kalau benar-benar tersambung**, ✗ kalau PLC menyala tapi terputus, `-` kalau PLC dimatikan), disk (sisa GB, kuning/merah di bawah ambang), lisensi, versi / model, antrean lokal, **Janjang tak tersimpan** (`capture_save_dropped`) dan **TP telat** (`tp_telat`), lalu worker satu per baris (✓ hijau hidup, ✗ merah mati; judulnya memberi hitungan, mis. `5/6`). Line mati tetap tampil dengan sebabnya. ⚠️ Janjang tak tersimpan dan TP telat **harus nol** (hijau), di atas nol merah: ada janjang yang tidak tersimpan, atau tangkai panjang yang tidak tercatat. Disegarkan tiap 5 detik selama tab Status terbuka |
| **Status**, bagian Antrean line | janjang yang belum sampai dari tiap line ke konsol: jumlah, umur yang tertua, keadaan (dengan sebab, sejak kapan, dan harus ngapain), jam pengiriman terakhir yang gagal (teks galatnya di tab Log); tombol **Kirim Ulang** per line. Antrean ini tidak pernah menyerah: konsol mati berjam-jam pun janjangnya menunggu dan terkirim sendiri begitu konsol hidup lagi |
| **Status**, bagian Antrean ERP | pesan yang belum sampai ke AutoERP: sebab gagal, percobaan, jadwal berikutnya; tombol **Kirim Ulang**. Plus antrean manifest R2 |
| **Akun** | semua akun yang bisa masuk konsol di PC ini: nama, email, role, asal (**Lokal** / **AutoERP**), status (Aktif / Mati / Terkunci), sedang masuk atau tidak. **Tambah akun** membuat akun **Lokal** baru (nama, email, role, sandi minimal 8 karakter); akun ini cuma ada di PC ini dan **tidak masuk ke AutoERP**. Tiap akun Lokal punya tombol **Ganti sandi** (semua sesinya langsung berakhir), **Matikan / Aktifkan**, dan **Jadikan support / operator**; di baris akunmu sendiri cuma Ganti sandi. Akun AutoERP tidak punya tombol: diurus di AutoERP. **Sandi tidak bisa dilihat**: yang disimpan cuma hash-nya. Lupa sandi: akun AutoERP diganti di AutoERP (AutoGrade Operator → New Password, sampai ke PC ±5 menit), akun Lokal dengan Ganti sandi. Tiap perubahan tercatat di tab Log beserta siapa yang mengubah |
| **Line** → Sumber Kamera | pilih sumber gambar tiap line: kamera Hikrobot, webcam, berkas video, atau foto diam. Menyimpan **merestart** line yang berubah (~10 detik); kotak kamera line itu menulis "sedang dinyalakan ulang" sampai gambarnya muncul lagi (§3.2) |
| **Line** → Model Deteksi | pilih model YOLO tiap line dari berkas di `models/release/`. Tiap model menampilkan **kelasnya** dan status engine TensorRT; model yang kelasnya bukan `Ripe/Unripe/JK/TP` tampil tapi tidak bisa dipilih. Kartu line menunjukkan model yang **sedang jalan** menurut line itu sendiri, beserta kelasnya, **merah** kalau bukan empat kelas itu, artinya line tidak menghitung janjang. Simpan membuka **modal konfirmasi** yang menyebut line yang akan restart (~10 detik) dan truk yang sedang diproses di situ. Bawaan PC = `MODEL_FILE` di `.env`. Runbook: `docs/runbooks/2026-09-24-model-deteksi-per-line.md` |
| **Line** → Uji PLC | tombol uji coil per line (OK hijau, NG merah, Error kuning, alamat M di tiap tombol) + kartu peta alamat PLC di bawahnya. Mati saat line memproses truk; konfirmasi tombol Jalankan/Batal; heartbeat (M1009) sengaja tidak ada |
| **Line** → Rekam Video | rekam gambar kamera ke MP4, satu tombol per line, jalan sampai ditekan Stop. Gambarnya **polos tanpa kotak deteksi** (diambil sebelum model jalan). Resolusi (lebar × tinggi) diatur di tab ini juga, dan berlaku untuk rekaman **berikutnya**, mengubahnya di tengah rekaman menghasilkan berkas rusak. ⚠️ **FPS mengikuti sumbernya, tidak diatur dari layar** (kolom FPS dan Bitrate dicabut 2026-09-25, dua-duanya tidak pernah sampai ke berkas): berkas video memakai laju aslinya, kamera Hikrobot memakai `CAMERA_FPS`. Itu yang membuat durasi rekaman sama dengan lama menekan Record. ⚠️ **Rekaman tidak pernah dihapus otomatis**: hapus sendiri dari folder yang tertulis di kaki layar (`Disimpan di …`, di PC pabrik `/opt/palmgrade/autograde/videos/`). Sesudah menekan Stop, jalur lengkap berkasnya juga muncul sekali di notifikasi hijau. Stop menulis dulu gambar yang sudah antre saat tombol ditekan (paling banyak 30 gambar; di Mac sekitar 0,6 detik, belum diukur di Lampung); yang berhenti karena disk mepet tetap berhenti seketika. Berhenti sendiri kalau sisa disk di bawah 20 GB, supaya grading tidak pernah kehabisan tempat menulis |
| **Setelan** | ambang keyakinan (0–1), ukuran minimum (piksel), **arah conveyor**, **garis capture** (piksel), dan saklar **Mode dev**. Tersimpan dan langsung dikirim ke tiga line, menang atas `.env`. Tab paling kanan |

### 3.6 Layar penuh di PC pabrik

`make kiosk` membuka Chrome mode kiosk (keluar dengan `Alt+F4`). Untuk jalan otomatis saat login
pasang `scripts/palmgrade-console.desktop`. Skrip itu menunggu konsol menjawab dulu, karena
setelah listrik padam desktop sering login sebelum Docker siap.


### 3.7 Danger Zone (tab Setelan, support)

Kotak merah di paling bawah tab **Setelan**, tertutup saat tab dibuka. Isinya lima aksi, dari
yang paling ringan:

| Aksi | Yang terjadi | Konfirmasi |
|---|---|---|
| **Restart semua line** | ketiga line mati sekitar 10 detik, lalu hidup lagi | Batal / Jalankan |
| **Logout paksa semua akun** | semua sesi dihapus, termasuk layar operator di PC pabrik dan akunmu | Batal / Jalankan |
| **Hapus rekaman video** | rekaman ketiga line di `videos/` hilang; line yang sedang merekam atau mati dilewati | ketik `HAPUS` |
| **Hapus data transaksi** | grading, foto, timbangan, antrean, log hilang; truk, akun, setelan **tetap** | ketik `HAPUS` |
| **Hapus semua data** | yang di atas, ditambah akun yang dibuat di PC ini, truk, dan supplier. Setelan **tetap**, dua akun bawaan dibuat ulang, dan akun AutoERP ditarik lagi | ketik `HAPUS` |

Tiap tombol membuka panel di bawah barisnya: apa yang akan hilang (dengan angka), **hambatan**
merah (kalau ada, tombol eksekusinya tidak muncul), dan **peringatan** kuning. `HAPUS` harus
huruf besar.

**Kapan ditolak:** ada line yang tidak menjawab, ada line yang sedang dipasangi truk, masih ada
janjang yang belum sampai ke konsol, ada truk yang sudah timbang masuk **hari ini** tapi belum
timbang keluar (bruto-nya yang dibayar, jadi tunggu tiketnya lengkap), atau masih ada kiriman
yang belum sampai ke AutoERP (tunggu Antrean ERP di tab Status kosong). "Hapus semua data" juga ditolak
kalau `.env` tidak punya hash akun **support** yang terbaca (`CONSOLE_SUPPORT_HASH`) dan AutoERP
tidak disetel, karena sesudahnya tidak ada yang bisa membuka menu support. Tiket terbuka dari hari-hari
sebelumnya cuma diperingatkan: itu hampir pasti sisa uji coba.

**Selama menghapus, truk tidak bisa ditugaskan ke line.** Layar menjawab "Data sedang dihapus";
tunggu sebentar, lalu tugaskan lagi.

**Yang tidak pernah tersentuh:** data yang sudah masuk AutoERP, foto yang sudah di R2, setelan
grading, `.env`, `media.env`, dan `license.db`. Foto yang **belum** naik ke R2 ikut hilang.

Cara kerjanya: tiap line menulis penanda lalu restart, dan menghapus datanya sendiri saat
menyala lagi. Itu sebabnya kartu line OFFLINE sesudah menekan, bisa **beberapa menit** kalau
fotonya sudah berbulan-bulan. Siapa menekan apa tercatat di tab **Log**
(`[Danger Zone] … oleh <email>`). Di terminal, padanannya `autograde reset-data-fresh`, tapi
yang itu menghapus **semuanya**, termasuk setelan dan lisensi.

**Membaca hasilnya:** toast hijau = semua beres. Toast kuning yang **bertahan 10 detik** (bukan
5; berhenti menghitung selama kursor di atasnya) = ada line yang perlu perhatian, disebut satu
per satu:

| Di toast | Artinya | Yang dilakukan |
|---|---|---|
| lisensi line habis | lisensi line itu mati, jadi perintahnya ditolak | pasang token baru (`autograde licence`), lalu tekan lagi |
| versi line lama | image line belum punya fitur ini | `autograde pull`, lalu tekan lagi |
| tidak menjawab | line mati saat perintah dikirim | nyalakan line-nya, lalu tekan lagi |
| truk terpasang | truk ditugaskan tepat saat tombol ditekan | lepas truknya, lalu tekan lagi |
| diterima tapi belum restart | perintahnya sampai, tapi line belum restart dalam 12 detik | tunggu, datanya terhapus begitu line itu restart |

Data konsol sudah dikosongkan kalau **minimal satu** line menerima, jadi menekan lagi cuma
membersihkan line yang tadi tertinggal. Kalau **tidak satu pun** line menerima, tidak ada yang
dihapus sama sekali, dan layar menyebut alasannya per line.

"Logout paksa" dan "Hapus semua data" ikut mengeluarkan akunmu sendiri: hasilnya muncul
sesudah kamu masuk lagi.

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
  kalau dibiarkan akan menutupi baris yang baru digrading, janjangnya berstempel sampai
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
MVS, NVIDIA, dan firewall ada di `docs/SETUP.md`; ini urutan ringkasnya.

Ada **dua cara** memasang. Bagian ini cara **dari source** (`git clone` + `make up`, konsol di port
8000). PC Lampung memakai cara **image produksi**: tanpa source code, cuma compose + `.env` + data di
`/opt/palmgrade/autograde`, dijalankan launcher `autograde` (`autograde pull`, `autograde use vX.Y.Z`),
konsol di port 8100. Langkah cara itu ada di workspace `sawit`: skill `install-factory-pc` dan
`../docs/runbooks/2026-08-21-checklist-pasang-pc-pabrik.md`. Jebakan compose host-nya di skill
`compose-host-pabrik`.

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
| PLC Mitsubishi (kalau ada) | `192.168.0.14`: satu segmen dengan NIC kamera PC (`192.168.0.10`), dicolok ke switch kamera |

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
| `BACKEND_URL` | `http://localhost:8100` (image produksi) atau `:8000` (dari source) | tiga line mengirim ke **konsol lokal**. Jangan pernah ke API cloud |
| `WEBHOOK_SECRET` | `openssl rand -hex 32` | dipakai line ↔ konsol di PC ini |
| `FACTORY_TZ` | `Asia/Jakarta` (sesuaikan) | batas tanggal kerja |
| `CONSOLE_DEFAULT_HASH`, `CONSOLE_SUPPORT_HASH` | keluaran `make hash-sandi` | dua sandi **berbeda**, catat di catatan internal. Tulis `$$` untuk tiap `$` (compose memakan `$`) |
| `CONF_THRESHOLD`, `MINIMUM_SIZE`, `ROI_*` | nilai pabrik | Lampung: 0.5, 3000, ROI 100/100/1180/620. Bisa diubah dari tab Setelan |
| `GARIS_CAPTURE`, `SUMBU_GARIS`, `MODE_DEV` | `300`, `tegak`, `false` | **nilai awal saja**: yang dipakai sehari-hari diatur dari tab Setelan, berlaku tanpa restart. Garis `0` = tanpa garis |
| `BORDER_THICKNESS`, `FONT_SCALE`, `FONT_THICKNESS` | 8, 2.5, 5 | frame 2448×2048 butuh angka besar |
| `R2_ACCOUNT_ID` … `R2_PUBLIC_URL` | dari Cloudflare, atau kosong | kosong = foto tidak diunggah, tidak ada `detail_url` di tiket ERP |
| `UPLOAD_API_URL`, `UPLOAD_API_SECRET` | **kosong** | penerima teks per janjang sudah pensiun |
| `UPLOAD_RETENTION_DAYS`, `UPLOAD_DISK_MIN_FREE_GB` | 180, 20 | penjaga disk membuang arsip `done` tertua saat disk tinggal 20 GB |
| `DISK_PERINGATAN_GB`, `DISK_KRITIS_GB` | 15, 5 | pita disk di layar konsol (kuning / merah), dengan atau tanpa R2, tidak menghapus apa pun. Peringatan wajib di bawah `UPLOAD_DISK_MIN_FREE_GB` |
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

Buka konsol (port di §2), masuk dengan `support@autograde.local`, cek tab
**Status** (bagian Diagnostik): tiga kartu line harus hijau dengan fps terbaca.

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
dan supplier dari ERP, Antrean ERP di tab Status kosong.

Konsol yang memanggil AutoERP, tidak pernah sebaliknya. PC pabrik nol inbound. Akun dari ERP
hanya diterima untuk peran di `ERP_ALLOWED_ROLES` (bawaan `support`).

### 5.9 PLC (Mitsubishi Q03UDECPU, MC Protocol)

`PLC_ENABLED=true`, `PLC_HOST=192.168.0.14`, lalu `make start` (port per line 1025/1026/1027 sudah
dipatok di compose: satu Open Setting PLC per koneksi). PC bicara langsung ke port
Ethernet bawaan CPU (coupler ODOT dibatalkan 2026-09-21). Alamat M per line dipatok di
`docker-compose.yml` mengikuti daftar pak Ocit: camera 1 = M1000–M1002 + heartbeat M1009,
camera 2 = M1003–M1005, camera 3 = M1006–M1008; yang dibaca M1100–M1115 (motor fault, E-stop
M1111). Piston manual **belum dialokasikan**: fiturnya mati sampai panel memberi bitnya.
Dokumen tim PLC: `docs/plc-mc-handoff.pdf`; referensi teknis: `docs/plc-integration.md`. Uji
dari tab **Line → Uji PLC**: tombol per coil bernama ("Kamera 1 OK / M1000") dan peta alamat
lengkap di bawahnya. Motor fault dan E-stop dari PLC tampil sebagai pita merah di atas
kartu line (bukan di Uji PLC); E-stop tidak menghentikan grading.

### 5.10 Lisensi

Bawaan mati. Kalau dinyalakan (`LICENSE_ENABLED=true`, `LICENSE_TOKEN=<token dari cloud>`),
lisensi kedaluwarsa menghentikan inferensi dan menjatuhkan heartbeat PLC, jadi terlihat di lantai
pabrik. Kunci publik sudah tertanam di image; `LICENSE_PRIVATE_KEY` **tidak boleh** ada di PC
pabrik. Status terlihat di bawah tulisan AUTOGRADE (semua akun) dan di tab Status (support).

### 5.11 Catatan PC Lampung (per 28 September 2026)

Sejak 2026-09-20 PC Lampung menjalankan **AutoGrade saja** (api dan frontend lama di-stop, volumenya
utuh) dengan image `ghcr.io/delta-anugrah/autograde`, compose di host `/opt/palmgrade/autograde`, dan
launcher `autograde`. Layar operator konsol `:8100/console`, dibuka sebagai kiosk. ⚠️ **Compose host
tidak ikut `autograde pull`**: variabel atau mount konsol yang baru harus ditambah tangan di sana
(2026-09-28: `LICENSE_ENABLED` hilang dari blok konsol, lisensi terbaca "Inactive"). Spek terukur
(disk, GPU, NIC) ada di skill `.claude/skills/spek-pc-pabrik/`. Akses hanya lewat AnyDesk, tidak ada
SSH masuk.

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
| `make demo-off` | hapus data demo, berhenti di situ (tidak mengisi ulang seperti `demo-reset`). Data sungguhan tidak disentuh: jalankan sesudah showcase, sebelum uji coba. AutoERP punya tiga perintah nama sama |
| `make rebuild-clean` | build ulang tanpa cache, hanya kalau cache dicurigai rusak |

### 6.2 Memperbarui kode di pabrik

```bash
cd ~/autograde
git checkout config/camera/hikrobot.mfs   # kalau .mfs sempat diubah untuk uji; berkas ini dilacak git
git pull
make restart                              # atau make up kalau dependency berubah
```

**Rilis lewat tag dibuka lagi 2026-09-18.** Tag `vX.Y.Z` menerbitkan image ke GHCR; PC pabrik
menariknya sendiri (`autograde pull`, atau `autograde use vX.Y.Z` untuk memilih versi): tidak ada
deploy otomatis, karena PC pabrik tidak punya alamat publik.

Nama image sekarang **`ghcr.io/delta-anugrah/autograde`**: satu nama, nama lama
`palmgrade-vision` sudah dicabut.

Di PC pabrik image-nya dipilih `PALMGRADE_AUTOGRADE_IMAGE` di `/opt/palmgrade/autograde/.env`
(dulu `vision`, diganti 2026-09-18). Jangan diedit tangan: pakai `autograde use vX.Y.Z`, yang juga
membuat ulang container supaya versinya benar-benar terpasang.

### 6.3 Cek kesehatan

| Cara | Yang dilihat |
|---|---|
| tab **Status**, bagian Diagnostik (support) | worker, kamera, fps terukur, umur gambar, GPU, PLC tersambung, disk, lisensi, versi / model per line |
| `curl localhost:8001/health/detail` | `camera_connected`, `fps_kamera`, `frame_umur_detik`, `gpu_available`, `plc.connected`, `disk`, `current_assignment_id`, `outbox_pending`, dan **`capture_save_dropped` + `tp_telat` yang harus NOL** |
| tab **Status**, bagian Antrean line | janjang yang belum sampai dari line ke konsol dan sebabnya |
| tab **Status**, bagian Antrean ERP | pesan yang belum sampai ke AutoERP dan sebabnya |
| tab **Log** | ERROR/WARNING 180 hari, bertahan lewat restart |
| `docker logs ripe_line_1` | tiap baris: jam bertanda zona (`+07:00`), kode line, level; polling yang sukses tidak ditulis; PLC/kamera putus cuma satu baris saat putus dan satu saat pulih |
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
| Kartu line "Kamera tidak tersambung" padahal line jalan | tulisan itu muncul kalau **browser** gagal memuat stream `http://<host konsol>:800N/api/video_feed`; sebabnya line di port lain, stream mati, atau port line tidak terjangkau dari PC yang membuka konsol | buka `http://<host>:800N/health/detail` dari browser yang sama; `make line N=…` (bukan port bebas); tab Status (bagian Diagnostik) untuk status kamera sesungguhnya |
| Janjang line 2 mendarat di kartu line 1 | konsol mencocokkan event lewat `machine_id`, bukan port; `MACHINE_ID` kembar | cek `LINE_N_MACHINE_ID` berbeda per line (`make line N=2` sudah mengaturnya) |
| Layar nol, log line "Outbox delivery failed … HTTP 404" | `BACKEND_URL` menunjuk port yang salah (8000 vs 8100) | betulkan `.env`, `make start` |
| Line `OFFLINE`, `camera_connected: false` | MVS masih membuka kamera; kabel/switch; IP kamera bukan `.10/.11/.12` | tutup MVS; cek LED link; `ip -br addr`; kamera dicoba ulang otomatis tanpa restart |
| Frame hitam di malam hari | gelap, `Gain 0`, bukan bug | pencahayaan; jangan ubah kode |
| fps tidak berubah walau `CAMERA_FPS` diganti | Hikrobot membaca laju dari `.mfs` | ubah `config/camera/hikrobot.mfs`, `make restart` |
| `backend=pt` di log, bukan `tensorrt` | engine belum dibangun / GPU beda | `make build-engine` lalu `make restart` |
| `gpu_available: false` | NVIDIA Container Toolkit belum benar | ulangi §5.4, tes `nvidia-smi` di container |
| Login 401 "belum masuk" | sesi 12 jam habis | masuk lagi |
| 403 "menu ini untuk akun support" | akun berperan operator membuka tab support | akun support lain: tab Akun → **Jadikan support**; atau `make operator-docker AKSI=role ROLE=support` |
| Log konsol: "Tidak ada akun dengan peran support" | `.env` dibuat sebelum fitur peran ada | perintah yang sama di atas |
| Akun bawaan ditolak saat start | hash di `.env` terpotong karena `$` | tulis `$$` untuk tiap `$` |
| Antrean line (tab Status) menumpuk, keadaan "Konsol tidak terjangkau" / "menolak kunci" / "alamat salah" | konsol mati, `WEBHOOK_SECRET` beda antara line dan konsol, atau `BACKEND_URL` line salah | ikuti kalimat di kolom Keadaan; janjang tidak hilang dan terkirim sendiri sesudah pulih, atau tekan **Kirim Ulang** |
| Antrean line (tab Status): "N janjang DITOLAK konsol"; Danger Zone dan `autograde reset-data` menolak hapus data | konsol menjawab 400/422 untuk janjang itu (timestamp cacat, `ripeness_status` asing); line menyimpannya dan mencoba tiap 10 menit, tapi tidak akan sampai sendiri | tab Log, baris `Janjang … DITOLAK konsol: <alasan>`; betulkan penyebabnya lalu **Kirim Ulang**, atau keluarkan barisnya dengan tangan (§7.1) |
| Sesudah update, angka Rekap/Riwayat hari-hari lalu berubah | janjang yang dulu berhenti dicoba versi lama (50 percobaan) dikirim lagi dan mendarat di tanggal kerja ASLINYA, bukan hari ini; kunjungan AutoERP-nya bisa diantre ulang, tiket final ditandai **Cek AutoERP** | wajar, tidak ada yang dihitung dua kali; cek dulu jumlahnya sebelum update (skill `compose-host-pabrik`, urutan pasang batch 2) |
| Sesudah update, log line `Simpan janjang … lambat` lebih sering, atau `capture_save_dropped` di atas nol | foto dan sidecar kini ditulis dengan fsync (tahan listrik padam), jadi menulis satu janjang lebih lama; disk lambat terasa lebih dulu | amati beberapa jam pertama; `capture_save_dropped` harus tetap nol, kalau naik laporkan angka `tulis … ms` dari log itu ke support |
| Antrean ERP (tab Status) menumpuk, sebab 4xx | pesan **ditolak** ERP (field tidak dikenal, versi ERP lama, 417) | betulkan di ERP, lalu **Kirim Ulang** |
| Antrean ERP (tab Status) menumpuk, sebab jaringan/5xx | ERP **tidak terjangkau**; backoff 30 dtk → 1 jam | tunggu, atau Kirim Ulang setelah ERP pulih |
| Last Sync: **AutoERP** kuning (terputus) | internet PC pabrik putus, AutoERP sedang mati, atau `ERP_URL` / kunci salah | tab Log, baris "AutoERP terputus: …" menyebut alasannya; data menunggu di Antrean ERP di tab Status dan terkirim sendiri saat pulih |
| Last Sync: **Cloud Photo** kuning (terputus) | internet putus, kredensial `R2_*` salah, atau `UPLOAD_API_URL` masih menunjuk api lama yang mati | arahkan kursor ke baris untuk melihat line mana; tab Log "Cloud Photo line-N terputus: …"; kosongkan `UPLOAD_API_URL` lalu `make start` (PC pabrik: `autograde restart`) |
| Plat yang sama muncul dua baris di tab Truk | `ERP_URL` diisi sebelum OPS-2 | jalankan checklist OPS-2 (§5.8) |
| Unggah ke R2 berhenti tanpa error | `R2_BUCKET` kosong, atau JSON sidecar dipindah ke subfolder | isi R2; JSON wajib datar di folder tanggal |
| Impor CSV ditolak "bukan CSV Per janjang" | berkas ringkasan (Per hari / Per truk), atau disimpan ulang dari Excel | di tab Rekap pilih **Per janjang**, **Unduh CSV**, impor berkas itu tanpa dibuka di Excel |
| Disk penuh, grading berhenti tersimpan | penjaga disk mati (`UPLOAD_DISK_MIN_FREE_GB=0`) atau Docker menumpuk image lama | `docker system prune`; kembalikan penjaga ke 20 |
| Pita **Disk PC hampir penuh / hampir habis** | sisa disk di bawah `DISK_PERINGATAN_GB` / `DISK_KRITIS_GB`. Tanpa R2 tidak ada yang membersihkan arsip lokal (itu satu-satunya salinan bukti, jadi sengaja tidak dihapus otomatis) | `docker system prune`, hapus rekaman video lama (`/opt/palmgrade/autograde/videos/`), pastikan unggah Cloud Photo jalan; pita hilang sendiri begitu lega |
| Pita **kamera berhenti mengirim gambar** (di log line tertulis `FRAME_BERHENTI`; pitanya sendiri tanpa kode) | kamera masih terbuka di SDK tapi gambarnya tidak datang: kabel data longgar, switch/splitter, bandwidth GigE, SDK macet | periksa kabel dan LED link, lalu restart line (Danger Zone atau `autograde restart`); log line menyebut `FRAME_BERHENTI` |
| Log line `Tutup line: N janjang TIDAK tertulis` | disk lambat atau macet saat line diminta restart/hapus data | cek disk (`df -h`, `dmesg`), janjang yang disebut tidak punya foto; laporkan ke support |
| Cloud Photo: foto `rusak` bertambah sesudah update | foto atau sidecar 0 byte dari listrik padam sebelum versi ini; tidak diunggah, dibiarkan di disk | tidak perlu apa-apa; boleh diperiksa lalu dihapus tangan |
| Laptop: `make console` terasa memakai kode lama | port 8100 masih dipegang proses lama | cari pid-nya dengan `lsof -ti:8100`, matikan, jalankan ulang |
| Laptop: `make up` gagal "MVS SDK not found" | memang, target Docker untuk Linux + GPU | pakai `make console` / `make line` |
| Kamera "tidak terjawab" saat E2E di macOS | `CONSOLE_LINE_HOST=http://localhost` → IPv6 | ganti `http://127.0.0.1` |
| Tab Timbangan: tanda **Cek AutoERP** di plat | janjang tiba sesudah tiket AutoERP-nya final (konsol sempat tidak terjangkau dari line, atau truk ditimbang keluar saat janjang terakhir masih diproses); AutoERP tidak mengubah angka yang dibukukan | tab Log baris `[TIKET_FINAL_BERBEDA]` menyebut tiketnya; minta backoffice memeriksa tiket itu di AutoERP (tanda `grading_revised`) |
| Antrean ERP: satu baris `HTTP 500` dengan alasan Frappe, yang lain terkirim | isi kunjungan itu membuat AutoERP galat | kirim alasannya ke pengelola AutoERP; setelah dibetulkan, **Kirim Ulang** |
| Kartu line merah, AI berhenti memproses | loop deteksi melempar galat terus (CUDA/GPU), atau macet | `curl :800N/health/detail` → `ai.galat_terakhir` (galat terakhir sejak boot, lihat `galat_at` untuk umurnya); restart line (Setelan, Danger Zone); kalau terulang, `nvidia-smi` dan log line |
| Kartu line merah sesudah update ke versi baru | model/engine versi baru gagal pada frame sungguhan. **Update tidak mundur sendiri**: gerbang `autograde` selesai pada jawaban sehat pertama, yang selalu jatuh di 30 detik pertama | lihat kartu line paling cepat 30 detik sesudah update; kalau merah, `autograde use <versi sebelumnya>` |
| Log line: "PLC … tidak bisa disambung" / "Kamera tidak mengirim gambar" | kabel PLC atau kamera lepas, perangkat mati | cek kabel dan lampu perangkat; baris "tersambung lagi sesudah …" / "mengirim gambar lagi sesudah …" muncul sendiri begitu pulih |
| Tab Log: "Lapor ke Discord DITOLAK ... (HTTP 404)" | webhook Discord salah atau sudah dihapus | buat webhook baru di kanal support, isi `DISCORD_WEBHOOK_URL` di `.env` PC, lalu `autograde restart`; pesan yang menunggu tidak hilang |
| Tab Log: "Lapor ke Discord tertahan" | internet pabrik putus | tidak perlu apa-apa, terkirim sendiri begitu internet ada |

### 7.1 Janjang yang ditolak konsol

Line tidak pernah membuang janjang (`docs/rules.md` aturan 31). Janjang yang dijawab konsol dengan
400/422 dicoba lagi tiap 10 menit selamanya dan tidak akan pernah sampai sendiri. Tandanya: tab
Status, bagian Antrean line, menulis **"N janjang DITOLAK konsol"**, dan tab Log punya baris
`Janjang <event_id> dari line-N (jam …) DITOLAK konsol: <alasan>`. Selama baris itu ada, Danger
Zone hapus data dan `autograde reset-data` menolak, karena antrean line belum kosong. Tidak ada
tombol yang membuangnya: orang yang memutuskan, dengan tiga langkah di PC pabrik (AnyDesk).

1. Lihat baris mana yang ditolak di tiap line (baca saja): `event_id`, jam grading, jam
   penolakan terakhir (UTC), alasannya.

```bash
for n in 1 2 3; do docker exec ripe_line_$n python -c 'import os,sqlite3; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); print(p); [print(*r, sep=" | ") for r in sqlite3.connect(p).execute("select event_id, json_extract(payload, ?), datetime(ditolak_at, ?), last_error from outbox_events where ditolak_at is not null", ("$.timestamp", "unixepoch"))]'; done
```

2. Kalau penyebabnya bisa dibetulkan (misalnya konsol masih versi lama), betulkan lalu tekan
   **Kirim Ulang**. Kalau janjang itu memang tidak bisa diterima, simpan dulu ke berkas di host,
   satu per `event_id`. Ganti `ripe_line_1` dengan line yang disebut dan `EVENT_ID` dengan kolom
   pertama langkah 1. Berkasnya harus berisi satu baris JSON; kosong = `event_id` salah atau
   baris itu tidak (lagi) tercatat ditolak, jangan lanjut ke langkah 3. Berkas yang sudah ada
   tidak pernah ditimpa, jadi menjalankannya lagi sesudah langkah 3 tidak menghapus salinannya.

```bash
f=~/janjang-ditolak-EVENT_ID.json; if [ -e "$f" ]; then echo "$f sudah ada, TIDAK ditimpa"; else docker exec ripe_line_1 python -c 'import json,os,sqlite3,sys; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); db=sqlite3.connect(p); db.row_factory=sqlite3.Row; r=db.execute("select * from outbox_events where event_id=? and ditolak_at is not null", (sys.argv[1],)).fetchone(); r or sys.exit("tidak ada baris ditolak dengan event_id itu"); print(json.dumps(dict(r)))' EVENT_ID > "$f.baru" && mv "$f.baru" "$f"; rm -f "$f.baru"; fi
cat "$f"
```

3. Baru hapus barisnya. Perintah ini hanya menghapus baris yang tercatat ditolak, jadi
   `event_id` yang salah ketik tidak menghapus apa pun (`0 baris dihapus`). Line boleh tetap
   jalan. Berkas `~/janjang-ditolak-*.json` itu satu-satunya salinan janjang tersebut: jangan
   dihapus.

```bash
docker exec ripe_line_1 python -c 'import os,sqlite3,sys; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); db=sqlite3.connect(p); n=db.execute("delete from outbox_events where event_id=? and ditolak_at is not null", (sys.argv[1],)).rowcount; db.commit(); print(n, "baris dihapus")' EVENT_ID
```

Tab Status bagian Antrean line menghitung ulang dalam 5 detik.

Dua jebakan umum di balik "setelan `.env` tidak berlaku": **env var proses menang atas
`.env`** (`load_dotenv(override=False)`; cek `/health/detail`), dan `.env` yang diubah baru
berlaku setelah `make start`, bukan `make restart` atau reboot.

Kalau gejalanya tidak ada di tabel: tab Log dulu, lalu `make logs-<line>`, lalu `docs/rules.md`
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
9. **Nama image GHCR `ghcr.io/delta-anugrah/autograde`**, satu nama sejak 2026-09-18, dijaga test. Tag rilis pertama di nama baru ditarik manual karena lebih tua dari versi terpasang.
10. **`.mfs` dilacak git.** `git checkout config/camera/hikrobot.mfs` sebelum `git pull`.
11. **Unit test tidak boleh memuat torch, OpenCV, atau hardware.** CI jalan tanpa GPU.
12. **Alur kode:** branch baru → PR squash ke `staging` → PR merge commit ke `main` → tag `vX.Y.Z` (image ke GHCR). Judul, isi PR, **dan pesan commit** bahasa Inggris (repo squash memakai pesan commit); tanpa `Co-Authored-By`; tanpa em dash.
13. **Port 8000 di Mac milik AutoERP lokal.** Konsol di Mac selalu 8100 (`make console`).

## 9. Peta Repositori dan Dokumen

| Butuh | Lihat |
|---|---|
| Peta aturan padat untuk AI agent | `CLAUDE.md` (= `AGENTS.md`) |
| Alur rinci, worker, invariant beserta alasannya | `docs/overview.md` |
| Daftar lengkap endpoint, event, variabel lingkungan | `docs/backend-overview.md` |
| Pasang dari nol: MVS, NVIDIA, firewall, IP kamera | `docs/SETUP.md` |
| Spesifikasi dan setelan kamera, kenapa `.mfs` menang | `docs/camera-spec.md`, skill `mvs-camera` |
| PLC: alamat M, heartbeat, commissioning | `docs/plc-mc-handoff.pdf`, `docs/plc-integration.md`, skill `plc-mc-protocol` |
| Runbook per fitur (sumber kamera, model per line, commissioning PLC) | `docs/runbooks/` |
| Compose di host PC pabrik (yang tidak ikut `autograde pull`) | skill `compose-host-pabrik` |
| Kerja di layar konsol (tab, test, aturan teks) | skill `konsol-autograde` |
| Spek terukur PC Lampung | skill `spek-pc-pabrik` |
| Kontrak dengan AutoERP (yang harus dicocokkan dulu) | `../autoerp/docs/autograde-integration.md` |
| Pasang PC pabrik (image produksi), OPS-2, rilis | `../docs/runbooks/` dan skill `install-factory-pc` / `tag-release` di workspace `sawit` |
| Sisa pekerjaan | `../docs/TODO-AUTOGRADE-AUTOERP.md` |
| Membuat ulang PDF dokumen ini | `scripts/md_to_pdf.py docs/MANUAL.md` |

### 9.1 Folder

| Folder | Isi |
|---|---|
| `src/palmgrade/` | seluruh kode Python (rincian di bawah) |
| `tests/` | `unit/` (tanpa torch/cv2, jalan di CI), `e2e/`, `integration/` |
| `docs/` | dokumen ini, dokumen teknis, runbook, gambar diagram di `docs/assets/manual/` |
| `scripts/` | kiosk, data demo, build engine, hash sandi, pembuat PDF |
| `config/camera/` | `hikrobot.mfs`: setelan kamera, termasuk **fps** |
| `sdk/` | SDK kamera Hikrobot (MVS), supaya build Docker tidak butuh internet |
| `models/release/`, `engines/` | model YOLO (`.pt`) dan engine TensorRT per GPU. Tidak di git |
| `artifacts/`, `state/` | hasil runtime (foto, sidecar, outbox) dan SQLite (`console.db`, antrean). Tidak di git |
| `media/`, `videos/` | berkas video/foto untuk Sumber Kamera, dan hasil Rekam Video. Tidak di git |

Kode di `src/palmgrade/` berlapis, urutannya tidak boleh dilompati: `routes/` (HTTP saja) →
`controllers/` → `services/` (alur bisnis) → `repositories/` (disk dan SQLite) / `pipelines/`
(YOLO) / `integrations/` (kamera, R2, ERP, outbox). `domain/` berisi aturan murni tanpa I/O (contoh
`working_day.py`: shift malam masuk tanggal kerja mana); paling mudah diuji, paling mahal kalau
keliru. `workers/` thread dan task latar; `plc/` MC Protocol ke CPU Mitsubishi; `license/` penjaga
langganan; `static/console.html` layar operator dalam **satu berkas** tanpa build dan tanpa CDN.
Konsol sengaja lewat `routes → services` tanpa controller (CLAUDE.md, bagian Layer rule).

### 9.2 Langkah pertama untuk orang baru

1. Baca bagian **Critical Rules** di `docs/rules.md` (indeksnya `CLAUDE.md` §3).
2. `make operator` (akun lokal), `make console`, lalu masuk ke `http://127.0.0.1:8100/console`.
   `make demo` mengisi data contoh seminggu.
3. Buka `src/palmgrade/workers/frame_processing_worker.py`: di sinilah janjang jadi angka.
4. Buka `src/palmgrade/domain/working_day.py`: contoh aturan murni yang ringkas.
5. `.venv/bin/pytest tests/unit` harus lolos semua sebelum mulai mengubah kode.

Yang membingungkan atau tampak keliru: **catat sebagai temuan**, jangan dianggap "memang begitu".

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
| 2.1 | 1 Oktober 2026 | §3.2 sampai §3.4 mengikuti layar sekarang: kolom scan QR disembunyikan sampai scanner dipasang, plat dipilih dari daftar, tara lewat tombol **Timbang keluar** di baris tiket (petunjuk di layar kini menyebut nama tombol itu). Scan yang menemukan truk yang belum ada di daftar layar memuat ulang daftarnya dulu, dan truk yang dinonaktifkan disebut nonaktif. Tab Setelan: line yang belum menerima perubahan ditulis dalam bahasa layar. Tabel Rekap tidak lagi melebarkan halaman di layar 1024 px. |
| 2.0 | 30 September 2026 | Log line dan konsol bertanda jam zona pabrik dan kode line; konsol kini menulis ke `docker logs` dan galat 500 masuk tab Log; PLC, kamera, dan AutoERP yang putus cuma dicatat saat putus dan saat pulih; `LOG_LEVEL` bisa diatur. Tab Log menampilkan galat ketiga line (tetap ada walau line direstart), traceback, dan jam pertama muncul; galat penting bisa dilaporkan otomatis ke Discord. Kartu line merah FRAME_BERHENTI kalau kamera tersambung tapi berhenti mengirim gambar; video uji yang selesai tidak lagi terbaca rusak; satu pita disk di atas kartu saat disk hampir penuh atau kritis; kartu Diagnostik memakai fps terukur, umur frame, disk, lisensi, dan status sambungan PLC. |
| 1.9 | 29 September 2026 | §3.2: kotak kamera line yang sedang restart memakai bar berjalan, bukan hitungan detik, dan tidak lagi ikut menulis "Kamera tidak tersambung"; strip "Hari ini" berlabel **Data timbangan** (dulu Neto timbangan). Tab Akun: semua tombol aksi selebar sama. Tab Line: empat pilihan membentang selebar panel. |
| 1.8 | 29 September 2026 | §3.2: kotak kamera line yang sedang restart (Sumber Kamera, Model Deteksi, Danger Zone) memberi spinner dan hitungan detik, videonya kembali tanpa memuat ulang halaman, dan lewat 60 detik (hapus data: 10 menit) berganti pesan `RESTART_LAMA`. Notifikasi pojok tidak ada lagi yang menunggu ditutup: paling lama 10 detik, berhenti selama kursor di atasnya, maksimal 30 detik (§3.2). |
| 1.7 | 28 September 2026 | Restart dan hapus data dari konsol menutup line dengan rapi (coil PLC mati, antrean simpan habis); foto dan sidecar ditulis tahan listrik padam; foto 0 byte lama tidak diunggah. Tab Status punya bagian **Antrean line**: antrean janjang tiap line ke konsol tidak lagi menyerah sesudah 50 percobaan, dan bisa dilihat serta dikirim ulang dari layar; janjang yang ditolak konsol terbaca "DITOLAK konsol" dan dikeluarkan dengan tangan (§7.1). Kartu line jadi merah kalau AI berhenti memproses gambar (§7). §7: tanda **Cek AutoERP** di tab Timbangan untuk janjang susulan pada tiket AutoERP yang sudah final, dan baris antrean ERP `HTTP 500` beramplop Frappe. |
| 1.6 | 28 September 2026 | ONBOARDING digabung ke sini (§9.1 folder, §9.2 langkah pertama) lalu dihapus; port konsol ditulis dua cara pasang (8100 image produksi, 8000 dari source); §5.11 Lampung per 28 September; aturan image GHCR dan alur rilis diperbarui. |
| 1.5 | 28 September 2026 | Tab digabung dari 15 jadi 9: **Rekap** = Rekap + Riwayat (dibuka di Hari ini, Per truk), **Status** = Versi + Diagnostik + Antrean ERP, **Line** = Sumber Kamera + Model Deteksi + Uji PLC + Rekam Video. §3.4 dan §3.5 ditulis ulang. |
| 1.4 | 28 September 2026 | Versi dan lisensi PC ditampilkan di bawah tulisan AUTOGRADE untuk semua akun, termasuk operator; klik untuk rinciannya. |
| 1.3 | 28 September 2026 | Umpan balik tes staging: tombol cepat Riwayat menandai rentang yang dipakai, tombol **Lihat** di kolom sandi form akun, tombol aksi tab Akun berwarna, Last Sync menulis `-` untuk yang belum pernah sinkron, dan tab tetap benar saat berganti akun tanpa memuat ulang halaman. |
| 1.2 | 27 September 2026 | **Last Sync** di strip "Hari ini" (AutoERP dan Cloud Photo: jam sinkron terakhir + status sambungan) dan **Impor CSV** di tab Riwayat (akun support: periksa dulu, impor berkas yang sama, batalkan per impor), plus tiga baris penanganan masalahnya di §7. |
| 1.1 | 27 September 2026 | Tab **Riwayat** (grading hari sebelumnya, maks 31 hari, CSV), tab **Akun** yang bisa menambah dan mengurus akun lokal, **Danger Zone** di tab Setelan, tombol yang terkunci selama menunggu server, dan path PC Lampung `/opt/palmgrade/autograde`. Dicocokkan dengan kode `staging` sesudah autograde #180. |
| 1.0 | 17 September 2026 | Terbitan pertama. Dicocokkan dengan kode `staging` (`a559427`): konsol dengan login email+sandi, lima tab support, scan QR dua gerbang, Setelan grading, seeder demo, detail grading via R2. |
