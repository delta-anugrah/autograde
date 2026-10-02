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
| Skrip | `deploy/demo/demo-autograde.test.sh` (dijalankan juga oleh `test_demo_kit.py`) | bash |
| E2E | `tests/e2e/test_demo_kit_docker.py` | Docker + image demo yang sudah dibangun |

E2E menyalakan image lewat compose kit di port 18100 (bukan 8100), mengisi data, login dengan
akun demo, dan memeriksa ukuran image serta batas RAM:

```bash
docker buildx build --platform linux/amd64 --load --build-arg TORCH_VARIANT=cpu \
    --build-arg WITH_SDK=false --build-arg APP_VERSION=v0.0.0 -t autograde-demo:test .
E2E_DEMO_IMAGE=autograde-demo:test pytest tests/e2e/test_demo_kit_docker.py -rs
```
