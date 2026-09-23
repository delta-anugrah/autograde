---
name: install-factory-pc
description: Pasang PC pabrik Palmgrade baru dari nol — jaringan kamera, docker, GPU, image GHCR, .env, lisensi. Pakai kalau user bilang "pasang PC pabrik baru", "install dari 0", "setup PC Lampung/site baru", "PC baru mau dipasang", atau lagi debug instalasi pabrik yang gagal di tengah jalan.
---

# Pasang PC pabrik Palmgrade dari nol

⚠️ Dua berkas di bawah ada di repo **`sawit`** (workspace internal), bukan di repo ini:
`../docs/runbooks/2026-08-21-checklist-pasang-pc-pabrik.md` (checklist ringkas buat operator)
dan `../docs/runbooks/2026-08-15-factory-pc-install-ringkas.md` (detail panjang + template
`.env` lengkap). Tanpa akses ke sana, mintalah `.env` contoh ke yang memegang repo itu —
sisanya di skill ini sudah cukup untuk memandu pemasangan.

Skill ini isinya yang **nggak** ada di dua file itu: cara mandu sesinya, gerbang
mana yang nggak boleh dilewat, dan jebakan yang bikin instalasi gagal diam-diam.

## Mode kerja

Guided/manual. **Kamu nggak megang PC pabrik.** Operator yang ngetik, terus
paste output, kamu yang baca. Kasih satu blok perintah, tunggu hasilnya, baru
lanjut. Jangan kasih 5 langkah sekaligus — kalau nomor 2 gagal, nomor 3-5
jalan di atas puing dan diagnosisnya jadi kabur.

## Sebelum mulai: kumpulin ini dulu

Tanyain sekaligus di awal. Kalau ada yang belum ada, instalasi bakal ngadat di
tengah dan operator nunggu.

- PAT GitHub scope `read:packages`
- File model `best.pt` **4 kelas** (±50 MB, kelas `JK/Ripe/TP/Unripe`) — **nggak ada di repo**, harus dibawa. Yang 130 MB (`best_3class_v2.pt`) model lama: kode nggak kenal kelasnya, line jalan tapi nol hitungan
- Serial 3 kamera Hikrobot
- `WEBHOOK_SECRET` dari droplet produksi (jadi kunci B)
- 4 nilai `R2_*` Cloudflare
- Kode site (huruf kecil, unik per pabrik)
- Di cloud: company-nya udah dibikin dan **Valid Until** udah diisi — kalau
  belum, `Cetak Token` bakal 400 dan langkah 14 mentok

## Versi image: jangan pernah hardcode

Nomor versi di runbook **selalu basi**. Ambil yang beneran:

```bash
for r in palmgrade-api palmgrade-frontend autograde; do
  echo -n "$r: "
  gh api "/orgs/delta-anugrah/packages/container/$r/versions" \
    --jq '.[0].metadata.container.tags | join(", ")'
done
```

Frontend **nggak punya** tag `latest` polos — cuma `latest-edge`. Tapi `?ref=`
git-nya pakai `v1.5.3` **tanpa** `-edge`; akhiran itu cuma ada di tag image.

## Gerbang keras — berhenti kalau gagal

Tiga titik ini nggak boleh dilewat "nanti aja". Lanjut tanpa ini bikin gagal
5 langkah kemudian dengan pesan yang nggak nyambung ke sebabnya.

1. **`newgrp docker` doang nggak cukup** — operator wajib logout terus login
   lagi. Kalau nggak, ikon Start di desktop gagal nanti, pesannya soal socket.
2. **`docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi`
   harus ngeluarin tabel GPU.** Nggak keluar = vision nggak bakal jalan, semua
   langkah setelahnya cuma puing.
3. **`grep -r LICENSE_PRIVATE_KEY /opt/palmgrade/*/.env` harus nol hasil**
   sebelum `palmgrade start`.

## Jebakan yang bikin gagal diam-diam

Ini semua pernah kejadian beneran. Nggak ada yang ngasih error jelas.

- **`palmgrade pull` cuma mindahin image.** File compose dan `palmgrade.sh`
  duduk di disk host, ditarik manual lewat GitHub contents API `?ref=vX.Y.Z`.
  Pull image baru tanpa refresh `palmgrade.sh` = script operator masih
  verifikasi token pakai kunci lama.
- **Folder `api/` dan `frontend/` cuma boleh punya `prod` + `factory`.**
  `docker-compose.yml` polos itu compose DEV (`adminer`, `mongo-express`,
  `build:`) — kalau ikut ketarik, start gagal. **Vision butuh tiga-tiganya.**
- **`NODE_ENV: development` di `api/docker-compose.factory.yml` itu disengaja.**
  Di `production`, cookie login dapat flag `Secure` yang butuh HTTPS. LAN pabrik
  HTTP polos → browser buang cookie diam-diam → operator muter di halaman login
  **tanpa satu pun pesan error**. Jangan "diperbaiki".
- **`ports: !override` ke `0.0.0.0` wajib.** Bawaan bind `127.0.0.1` — bener
  buat droplet yang ada nginx di depan, di pabrik bikin dashboard nggak
  kejangkau dari PC lain.
- **Jangan nyalin `docker-compose.factory.yml` vision dari laptop developer.**
  Versi laptop punya `profiles: ["all-lines"]` di line 2 dan 3 → dua line
  diam-diam nggak nyala.
- **Model wajib di `models/release/`**, bukan `models/`. Salah folder =
  container mati.
- **Jangan pernah nyalin isi `engines/` dari mesin lain** — terkunci ke compute
  capability GPU tertentu. Build ulang di PC itu, ±10 menit.
- **`make build-engine` nggak bisa dipakai di pabrik** — target Makefile-nya
  nge-build dari source yang nggak ada di situ. Pakai `docker compose ... run`
  tiga-`-f` (lihat langkah 13 checklist); yang `prod` itu yang bawa mount
  `./engines`, tanpa itu engine ilang begitu perintah selesai.
- **Compose makan `$`.** Hash bcrypt di `.env` wajib `$$` tiap `$`.
- **`hikrobot.mfs` ngunci fps di 10.** Naikin `CAMERA_FPS` di `.env` nggak
  ngefek selama file itu masih bilang 10.
- **Loop nunggu docker di autostart wajib di file script**, jangan di baris
  `Exec=`. `Exec=` bukan shell.
- **Habis upgrade frontend, browser operator wajib `Ctrl+Shift+R`.** Bundle
  lama yang ke-cache bikin tampilan lama nempel padahal container udah baru.

## Tiga kunci yang gampang ketuker

Namanya mirip, perannya beda total, ketuker nggak ngasih error yang jelas.

| | Nama | Dapatnya | Buat apa |
|---|---|---|---|
| **A** | `JWT_SECRET` | **generate** di PC itu | Login. api **dan** frontend harus kembar. Beda dikit = login sukses lalu dilempar balik |
| **B** | `EDGE_SYNC_SECRET`, `UPLOAD_API_SECRET` | **SALIN** dari `WEBHOOK_SECRET` droplet | Jalur pabrik → cloud |
| **C** | `WEBHOOK_SECRET` | **generate** di PC itu | Jalur api ↔ vision di dalam PC itu. Namanya kebetulan sama kayak punya droplet, isinya beda |

`DOCKER_PROFILE_SECRET_KEY` + `DOCKER_ENCRYPTED_PROFILES` itu **sepasang**.
Ambil satu doang = login gagal total.

**`LICENSE_PRIVATE_KEY` JANGAN PERNAH nyampe PC pabrik.** Operator ada di grup
`docker` ≈ root, jadi siapa pun yang pegang keyboard bisa baca semua `.env`.
Pabrik cuma butuh kunci publik, dan itu **udah ditanam di dalam image** — nol
langkah manual.

Kunci publik lisensi ditanam di **tiga** tempat, wajib sama semua:
`palmgrade-api/src/utils/license.ts`, `palmgrade-api/deploy/edge/palmgrade.sh`,
`autograde/src/palmgrade/core/config.py`.

Kunci yang di-generate **jangan di-paste ke chat, tiket, atau screenshot**.
Suruh operator simpan langsung ke password manager. Kunci **publik** lisensi
aman dipaste.

## Waktu ngoperasiin

- **Jangan pernah `docker compose` mentah di PC pabrik.** Selalu lewat
  `palmgrade`. Perintah mentah bikin file override pabrik nggak kebaca.
  Pengecualian resmi cuma dua: build engine TensorRT (langkah 13) dan wipe
  volume waktu reset DB.
- `palmgrade license <token>` verifikasi dulu baru nulis — token salah = error,
  nol perubahan. Dia stop lalu start ulang seluruh stack sendiri (±30 detik),
  karena `.env` baru cuma nempel waktu container **dibuat ulang**; reboot aja
  nggak cukup. Jangan dijalanin tengah shift.
- Ganti token kapan aja tinggal ulang perintah yang sama. Nggak ada mode
  "cek status".
- Reboot **nggak** nerapin `.env` baru — wajib `palmgrade restart`.

## Bukti selesai

Yang dihitung cuma output beneran, bukan "perintahnya udah jalan".

```bash
palmgrade status
curl -s localhost:2500/health                        # version = tag yang dipasang
docker logs ripe_line_1 2>&1 | grep backend=         # backend=tensorrt
grep -r LICENSE_PRIVATE_KEY /opt/palmgrade/*/.env    # nol hasil
```

Plus: dashboard kebuka dari PC lain di LAN, login nggak nendang balik, nggak
ada banner lisensi, 3 line vision `healthy`, dan reboot → nyala sendiri.
