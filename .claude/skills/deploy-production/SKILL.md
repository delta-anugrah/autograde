---
name: deploy-production
description: Menaikkan aplikasi ber-database ke satu server (droplet/VPS) dengan aman — snapshot, image immutable, backup sebelum migrate, rollback otomatis, nginx+TLS, dan uji yang membuktikan. Pakai kalau user bilang "deploy ke produksi", "naikkan ke server", "setup droplet", "bikin CI/CD deploy", "rollback gimana", "aman nggak ini buat produksi", atau lagi menyiapkan rilis pertama sebuah layanan.
---

# Menaikkan aplikasi ke produksi, tanpa jalan buntu

Berlaku untuk satu server (droplet/VPS) yang menjalankan aplikasi ber-database di
Docker, di belakang nginx milik host. Bukan untuk Kubernetes, bukan untuk serverless.

**Aturan yang membentuk semuanya:** setiap langkah harus punya jalan pulang, dan setiap
klaim "berhasil" harus dibuktikan oleh perintah, bukan oleh perasaan.

## Urutan yang tidak boleh dibalik

| # | Langkah | Kalau dilewati |
|---|---|---|
| 1 | **Snapshot server** | Tidak ada tombol undo. Salah satu langkah di bawah = server rusak permanen |
| 2 | Resize / tambah RAM kalau perlu | Layanan mati sendiri saat dipakai, bukan saat dipasang |
| 3 | Reboot kalau OS memintanya | Update keamanan tertunda, dan reboot-nya nanti jatuh saat jam sibuk |
| 4 | **`stop`** layanan lama, bukan `down -v` | `down -v` **menghapus volume** — datanya hilang permanen |
| 5 | `.env` + `up` layanan baru | — |
| 6 | Bikin database/site | — |
| 7 | nginx + TLS | Sandi login melintas **polos** di internet |
| 8 | Uji yang membuktikan | "Halaman login terbuka" bukan bukti sistemnya jalan |

Langkah 1 lebih penting dari semua sisanya digabung. Kerjakan meski terasa berlebihan.

## Yang harus ada sebelum rilis pertama

Ini yang membedakan "jalan" dari "layak produksi". Semuanya bisa diuji **sebelum**
menyentuh server.

### Image immutable, tag versi persis
- Satu tag `vX.Y.Z` = satu isi, selamanya. **Tolak build kalau tag-nya sudah ada di
  registry** — kalau tidak, "versi yang jalan" jadi tebakan.
- Jangan deploy dari tag yang bergerak (`latest`, `main`). Pin ke versi persis di `.env`.
- Tag rilis wajib **turunan branch rilis**. Tanpa gerbang ini, orang bisa menandai
  commit yang belum direview.

### Backup SEBELUM migrate, bukan sesudah
Menukar image **tidak membatalkan perubahan skema database**. Kalau migrate merusak
data, satu-satunya jalan pulang adalah dump yang diambil sebelum dia jalan.

```
pull image baru  →  backup DB  →  ganti tag di .env  →  up  →  migrate  →  cek sehat
                                        ↑ gagal di mana pun sesudah ini → rollback
```

### Rollback otomatis, bukan manual
Kalau versi baru tidak lolos health check, skrip yang mengembalikan versi lama —
bukan orang yang panik jam 2 pagi. Simpan `.env` lama sebelum mengubahnya.

⚠️ Rollback image **tidak** mengembalikan skema. Kalau `migrate` sudah jalan, pesan
rollback harus menyebutkan perintah restore dump-nya, bukan diam-diam mengaku berhasil.

### Container tidak menghadap internet
Bind ke `127.0.0.1:PORT` saja. nginx milik host yang menerima 80/443 dan meneruskan ke
loopback. Port publik cukup **22, 80, 443**.

Alasannya: kalau aplikasinya punya lubang, orang luar tetap tidak bisa menyentuhnya
langsung. Ini gratis dan satu baris.

### Rotasi log
Driver `json-file` tumbuh **tanpa batas** sampai disk penuh. Yang mati duluan biasanya
database, bukan layanan yang membuat lognya — jadi gejalanya menyesatkan.

```yaml
x-logging: &default-logging
  driver: json-file
  options: { max-size: "50m", max-file: "3" }
```

### Sandi dibuat di server
`openssl rand -base64 32`, langsung di server, masuk ke `.env` yang tidak pernah
di-commit. Sandi yang pernah lewat chat atau tiket harus dianggap bocor.

⚠️ `.gitignore` berpola `.env*` ikut menelan `.env.example`. Tambahkan
`!.env.example` — template yang tidak pernah ter-commit tidak menolong siapa pun.

## Membangun image: hindari satu jebakan yang mahal

**Jangan membangun ulang seluruh dunia kalau ada image resmi.** Banyak framework
(Frappe/ERPNext, Odoo, Rails) menerbitkan image dasar yang sudah memuat runtime dan
seluruh dependensi. Membangun dari nol berarti setiap build bergantung pada beberapa
`git clone` besar yang berhasil — dan di jaringan yang buruk itu gagal di tengah,
setelah 50 menit, berulang kali.

Kalau aplikasinya fork: pakai image resmi sebagai **dasar**, lalu tukar direktori
app-nya. Dari ~1 jam (sering gagal) jadi ~2 menit.

Kalau repo-nya privat dan build butuh meng-clone-nya:
- Jangan menaruh token di berkas yang di-commit.
- Lebih baik lagi: **cermin lokal** dari checkout yang sudah ada (`git clone --bare
  --depth 1 file://...`) — nol kredensial, nol jaringan.
- ⚠️ Cermin dari `origin/<branch>`, **bukan** branch lokal. Keduanya bisa berbeda, dan
  membangun dari yang tertinggal mengirim kode lama tanpa ada yang memberi tahu.

⚠️ **Log build bisa memuat kredensial.** Beberapa alat mencatat perintah `git clone`
lengkap dengan URL ber-token, dan berkas log itu ikut ke dalam image:

```bash
docker run --rm --entrypoint bash <image> -c "grep -rn 'x-access-token' logs/"
```

Kosongkan `logs/` di lapisan terpisah, lalu **tolak push kalau masih terbaca**.

## Penjaga di akhir build

Periksa isi image sebelum di-push. Yang terpasang mulus tapi salah akan ketahuan jauh
kemudian, di tempat yang tidak menunjuk ke sini:

```bash
docker run --rm --entrypoint bash "$IMAGE" -c '
  set -e
  test -f <jalur modul inti> || { echo "modul inti TIDAK ADA"; exit 1; }
  test -d <jalur aset terbangun> || { echo "aset tidak terbangun"; exit 1; }
  grep -rqE "<pola kredensial>" <jalur app> && { echo "kredensial di dalam image"; exit 1; }
  echo "ok"
'
```

⚠️ Jangan biarkan penjaga mencari polanya **di dalam berkasnya sendiri** — skrip build
yang ikut ke image memuat pola itu, dan penjaganya akan menuduh dirinya sendiri di
setiap rilis. Kecualikan direktori skrip deploy.

## Uji yang membuktikan

Urutannya dari murah ke mahal. Jangan lompat ke yang terakhir.

1. **Unit** — jalankan; untuk perbaikan bug, buktikan **negative control**: test merah
   sebelum fix, hijau sesudah. Test yang tidak pernah merah tidak membuktikan apa pun.
2. **`compose config`** — variabel wajib menyala, port terikat `127.0.0.1`, service lengkap.
3. **Stack lokal** — jalankan compose **produksi** yang sama, bikin site dari nol,
   lalu jalankan alur bisnis ujung-ke-ujung lewat HTTP seperti klien sungguhan.
4. **Bandingkan dengan baseline** kalau ada test yang merah. Jalankan di commit induk:
   kalau merahnya identik, itu utang lama, bukan regresi. **Katakan mana yang mana.**

Yang membuktikan berhasil adalah **satu transaksi bisnis nyata** yang lewat
ujung-ke-ujung, bukan halaman login yang terbuka.

## Sesudah live — jangan berhenti di sini

| | Kenapa |
|---|---|
| **Backup terjadwal + uji restore** | Backup yang belum pernah di-restore belum tentu backup. Ini nomor satu sesudah live |
| Firewall diperiksa | Pastikan hanya 22/80/443 |
| Monitoring / uptime check | Supaya bukan orang lapangan yang memberi tahu bahwa sistemnya mati |
| Runbook rollback tertulis | Orang yang mengeksekusi jam 2 pagi mungkin bukan yang membangunnya |

## Jebakan yang berulang di mana-mana

1. **Reboot tidak membaca `.env` yang berubah.** Perlu `restart` layanan.
2. **Nama site harus sama dengan Host header** yang diteruskan nginx, kalau tidak
   framework menjawab "site tidak ada".
3. **Pin versi image dasar** (`v16.35.0`, bukan `v16`). Tag bergerak = dua build dengan
   commit sama menghasilkan isi berbeda.
4. **`--branch` pada `git clone` menolak SHA mentah.** Untuk memakukan commit persis,
   baca dari checkout lokal, bukan dari clone jaringan.
5. **Data uji yang bocor antar-sesi** membuat test merah yang bukan salah kodenya —
   khususnya baris yang sudah di-submit, yang selamat dari rollback transaksi.
6. **Jangan percaya dokumen sendiri.** Sesudah mengubah alur, periksa docs **dan**
   skill: keduanya gampang bercabang, dan pembaca yang mengikuti yang usang akan
   mengira instalasinya rusak padahal benar.
