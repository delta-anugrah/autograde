# Danger Zone di layar Setelan — rancangan

Tanggal: 2026-09-25 · Repo: autograde · Status: **disetujui user 2026-09-25** ("langsung lanjut") · Rencana: `docs/superpowers/plans/2026-09-25-danger-zone.md`

## 1. Tujuan

Aksi yang berbahaya atau tidak bisa dibatalkan dikumpulkan di satu tempat di
konsol, khusus akun **support**, supaya teknisi tidak perlu AnyDesk + terminal
untuk hal-hal ini. Pola tampilannya meniru "Danger Zone" di Settings GitHub.

Keputusan user (2026-09-25, jangan ditanya ulang):

- Ada **dua** tombol reset, support yang memilih: **Hapus data transaksi** dan
  **Hapus semua data** (setara `autograde reset-data-fresh`).
- Ditambah tiga aksi lain: **Restart semua line**, **Hapus rekaman video**,
  **Logout paksa semua akun**.
- Setelan grading, garis capture, dan setelan rekam **tetap** di kedua reset.

## 2. Tampilan

Satu kotak berbingkai merah di **paling bawah tab Setelan**, di bawah tombol
Simpan, berupa `<details>` yang **tertutup** saat tab dibuka (layar Setelan
dipakai sehari-hari untuk angka grading; kotak bahaya tidak boleh ikut terbuka).

Isinya lima baris, urut dari yang paling ringan ke yang paling berat. Tiap baris:
judul, satu kalimat akibatnya, dan satu tombol di kanan.

| # | Aksi | Akibat | Konfirmasi |
|---|---|---|---|
| 1 | Restart semua line | tiga line mati ±10 detik lalu hidup lagi | Batal / Jalankan |
| 2 | Logout paksa semua akun | semua sesi dihapus, termasuk layar operator di PC pabrik dan akun yang menekan | Batal / Jalankan |
| 3 | Hapus rekaman video | semua MP4 di folder `videos/` hilang permanen | ketik `HAPUS` |
| 4 | Hapus data transaksi | grading, foto, timbangan, antrean, log hilang permanen | ketik `HAPUS` |
| 5 | Hapus semua data | nomor 4 + akun buatan sendiri + truk & supplier | ketik `HAPUS` |

Menekan tombol **membuka panel di bawah baris itu**, bukan dialog yang menutup
layar (alasan yang sama dengan tara di Timbangan dan konfirmasi Uji PLC: kamera
line dan strip tally tidak boleh hilang dari pandangan). Cuma satu panel terbuka
dalam satu waktu. Panelnya berisi:

- apa yang akan terjadi, dengan angka (mis. "1.234 janjang, 56 tiket, 18.402 foto");
- **hambatan** (merah) — kalau ada, tidak ada tombol eksekusi sama sekali;
- **peringatan** (kuning) — boleh lanjut, tapi dibaca dulu;
- tombol **Batal lebih dulu** (fokus awal jatuh di Batal, jadi Enter tak sengaja
  membatalkan), lalu tombol eksekusi. Untuk aksi 3–5 tombol eksekusi mati sampai
  kolom berisi persis `HAPUS`.

Konfirmasi ketik dipertahankan untuk aksi hapus walaupun Uji PLC sudah
membuangnya (2026-09-24): Uji PLC diulang puluhan kali saat commissioning,
sedangkan hapus data dipakai sekali-sekali dan tidak bisa dibatalkan.

## 3. Dua mode reset

| Isi | Hapus data transaksi | Hapus semua data |
|---|---|---|
| Grading (janjang) + foto bbox/clean/thumb + sidecar | dihapus | dihapus |
| Tiket timbangan, penugasan truk | dihapus | dihapus |
| Antrean line → konsol, konsol → AutoERP, manifest R2, status upload R2 | dihapus | dihapus |
| Log kejadian (tab Log) | dihapus | dihapus |
| Truk + supplier | **tetap** | dihapus, turun lagi dari AutoERP |
| Akun | **tetap** | dihapus; 2 akun bawaan dibuat ulang, akun AutoERP turun lagi, **akun lokal buatan sendiri hilang** |
| Sesi login | **tetap** (tidak ada yang keluar) | dihapus (semua keluar) |
| Kursor tarik AutoERP | tetap | dihapus, supaya semua master ditarik ulang |
| Setelan grading, garis capture, setelan rekam | tetap | tetap |
| `.env` (lisensi), `media.env` (sumber kamera, model) | tidak disentuh | tidak disentuh |
| `license.db` line (penjaga jam lisensi) | **tetap** | **tetap** |
| Rekaman video | tidak disentuh (aksi 3) | tidak disentuh (aksi 3) |
| Data yang sudah masuk AutoERP, foto yang sudah di R2 | tidak disentuh | tidak disentuh |

Beda dengan `autograde reset-data-fresh` di terminal: CLI menghapus seluruh
`state/` dan `artifacts/`, termasuk setelan grading dan `license.db`. Tombol ini
sengaja menyisakan keduanya — setelan grading yang diam-diam kembali ke `.env`
mengubah angka yang dibayar tanpa ada yang sadar, dan `license.db` adalah
penjaga agar jam PC tidak bisa dimundurkan untuk memperpanjang langganan.

## 4. Pengaman sebelum menghapus data (aksi 4 dan 5)

Diperiksa dua kali: di layar saat panel dibuka (supaya support tahu), dan
**di server saat eksekusi** (layar tidak pernah dipercaya).

**Hambatan — menolak (409), tidak ada yang berubah:**

1. Ada line yang tidak menjawab. Line yang mati tidak bisa menghapus datanya
   sendiri, dan line mati justru yang paling mungkin masih memegang grading
   (pelajaran yang sama dengan `antrean_tertunda()` di `autograde.sh`).
2. Ada line yang sedang dipasangi truk — grading sedang berjalan.
3. Antrean line → konsol belum kosong (`outbox_pending > 0`): ada janjang yang
   belum sampai ke konsol.
4. `ERP_URL` terisi **dan** antrean konsol → AutoERP masih punya kiriman
   `pending`: kunjungan yang belum masuk buku AutoERP akan hilang dari
   pembukuan.

**Peringatan — boleh lanjut:**

- Foto yang belum naik ke R2 ikut terhapus — ditulis sebagai peringatan tetap,
  tanpa angka. Menghitungnya dengan benar berarti menyisir seluruh `results/`
  (ratusan ribu berkas di Lampung), karena foto baru belum masuk manifest upload
  sampai tick jam berikutnya; angka dari manifest saja akan terbaca "0" padahal
  belum.
- Kiriman AutoERP yang sudah **gagal** (ditolak ERP) ikut terhapus.
- `ERP_URL` kosong: antrean tidak pernah terkirim ke mana pun, N baris ikut terhapus.
- Khusus "semua": semua orang keluar, termasuk layar operator di PC pabrik;
  akun AutoERP baru bisa dipakai lagi setelah tarikan berikutnya.

**Hapus rekaman (aksi 3):** line yang sedang merekam menolak (berkasnya sedang
ditulis); line yang tidak menjawab dilewati dan disebut di hasil.

**Restart (1) dan logout (2):** tanpa hambatan. Restart memberi peringatan kalau
ada truk terpasang ("janjang yang lewat selama ±10 detik tidak dihitung") —
sama dengan keputusan Model Deteksi: diperingatkan, tidak diblokir — dan kalau
ada line yang sedang merekam (restart container = rekaman berhenti; berkasnya
tetap ada sampai detik itu).

## 5. Cara kerja

### Kenapa line menghapus datanya sendiri, dan saat boot

Konsol tidak bisa menghapus foto line: `artifacts/line-N` di-mount **read-only**
ke konsol. Dan SQLite yang sedang dibuka tidak boleh dihapus dari bawah proses
yang memakainya (proses tetap menulis ke berkas yang sudah di-unlink, layar
masih menampilkan data lama sampai restart).

Jadi line menerima perintah, menulis **penanda** `state/.hapus-data`, lalu
restart dengan mekanisme yang sudah terbukti di Sumber Kamera/Model Deteksi
(`/internal/restart` → `os._exit(0)` → `restart: unless-stopped`). Saat boot,
**sebelum** satu pun store atau worker membuka berkas, line melihat penanda itu:

1. hapus isi `artifacts/` **kecuali `license.db*`** (foto, sidecar, `outbox.db`);
2. hapus isi `state/` kecuali penandanya (`upload_manifest.db`);
3. hapus penanda **paling akhir** — boot yang terputus di tengah menghapus
   ulang saat boot berikutnya, bukan meninggalkan separuh data;
4. `logger.warning` siapa yang meminta dan mode apa.

Kedua mode sama persis di sisi line: line cuma memegang data transaksi.

### Konsol menghapus miliknya di tempat

Konsol tidak restart: semua yang dihapus ada di SQLite miliknya sendiri, jadi
cukup `DELETE` di dalam transaksi lewat store yang sudah terbuka.

- `console.db`: `inspections`, `assignments`, `auto_releases`, `weighings`;
  `sync_state` kecuali `setelan_*` dan (mode transaksi) `erp_cursor_*`.
  Mode semua: + `trucks`, `suppliers`, `operators`, `sesi`, lalu
  `seed_default_accounts()` dan tarikan master data langsung (kalau AutoERP
  disetel; kalau gagal, tarikan terjadwal ≤ `CONSOLE_SYNC_INTERVAL_S`).
- `erp_outbox.db`, `manifest_outbox.db` (kalau ada): semua baris.
- `log_kejadian.db`: semua baris, **lalu** satu baris WARNING jejak (bagian 6).

Daftar tabel ditulis eksplisit per mode, dan ada test yang membandingkannya
dengan `sqlite_master`: tabel baru yang belum diputuskan masuk mode mana
membuat test merah, bukan diam-diam tertinggal atau ikut terhapus.

### Urutan eksekusi hapus data

1. Periksa ulang hambatan (bagian 4). Ada satu → 409, selesai.
2. Kirim `POST /internal/hapus-data` ke ketiga line. Line memeriksa lagi
   penugasan truknya sendiri (yang tahu pasti keadaan line adalah proses line,
   pola yang sama dengan Uji PLC).
3. Tunggu ketiga line benar-benar mati (`/health` tidak menjawab, dicek tiap
   ¼ detik, paling lama 5 detik). Line keluar 1 detik sesudah menjawab, dan
   janjang yang lewat di detik itu masih dikirim ke konsol — menghapus data
   konsol lebih cepat dari itu meninggalkan baris grading yang fotonya sudah
   hilang.
4. Hapus data konsol — **tetap dijalankan** walau ada line yang gagal di
   langkah 2. Line yang gagal disebut di hasil; menekan tombol lagi setelah
   line itu hidup menyelesaikannya (kedua sisi aman diulang).
5. Tulis jejak, jawab dengan hasil per line + jumlah yang dihapus.

### Endpoint

Konsol (semua lewat `require_support`, 401/403 seperti lane dev lain):

| Method | Path | Isi |
|---|---|---|
| GET | `/api/console/dev/bahaya` | angka untuk panel + hambatan + peringatan per aksi |
| POST | `/api/console/dev/bahaya/restart-line` | restart ketiga line, hasil per line |
| POST | `/api/console/dev/bahaya/logout-semua` | hapus semua sesi, balas jumlahnya |
| POST | `/api/console/dev/bahaya/hapus-rekaman` | `{konfirmasi:"HAPUS"}` |
| POST | `/api/console/dev/bahaya/hapus-data` | `{mode:"transaksi"\|"semua", konfirmasi:"HAPUS"}` |

400 kalau `konfirmasi` bukan persis `HAPUS` atau `mode` asing; 409 dengan daftar
kode hambatan kalau diblokir.

Line (lane mesin, `x-internal-secret`, sama dengan `/internal/restart`). Ketiganya
di router baru `routes/internal_bahaya.py` yang dirakit lewat fungsi pabrik dan
tidak mengimpor torch — `routes/internal.py` menarik torch, jadi test untuknya
dilewati di CI, dan fitur yang menghapus data tidak boleh diuji cuma di laptop:

| Method | Path | Isi |
|---|---|---|
| POST | `/internal/hapus-data` | tulis penanda lalu restart; 409 kalau line sedang dipasangi truk |
| POST | `/internal/rekam/hapus` | hapus rekaman **milik line ini** (`{line_code}_*.mp4`); 409 kalau sedang merekam |
| GET | `/internal/rekam/berkas` | jumlah + ukuran rekaman milik line ini, dan apakah sedang merekam |

Tiap line menghapus rekamannya sendiri berdasarkan nama berkas yang ditulis
`VideoRecorder` (`{line_code}_{stempel}.mp4`), jadi tetap benar walau folder
`videos/` dipakai bersama tiga line.

## 6. Jejak

Tiap aksi menulis satu baris WARNING di `event_log` berisi email yang menekan
dan ringkasan angkanya, mis. `[Danger Zone] Data transaksi dihapus oleh
support@autograde.local: 1.234 janjang, 56 tiket, 18.402 foto`. Untuk aksi 4–5
baris ini ditulis **sesudah** log dikosongkan, jadi dia baris pertama di log
yang baru. Line juga mencatat penghapusannya sendiri saat boot.

## 7. Yang tidak dikerjakan

- Menghapus data di AutoERP atau foto di R2.
- Backup otomatis sebelum menghapus (CLI juga tidak).
- Undo. Tidak ada.
- Mengubah `autograde reset-data` / `make reset-data`.
- Menyunting akun (tambah, ganti sandi, matikan) — aturan 19.

## 8. Pengujian

- **Murni:** penilaian hambatan/peringatan dari keadaan line + antrean; cek
  konfirmasi; daftar tabel per mode lawan `sqlite_master`.
- **Store:** hapus mode transaksi dan semua di DB sementara — yang harus tetap
  benar-benar tetap (setelan, akun/truk di mode transaksi), akun bawaan dibuat
  ulang di mode semua.
- **Line:** hapus-saat-boot di folder sementara — `license.db` selamat, penanda
  dihapus terakhir, boot yang terputus mengulang dengan benar.
- **Route:** 401/403, 400 konfirmasi salah, 409 dengan kode hambatan, 200 dengan
  line palsu yang mencatat panggilan.
- **HTML:** kotak bahaya ada di bawah Simpan dan tertutup, Batal lebih dulu,
  tombol eksekusi mati sampai `HAPUS`, kunci i18n di dua bahasa.
- **Browser:** konsol native + tiga line palsu, kelima aksi dijalankan sungguhan.

## 9. Pemasangan

Konsol dan line harus versi yang sama (endpoint internal baru). Keduanya satu
image dan `autograde use <tag>` memasang keempatnya sekaligus, jadi ini hanya
masalah kalau ada line yang ditahan di versi lama — line seperti itu menjawab
404 dan disebut gagal di hasil. Tidak ada perubahan compose atau `.env`.
