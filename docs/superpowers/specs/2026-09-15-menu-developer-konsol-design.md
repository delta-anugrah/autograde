# Menu developer di konsol AutoGrade

Tanggal: 2026-09-15
Status: rancangan disetujui (diperbarui 2026-09-15 — peran dari ERP dinyalakan)

## Masalah

Kalau PC pabrik bermasalah, satu-satunya jalan adalah AnyDesk lalu `docker logs`.
Dua hal membuat itu mahal:

1. **Log hilang saat restart.** Yang paling sering terjadi justru "tadi error,
   saya restart, sekarang normal" — persis saat itu buktinya lenyap.
2. **Banyak sinyal sudah dicatat tapi tidak punya layar.** `/health/detail`
   sudah melaporkan worker, kamera, GPU, PLC, dan antrean outbox;
   `outbox_events.last_error` sudah menyimpan sebab tiap kiriman ERP yang gagal.
   Semua itu hari ini cuma terbaca lewat `curl` di terminal.

Jadi pekerjaan ini sebagian besar **memberi layar pada data yang sudah ada**,
ditambah satu tabel baru untuk riwayat error yang tahan restart.

## Batasan yang tidak boleh dilanggar

- **Konsol harus tetap jalan saat internet putus.** `console.html` nol referensi
  `https://`. Tidak ada menu baru yang boleh memanggil ke luar.
- **Layar operator dibaca dari beberapa meter, di luar ruangan.** Tab yang tidak
  bisa dipakai operator hanya mempersempit layar — karena itu disembunyikan,
  bukan dinonaktifkan.
- **DocType `AutoGrade Operator` milik repo kita**, jadi menambah field peran tidak
  perlu menunggu siapa pun. Tapi Frappe membalas **417** untuk satu field asing di
  `/api/resource`, jadi urutannya terkunci: field di ERP dulu, baru AutoGrade memintanya.

## Keputusan

### 1. Peran akun

Kolom baru di `operators`:

```sql
peran TEXT NOT NULL DEFAULT 'operator'
```

Dua nilai dipakai sekarang: `operator` dan `support`. Kolom sengaja TEXT bebas,
bukan enum, supaya peran lain bisa ditambah tanpa migrasi lagi.

Migrasi memakai jalur `_migrate()` yang sudah ada di `console_repository.py`.
Daftar `(table, column)` di situ hanya bisa `ADD COLUMN ... TEXT` polos, jadi
kolom ini ditambah lewat pass-nya sendiri: `ALTER TABLE operators ADD COLUMN
peran TEXT NOT NULL DEFAULT 'operator'` (diverifikasi jalan di SQLite — baris
lama langsung terisi default). Tidak ada akun yang tiba-tiba naik hak.

`support@autograde.local` di-seed dengan `peran = 'support'` di
`akun_bawaan.py`. Akun bawaan yang sudah terlanjur ada di PC pabrik **tidak
di-upsert ulang** (aturan lama: restart tidak boleh mengembalikan sandi pabrik);
peran untuk baris yang sudah ada diisi lewat satu pass migrasi terpisah yang
menyetel `peran='support'` khusus untuk email itu.

**Penjaga aksesnya di backend, bukan di tampilan.** Menyembunyikan tab hanya
kerapian layar. Setiap endpoint developer memeriksa peran sendiri dan menolak
dengan 403 kalau bukan `support`. Satu dependency FastAPI dipakai bersama oleh
semua endpoint itu, supaya tidak ada yang lupa dipasangi.

`/api/console/me` menambah field `peran` supaya `console.html` tahu tab mana yang
dirender.

### 2. Peran dari ERP — dinyalakan, tapi disaring dari sisi pabrik

DocType `AutoGrade Operator` **milik repo ini sendiri** (`autoerp/erpnext/palm_mill/
doctype/autograde_operator/`), bukan milik Mas Samuel, dan kita punya akses write.
Jadi tidak ada yang perlu ditunggu: field peran ditambah sendiri.

Field baru di DocType: `peran`, fieldtype **Select**, pilihan `operator` / `support`,
default `operator`. Ditambah bersama patch migrasi supaya baris yang sudah ada terisi.
`master_data_worker` menambahkannya ke daftar field yang diminta (§4.A).

**Penyaring `.env` tetap dipertahankan**, dan sekarang defaultnya terisi:

```
ERP_ALLOWED_ROLES=support     # bawaan; kosongkan untuk menolak peran dari ERP
```

Ini satu-satunya rem yang bisa ditarik **dari sisi pabrik**. Kalau akun ERP suatu saat
bermasalah — bocor, salah setel, atau ada yang iseng — PC pabrik bisa dikosongkan
setelannya lalu restart, dan piston aman dalam hitungan menit tanpa menunggu ERP
dibereskan. Tanpa penyaring ini, satu-satunya jalan adalah memperbaiki ERP, dan selama
itu semua PC pabrik terbuka. Biayanya nol: kodenya sama, hanya beda nilai bawaan.

Peran yang datang dari ERP tapi tidak ada di daftar izin dibuang jadi `operator` —
bukan ditolak, supaya akunnya tetap bisa masuk sebagai operator biasa.

**Akun lokal tidak tersentuh.** Aturan lama tetap: tarikan ERP tidak pernah menimpa
baris `asal='lokal'`, dan sebaliknya. Konsekuensinya jelas dan memang diinginkan —
saat internet putus, menaikkan seseorang jadi support dilakukan lewat `make operator`
di PC itu, bukan lewat ERP. ERP untuk sehari-hari, lokal untuk darurat.

**Hanya dua peran.** `operator` dan `support`. Peran ketiga (`developer`) sengaja tidak
dibuat: dari lima menu di §4, tidak ada satu pun yang masuk akal dibuka untuk yang satu
tapi ditutup untuk yang lain — jadi ia akan jadi nama kedua untuk hal yang sama, dan satu
tempat lagi untuk salah setel. Kolom `peran` sengaja TEXT bebas (bukan CHECK constraint)
dan field ERP-nya Select, jadi menambah peran ketiga nanti = satu nilai baru, tanpa
migrasi. Yang akan membenarkan peran ketiga adalah pembagian yang nyata — misalnya
support boleh membaca Log tapi tidak boleh memegang Uji PLC.

### 3. Tabel `log_kejadian`

```sql
CREATE TABLE IF NOT EXISTS log_kejadian (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    waktu       REAL NOT NULL,
    level       TEXT NOT NULL,        -- ERROR | WARNING
    sumber      TEXT NOT NULL,        -- nama logger
    pesan       TEXT NOT NULL,
    detail      TEXT,                 -- traceback, kalau ada
    sidik       TEXT NOT NULL,        -- hash level+sumber+pesan, untuk penggabungan
    jumlah      INTEGER NOT NULL DEFAULT 1,
    terakhir_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_waktu ON log_kejadian (waktu DESC);
CREATE INDEX IF NOT EXISTS idx_log_sidik ON log_kejadian (sidik, terakhir_at DESC);
```

**Hanya ERROR dan WARNING yang masuk.** INFO terlalu berisik dan tidak menolong
saat mencari sebab.

**Penggabungan pesan kembar.** Baris dengan `sidik` sama dalam **60 detik**
terakhir tidak membuat baris baru: `jumlah` dinaikkan dan `terakhir_at`
diperbarui. Ini menjawab kasus nyata — kabel kamera putus menghasilkan error
tiap detik. Tanpa penggabungan, layarnya tidak kebaca dan log lain tenggelam.

**Retensi 180 hari.** Pembuangan dijalankan saat menulis, bukan lewat worker
sendiri, dan dibatasi sekali per jam supaya tidak jadi beban tiap baris.

Tidak ada batas jumlah baris, sengaja. Batas baris berbahaya diam-diam: saat
error membanjir, justru log lama yang penting yang terbuang — persis ketika
dibutuhkan. Batas waktu tidak punya sifat itu.

Perkiraan ukuran: ±300 byte/baris. Pada 200 kejadian/hari (sudah banyak untuk
sistem sehat), 180 hari ≈ 10 MB. `console.db` hari ini 200 KB; disk PC pabrik
ratusan GB.

**Penyaringan rahasia.** Pesan error kadang memuat potongan payload. Sebelum
ditulis, pesan dan detail dilewatkan penyaring yang menutup nilai di dekat kata
kunci rahasia (`password`, `sandi`, `token`, `secret`, `authorization`,
`hash`). Ini wajib: log dibaca lewat AnyDesk dan bertahan 180 hari.

**Handler tidak boleh menjatuhkan aplikasi.** Kegagalan menulis log ditelan
(kecuali dicatat sekali ke stderr). Log adalah alat bantu; ia tidak boleh
menjadi sebab baru matinya line.

### 4. Lima menu

Semua hanya muncul untuk `peran = 'support'`.

| Menu | Sumber data | Baru? |
|---|---|---|
| Log | `log_kejadian` | tabel baru |
| Diagnostik | `/health/detail` | sudah ada |
| Antrean ERP | `outbox_events` | sudah ada |
| Versi & Lisensi | settings + license manager | sudah ada |
| Uji PLC | `plc.inputs()`, `plc.request_piston()` | sudah ada |

**Log** — daftar terbaru di atas, saring per level, kotak cari. Baris gabungan
menampilkan `×jumlah`.

**Diagnostik** — membungkus `/health/detail`: worker hidup/mati, kamera per
line, fps inferensi, GPU, PLC, outbox. Menyegar berkala.

**Antrean ERP** — jumlah nyangkut, `last_error` dan `retry_count` per baris,
plus tombol **Kirim Ulang** yang memanggil `requeue_failed()` yang sudah ada.

**Versi & Lisensi** — versi aplikasi, `machine_id`, status lisensi dan masa
berlakunya.

**Uji PLC** — baca DI apa adanya, dan tombol untuk memicu coil satu per satu.
Gunanya memisahkan "kabel rusak" dari "program salah" saat memasang PC baru atau
menanggapi keluhan piston. Ini satu-satunya layar yang **menulis** ke barang
fisik, karena itu tiga pengaman:

1. **Ditolak saat line sedang memproses truk** — `RuntimeState.current_assignment_id`
   tidak `None` berarti ada penugasan berjalan; tombolnya mati.
2. **Konfirmasi ketik**, bukan sekadar klik setuju.
3. **Tiap penekanan dicatat ke `log_kejadian`** pada level WARNING, memuat email
   penekan, coil mana, dan waktunya.

## Urutan kerja

Lima PR, dua repo. PR 0 di `autoerp` harus lebih dulu karena urutan kontraknya
terkunci. PR 1 berdiri sendiri karena ia pondasi: kalau penjaga aksesnya salah, semua
menu ikut bocor.

| Repo | PR | Isi | Kenapa terpisah |
|---|---|---|---|
| autoerp | **0** | Field `peran` (Select) di DocType + patch migrasi + tes | Harus lebih dulu: AutoGrade tidak boleh meminta field yang belum ada (417) |
| autograde | **1** | Kolom `peran`, seed support, dependency penjaga 403, `ERP_ALLOWED_ROLES`, tarik peran di `master_data_worker`, `me` mengembalikan peran, kerangka tab tersembunyi | Pondasi keamanan, diuji sendiri |
| autograde | **2** | `log_kejadian` + handler + penggabungan + retensi + penyaring rahasia + layar Log | Satu-satunya yang menulis data baru |
| autograde | **3** | Diagnostik + Antrean ERP + Versi & Lisensi | Tiga-tiganya hanya membaca, aman disatukan |
| autograde | **4** | Uji PLC + tiga pengaman | Satu-satunya yang menggerakkan barang fisik |

## Pengujian

- **Peran**: akun lama default `operator`; endpoint developer menolak `operator`
  dengan 403; peran dari ERP di luar `ERP_ALLOWED_ROLES` jatuh jadi `operator`;
  `ERP_ALLOWED_ROLES` kosong membuang semua peran dari ERP; tarikan ERP tidak
  menimpa peran akun `asal='lokal'`.
- **Log**: hanya ERROR/WARNING tertulis; dua pesan identik dalam 60 detik jadi
  satu baris `jumlah=2`; baris lebih tua dari 180 hari terbuang; sandi dan token
  tidak muncul di baris tersimpan; handler yang gagal menulis tidak melempar.
- **Antrean ERP**: tombol kirim ulang memindahkan baris gagal jadi pending.
- **Uji PLC**: tombol ditolak saat `current_assignment_id` terisi; penekanan
  yang berhasil meninggalkan satu baris WARNING di `log_kejadian`.

Semua lewat `pytest`. Layar diuji seperti Fase 4: pytest + Playwright.

Modul konsol sudah masuk scope `ruff check`, jadi berkas baru di jalur konsol
(`routes/console.py`, `services/`, `repositories/console_repository.py`) wajib
lolos lint. Test yang menyentuh HTTP merakit app-nya sendiri dengan dependensi
di-override — **bukan** `create_console_app()`, yang menyentuh `state/console.db`
milik developer.

## Yang sengaja tidak dikerjakan

- **Mengubah konfigurasi lewat UI.** Konfigurasi hidup di `.env` dan itu memang
  tempatnya. UI yang menulis `.env` membuat keadaan PC tidak lagi bisa ditebak
  dari berkas — itu mempersulit dukungan, bukan mempermudah.
- **Mengirim log ke luar** (Discord, cloud). Konsol harus tetap jalan offline;
  jalur lapor masalah sudah ada di repo lain.
- **Peran ketiga (`developer`)**. Lihat §2 — jalannya sudah dibuka, tapi belum ada
  pembagian nyata yang membenarkannya.
