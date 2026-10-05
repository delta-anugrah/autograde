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
| Grading | semua | polling `refresh` 2 dtk | 20 grading terakhir hari ini, kartu line merah + pita AI mati / kamera berhenti mengirim dari blok `plc.ai` (`pitaAi`, `perbaruiAi` tiap polling, keadaan `ai_mati` atau `frame_berhenti`, test `test_console_html_ai_mati.py` + `test_console_html_frame_disk.py`); satu pita disk PC untuk seluruh layar dari blok `plc.disk` (`#pita-disk`, `gambarPitaDisk` tiap polling, aturan 35): satu baris (ikon SVG, judul, jam, line, sisa GB; langkah pengosongan cuma di MANUAL dan log line), peringatan berdenyut pelan dan bisa ditutup 24 jam per browser (`localStorage` `pitaDiskDitutupPada`), kritis tidak bisa ditutup; tanda "sedang dinyalakan ulang" di kotak kamera sesudah aksi yang merestart line (`tandaiRestart`, `pantauRestart` 1 dtk, spinner + bar berjalan tanpa hitungan detik, kelas kartu `sedang-restart` menyembunyikan "Kamera tidak tersambung" selama itu, test `test_console_html_restart.py`); strip "Hari ini" berlabel **Data timbangan** (`labelNetoTimbangan`) |
| Truk | semua | `muatTrucks` 60 dtk | master truk, truk manual, kartu QR |
| Timbangan | semua | `muatTimbangan` 15 dtk | tiket, empat langkah berlabel (1 Datang = `arrivals` lewat `POST /api/console/arrivals`, 2 Timbang isi, 3 Timbang kosong, 4 Keluar = `weighings.left_at` lewat `POST /api/console/departures`; aturan 37, tidak pernah ke AutoERP), plat dari daftar **Pilih Truk**, tombol baris **Timbang kosong** lalu **Keluar** (`data-aksi="pergi"`, kolom dipaku di kanan), kolom pertama **Status** (`lencanaTahap(w.tahap)`, warna sama dengan judul langkah; yang menunggu = baris teratas `barisMenunggu`), urut timbang isi terbaru menurut `julianday`, kolom **Antre** / **Total** (`tanpa scan 1` kuning `.tag.peringatan`, strip bukan 0), lencana **Menunggu n** (`#antre`, `gambarLencanaAntre`, plat di `title`) dari `waiting`, dan dropdown langkah 2 dengan bagian **Menunggu timbang** / **Truk lain** (`opsiPlatTimbang`, `isiPlatTimbang`: tidak dibangun ulang saat terbuka); 12 kolom (kepala **Jam timbang isi** / **Jam timbang kosong**); di atasnya strip empat ruas `.langkah-ruas` (pita tahap + kalimat di mana langkah itu dikerjakan, sama lebar dan tinggi, `repeat(4, minmax(0,1fr))` mulai 960 px, 2 x 2 dari 600 px), dua form `.timbang-form` sama lebar (Datang, Timbang isi; berdampingan mulai 1100 px) dengan baris kaki `.timbang-kaki` untuk pesan scan dan petunjuk desimal (juga `title` Bruto), dan bar tara `#tara-grup` selebar panel berwarna langkah 3 (plat, Tara, Simpan, Batal satu baris; ruas `#ruas-kosong` menyala `.aktif` selama terbuka; pesan tara `#scan-keluar-pesan` di bar itu); semua kontrol setinggi `--tinggi-timbang`, tombol utama selebar `--lebar-aksi-timbang`; empat kolom scan `hidden` sampai scanner dipasang (tes browser memunculkannya lewat JS), tanda **Cek AutoERP** untuk janjang susulan pada tiket yang sudah final (`erp_perlu_dicek`, `tests/unit/test_console_html_timbangan_erp.py`) |
| Rekap | semua | `muatRiwayat` (+ `segarkanRekap` 15 dtk) | Rekap + Riwayat: buka di Hari ini, Per truk; Impor CSV support saja |
| Log | support | `muatLog` (+ `muatLaporDiscord`) | ERROR/WARNING 180 hari, konsol DAN ketiga line (tag line-1/2/3 atau konsol), jam pertama muncul untuk baris gabungan, traceback bisa dibuka per baris; kalimat di atas tabel menyebut keadaan lapor ke Discord (`mati`/`url_salah`/`aktif`/`tertahan`/`ditolak`); pesan identik dalam 60 dtk digabung sesudah id yang berganti (uuid, hex 8+, desimal, bilangan 6+ digit) dinormalkan (`domain/sidik_log.py`, batch 3.3); galat 500 uvicorn konsol (termasuk saat start gagal) kini ikut masuk lewat `configure_logging` (batch 3.1) |
| Status | support | `muatStatus` (diagnostik 5 dtk, antrean line 5 dtk) | Versi, Diagnostik (fps terukur, umur gambar, PLC ✓ hanya kalau `plc.connected`, disk, lisensi, versi / model, `capture_save_dropped` + `tp_telat` harus nol; pembantu `diag*`, test `test_console_html_diagnostik_jujur.py`), Antrean line, Antrean ERP, Manifest R2 (judul `.status-judul` sendiri sejak 2026-10-04; bar ringkasnya hilang lewat `:has()` selama R2 belum disetel). Kartu Diagnostik berkelompok dan bisa dibuka-tutup: `<details class="diag-kelompok" data-grup=...>` + `<summary class="diag-grup">`, TERTUTUP dari awal, kelompok yang dibuka diingat di `diagTerbuka` (localStorage) dan dibuka lagi sesudah tiap gambar ulang 5 dtk di `muatDiagnostik`, judul kelompok merah lewat `:has(dd .tanda-gagal)` supaya galat tidak tersembunyi; dulu `<h3 class="diag-grup">` (Kamera dan gambar, Mesin, Data, Workers + hitungan `n/m`) masing-masing diikuti `<dl>`-nya; nilai panjang turun baris, tidak dipotong `…` |
| Akun | support | `muatAkun` | akun lokal/AutoERP, tombol aksi berwarna, semua tombol aksi satu lebar (`--lebar-tombol-akun`, satu aturan `#sec-akun :is(...) button`) |
| Line | support | `muatLine` → `MUAT_SUB_LINE[subLine]` | Sumber Kamera, Model Deteksi, Uji PLC (1 dtk), Rekam Video (3 dtk); empat tombol pilihan `#line-sub` = grid 4 kolom selebar panel, 2 x 2 di bawah 600 px |
| Setelan | support | `muatSetelan` (+ `muatPenugasan`) | setelan grading, garis capture, dua saklar tampilan `#set-tampil-garis` / `#set-tampil-roi` (2026-10-04: sembunyikan GAMBAR garis capture dan kotak ROI di video untuk semua line; deteksi dan pemotretan tidak berubah; bawaan nyala, `r.tampil_* !== false` supaya server lama tetap tercentang); grup Kamera & Conveyor = tiga `<fieldset class="setelan-sub">` (Conveyor, Garis capture, Kotak area deteksi) dalam `.setelan-tiga` (3fr 4fr 5fr mulai 1100 px, satu kolom di bawahnya; empat sisi kotak satu baris); kotak area deteksi (ROI) diatur lewat `#set-roi-x1/y1/x2/y2` (`KOTAK_ROI`): keempatnya kosong dikirim `null` = line memakai `ROI_*` dari `.env`, `0` semua = seluruh gambar, `domain/setelan_grading._kotak` menolak kotak tanpa luas; tes `tests/browser/test_browser_setelan.py`, **Penugasan line** (saklar + line pilihan, tombol simpan sendiri, `GET/POST /api/console/dev/auto-assign`, hasil simpan lewat toast), Danger Zone. Selalu paling kanan |

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
    Render pertama memanggilnya juga supaya poll berikutnya punya pembanding. Tabel Grading
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
- Header: versi + lisensi di bawah AUTOGRADE untuk semua akun (`teksInfoSistem`, data dari
  `/api/console/state`: `versi`, `lisensi`). Nomor token tidak pernah ke layar operator.

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
- Angka tally (strip Hari ini dan `.counts b[data-k]` kartu line) ditulis lewat
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
