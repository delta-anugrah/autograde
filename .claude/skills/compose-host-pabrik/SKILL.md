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

Terkait: skill `install-factory-pc` dan `spek-pc-pabrik`, runbook `docs/runbooks/` di repo ini
dan di `sawit`.
