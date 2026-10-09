---
name: konsol-autograde
description: Use when changing the AutoGrade operator console screen (src/palmgrade/static/console.html) or its /api/console routes, adding a tab or a support screen, touching tab switching, timers, the header, or screen text, or when a user reports a console screen bug. Maps the nine tabs, which role sees them, what loads each, which tests cover them, and the text and safety rules the tests enforce.
---

# Layar konsol AutoGrade

Satu berkas `src/palmgrade/static/console.html`: vanilla JS, tanpa build, tanpa CDN, nol
`https://` (harus jalan saat internet putus). Server: `console_main.py` + `routes/console.py`, plus
`routes/console_antrean_line.py` (bagian Antrean line di tab Status), `routes/console_gerbang.py`
(scan 1 dan 4, Batal datang, Tugaskan sekarang / Lewati; disertakan oleh `routes/console.py`),
`routes/console_ingest.py`
(kiriman janjang dari line) dan `routes/console_deps.py` (sesi dan peran).
Aturan coding untuk setiap perubahan layar ini: `docs/coding-standard.md` bagian Frontend (F1 sampai F12).

## Sembilan tab (sejak 2026-09-28, dulu 15)

| Tab | Siapa | Pemuat | Isi |
|---|---|---|---|
| Grading | semua | polling `refresh` 2 dtk | grading hari ini dari `/api/console/history` (halaman, saringan line dan truk, foto kecil `thumb_url`), kotak kamera `.feed` mengikuti bentuk gambar pertama dari line (`feedMemuat` menyimpan `naturalWidth / naturalHeight` di `rasioFeed` per line, `gayaRasioFeed` menulisnya lagi tiap `kartuLine` digambar ulang; `object-fit:contain`, `max-height:72vh`, 16:9 cuma sebelum frame pertama; 2026-10-07, test `test_console_html_feed_rasio.py` + `tests/browser/test_browser_feed_rasio.py`), kartu line merah + pita AI mati / kamera berhenti mengirim dari blok `plc.ai` (`pitaAi`, `perbaruiAi` tiap polling, keadaan `ai_mati` atau `frame_berhenti`, test `test_console_html_ai_mati.py` + `test_console_html_frame_disk.py`); satu pita disk PC untuk seluruh layar dari blok `plc.disk` (`#pita-disk`, `gambarPitaDisk` tiap polling, aturan 35): satu baris (ikon SVG, judul, jam, line, sisa GB; langkah pengosongan cuma di MANUAL dan log line), peringatan berdenyut pelan dan bisa ditutup 24 jam per browser (`localStorage` `pitaDiskDitutupPada`), kritis tidak bisa ditutup; tanda "sedang dinyalakan ulang" di kotak kamera sesudah aksi yang merestart line (`tandaiRestart`, `pantauRestart` 1 dtk, spinner + bar berjalan tanpa hitungan detik, kelas kartu `sedang-restart` menyembunyikan "Kamera tidak tersambung" selama itu, test `test_console_html_restart.py`); strip "Hari ini" berlabel **Data timbangan** (`labelNetoTimbangan`); angka besarnya berat live dari PLC (`muatTimbanganLive` tiap 1 dtk di semua tab, `GET /api/console/scale/live`, `gambarTimbanganLive`, `#timbang[data-keadaan]`, kotak lebar tetap 15.5rem supaya Last Sync tidak bergeser tiap status ganti; selama `SCALE_PLC_REGISTER` kosong tertulis Belum tersambung, aturan 39), neto hari ini pindah ke baris kecil (`#tot-neto`, `#tot-tiket`) |
| Truk | semua | `muatTrucks` 60 dtk | master truk, truk manual, kartu QR |
| Timbangan | semua | `muatTimbangan` 15 dtk | tiket, dua form berlabel + papan empat kolom (strip langkah dibuang 2026-10-08; `#ruas-kosong` = kolom papan `kosong`, `#scan-pergi-pesan` di kolom `selesai`, `#antre` di judul form 1) (1 Datang = `arrivals` lewat `POST /api/console/arrivals`, 2 Timbang isi, 3 Timbang kosong, 4 Keluar = `weighings.left_at` lewat `POST /api/console/departures`; aturan 37, tidak pernah ke AutoERP), plat dari daftar **Pilih Truk**, tombol baris **Timbang kosong** lalu **Keluar** (`data-aksi="pergi"`, kolom dipaku di kanan), kolom pertama **Status** (`lencanaTahap(w.tahap)`, warna sama dengan judul langkah; yang menunggu = baris teratas `barisMenunggu`), urut timbang isi terbaru menurut `julianday`, kolom **Antre** / **Total** (`tanpa scan 1` kuning `.tag.peringatan`, strip bukan 0), lencana **Menunggu n** (`#antre`, `gambarLencanaAntre`, plat di `title`) dari `waiting`, dan dropdown langkah 2 dengan bagian **Menunggu timbang** / **Truk lain** (`opsiPlatTimbang`, `isiPlatTimbang`: tidak dibangun ulang saat terbuka); 12 kolom (kepala **Jam timbang isi** / **Jam timbang kosong**); di atasnya strip empat ruas `.langkah-ruas` (kartu berwarna tahap lewat `--warna-tahap`/`--latar-tahap`/`--ikon-tahap` + `color-mix`, ikon `.langkah-ikon` mulai 1280 px, pita tahap + kalimat di mana langkah itu dikerjakan, sama lebar dan tinggi, `repeat(4, minmax(0,1fr))` mulai 960 px, 2 x 2 dari 600 px), dua form `.timbang-form` sama lebar (Datang, Timbang isi; berdampingan mulai 1100 px) dengan baris kaki `.timbang-kaki` untuk pesan Catat datang dan petunjuk desimal (juga `title` Bruto), dan bar tara `#tara-grup` selebar panel berwarna langkah 3 (plat, Tara, Simpan, Batal satu baris; ruas `#ruas-kosong` menyala `.aktif` selama terbuka; pesan tara `#scan-keluar-pesan` di bar itu); semua kontrol setinggi `--tinggi-timbang`, tombol utama selebar `--lebar-aksi-timbang`; satu kolom scan `#scan-otomatis-grup` di atas strip (2026-10-06), `hidden` di markup, dimunculkan `tampilkanKolomScan(s.scanner_qr === true)` di `refresh()` kalau saklar **Scanner QR** nyala; scan jalan dari **tab mana pun** (2026-10-07): `tangkapScan` (keydown fase capture di `document`: jeda huruf 100 ms, Enter dalam 500 ms, minimal 3 karakter, larian cepat yang putus, atau yang mulai kurang dari 1 dtk sesudah tombol di luarnya = bacaan gagal "Scan tidak terbaca, ulangi scan"; Enter yang tidak mengirim apa-apa ditahan dengan popup yang sama kalau ada 3+ tombol dalam 1,5 dtk), Spasi+N dan P+N dijaga `ledakanScan()` (3 karakter cepat) dan tetap jalan di kotak `#scan-popup-berat` (`diKolomBerat`, angkanya tidak masuk); `kirimScanOtomatis` → `POST /api/console/scan/auto`, server memilih langkahnya, `tanganiScan` menulis hasil sebagai popup `#scan-popup` (`div`, bukan dialog; sukses 4 dtk, gagal 8 dtk, line menurut urutan kartu, `teksPopupScan`/`tampilkanPopupScan`); `perlu_berat` → `mintaBerat` membuka popup berat dengan kolom angka `#scan-popup-berat` (Enter / QR sama = simpan lewat `simpanBeratPopup`, QR lain atau Esc menutup, 60 dtk diam menutup, huruf tidak jadi berat, `tombolPopupBerat`; `muatanBruto`/`muatanTara` dipakai bersama kotak Bruto dan bar tara yang tetap untuk ketik tangan), `perlu_konfirmasi` → `tanyaScanUlang` lewat `tanyaKonfirmasi`; selama terbuka, listener keydown capture menangkap ketikan scanner: QR sama sesudah 2 dtk = Catat, QR lain = Batal, `scanUlang`), QR yang sama dalam 2 dtk dibuang (`scanTerakhir`), kolom memegang fokus di tab Timbangan (`jagaFokusScan`/`bolehAmbilFokus`, tidak merebut dari input lain, pilih terbuka, dialog, atau popup berat; ketukan di popup berat mengembalikan fokus ke kotaknya), Enter di `#bruto` = Timbang isi; tes browser `tests/browser/test_browser_scan_otomatis.py` (fixture `scanner_nyala` di `tests/browser/conftest.py`, helper `setel_scanner` di `tests/browser/langkah.py`; tes yang mengetik banyak scan mengosongkan `scanTerakhir` dulu), `tests/browser/test_browser_scanner_qr.py` menguji saklarnya, tanda **Cek AutoERP** untuk janjang susulan pada tiket yang sudah final (`erp_perlu_dicek`, `tests/unit/test_console_html_timbangan_erp.py`) |
| Rekap | semua | `muatRiwayat` (+ `segarkanRekap` 15 dtk) | Rekap + Riwayat: buka di Hari ini, Per truk; Impor CSV support saja; saringan dua baris `.riwayat-baris` (2026-10-08): baris 1 `.riwayat-periode` = Dari, Sampai, rentang cepat; baris 2 = Line, Plat, Hasil, lalu `.riwayat-aksi` (Tampilkan, Unduh CSV, Impor CSV) didorong ke kanan, semua setinggi `--tinggi-tombol` |
| Log | support | `muatLog` (+ `muatLaporDiscord`) | kolom Level = chip `.log-tingkat[data-level]` (ERROR merah `--rej`, WARNING kuning `--warn`, 2026-10-08); saring `#log-level`: garis tepi saja, tanpa isi (Semua `--fg`, WARNING `--warn`, ERROR `--rej`), yang dipilih = `box-shadow:0 0 0 2px currentColor` + opasitas penuh, lainnya `.6`; BUKAN warna aksen, tanpa centang (user 2026-10-05); ERROR/WARNING 180 hari, konsol DAN ketiga line (tag line-1/2/3 atau konsol), jam pertama muncul untuk baris gabungan, traceback bisa dibuka per baris; kalimat di atas tabel menyebut keadaan lapor ke Discord (`mati`/`url_salah`/`aktif`/`tertahan`/`ditolak`); pesan identik dalam 60 dtk digabung sesudah id yang berganti (uuid, hex 8+, desimal, bilangan 6+ digit) dinormalkan (`domain/sidik_log.py`, batch 3.3); galat 500 uvicorn konsol (termasuk saat start gagal) kini ikut masuk lewat `configure_logging` (batch 3.1) |
| Status | support | `muatStatus` (diagnostik 5 dtk, antrean line 5 dtk); sub-tab `#status-sub` sejak 2026-10-05 (`SUB_STATUS`, `terapkanSubStatus`, diingat `subStatus`; panel `.status-bagian[data-status-sub]`, kelimanya tetap dimuat bersama saat tab dibuka); tes browser buka lewat `buka_status(page, sub)` di `tests/browser/langkah.py` | Versi & pembaruan (**Pasang sekarang** sejak 2026-10-07: `tanyaKonfirmasi` menyebut truk + line, server melepas truknya sendiri, tirai layar penuh `#tirai-pembaruan` (`div`, bukan dialog) sampai halaman dimuat ulang, toast sukses cuma kalau penunggu menjawab `ok` untuk versi tujuan, penanda `sessionStorage` `autograde.pasang` kedaluwarsa 25 mnt, tirai mengalah pada gerbang login), Diagnostik (fps terukur, umur gambar, PLC ✓ hanya kalau `plc.connected`, disk, lisensi, versi / model, `capture_save_dropped` + `tp_telat` harus nol; pembantu `diag*`, test `test_console_html_diagnostik_jujur.py`), Antrean line, Antrean ERP, Manifest R2 (sub-tab sendiri; `.status-judul` dibuang 2026-10-05; bar ringkasnya hilang lewat `:has()` selama R2 belum disetel). Kartu Diagnostik berkelompok dan bisa dibuka-tutup: `<details class="diag-kelompok" data-grup=...>` + `<summary class="diag-grup">`, TERTUTUP dari awal, kelompok yang dibuka diingat di `diagTerbuka` (localStorage) dan dibuka lagi sesudah tiap gambar ulang 5 dtk di `muatDiagnostik`, judul kelompok merah lewat `:has(dd .tanda-gagal)` supaya galat tidak tersembunyi; dulu `<h3 class="diag-grup">` (Kamera dan gambar, Mesin, Data, Workers + hitungan `n/m`) masing-masing diikuti `<dl>`-nya; nilai panjang turun baris, tidak dipotong `…` |
| Akun | support | `muatAkun` | akun lokal/AutoERP, tombol aksi berwarna, semua tombol aksi satu lebar (`--lebar-tombol-akun`, satu aturan `#sec-akun :is(...) button`) |
| Line | support | `muatLine` → `MUAT_SUB_LINE[subLine]` | Sumber Kamera, Model Deteksi, Uji PLC (1 dtk), Rekam Video (3 dtk); empat sub-tab `#line-sub` = grid 4 kolom selebar panel, 2 x 2 di bawah 600 px |
| Setelan | support | `muatSetelan` (+ `muatPenugasan`); satu kartu per sub-tab (sejak 2026-10-08 tiap kategori = `details.setelan-bagian[data-bagian]` selebar penuh, bertumpuk, judul `summary.setelan-bagian-judul`; `#sec-setelan .setelan-form` tanpa bingkai; sub-tab satu kategori `open` dari markup; yang dibuka diingat `setelanTerbuka`; field yang ditolak membuka panelnya; tes browser membuka semua panel lewat `buka_setelan`; sub-tab `#setelan-sub` sejak 2026-10-05 (`SUB_SETELAN`, `terapkanSubSetelan`, diingat `subSetelan`): grading/kamera/dev di satu form `#setform-utama` dengan satu Simpan, penugasan/scanner/slip/harikerja/bahaya form sendiri (sub-tab `scanner` = saklar Scanner QR, `#set-scanner` + `#set-scanner-simpan`, `muatScanner`, `GET/POST /api/console/dev/scanner-qr`) (sub-tab `dev` (Mode Developer) punya saklar **Timbangan dummy** sejak 2026-10-07: `#set-dummy` (disimpan `#set-simpan` kalau berubah dari `dummyTersimpanNilai`, sejak 2026-10-08 tanpa tombol sendiri), `GET/POST /api/console/dev/timbangan-dummy`, pita oranye `#pita-dummy` di semua tab dari `s.timbangan_dummy`, scan menyimpan 30.000 / 10.000 kg) (sub-tab `harikerja` = cutoff hari kerja, batch 5.11); tes browser buka lewat `buka_setelan(page, sub)` di `tests/browser/langkah.py`; penugasan otomatis bawaannya NYALA (konsol sesi browser menyimpan mati sekali di `conftest._penugasan_manual`) | setelan grading, garis capture, dua saklar tampilan `#set-tampil-garis` / `#set-tampil-roi` (2026-10-04: sembunyikan GAMBAR garis capture dan kotak ROI di video untuk semua line; deteksi dan pemotretan tidak berubah; bawaan nyala, `r.tampil_* !== false` supaya server lama tetap tercentang); grup Kamera & Conveyor = tiga panel `conveyor`, `garis`, `kotak` (empat sisi kotak satu baris, 2 x 2 di bawah 700 px); kotak area deteksi (ROI) diatur lewat `#set-roi-x1/y1/x2/y2` (`KOTAK_ROI`): keempatnya kosong dikirim `null` = line memakai `ROI_*` dari `.env`, `0` semua = seluruh gambar, `domain/setelan_grading._kotak` menolak kotak tanpa luas; bawaan PC (`.env` line) dari `GET /api/console/dev/roi-bawaan` (`muatRoiBawaan`, tidak ditunggu `muatSetelan`) jadi placeholder dan kalimat `#set-roi-bawaan`, tombol `#set-roi-reset` (`button.bahaya`) mengosongkan keempat kolom lalu toast peringatan "klik Simpan"; kotak **Conveyor & tampilan** di Kamera & Conveyor (2026-10-05; sempat sub-tab sendiri, pindah atas permintaan user): `#set-ukuran-label` = ukuran tulisan label di video dalam persen, 25 sampai 400, `r.ukuran_label ?? 100` untuk server lama, dikirim sebagai `ukuran_label`; tes `tests/browser/test_browser_setelan.py`, **Penugasan line** (saklar + line pilihan, tombol simpan sendiri, `GET/POST /api/console/dev/auto-assign`, hasil simpan lewat toast), **Hari kerja** (`#set-cutoff` + `#set-cutoff-simpan`, `muatCutoffSetelan`, batch 5.11), Danger Zone. Selalu paling kanan |

- Data segar tanpa refresh (batch 5.3, 5.4, 5.8, 6.4; 2026-10-04):
  - `refresh` mengambil giliran lewat `kunciRefresh` (`kunciAntre`): satu tarikan pada satu
    waktu, panggilan sesudah aksi antre di belakang yang sedang jalan. Timer memanggil
    `detakRefresh` (detak dibuang selama masih ada tarikan); `muatTrucks` dan `muatTimbangan`
    dibungkus `sekaliJalan`. Tanda tangan `async function refresh()` jangan diubah: banyak tes
    memotongnya lewat teks itu, dan tes browser memanggil `refresh()` langsung.
  - `ambil` memberi setiap permintaan batas waktu (`AbortSignal.timeout(batasJawab(opts))`:
    GET 10 dtk, yang lain 60 dtk); habis waktu = `konsol_putus`. Tes node yang menjalankan
    `ambil` harus ikut membawa `batasJawab` dan dua konstantanya.
  - Kartu line diperbarui lewat satu fungsi, `perbaruiKartu(c, l)`, semuanya `tulisKalauBeda`:
    `.truk`, `.slot-lepas`, `.slot-piston` (`display:contents`), `.slot-pita-piston`, `.slot-ai`.
    Render pertama memanggilnya juga supaya poll berikutnya punya pembanding. Pemilih truk kartu
    (`.assign .pilih`) mengikuti truk yang ditugaskan dari tempat lain lewat `ikutiPenugasan`
    (2026-10-06): cuma saat truk tugasnya berubah (`c.dataset.trukTugas`) dan daftarnya tertutup. Tabel Grading
    (`#recent`) dan nomor halamannya ditulis lewat `tulisKalauBeda`; `/api/console/state` tidak
    lagi membawa `recent`, sumbernya cuma `/api/console/history`.
  - Dropdown yang sudah di layar diisi ulang lewat `isiUlangPilih(root, opsi)` (baris dari
    `barisPilih`, pilihan dipertahankan, daftar yang sedang terbuka dilewati sampai tertutup).
    Daftar truk kartu: `opsiTrukKartu` + `segarkanPilihTruk` (dipanggil `isiTrucks` dan tiap poll).
  - Line bertambah atau berkurang di server = kartu digambar ulang (`kartuSesuai`, `daftarSama`).
  - `cekVersiBaru(s.versi)`: versi beda dari saat halaman dimuat = `location.reload()`, ditunda
    selama `amanMuatUlang()` palsu (dialog terbuka, tombol `.sibuk`, isian sedang diketik).
    `/console` dikirim dengan `Cache-Control: no-cache`.
  - Indikator basi: `catatSegar(berhasil)` dari `refresh` (bukan untuk `belum_masuk`),
    `#segar` di bawah jam (`segarPada` / `basiSejak`), `GAGAL_SAMPAI_BASI` 3 poll gagal =
    `body[data-basi="1"]` yang mengabu-abukan `#tally`, `.counts`, `.card .body`, antrean bongkar
    dan semua tabel (bukan `.feed`: gambar kamera datang dari line).
  - Tombol `#segarkan` di header (`segarkanSemua`): semua poll + pemuat tab yang terbuka.
    Ganti bahasa juga memuat ulang tab yang terbuka (`muatUlangTabTerbuka`), kecuali Setelan dan
    Line (`TAB_TANPA_MUAT_ULANG`: form, isian support tidak boleh hilang).
  - Tes: `test_console_html_data_segar.py`, `tests/integration/test_data_segar_integrasi.py`,
    `tests/e2e/test_data_segar_lane.py`, `tests/browser/test_browser_data_segar.py`.
- Penugasan otomatis (aturan 36): strip **Antrean bongkar** `#antrean-bongkar` di atas kartu line di tab
  Grading (`htmlAntreanBongkar` / `gambarAntreanBongkar`, tombol `data-aksi="pasang"|"lewati"`,
  routes `/api/console/unloading-queue/{id}/assign|skip`), dari kunci `antrean_bongkar` dan
  `penugasan_otomatis` di `/api/console/state`; strip cuma tampil saat saklar nyala (D13).
  Jawaban timbang, Lepas, dan simpan saklar membawa `dipasang` (per line `terpasang`, plus
  `tertahan` + `plate_lama` untuk line yang masih memegang truk yang sudah keluar), jangan pernah namai variabel tingkat atas `dipasang` (sudah dipakai
  "kartu line tergambar"). Bukan "Antrean line": itu antrean janjang line ke konsol (tab Status).
  Toast pelepasan otomatis (`umumkanPelepasanOtomatis`) diumumkan sekali per id per tab browser:
  id yang sudah diumumkan disimpan di `sessionStorage` `autograde.pelepasanDiumumkan` (200 terakhir),
  jadi muat ulang sesudah Update now tidak mengulangnya dan toast "terpasang" tidak terdepak dari
  `TOAST_MAKS` (2026-10-08).
  Tes: `test_console_html_antrean_bongkar.py`, `tests/browser/test_browser_penugasan.py`.
- Tombol **Sambung ulang** kamera (2026-10-04, semua akun) di `<h2>` kartu line, di sebelah
  ONLINE/OFFLINE (`tombolSambungUlang`, 44 px; di kartu sempit cuma ikon lewat
  `@container (max-width:460px)` pada `.card h2`). Klik → `sambungUlangKamera`: tanya dulu
  (`tanyaKonfirmasi`), lalu `denganSibuk` + `POST /api/console/lines/{kode}/reconnect-camera`
  (route `routes/console_kamera.py`) → `toastSukses`; kode `kamera_tanpa_sambung_ulang`
  (video/foto) dan `line_tidak_menjawab`/`line_menolak` lewat `gagalKarena`. Tanda sibuk juga
  disimpan di `sambungUlangBerjalan`, jadi kartu yang digambar ulang (`dipasang = false`) di
  tengah permintaan tetap sibuk. Line cuma memasang bendera; `FrameCaptureWorker` yang
  menyambung ulang di bawah `state.lock`. Tes: `test_console_html_sambung_ulang.py`,
  `tests/browser/test_browser_sambung_ulang.py`.
- Baris tombol kartu line `.assign` (2026-10-04) = grid empat kolom sama lebar: pemilih truk dua kolom
  (persis selebar Reject Manual di `.aksi-line`), Tugaskan dan Lepas / Lepas paksa satu kolom
  masing-masing; label panjang turun baris di dalam tombolnya.
- Tombol **Lepas paksa** (2026-10-04, aturan 13, semua akun) menggantikan Lepas di slot
  `.slot-lepas` (`display:contents`) selama `l.plc.reachable === false` dengan `sebab_kode`
  `tak_terjangkau` DAN kartu memegang truk (`bisaLepasPaksa`, `tombolLepas`, `bahaya pekat`,
  `data-aksi="lepas-paksa"`). Slot ditulis ulang tiap poll lewat `tulisKalauBeda`. Klik →
  `lepasPaksa`: `tanyaKonfirmasi({bahaya: true})`, lalu `denganSibuk` +
  `POST /api/console/lines/{kode}/force-release` (`routes/console_lepas_paksa.py`); `paksa: true`
  = `toastPeringatan` `sukLepasPaksa` (sampai konsol saja), `paksa: false` = `toastSukses`
  `sukLepas`; gagal lewat `gagalKarena("gagalLepasPaksa", e)`. Tanda sibuk juga di
  `lepasPaksaBerjalan`. Tes: `test_console_html_lepas_paksa.py`,
  `tests/browser/test_browser_lepas_paksa.py` (line palsu `atur_diam`).
- Baris tabel Timbangan (aturan 37, 2026-10-03): baris **Datang** (`barisMenunggu`) membawa tombol
  merah **Batal datang** (`button.bahaya`, `data-aksi="batal-datang"`, `data-arrival` = `id` dari
  `waiting`); `batalDatang` dua klik seperti Batalkan impor (`yakin pekat`, 5 dtk), `denganSibuk`,
  `POST /api/console/arrivals/{id}/cancel` → `dibatalkan` = `toastSukses`, `tidak_ada` =
  `toastPeringatan`. Tiket yang server tandai `tanpa_scan_4` (bertara, tidak pernah Keluar, lewat
  24 jam atau truknya datang lagi) berlencana Selesai dan `aksiTiket` menaruh `.tag.peringatan`
  **tanpa scan 4** di tempat tombol Keluar. Tes: `test_console_html_batal_datang.py`,
  `tests/browser/test_browser_batal_datang.py`.
- Riwayat Batal datang (round 4, 2026-10-03): `<details id="riwayat-batal">` di bawah tabel
  Timbangan, `hidden` selama `dibatalkan` (dari `GET /api/console/weighings`) kosong.
  `gambarRiwayatBatal` (dipanggil `muatTimbangan`) cuma menulis `#riwayat-batal-judul` dan
  `#riwayat-batal-isi` lewat `tulisKalauBeda`, tidak pernah `<details>`-nya, jadi buka/tutup
  bertahan melewati poll 15 dtk; `barisBatal` = Plat, Jam datang, Jam dibatalkan, Oleh
  (`cancelled_by_name`, nama yang disimpan saat batal, email jadi `title`; tanpa nama = email).
  Kolom terakhirnya dilepas dari paku `#sec-timbangan td:last-child`. KAMUS `riwayatBatalJudul`,
  `thJamDatang`, `thJamBatal`, `thOleh`. Tes: `test_console_html_riwayat_batal.py`,
  `tests/browser/test_browser_riwayat_batal.py`.
- Slip grading (batch 5.9): saklar support `#set-slip` + `#set-slip-simpan` di Setelan
  (`/api/console/dev/slip`, `services/slip_grading.py`, kunci `sync_state` `setelan_slip_cetak`, ikut selamat dari Danger Zone, bawaan
  mati). `/state` membawa `slip_cetak` -> `aturSlipCetak` -> `slipCetak`; berubah = tabel Rekap
  digambar ulang. Baris truk Rekap (`barisRiwayatTruk`) dapat tombol `data-cetak` selama nyala.
  `cetakSlip`: `GET /api/console/slip` (server menolak 403 `slip_mati` kalau mati, aturan 21)
  -> `htmlSlip` ke `#slip-cetak` (anak langsung `body`) -> `body[data-cetak="slip"]` ->
  `window.print()`; `afterprint` mencabut atributnya. Aturan `@media print` kartu QR hanya
  berlaku tanpa atribut itu, jadi dua mode cetak tidak bentrok. Angka slip dari server (L4).
  Tes: `test_console_html_slip.py`, `test_slip_grading.py`,
  `tests/integration/test_slip_grading_integrasi.py`, `tests/e2e/test_slip_grading_lane.py`,
  `tests/browser/test_browser_slip.py`.
- Cutoff hari kerja (batch 5.11): `#set-cutoff` (`<input type="time">`, 00:00 sampai 23:59; lewat 12:00 `cutoffPerluTanya` -> `tanyaKonfirmasi` dengan contoh efeknya; zona dari `/state` `timezone` di `#set-cutoff-zona`) +
  `#set-cutoff-simpan` di Setelan (`GET/POST /api/console/dev/shift`, `services/hari_kerja.py`,
  kunci `sync_state` `setelan_cutoff_shift`, ikut selamat dari Danger Zone, bawaan 00:00). `/state`
  membawa `cutoff_shift` -> `aturCutoffShift` -> `cutoffShift` + label `#riwayat-cutoff` di kepala
  tabel Rekap (`teksCutoffRekap`, kosong dan tersembunyi kalau 00:00; ganti bahasa membacanya
  ulang). Judul Rekap `#riwayat-judul-rentang` dari `judulRentangRiwayat` (satu hari ditulis
  sekali, "Hari kerja ..."). `refresh` cuma menyimpan `zonaPabrik`; `#set-cutoff-zona` diisi
  `muatCutoffSetelan`, karena tab Setelan dicabut dari halaman untuk operator (`data-dev`). `#set-cutoff-simpan` mati sampai `muatCutoffSetelan` berhasil (kolom kosong akan
  menyimpan 00:00). Tanggal kerja tetap dari server (`work_date` di `/state`, aturan 10); layar tidak
  menghitung apa pun. Tes: `test_console_html_cutoff.py`, `test_working_day_cutoff.py`,
  `test_hari_kerja.py`, `tests/integration/test_cutoff_shift_integrasi.py`,
  `tests/e2e/test_cutoff_shift_lane.py`, `tests/browser/test_browser_cutoff.py`.
- Tab Grading (batch 5.10, 5.12): saringan `#grading-line` dan `#grading-truk` (komponen
  dropdown, diisi `segarkanSaringGrading` dari `refresh` dan `isiTrucks`), nilainya di
  `gradingSaring` (memori, tidak disimpan), permintaan dirakit `paramGrading`; ganti saringan =
  halaman 1 (`gantiSaringGrading`). Sel foto tabel Grading dan Riwayat satu fungsi, `selFoto`:
  `<img>` = `thumb_url` (400 px dari folder `thumb/`, dihitung server di
  `services/tampilan_baris.py` `_with_foto`), `data-foto` = foto penuh untuk dialog; foto kecil
  yang gagal dimuat jatuh sekali ke foto penuh (listener `error` fase capture, `data-penuh`).
  Tes: `test_console_html_grading_saring.py`, `tests/integration/test_grading_saring_integrasi.py`,
  `tests/e2e/test_grading_saring_lane.py`, `tests/browser/test_browser_grading_saring.py`.
- Sesi geser (batch 5.7, aturan 19): `tandaiAktif` (pointerdown/keydown, capture) menandai
  aktivitas; `pantauSesi` tiap 1 dtk mengirim `perpanjangLatar()` (= `perpanjangSesi(null)`
  dibungkus `sekaliJalan`) kalau `perluPerpanjang` (aktif DAN 5 menit sejak renew terakhir, atau
  sisa 15 menit atau kurang). Akhir sesi disimpan di jam browser (`sesiBerakhirPada`, dari
  `sisa_detik` login, `/me` dan renew lewat `aturSisaSesi`); sisa nol = `cekSesiLatar()` dulu,
  bukan langsung gerbang (tab lain di browser yang sama bisa sudah memperpanjang). Pita
  `#pita-sesi` + tombol `#pita-sesi-perpanjang` (toast cuma dari tombol). Polling tidak boleh
  memanggil renew atau `tandaiAktif`. Login dihitung sebagai renew. Route:
  `routes/console_sesi.py` (`POST /api/console/session/renew`, `pasang_cookie_sesi` dipakai juga
  oleh login). Tes: `test_console_html_sesi_geser.py`, `test_operator_login.py`,
  `tests/integration/test_sesi_geser_integrasi.py`, `tests/e2e/test_sesi_geser_lane.py`,
  `tests/browser/test_browser_sesi_geser.py`.
- Satu komponen tooltip (user 2026-10-05): `data-t-tip="<kunci KAMUS>"` di elemen apa pun;
  `terapkanBahasa` mengisi `data-tip`, CSS `[data-tip]::after` menggambarnya di bawah elemen saat
  hover/fokus keyboard (jeda .35 dtk). `data-tip-sisi="akhir"` untuk elemen dekat tepi kanan
  (`::after` cuma digambar saat hover/fokus, jeda lewat `animation`: tooltip tersembunyi yang tetap punya kotak melebarkan halaman 390 px). Jangan pakai `::before` (spinner
  `button.sibuk`) dan jangan `title` untuk tombol yang sudah punya tooltip. Dipakai empat tombol
  `#topbar .aksi` (`tipSegarkan`, `tipBahasa`, `tipTema`, `tipKeluar`); `#topbar` diberi `z-index:30`.
- Isi panel selebar panelnya (2026-10-05): tidak ada `margin:0 var(--pad)` di dalam `.panel`
  (dulu indentasi ganda; Rekam Video, Akun, Log, Manifest, konfirmasi PLC sudah diluruskan).
- Satu komponen sub-tab (user 2026-10-05): `<div class="line-sub-bar"><div class="sub-tab" id=...
  role="group">` dengan `button[data-sub]` + `aria-pressed`, dipakai Setelan, Line, Status, dan
  tampilan Rekap (`.sub-tab.riwayat-tampilan`). Garis bawah, bukan tombol: yang terbuka
  teks `--merek` dan garis bawah 3 px `inset 0 -3px 0 var(--merek)` (biru merek, sejak PR 5). `.line-sub-bar` tanpa padding samping, jadi barnya
  selebar isi panelnya (dijaga `test_sub_tab_bars_span_their_panel`); tiap bar cuma
  menyetel jumlah kolomnya. Sub-tab baru: pola `SUB_*` + `terapkanSub*` + `simpan/baca` seperti
  `SUB_SETELAN`. Jangan pakai `.log-level` untuk sub-tab: itu tombol saring.
- Satu komponen dropdown untuk seluruh konsol (batch 5.6, 2026-10-05): tidak ada `<select>`
  bawaan lagi (`test_console_html_pilih_cari.py` menjaganya). Bentuknya `.pilih` dengan
  `data-nilai`, `.pilih-tombol` dan `.pilih-panel`; kerangkanya ditulis di markup, isinya lewat
  `isiUlangPilih(root, opsi)` (jangan `outerHTML = komponenPilih(...)`: itu menutup daftar dan
  membuang fokus). Baca nilainya dari `root.dataset.nilai`, setel tanpa event lewat
  `aturPilih(root, v)`, dengan event lewat `pilihNilai`; dengarkan event `pilih`, bukan `change`.
  Opsi boleh membawa `grup` (kepala bagian), `catatan`, `mati` (tampil tapi tidak bisa dipilih,
  `aria-disabled`) dan `judul` (alasan, jadi `title`). Jangan bungkus `.pilih` dengan `<label>`
  (klik pada baris diteruskan ke tombolnya dan membuka daftar lagi): pakai `<div class="label">`.
  - Ketik untuk mencari: daftar dengan `AMBANG_CARI` (8) opsi ke atas mendapat `.pilih-cari`
    selama terbuka (`pasangCari` di `bukaPilih`, dicabut `lepasCari` di `tutupPilih`, jadi panel
    yang tertutup isinya cuma baris). `cocokCari` mengabaikan huruf besar-kecil, spasi, titik
    dan tanda hubung; `hasilSaring` menjaga kepala bagian cuma tampil selama ada baris di
    bawahnya; papan ketik berjalan di `opsiTampak`. Baris tersaring memakai atribut `hidden`.
  - Truk di lokasi dulu: `GET /api/console/trucks` membawa `di_lokasi` (server yang menentukan,
    `store.trucks_with_open_ticket`), `opsiTrukKartu` menaruhnya di bagian `grupDiLokasi`.
  - Tes: `test_console_html_pilih_cari.py`, `tests/integration/test_pilih_truk_integrasi.py`,
    `tests/e2e/test_pilih_truk_lane.py`, `tests/browser/test_browser_pilih_cari.py`.
- Registri: `TAB_SAH`, `SUB_LINE`, `MUAT_TAB`, `MUAT_SUB_LINE`. Tab lama yang tersimpan di
  localStorage dipetakan `tabDariSimpanan` / `TAB_LAMA` (riwayat → rekap, diagnostik/antrean/versi
  → status, empat layar per line → line + pilihannya).
- Timer cuma untuk yang terlihat: semua dihentikan dan dinyalakan ulang di `bukaTabDev`.
- Peran: elemen `data-dev="1"` dibuang dari DOM untuk non-support dan dikembalikan saat support
  masuk (`aturTabDeveloper`); `pastikanTabTersedia` menjatuhkan tab yang hilang ke Grading.
  Ini cuma kerapian: backend yang menjaga (`require_support`, 403).
- Header: perusahaan lalu versi + lisensi di bawah AUTOGRADE untuk semua akun (`teksInfoSistem`, data dari
  `/api/console/state`: `versi`, `lisensi`), huruf sama dengan nama perusahaan (bukan monospace),
  TANPA tanggal (Lampung 2026-10-08: `#hari-kerja` dibuang, jam sudah menyebut tanggal). Nomor token
  tidak pernah ke layar operator.
- Demo hidup (`DEMO_MODE`, 2026-10-09, blok `// ── demo hidup` di `console.html`): `s.demo_mode` di
  `/api/console/state` menyalakan simulasi khusus browser (foto kamera `GET /demo/frame-1..5.webp`
  + `frames.json`, angka, baris Grading halaman 1 tanpa saringan, strip foto kartu, kotak
  Timbangan); tidak ada yang disimpan atau dikirim. `console_deps.get_demo_mode` sengaja tanpa
  cache. Foto dibuat ulang dengan `scripts/buat-frame-demo.py`. Test: `test_console_html_demo_hidup.py`,
  `test_demo_frames.py`, `test_demo_mode_setting.py`, `tests/browser/test_browser_demo_hidup.py`
  (`KonsolUji(..., env=)`).

- Tombol (2026-10-08, pemilik: "semua tombol berikon, ukurannya seragam"): tombol aksi membawa
  `data-ikon="<nama>"`; ikonnya mask CSS di `button[data-ikon]::before` (warna teks, tidak hilang
  saat `data-t` menulis ulang teks), daftar gambarnya ditulis `scripts/ikon_tombol.py` di antara
  penanda `ikon-tombol:mulai/selesai`. Tombol dari JS cukup membawa atributnya. Saat `.sibuk`,
  spinner menggantikan ikon. Tab, sub-tab, chip saringan, pemicu dropdown, foto, dan tombol
  Lihat di dalam kolom sandi (`.sandi-lihat`, wajahnya kata, lebar 5rem): tanpa ikon.
  Ukuran: `--tinggi-tombol` 44 px untuk semua tombol, `--lebar-tombol` 9.5rem minimal untuk tombol
  berikon (specificity nol lewat `:where`, jadi aturan lokal seperti `.assign button` menang;
  tombol di sel tabel, `.antrean-aksi`, `.truk-grup` dibebaskan, `min-width:0`); ikon dua tombol
  antrean disembunyikan di bawah 1600 px (kolomnya ±190 px di 1366). Timbangan pakai
  `--lebar-aksi-timbang` 11.5rem supaya "Record arrival" satu baris di 1366 px. Reject + Piston
  tetap SAMA LEBAR dan 52 px (`test_browser_data_segar`); padding, jarak, pintas, dan huruf Reject
  (.9rem) dirapatkan supaya "Manual Reject" + pintas satu baris di 1680 px. Di menu ⋯ kartu, pemilih truk satu baris penuh, Tugaskan / Lepas berbagi baris kedua.
  Tes: `tests/unit/test_console_html_ikon_tombol.py`, `tests/browser/test_browser_tampilan_lampung.py`.
- Popup scan `#scan-popup`: latar padat (kartu + warna langkah), warna dan nomor dari
  `data-langkah` = kolom papan Timbangan (datang abu, timbang_isi kuning, timbang_kosong biru,
  keluar hijau), gagal merah; plat bergaya pelat. `teksPopupScan` mengembalikan `langkah`.

## Tampilan (sejak 2026-10-07, spec `sawit/docs/superpowers/specs/2026-10-07-autograde-konsol-baru-design.md`)

- Font tertanam: Plus Jakarta Sans (teks, `--font`) dan Barlow Condensed (angka dan plat,
  `--angka`) sebagai woff2 data URI, ditulis `scripts/tanam_font.py` dari `assets/fonts/` (OFL).
  `--kode` = monospace sungguhan untuk log, kode, alamat PLC. Jangan pakai `--mono` (sudah tidak ada).
- Token warna di `:root` dan `:root[data-theme="dark"]`: `--merek` (biru logo, aksi/pilihan/fokus),
  `--ripe --unripe --jk --tp` (kelas; JK ungu), `--panel2`, `--inset`, `--muted2`, `--plat-bg/fg`,
  `--r-kartu` 18px, `--bayang-kartu`. Warna teks wajib 6:1 di atas `--card` di dua tema
  (`test_console_html_token.py`); tambahan `@container` / `container-type` ditolak.
- Rel kiri = `#tabs` (`position:fixed`, `--rel` 96px), ikon + `span[data-t]` (data-t di span,
  bukan di tombol, supaya ikon tidak terhapus). Garis `.rel-pisah` ber-`data-dev="1"` ikut
  dibuang untuk operator. `#menu-samping` menyembunyikan rel (`body.menu-tutup`, `localStorage.menuSamping`);
  rel tersembunyi `visibility:hidden` sesudah geser .28 dtk, jadi tombolnya keluar dari urutan Tab.
- Kaki rel: `.rel-akun` = `#operator-inisial` (`inisialNama`), `#operator-aktif`, `#keluar`
  (`data-tip-sisi="atas"`, warna bahaya tetap). Gaya rel cuma untuk `#tabs button[data-tab]`.
  Kepala satu baris: `.tata` ikon saja (teks `.pilih-teks` sr-only), `#segarkan` / `#bahasa` /
  `#tema` tombol bulat, `#tz` disembunyikan di bawah 1600 px. Semua kontrol kepala (pil, jam,
  `.tata`, tombol bulat, `#menu-samping`) setinggi `--tinggi-kepala` 48 px (2026-10-08); jam +
  `#segar` dirapatkan supaya muat.
- `terapkanTab` menulis `body[data-tab]`; judul `#judul-tampilan` tetap "AutoGrade" (pemilik 2026-10-07, tanpa logo biru). `#tally` dan `#lines`
  cuma tampil di Grading (`display:none`, tidak dibuang: Spasi+n dan P+n tetap jalan).
- Kepala: `#perusahaan` (`lisensi.perusahaan`), `#info-sistem`, pil `#sinkron-erp` /
  `#sinkron-cloud` (kelas `sinkron-baris pil <keadaan>`), jam, `.tata` (Grading saja). Pita di
  bawah kepala. TIDAK ada pil PLC: `/internal/status` cuma membawa `piston.requested`, bukan
  sambungan PLC (`connected` hanya di `/health/detail`), jadi pil akan hijau walau kabel putus.
- Strip foto cuma diambil saat `tab === "grading"` dan tab browser terlihat; Lepas di kartu
  truk dijaga `lepasTrukBerjalan` (tekan kedua ditolak walau kartunya digambar ulang).
- `#tally` = tiga `.ringkas`: hari (`#tot-all`, `#tot-rate`, `#bar-kelas` dari `htmlBarKelas`),
  `#tally` = grid yang sama dengan `#lines` (tiga kolom sejajar kartu line). `#timbang` (ikut tema lewat `--timbang-bg/fg/garis/jejak*`, isi bar dan titik kelas pakai `--ripe-isi` dkk, `#timbang-jejak` 24 bacaan `catatJejak`/`htmlJejak`,
  `#timbang-saran` dari `SARAN_TIMBANG[keadaan]`), dan truk (`#truk-di-line` dari
  `htmlTrukDiLine`, Lepas = `lepasTruk` = `release-truck` per line berurutan; `#antrean-bongkar`
  tampil selama penugasan otomatis nyala, kosong pun). `#tot-neto`/`#tot-tiket` di `#sec-timbangan`.
  Tombol kartu truk dan antrean 44 px; `.truk-grup-atas` dan `.antrean-aksi` boleh membungkus
  (di 1366 px separuh kartu ±200 px; `test_truck_card_buttons_fit_their_card_at_1366` memalsukan
  `/api/console/state` jadi mode otomatis + satu antrean).
- Kartu line: `.feed` di atas, `h2` (nama + `.sinyal`) melayang di pojok kiri atasnya (karena itu line menggambar pil FPS gelap di pojok KANAN atas sejak 2026-10-08, `pil_fps` di `domain/skala_tampilan.py`, digambar `RealtimeInspectionPipeline.draw_fps`); strip `.strip-foto`
  (empat terbaru per line, `ambilStrip` = `history?line_code=X&limit=4` per line, `button.foto`
  jadi klik membuka `#foto-modal`), `.counts`, `.bar-kelas`, Reject + piston, `details.lagi`
  (menu ⋯: `.truk`, `.assign`, `.ord`; klik di luar atau Esc menutupnya, `tutupMenuLagi`). Tes browser yang klik
  Tugaskan/Lepas/geser memanggil `buka_menu_line(kartu)` dulu (`tests/browser/langkah.py`).
- Pendengar `load`/`error` di `#lines` (fase capture) cuma untuk gambar di `.feed`: kartu juga
  memuat strip foto, dan foto strip dulu menimpa `rasioFeed` serta bisa menandai kartu `putus`
  (ketemu dari CI #257, bergantung urutan tes; `test_a_strip_photo_never_sets_the_camera_shape`).
- Tinggi kamera: `aturTinggiKamera` mengukur sisa jendela ke `--tinggi-tetap`; `#lines .feed`
  `max-height` di layar ≥1100 px, jadi layar pertama Grading tanpa scroll.
- Tabel Grading: baris teratas halaman 1 berkedip sekali (`tr.baris-baru`) kalau janjang baru;
  `gantiSaringGrading` mengosongkan `barisAtasGrading` supaya ganti saringan tidak berkedip.
- Gerbang (PR 4, 2026-10-08): `#gerbang` = grid `.gerbang-hero` (selalu gelap, token lokal
  `--hero-*`; foto per kelas `--foto-masuk-<kelas>` = JPEG ≤ 60 KB, ditulis
  `scripts/tanam_foto_masuk.py` dari `assets/masuk/<kelas>.jpg` + kotak di `assets/masuk/kotak.json`,
  juga `const KELAS_FOTO_MASUK`; `gantiFotoMasuk` tiap 4 dtk menukar `.gerbang-bingkai[data-kelas]`
  selama gerbang tampil (sekarang ripe + unripe; JK/TP tinggal tambah berkas); satu `.gerbang-deteksi`; tiga
  `ul.gerbang-fakta`; judul sampai foto di tengah, `.gerbang-tengah` `justify-items/text-align:center`, pemilik 2026-10-08) + `.gerbang-form` (`.gerbang-kotak` dengan id lama). Di bawah 900 px hero
  dibuang. Chip akun `tombolOperator` = email saja (nama di `title`), `aria-pressed` dari
  `tandaiOperator` (input email + klik chip). `#gerbang-bahasa` (ID / EN) memanggil
  `$("bahasa").click()`; `terapkanBahasa` menandai yang aktif. Tanpa logo dan tanpa angka hidup.
  Bahasa awal `bahasaAwal`: tersimpan > ada jejak konsol (`JEJAK_KONSOL`) = id > browser baru = en;
  langsung disimpan. Fixture tes browser `halaman` menyetel `bahasa=id` lewat `add_init_script`.
- Layar lain (PR 5): pilihan = biru merek (`.sub-tab` garis bawah 3 px `--merek`, tombol cepat
  Rekap = chip `--merek-tint`); kotak di dalam kartu (`.tools`, `.tabel`, `.riwayat-saring`,
  `.riwayat-ringkasan`, `.setelan-form`, `.daftar-definisi`) bergaris `--line`, bukan
  `--line-kuat`. Plat di tabel = `chipPlat(v)` → `<b class="plat">` (`td.key .plat` seukuran
  baris), kosong tetap `dash`. Ringkasan Rekap pakai kelas `ripe/unripe/jk/tp` (JK ungu).
  Timbangan: papan `#papan-timbang` (pemilik 2026-10-08, membalik spec §9 Q3) di antara
  `.tools.timbang-alat.berdiri` dan tabel "Semua tiket": empat `.papan-kolom[data-kolom]`
  (`datang` = `waiting`, `bongkar`/`kosong`/`selesai` dari `tahap`), `gambarPapan` dipanggil
  `muatTimbangan` dan `refresh` (tab timbangan), kartu `kartuPapan`, chip `chipPapan` dari
  `lineTerakhir` + `antreanTerakhir` (`namaLineRingkas`: "Di Line 1, 2, 3"), urutan Bongkar
  `urutBongkar` (di line, lalu antrean), Selesai maks `PAPAN_SELESAI_MAKS` 4 + tombol ke Rekap.
  Tombol `data-papan` memakai alur tabel: `pilihNilai($("plat-timbang"))` + fokus `#bruto`,
  `tanyaTara`, `kirimPergi`. Tanpa endpoint baru.
  `.timbang-kepala` (judul + `.timbang-ubin` Neto hari ini dan Tiket hari ini),
  langkah dengan celah 24 px (panah di celah), `.timbang-form` kartu di atas pita `.tools`.
  Setiap `var(--x)` harus terdefinisi (`test_console_html_komponen.py`; dulu `--r`, `--aksen`,
  `--kartu` hilang dan kolom Setelan jadi bersudut tajam).

## Aturan yang dijaga test (merah kalau dilanggar)

- Tanpa em dash dan tanpa " - " sebagai jeda di teks layar dan KAMUS (`test_console_copy.py`).
- Setiap string layar lewat `KAMUS` dua bahasa, id dan en; kunci tidak boleh dobel.
- Di luar tab Log tidak ada teks galat sistem (keputusan user 2026-10-01, aturan 21): tidak ada
  kode HTTP, alamat, teks server atau exception, nama env, nama berkas, atau kode galat. Pakai
  `alasan(e, kunciKonteks)` / `gagalKarena(kunci, e)`, jangan pernah `e.message`; data mentah
  dari server diterjemahkan dari kode (`sebab_kode`, `error_kind`), teks mentahnya milik tab Log.
  Penjaga: `tests/unit/test_console_html_teks_ramah.py`.
- Elemen `hidden` yang punya aturan `display` butuh aturan `[hidden]{display:none}`
  (`test_console_html_hidden.py`).
- Setiap POST pengubah data ada di dalam fungsi yang memakai `denganSibuk(` (spinner + tolak klik
  kedua, `test_console_tombol_sibuk.py`).
- Nilai dari server masuk HTML lewat `esc()`.
- Satu komponen tombol (coding standard F11): `button` dasar, `button.utama` aksi utama langkah,
  `button.bahaya` untuk batal / hapus / reset / urungkan / lepas / keluar akun, `bahaya pekat`
  untuk eksekusi terakhir; tanpa aturan warna satu-satu (`test_console_tombol_bahaya.py`).
  Aksi yang berhasil selalu menjawab dengan toast (`toastSukses`; tersimpan tapi belum sampai
  ke semua line = `toastPeringatan`), bukan kotak teks.
- Toast menutup sendiri paling lama 10 detik; tidak ada lagi toast yang menunggu ×
  (`test_console_html_toast.py`). Tumpukannya ala Sonner (2026-10-03): terbaru di depan, yang
  lama terlipat (`TOAST_TERLIHAT` 3 dari `TOAST_MAKS` 4 di DOM), kursor atau fokus membuka
  tumpukan dan menahan semua hitung mundur (`bukaTumpukanToast`), geser kanan membuang
  (`pasangGeserToast`). Posisi dari variabel CSS yang ditulis `susunToast`; tinggi diukur sekali
  saat toast dibuat. Kait test tetap: `#toasts`, `.toast.<jenis>`, `.pesan`, `.tutup`
  (`test_browser_toast_tumpukan.py`).
- Tidak ada `confirm`/`alert`/`prompt` bawaan browser (coding standard F12): tanya lewat
  `await tanyaKonfirmasi({judul, pesan, ya, batal, bahaya, asal})` (Promise<boolean>,
  `<dialog id="konfirmasi-modal">`), dan tanya SEBELUM tombolnya dikunci supaya fokus bisa
  kembali (`test_console_html_konfirmasi.py`, `test_browser_konfirmasi.py`).
- Berat live `#timbang-kg` ditulis `tulisBerat(el, v)`: odometer lima kolom (`odometerBerat`, nol
  depan `.redup`, titik ribuan dan "kg" digambar CSS lewat `data-c`), `textContent` tetap persis
  `kg(v) + " kg"`; desimal, negatif, null = teks biasa.
- Angka tally (kartu Janjang hari ini dan `.counts b[data-k]` kartu line) ditulis lewat
  `tulisAngka(el, nilai)`: odometer kalau nilainya berubah, polos untuk tulisan pertama, tab
  tersembunyi, dan gerak dikurangi. `textContent` tetap angkanya (`.odo-baca`).
  Arah gulir ikut arah angka: naik = semua digit yang berubah maju dan 9 menyambung ke 0
  (pita dua putaran, `--dari`/`--ke` baris 0 sampai 19 dari `kolomOdometer`), turun sebaliknya.
- Nama kelas baru dicek dulu terhadap aturan global (`.jam` misalnya `display:flex`); untuk
  keadaan elemen pakai atribut `data-*` seperti toast, bukan kelas umum.
- Aksi baru yang merestart line memanggil `tandaiRestart(lineDirestart(jawaban))` dari
  jawaban server; stream kamera diminta ulang lewat `mintaUlangFeed` saja (cap waktu
  `_dimintaPada` yang dipakai `restartSelesai`).
- Isi yang disegarkan tiap polling ditulis lewat `tulisKalauBeda`, bukan membandingkan
  `el.innerHTML` (`docs/rules.md` aturan 24(d)).
- Tidak ada `https://` di berkas ini.

## Test per bagian

`tests/unit/test_console_html*.py` (`_riwayat`, `_akun`, `_sinkron`, `_tab_gabung`, `_tab_peran`,
`_info_sistem`, `_model`, `_rekam`, `_sumber`, `_alarm`, ...). Pola: potong fungsi dengan
`_fungsi(nama)` (dari `function nama(` sampai `\n}` pertama) lalu jalankan di `node` dengan stub.
Test yang butuh node melewati dirinya kalau node tidak ada; runner CI punya node dan langkah
unit memakai `-rs`, jadi skip terbaca alasannya. Fungsi yang diekstrak tidak membuktikan
seluruh skrip sehat: sebelum PR jalankan juga
`python tests/cek_skrip_konsol.py src/palmgrade/static/console.html` (langkah CI yang sama,
batch 4.3), yang memparse tiap `<script>` utuh seperti browser.

## Cek di browser (tanpa menyentuh punya user)

Alur yang diklik operator dijaga otomatis oleh `tests/browser/` (Playwright, Firefox dan
Chromium, wajib lolos di CI lewat ruleset `ci-wajib-lolos`): `make test-browser`. Resep manual
di bawah untuk yang tidak bisa dinilai test, yaitu tampilan.

Menulis tes browser baru (pelajaran dari #203):
- Fixture `halaman` sudah menggagalkan galat skrip, jawaban 5xx konsol, 404 untuk route API
  yang tidak ada (404 sengaja ber-`detail.code` lolos), dan request ke luar 127.0.0.1.
  Penjaganya jangan dilonggarkan: yang tersandung dilaporkan sebagai bug layar.
- Kalimat dibaca dari layar (`kamus(halaman, kunci)`), tidak disalin ke tes.
- Angka dicek di selnya sendiri (`td.num`), bukan `to_contain_text` satu baris: `8.620` ikut
  cocok di dalam `8.620,5`. Tabel kosong juga satu `<tr>` (`barisKosong`), jadi tunggu sel data.
- Ukur tata letak sesudah data tab tergambar: `halaman.evaluate("(t) => MUAT_TAB[t] ? MUAT_TAB[t]() : null", tab)`.
  `MUAT_TAB` cuma punya enam tab (rekap, log, status, akun, line, setelan); grading, truk dan
  timbangan diisi polling layar.
  `wait_for_load_state("networkidle")` langsung lolos kalau halaman pernah diam.
- Tiap tes dibuktikan bisa gagal sekali (ubah satu harapan, lihat merah, kembalikan).

Jangan pakai port 8100 atau 8001 (milik `make console` / `make line` user). Worktree terpisah,
konsol uji di 8110/8111 dengan `env -i`, `CONSOLE_LINE_HOST=http://127.0.0.2`, data demo lewat
`scripts/seed-console-demo.py --hari 10`, Playwright dengan Chrome sistem. **Matikan konsol uji
begitu selesai.** Aturan bisnis di balik layar ada di `docs/rules.md` aturan 19 sampai 27, plus
28 (keamanan LAN: foto dan piston butuh sesi), 30 (route konsol yang berat pada SQLite tidak
boleh menahan event loop), 31 (Antrean line), 32 (AI mati), 36 (penugasan otomatis) dan 37 (jam
gerbang) yang juga mengatur layar ini.
