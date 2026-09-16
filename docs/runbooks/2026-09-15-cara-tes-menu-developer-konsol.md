# Cara tes menu developer konsol

Ditulis 2026-09-15 malam, untuk dites besok pagi.

Lima layar baru di konsol operator, cuma bisa dibuka akun ber-peran `support`:
**Log**, **Diagnostik**, **Antrean ERP**, **Versi**, dan **Uji PLC**.

Kenapa ada: kalau PC pabrik bermasalah, satu-satunya jalan selama ini adalah AnyDesk
lalu `docker logs` — dan log itu hilang tiap restart. Padahal yang paling sering terjadi
justru "tadi error, saya restart, sekarang normal", persis saat buktinya lenyap.

---

## 0. Siapkan (sekali saja)

PR di `autoerp` harus di-merge **lebih dulu**. Frappe membalas HTTP 417 untuk satu
field yang tidak dia kenal, jadi AutoGrade tidak boleh meminta field `peran` sebelum
field itu benar-benar ada di ERP.

```bash
cd ~/Desktop/Projects/sawit/autograde
git fetch origin
git checkout feat/konsol-peran-support
```

---

## 1. Tes otomatis — 1 menit

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -p no:warnings
```

Harus: **835 passed, 12 skipped, 0 failed.**

⚠️ Pakai `python -m pytest`, **jangan** `.venv/bin/pytest` — shebang-nya bisa menunjuk
venv checkout lain dan diam-diam salah jalan.

12 skip itu wajar: tes yang butuh AutoERP hidup.

---

## 2. Jalankan konsol

```bash
make console        # http://127.0.0.1:8100/console
```

⚠️ Dua jebakan yang sudah pernah makan waktu:
- `make console` memakai `WEBHOOK_SECRET=devsecret` dan **tanpa `--reload`** — ubah
  HTML, jalankan ulang, jangan menunggu auto-reload.
- Port 8100 kadang masih dipegang instance lama yang jalan kode basi. Kalau layarnya
  terasa tidak berubah, cek `lsof -ti:8100` dulu.

---

## 3. Buat dua akun untuk dibandingkan

```bash
make operator                          # email: op@uji  — biarkan peran default
make operator PERAN=support            # email: sup@uji — akun support
```

Sandi bebas, minimal 8 karakter.

Kalau akunnya sudah ada dan cuma mau menaikkan perannya:

```bash
make operator AKSI=peran PERAN=support
```

Di PC pabrik (konsolnya di Docker) pakai `make operator-docker`.

---

## 4. Yang dicek — inti tesnya

### a. Operator tidak boleh lihat apa-apa

Masuk sebagai **op@uji**. Di layar harus tetap **empat tab** seperti biasa:
Grading, Truk, Timbangan, Rekap. **Tidak ada** tab Log/Diagnostik/Antrean/Versi/Uji PLC.

Tab-nya dibuang dari layar, bukan dibuat abu-abu — layar operator dibaca dari beberapa
meter di luar ruangan, tab yang tidak bisa dipakai cuma bikin sempit.

### b. Support melihat sembilan tab

Keluar, masuk lagi sebagai **sup@uji**. Sekarang harus muncul lima tab tambahan.

### c. Yang menjaga itu backend, bukan tampilan

Ini bagian terpenting. Menyembunyikan tab cuma kerapian — kalau backend-nya bocor,
siapa pun bisa memanggil endpoint-nya langsung.

Masih sebagai **op@uji**, buka tab baru dan akses langsung:

```
http://127.0.0.1:8100/api/console/dev/log
```

Harus **403** dengan pesan "menu ini untuk akun support". Bukan 200, bukan halaman kosong.

Lalu tanpa login sama sekali (mode incognito): harus **401** "belum masuk" —
**bukan** 403. Bedanya penting: sesi habis harus terbaca "masuk lagi", bukan
"kamu tidak berhak".

### d. Layar Log

Sebagai support, buka tab **Log**.

Kalau masih kosong, pancing satu galat: isi `ERP_URL` di `.env` dengan alamat yang tidak
ada (misal `http://127.0.0.1:9`), jalankan ulang konsol, tunggu sebentar.

Yang dicek:
- Barisnya muncul, terbaru di atas
- Saring level ERROR / WARNING jalan
- Kotak cari jalan
- **Pesan yang sama berulang digabung jadi satu baris dengan `×N`** — bukan 300 baris
  identik. Ini yang bikin layarnya kebaca waktu kabel kamera putus.
- **Sandi dan token tidak pernah kelihatan.** Kalau ada baris yang memuat
  `password=...` atau `token=...`, nilainya harus tertulis `«ditutup»`.

Log bertahan **180 hari** dan selamat dari restart — itu inti fiturnya. Coba
`make restart` lalu buka lagi: barisnya harus masih ada.

### e. Layar Diagnostik

Di MacBook, ketiga line memang mati — dan **itu justru kasus yang mau dites**.

Layarnya harus tetap memuat **tiga kartu**, masing-masing bilang "tidak terjangkau"
beserta sebabnya. **Bukan** layar kosong, bukan error. Line yang mati justru yang paling
perlu dilihat.

Kalau ada line yang hidup, kartunya menampilkan worker, kamera, fps, GPU, dan PLC.

### f. Layar Antrean ERP

Menampilkan berapa yang nyangkut, sebab gagal terakhirnya, sudah dicoba berapa kali,
dan **kapan percobaan berikutnya**.

Tombol **Kirim Ulang**: sesudah ditekan, kolom "Percobaan berikutnya" semua baris harus
berubah jadi **"Sekarang"**. Itu tanda tombolnya benar-benar bekerja.

Catatan: `attempts` sengaja **tidak** di-reset. Kalau ERP sudah pulih, barisnya langsung
terkirim. Kalau ERP masih mati, satu percobaan lalu balik ke jeda panjang — itu memang
yang diinginkan, supaya tombol ini tidak jadi alat menggempur ERP yang masih mati.

### g. Layar Versi

Versi, machine_id, environment, status lisensi.

Yang dicek: **tidak ada rahasia di sini.** Lisensi cuma dua penanda ya/tidak, tokennya
sendiri tidak pernah keluar.

### h. Layar Uji PLC

Ini satu-satunya layar yang **menggerakkan barang sungguhan**.

Di MacBook tanpa PLC, layarnya harus terbuka normal dan bilang **"PLC mati di line ini"**
— bukan error.

Tiga pengaman yang dites di pabrik nanti:
1. **Tombol mati kalau line sedang memproses truk.** Piston bergerak saat janjang lewat
   itu bahaya, bukan cuma berantakan.
2. **Konfirmasi ketik `UJI`**, bukan klik. Klik bisa kesenggol di layar sentuh.
3. **Tiap penekanan tercatat** di layar Log sebagai WARNING, menyebut siapa, coil mana,
   line mana — termasuk saat percobaannya gagal.

⚠️ Coil 9 (HEARTBIT PC ON) **tidak ada** di daftar dan memang tidak boleh ada: memicunya
manual bisa bikin panel mengira PC mati lalu menyalakan alarm.

---

## 5. Kalau layar developer tidak muncul sama sekali

Cek `docker logs` konsol. Kalau ada peringatan:

> Tidak ada akun dengan peran support: layar developer konsol ini tidak bisa dibuka
> siapa pun.

berarti PC itu belum punya akun support. Perbaiki dengan:

```bash
make operator AKSI=peran PERAN=support
```

Ini kasus nyata di PC pabrik yang `.env`-nya dibuat sebelum fitur ini ada.

---

## 6. Setelan baru

| Setelan | Bawaan | Artinya |
|---|---|---|
| `ERP_ALLOWED_ROLES` | `support` | Peran mana yang boleh datang dari AutoERP. **Dikosongkan = semua peran dari ERP ditolak** — rem yang bisa ditarik dari sisi pabrik kalau akun ERP bermasalah, tanpa menunggu ERP dibereskan. |
| `LOG_RETENSI_HARI` | `180` | Berapa lama riwayat galat disimpan. ±10 MB pada 200 galat/hari. |

Keduanya sudah ada di `.env.example` dan diteruskan `docker-compose.yml`.

---

## Kalau ada yang aneh

Rinciannya di `CLAUDE.md` (tabel lane konsol + aturan bernomor soal lane developer)
dan `docs/backend-overview.md`.
