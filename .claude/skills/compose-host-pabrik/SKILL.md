---
name: compose-host-pabrik
description: Use when a change adds or renames an env var, mount, port or service that the factory PC must receive, when a setting "does nothing" on the Lampung PC although .env looks right, before telling the user a feature is live at the factory, or when writing steps for the factory PC. Covers why `autograde pull` never updates the host compose or launcher, how Compose overrides silently drop blocks, and how to verify what a container really got.
---

# Compose dan launcher di host PC pabrik

PC pabrik tidak punya source code. Yang ada di `/opt/palmgrade/autograde/`: `docker-compose.yml`,
`docker-compose.prod.yml`, (kadang) `docker-compose.factory.yml`, `.env`, `media.env`, data
(`state/`, `artifacts/`, `engines/`, `models/`, `videos/`). Launcher-nya `/opt/palmgrade/autograde.sh`
(diketik `autograde`), salinannya di repo `sawit`: `docs/runbooks/files/`.

## Aturan inti

1. **`autograde pull` cuma menarik IMAGE.** Compose, launcher, dan skrip kiosk di host tidak
   pernah ikut. Perbaikan compose di repo ini **tidak sampai** ke pabrik sampai ada yang
   menyalinnya tangan lewat AnyDesk. Kejadian: compose Lampung tertinggal sebulan (2026-09-22),
   `LICENSE_ENABLED` hilang dari blok konsol sampai lisensi terbaca "Inactive" (2026-09-28).
2. **Override MENGGANTI blok, tidak menambah** (Compose v2.40.3 di Lampung). Begitu
   `docker-compose.prod.yml` menyebut `environment:` untuk sebuah service, seluruh `environment:`
   service itu di `docker-compose.yml` dibuang; `network_mode` dan `container_name` ikut hilang.
   `docker compose config` di MacBook (Compose v5) **tidak membuktikan apa-apa**: di sana
   penggabungannya benar. Tanda blok konsol lama di Lampung: namanya `autograde-console-1`,
   bukan `palmgrade_console`.
3. **`.env` menang atas nilai bawaan compose** (`${X:-bawaan}`), dan `COMPOSE_PROJECT_NAME` di
   `.env` menang atas `--project-directory`. Sisa lama di `.env` (misal `PLC_PORT=502` era ODOT)
   diam-diam menimpa bawaan yang benar.
4. **`media.env` wajib lewat `--env-file`**, bukan `env_file:`. Launcher dan `Makefile` sudah
   membawanya; pemanggil lain harus membawa sendiri.
5. **Env baru nempel cuma saat container DIBUAT ULANG.** `autograde restart` (atau `use`) yang
   melakukannya (`up -d --force-recreate`); reboot saja tidak.

## Sebelum membuka PR: butuh perubahan host?

- Menambah env var yang dibaca **konsol**? Tambahkan juga di blok `console:` di
  `docker-compose.prod.yml` (dijaga `tests/unit/test_console_compose_env.py`, prefiks
  `ERP_`, `CONSOLE_`, `LOG_`, `R2_`, `MEDIA_`, `LICENSE_`), **lalu tulis di PR** bahwa compose
  host pabrik harus ditambah tangan, lengkap dengan barisnya.
- Menambah mount (folder `models/`, `engines/`, `videos/`, `media/`)? Sama: repo + langkah tangan.
- Mengubah launcher? Ubah salinan di repo `sawit` (`docs/runbooks/files/`) dan beri langkah
  salin ke `/opt/palmgrade/`.
- Tidak ada yang di atas? Tulis "No host-side change" di PR, seperti rilis `v1.18.0`.
- **`DISCORD_WEBHOOK_URL`** (batch 3.5): satu baris di blok `console:` compose host
  (`- DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL:-}`) lalu nilainya di `.env`, lalu
  `autograde restart`. Tanpa itu fitur mati, tidak ada yang rusak.
- **`INTERNAL_SECRET`** (batch 1 keamanan, 2026-09-28): kosong = perintah konsol → line ikut
  `WEBHOOK_SECRET`, jadi rilisnya sendiri backward compatible, tapi meneruskannya butuh
  menyentuh **empat blok** di compose host: tiga blok line di `docker-compose.yml`
  (`- INTERNAL_SECRET=${INTERNAL_SECRET:-}`) **dan** blok `console:` di
  `docker-compose.prod.yml`. Nilainya harus **sama persis** di keempat, kalau tidak line yang
  bedanya jadi menolak perintah konsol (kartunya menulis "kunci ditolak", bukan mati).
- **`AI_MATI_DETIK`** (batch 2.1, opsional): bawaan 30 jalan tanpa perubahan host, jadi rilisnya
  sendiri "No host-side change required". Tapi **menyetelnya** (misal `AI_MATI_DETIK=60` di
  `.env` untuk line yang lambat) tidak berpengaruh apa pun sampai tiga blok line
  `docker-compose.yml` host memuat `- AI_MATI_DETIK=${AI_MATI_DETIK:-30}`: gejala "setelan tidak
  berlaku" persis aturan 1. Tulis di PR: "the host line is only needed to tune AI_MATI_DETIK".
- **`LOG_LEVEL`** (batch 3.1, opsional) dan **`FACTORY_TZ`** untuk line (batch 3.4, opsional):
  keduanya jalan tanpa perubahan host. Kosong = `LOG_LEVEL` jatuh ke `INFO`, dan `FACTORY_TZ`
  jatuh ke `Asia/Jakarta` (bawaan `Settings`, yang dipakai Lampung hari ini). Compose host
  Lampung tidak perlu diedit untuk rilis ini.
- **`state/` di-mount dari host**, bukan sekadar ada di image: outbox line dan penjaga jam
  lisensi (`outbox.db`, `license.db`) sejak batch 1 hidup di `state/line-N`, bukan lagi
  `artifacts/line-N`. Cek read-only: `docker inspect ripe_line_1 --format
  '{{range .Mounts}}{{println .Destination}}{{end}}'` harus memuat `/app/state`. Kalau tidak,
  DB itu tetap di `artifacts/` (masih aman, tidak tersaji `/captures`) dan `logger.error`
  mencatatnya tiap boot, bukan gagal start.

## Memeriksa apa yang benar-benar diterima container

Beri user satu blok perintah (baca saja), minta hasilnya ditempel:

```bash
cd /opt/palmgrade/autograde
docker ps --format '{{.Names}}'                      # nama sebenarnya, jangan ditebak
docker exec autograde-console-1 printenv NAMA_VAR || echo "KONSOL: KOSONG"
docker exec ripe_line_1 printenv NAMA_VAR
grep -n "NAMA_VAR" docker-compose*.yml .env media.env 2>/dev/null
```

Kosong di container padahal ada di `.env` = blok compose host tidak menyebutnya (aturan 2).

## Menambal compose host

1. Backup dulu: `cp docker-compose.prod.yml docker-compose.prod.yml.bak-<tanggal>`.
2. Sisipkan baris dengan indentasi yang sama. Untuk satu baris sesudah baris yang diketahui,
   pakai `sed -i '<n>{p;s/LAMA=.*/BARU=${BARU:-bawaan}/;}'` dengan penjaga
   `sed -n <n>p berkas | grep -q LAMA &&` di depannya (dipakai 2026-09-28 untuk lisensi).
3. `autograde restart` (grading jeda sekitar 10 detik), lalu ulangi pemeriksaan di atas.
4. Catat di TODO `sawit` bagian P3 (berkas host tidak ikut rilis) supaya kejadian berikutnya
   tidak dianggap baru.

## Urutan pasang batch 1 keamanan LAN di Lampung

**Status Lampung:** langkah 1 dan 2 selesai. Cek pra-tag lolos 2026-09-30 (ketiga line me-mount
`/app/state`, `WEBHOOK_SECRET` konsol bukan bawaan) dan `v1.20.0` terpasang 2026-10-01. Langkah 3
(`INTERNAL_SECRET`) belum. Urutan di bawah tetap dipakai untuk PC berikutnya.

Rilisnya sendiri **backward compatible**: tidak butuh sentuh `.env` atau compose host lebih dulu.
Urutannya, kalau memang mau dikerjakan sekalian:

1. **Sebelum tag**, baca saja lewat AnyDesk: `docker inspect ripe_line_1 --format
   '{{range .Mounts}}{{println .Destination}}{{end}}'` (ulangi untuk line 2 dan 3) harus memuat
   `/app/state`; dan `docker exec autograde-console-1 printenv WEBHOOK_SECRET` **bukan** default
   publik (`supersecret123`), karena konsol sekarang ikut menolak boot di produksi dengan secret
   bawaan seperti line. `/app/state` yang tidak ada bukan penghalang: DB line tetap di
   `artifacts/` (aman, tidak tersaji `/captures`), cuma `logger.error` tiap boot, bukan gagal
   start; beri tahu user kalau ketemu.
2. **Rilis** (`autograde pull` / `use`). Boot pertama tiap line mencatat `outbox.db dipindah ...`
   dan `license.db dipindah ...`. Cek `/health/detail` `outbox_pending` sama dengan
   `outbox_pending + outbox_failed` sebelum upgrade (baris yang dulu menyerah ikut dihitung dan
   dikirim; batch 2.4), lalu turun sendiri ke 0 dalam beberapa menit, **kecuali** baris yang
   ditolak konsol (tab Status, Antrean line: "DITOLAK konsol"; lihat urutan pasang batch 2 di
   bawah), yang tetap terhitung sampai dikeluarkan tangan, `ls artifacts/line-1/*.db`
   kosong, `ls state/line-1/` memuat kedua berkas, dan foto
   konsol tetap tampil sesudah login. `outbox_lama_tertinggal: true` (dengan `outbox_pending:
   null`) = antrean lama gagal diserap: jangan hapus data apa pun, restart line itu, lalu baca
   log line-nya (`gagal diserap`).
3. **Belakangan, terpisah**: `INTERNAL_SECRET=<nilai baru>` di `.env`, **dan** tambahkan
   `- INTERNAL_SECRET=${INTERNAL_SECRET:-}` ke tiga blok line `docker-compose.yml` **serta** blok
   konsol `docker-compose.prod.yml` (backup dulu), lalu `autograde restart`. Verifikasi
   `docker exec <keempatnya> printenv INTERNAL_SECRET` sama persis. Sebagian tersentuh kelihatan
   sebagai line menolak perintah konsol (401 di log konsol, kartu line gagal), **bukan** data
   hilang senyap: kiriman janjang tetap sampai lewat `WEBHOOK_SECRET`, yang tidak berubah.
4. **Rollback** (`autograde use <versi lama>`) aman: image lama membuat ulang `artifacts/*.db`
   kosong; naik lagi menyerap isi dari dua tempat sekaligus.

## Urutan pasang batch 2 di Lampung

**Status Lampung:** terpasang bersama `v1.20.0` (2026-10-01). Precheck 2026-09-30: antrean outbox
ketiga line kosong (`[]`), jadi tidak ada janjang lama yang dikirim ulang.

Rilisnya **No host-side change required** (tanpa `.env`, compose, atau launcher baru). Yang perlu
dijaga ada di data, bukan berkas host:

1. **Sebelum tag**, baca saja lewat AnyDesk: berapa janjang yang versi lama sudah berhenti
   mencoba (`failed`) per line, dan rentang tanggalnya. Jalan di image lama juga, dan mencari di
   `state/` maupun `artifacts/`:

```bash
for n in 1 2 3; do docker exec ripe_line_$n python -c 'import os,sqlite3; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); print(p, sqlite3.connect(p).execute("select status, count(*), min(json_extract(payload, ?)), max(json_extract(payload, ?)) from outbox_events group by status", ("$.timestamp", "$.timestamp")).fetchall())'; done
```

   Beri tahu user angkanya **sebelum** update: tiap baris `failed` dikirim lagi ke konsol di boot
   pertama dan **mendarat di tanggal kerja ASLINYA**, bukan hari ini. Jadi total Rekap
   hari-hari lalu berubah, dan kunjungan AutoERP yang penugasannya masih tertaut bisa diantre
   ulang (tiket yang sudah final ditandai **Cek AutoERP** di tab Timbangan, satu WARNING
   `[TIKET_FINAL_BERBEDA]` per tiket). Tidak ada yang terhitung dua kali. Kalau user memutuskan
   sebagian itu sampah uji (misal banjir 2026-08-09), teknisi menghapusnya tangan SEBELUM update,
   tidak pernah lewat kode.
2. **Rilis.** Boot pertama line yang punya baris lama mencatat `N janjang yang dulu berhenti
   dicoba ... dihidupkan lagi`. `outbox_pending` naik sebesar `outbox_failed` lama lalu turun
   sendiri ke 0 dalam beberapa menit, **kecuali** baris yang ditolak konsol.
3. **Sesudah rilis, dua hal diamati:**
   - **Kartu line paling cepat 30 detik sesudah start** (atau `curl :800N/health`). Gerbang
     update launcher selesai pada jawaban sehat pertama, yang jatuh di tenggang AI 30 detik:
     AI yang mati pada frame sungguhan **tidak** membuat update mundur sendiri. Kartu merah =
     `autograde use <versi sebelumnya>`.
   - **`Simpan janjang ... lambat` di log line dan `capture_save_dropped`** di `/health/detail`
     beberapa jam pertama: foto dan sidecar kini ditulis dengan fsync (batch 2.6), jadi menulis
     satu janjang lebih lama. `capture_save_dropped` harus tetap nol; angka `tulis ... ms` dari
     WARNING itu yang dipakai menilai ulang batas kuras 6 detik (`BATAS_KURAS_S`).
4. **Janjang yang ditolak konsol** (Antrean line: "N janjang DITOLAK konsol"; tab Log: `Janjang
   ... DITOLAK konsol`) tidak pernah sampai sendiri dan menahan Danger Zone hapus data serta
   `autograde reset-data`. Tidak ada yang dibuang otomatis. Kalau penyebabnya tidak bisa
   dibetulkan, keluarkan dengan tangan (MANUAL §7.1, perintah yang sama, dijaga test):

```bash
for n in 1 2 3; do docker exec ripe_line_$n python -c 'import os,sqlite3; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); print(p); [print(*r, sep=" | ") for r in sqlite3.connect(p).execute("select event_id, json_extract(payload, ?), datetime(ditolak_at, ?), last_error from outbox_events where ditolak_at is not null", ("$.timestamp", "unixepoch"))]'; done
```

   Simpan satu baris ke berkas host dulu (berkasnya harus berisi satu baris JSON), baru hapus:

```bash
f=~/janjang-ditolak-EVENT_ID.json; if [ -e "$f" ]; then echo "$f sudah ada, TIDAK ditimpa"; else docker exec ripe_line_1 python -c 'import json,os,sqlite3,sys; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); db=sqlite3.connect(p); db.row_factory=sqlite3.Row; r=db.execute("select * from outbox_events where event_id=? and ditolak_at is not null", (sys.argv[1],)).fetchone(); r or sys.exit("tidak ada baris ditolak dengan event_id itu"); print(json.dumps(dict(r)))' EVENT_ID > "$f.baru" && mv "$f.baru" "$f"; rm -f "$f.baru"; fi
cat "$f"
```

```bash
docker exec ripe_line_1 python -c 'import os,sqlite3,sys; p=next(x for x in ("/app/state/outbox.db","/app/artifacts/outbox.db") if os.path.exists(x)); db=sqlite3.connect(p); n=db.execute("delete from outbox_events where event_id=? and ditolak_at is not null", (sys.argv[1],)).rowcount; db.commit(); print(n, "baris dihapus")' EVENT_ID
```

Terkait: skill `install-factory-pc` dan `spek-pc-pabrik`, runbook `docs/runbooks/` di repo ini
dan di `sawit`.
