# Konsol demo di droplet (demo-autograde.smagri.id)

Konsol AutoGrade yang bisa dibuka klien lewat internet, isinya data dummy, tersambung ke
site AutoERP demo `demo.smagri.id`. Tanpa line kamera, tanpa GPU. Jalan di droplet yang
sama dengan AutoERP produksi, jadi semua pengamannya soal **jangan mengganggu produksi**.

Rencana dan langkah pemasangan di droplet (DNS, nginx, TLS, user integrasi) ada di workspace
sawit: `sawit/docs/runbooks/2026-09-28-rencana-demo-autograde-droplet.md`. Berkas ini soal isi repo.

## Kenapa image-nya beda: `vX.Y.Z-cpu`

Image rilis pabrik (`vX.Y.Z`) berisi CUDA, TensorRT, dan SDK kamera Hikrobot: **18,2 GB**.
Di-pull ke droplet 2026-09-28, disk naik ke 97% di disk yang sama dengan MariaDB produksi.
Konsol tidak butuh semua itu (`console_main.py` memang tidak memuat torch), jadi demo memakai
image sendiri dari workflow `.github/workflows/demo-image.yml`:

| | Image pabrik `vX.Y.Z` | Image demo `vX.Y.Z-cpu` |
|---|---|---|
| Torch | `cu126` | `cpu` |
| SDK Hikrobot | ya | tidak |
| Workflow | `deploy.yml` | `demo-image.yml`, dipanggil `deploy.yml` |
| Cache build | `:buildcache` | `:buildcache-cpu` |
| Menulis `latest` | ya (penanda updater pabrik) | **tidak pernah** |

⚠️ **`latest` itu satu-satunya yang dibaca updater PC pabrik.** Kalau workflow demo sampai
menulisnya, PC Lampung akan memasang image tanpa GPU dan grading jadi lambat tanpa satu pun
error. Dijaga `tests/unit/test_demo_image_workflow.py`.

Workflow demo tidak jalan sendiri lagi: tiap tag rilis, `deploy.yml` menjalankan CI dulu,
lalu memanggil `demo-image.yml` di samping build image pabrik (batch 4.1). CI merah berarti
tidak ada image `-cpu` maupun image pabrik. Untuk rilis yang sudah ada: GitHub, Actions,
**Build AutoGrade Demo Image (CPU)**, Run workflow, isi versinya (misalnya `v1.19.0`).
Versinya harus tag yang sudah ada di `main` dan image pabrik `vX.Y.Z`-nya sudah terbit (bukti
tag itu lolos rilis); tag `-cpu` yang sudah terbit tidak ditimpa. Sejak batch 4.2 image demo
mula-mula terbit sebagai `candidate-vX.Y.Z-cpu` dan baru jadi `vX.Y.Z-cpu` sesudah lolos cek
`image-smoke.yml` (kit demo ikut dinyalakan); `demo-autograde upgrade` cuma menarik `vX.Y.Z-cpu`.
Rinciannya: `docs/rules.md`, butir batch 4.2.

## Isi kit (`deploy/demo/`)

| Berkas | Tempatnya di droplet | Isi |
|---|---|---|
| `docker-compose.yml` | `/opt/autograde-demo/` | satu service konsol, `mem_limit: 700m`, port cuma `127.0.0.1` |
| `.env.example` | `/opt/autograde-demo/.env` (chmod 600) | image `-cpu`, sandi, ERP demo, lisensi |
| `demo-autograde.sh` | `/opt/autograde-demo/`, symlink `/usr/local/bin/demo-autograde` | perintah harian |
| `demo-autograde-ci.sh` | `/opt/autograde-demo/`, symlink `/usr/local/bin/demo-autograde-ci` | satu-satunya yang boleh dijalankan kunci GitHub Actions: `status` atau `upgrade vX.Y.Z` |

Folder `deploy/` tidak ikut ke image (`.dockerignore`).

## Perintah harian

```bash
demo-autograde status            # versi, sehat atau tidak, RAM, sisa disk
demo-autograde upgrade v1.20.0   # ganti ke v1.20.0-cpu
demo-autograde reset             # data segar dua sisi sebelum showcase
demo-autograde logs              # ikuti log konsol
```

**`upgrade`**, urutannya:

1. Menolak kalau disk sisa di bawah 8 GB, sebelum mengunduh apa pun.
2. Mengunduh `vX.Y.Z-cpu`, menulis tag baru ke `.env`, menyalakan ulang.
3. Menunggu `/health` menjawab dengan **versi baru**.
4. Sehat: image lama dihapus. Tidak sehat: `.env` dikembalikan, versi lama dinyalakan lagi,
   image yang rusak dihapus.

Di disk hanya ada satu image demo, kecuali sebentar saat upgrade. Tidak ada cadangan versi
lama: kembali ke versi lama = `upgrade` ke versi itu.

**`reset`** menjalankan AutoERP demo dulu (90 hari, 20 sampai 40 menit), baru konsol
(365 hari). AutoERP gagal = konsol tidak disentuh, supaya plat kembar dua sisi tetap sejalan.
Site-nya **dipatok** `demo.smagri.id` di skrip dan tidak bisa diganti lewat environment:
site lain di stack yang sama adalah produksi.

## Upgrade otomatis sesudah tiap rilis

Sejak 2026-10-09 demo ikut naik versi sendiri. Urutannya tiap tag `vX.Y.Z`:

1. `deploy.yml` menjalankan CI, lalu membangun dan mengecek image pabrik `vX.Y.Z` dan image demo
   `vX.Y.Z-cpu` berdampingan.
2. Job `deploy-demo` baru jalan kalau **keduanya** terbit. Image pabrik gagal = demo tidak
   dinaikkan: versi yang tidak pernah sampai ke pabrik juga tidak dipamerkan ke klien.
3. `deploy-demo` memanggil `demo-deploy.yml`: SSH ke droplet sebagai `deploy` dengan kunci
   khusus, menjalankan `upgrade vX.Y.Z`. Sisanya sama seperti `demo-autograde upgrade` dengan
   tangan (cek disk, tunggu sehat, kembali ke versi lama kalau tidak sehat).

**Melihatnya:** GitHub, Actions, run tag itu, job `deploy-demo`. Berhasil = baris terakhir
`OK: the demo runs vX.Y.Z.` Gagal = demo tetap di versi lama; image pabrik tidak tersentuh.

**Kembali ke versi lama:** GitHub, Actions, **Deploy AutoGrade Demo**, Run workflow dari
`main`, isi versinya (misalnya `v1.26.2`). Atau dari terminal: `demo-autograde upgrade v1.26.2`.

**Kuncinya terkunci.** Baris di `~/.ssh/authorized_keys` milik `deploy` memaksa setiap
koneksi kunci itu lewat `/usr/local/bin/demo-autograde-ci` (`command="...",restrict`).
Skrip itu cuma menerima `status` dan `upgrade vX.Y.Z`; yang lain ditolak (exit 2), dan dua
deploy dari CI tidak bisa jalan bersamaan (yang kedua exit 75). `demo-autograde upgrade` yang
diketik tangan **tidak** ikut kunci itu: jangan jalankan selama job `deploy-demo` masih jalan.
Tiga tag beruntun dalam setengah jam: tag yang di tengah bisa terlewat; naikkan dengan Run
workflow kalau perlu. Droplet ini juga menjalankan AutoERP
produksi: kunci ini tidak bisa `reset`, `logs`, membuka shell, atau menyentuh `/opt/autoerp`.

**Pasang sekali** (sebelum tag pertama yang membawa fitur ini, kalau tidak job `deploy-demo`
pertama merah, tanpa akibat lain):

1. Laptop: `ssh-keygen -t ed25519 -N "" -C demo-deploy -f ~/.ssh/autograde_demo_deploy`.
2. Sesudah PR rilis masuk `main`, **sebelum** tag: salin skrip dari laptop, di folder repo
   autograde (droplet tidak punya git):
   `git show origin/main:deploy/demo/demo-autograde-ci.sh | ssh autoerpprod 'cat > /opt/autograde-demo/demo-autograde-ci.sh && chmod 755 /opt/autograde-demo/demo-autograde-ci.sh'`,
   lalu `ssh autoerpprod` dan `sudo ln -sf /opt/autograde-demo/demo-autograde-ci.sh /usr/local/bin/demo-autograde-ci`
   (sudo minta sandi, jadi dari terminal sungguhan).
3. Tambahkan satu baris ke `~/.ssh/authorized_keys` milik `deploy`, dari laptop:
   `printf 'command="/usr/local/bin/demo-autograde-ci",restrict %s\n' "$(cat ~/.ssh/autograde_demo_deploy.pub)" | ssh autoerpprod 'cat >> ~/.ssh/authorized_keys'`.
   Baris lain di berkas itu (kunci deploy AutoERP) jangan disentuh.
4. GitHub repo autograde, Settings, Environments, New environment `demo`. Deployment branches
   and tags: Selected, tambahkan tag `v*` dan branch `main`. Secrets: `DEMO_SSH_HOST`
   (`188.166.178.75`), `DEMO_SSH_USER` (`deploy`), `DEMO_SSH_KEY` (isi kunci privat),
   `DEMO_SSH_KNOWN_HOSTS` (keluaran `ssh-keyscan -t ed25519 188.166.178.75`).
5. Bukti kuncinya terkunci:
   `ssh -o IdentitiesOnly=yes -i ~/.ssh/autograde_demo_deploy deploy@188.166.178.75 status`
   menjawab status; ganti `status` dengan `reset` atau `bash` dan jawabannya `refused`.
   `IdentitiesOnly=yes` wajib: tanpa itu ssh menawarkan kunci lain di laptop dulu (kunci
   `deploy` yang bebas), dan yang teruji bukan kunci ini.

## Mode demo hidup (`DEMO_MODE=1`)

Sejak 2026-10-09 layar demo terlihat **hidup**, seperti desain: kotak kamera berganti foto
janjang lengkap dengan kotak deteksinya, angka Ripe/Unripe/Total naik, baris baru muncul di atas
tabel Hasil grading (plat `BE 8605 TSD`), strip foto kecil di kartu ikut berganti, dan
Timbangan sekarang naik, diam di 21.640 kg, lalu turun lagi (satu putaran 16 detik).

Menyalakannya, sekali, dari laptop (droplet tidak punya source code):

1. **Salin ulang compose kit dulu.** Compose di droplet adalah salinan lama yang belum
   meneruskan `DEMO_MODE`; tanpa langkah ini baris di `.env` diam saja dan layarnya tetap
   seperti dulu, tanpa error:
   `git show origin/main:deploy/demo/docker-compose.yml | ssh autoerpprod 'cat > /opt/autograde-demo/docker-compose.yml'`
2. Tambahkan `DEMO_MODE=1` ke `/opt/autograde-demo/.env`, lalu `docker compose up -d` di
   `/opt/autograde-demo`. Image lebih lama dari fitur ini mengabaikannya.
3. Cek: `docker exec autograde_demo_console printenv DEMO_MODE` menjawab `1`.

Yang perlu diketahui:

- **Semua cuma di browser.** Tidak ada yang ditulis ke database dan tidak ada yang dikirim ke
  AutoERP demo. Tekan refresh = mulai lagi dari angka hasil seeder.
- Baris simulasi hanya muncul di halaman 1 tabel tanpa saringan. Pilih satu line atau satu truk,
  atau pindah ke halaman 2, dan yang tampil cuma data seeder. Jumlah di bawah tabel halaman 1
  ikut menghitung baris simulasi, jadi angkanya tidak persis sama dengan halaman 2.
- Tab yang tidak sedang dilihat berhenti bergerak; tidak ada kerja di latar belakang.
- Fotonya lima gambar bawaan (`src/palmgrade/static/demo/`, dibuat dengan
  `scripts/buat-frame-demo.py`), disajikan di `/demo/<nama>` **hanya** kalau `DEMO_MODE` nyala.
  Konsol pabrik menjawab 404.
- ⚠️ **Jangan pernah di PC pabrik.** Compose pabrik tidak meneruskan `DEMO_MODE`, dan konsol
  **menolak menyala** kalau `DEMO_MODE` nyala bersama `PLC_ENABLED`, `PLC_HOST`,
  `SCALE_PLC_HOST` atau `SCALE_PLC_REGISTER`: angka palsu di layar yang menggerakkan piston
  sungguhan terlalu mahal.

## Pasang pertama kali

1. Buat folder `/opt/autograde-demo` beserta `state/console`, `artifacts/line-1..3`, `media`,
   `models`, `engines`, dan berkas kosong `media.env`.
2. Salin tiga berkas kit dari repo (droplet tidak punya source code):
   `git show origin/main:deploy/demo/<berkas> | ssh autoerpprod 'cat > /opt/autograde-demo/<berkas>'`.
3. Isi `.env` dari `.env.example`: `WEBHOOK_SECRET` baru (`openssl rand -hex 24`) dan dua hash
   akun bawaan dari `scripts/hash-sandi.py` (sandi acak panjang, demo menghadap internet).
   **`ERP_URL` biarkan kosong dulu.**
4. `sudo ln -s /opt/autograde-demo/demo-autograde.sh /usr/local/bin/demo-autograde`, lalu
   `demo-autograde upgrade v1.19.0` (pasang pertama = upgrade dari kosong).
5. Isi data **sebelum** link ERP: `docker compose exec -T console python
   scripts/seed-console-demo.py --hari 365`. Seeder menolak DB yang sudah punya akun dari
   AutoERP, dan tarikan dari ERP tidak menimpa akun lokal yang emailnya sama.
6. Baru isi `ERP_URL=https://demo.smagri.id` + kunci integrasi milik site demo, lalu
   `docker compose up -d`.

⚠️ **`ERP_COMPANY` wajib diisi `PT Sawit Rambang Lestari`, jangan dikosongkan.** Site
`demo.smagri.id` memuat **tiga** Company dan yang jadi default bukan punya seeder demo
(`REA KALTIM PLANTATIONS (Demo)`, terukur 2026-09-29). Kosong = AutoERP membukukan ke
Company default itu, cost center-nya milik Company lain, dan **setiap** kunjungan ditolak
`HTTP 417: Cost Center Main - SRL does not belong to the Company ...`. Layar operator tidak
menunjukkan apa pun; gagalnya hanya terlihat di tab Status, bagian Antrean ERP. Di PC pabrik
kosong itu benar, karena site-nya cuma punya satu Company.

⚠️ **Baris antrean yang sudah mentok percobaan tidak ikut terkirim sesudah `.env`
diperbaiki**, walau ditekan Kirim Ulang: jadwal coba lagi sudah lewat batasnya. Kiriman
**baru** langsung jalan. Bersihkan sisanya sekali saja sesudah perbaikan benar-benar
terbukti (kirim satu timbangan uji, pastikan tiketnya muncul di ERP demo dengan Company
yang benar, lalu hapus tiket uji itu).

## Test

| Lapis | Berkas | Butuh |
|---|---|---|
| Unit | `tests/unit/test_demo_image_workflow.py`, `tests/unit/test_demo_kit.py` | tidak ada |
| Kunci CI (`upgrade`/`status` saja) | `deploy/demo/demo-autograde-ci.test.sh` (dijalankan juga oleh `test_demo_kit.py`), `tests/unit/test_demo_image_workflow.py` | bash; kasus kunci butuh `flock` (CI, droplet) |
| Mode demo hidup | `tests/unit/test_demo_mode_setting.py`, `tests/unit/test_demo_frames.py`, `tests/unit/test_console_html_demo_hidup.py`, `tests/browser/test_browser_demo_hidup.py` | node, Playwright |
| Skrip | `deploy/demo/demo-autograde.test.sh` (dijalankan juga oleh `test_demo_kit.py`) | bash |
| E2E | `tests/e2e/test_demo_kit_docker.py` | Docker + image demo yang sudah dibangun |

E2E menyalakan image lewat compose kit di port 18100 (bukan 8100), mengisi data, login dengan
akun demo, dan memeriksa ukuran image serta batas RAM:

```bash
docker buildx build --platform linux/amd64 --load --build-arg TORCH_VARIANT=cpu \
    --build-arg WITH_SDK=false --build-arg APP_VERSION=v0.0.0 -t autograde-demo:test .
E2E_DEMO_IMAGE=autograde-demo:test pytest tests/e2e/test_demo_kit_docker.py -rs
```
