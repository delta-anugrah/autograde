# Mengganti sumber kamera satu line

Untuk teknisi di lapangan (AnyDesk ke PC pabrik) yang perlu mengganti sumber
gambar satu line kamera — misalnya kamera lepas kabel dan sementara mau diuji
pakai video rekaman, atau sedang training pakai foto diam.

Layar: konsol → login **support** (bukan operator biasa) → tab **Sumber Kamera**.

## Yang bisa dipilih

| Pilihan | Dipakai untuk | Butuh berkas |
|---|---|---|
| Kamera Hikrobot | produksi | tidak — malah **ditolak** kalau diisi |
| Webcam | dev di laptop | tidak — malah **ditolak** kalau diisi |
| Video | uji ulang rekaman | ya |
| Foto | uji satu frame diam | ya |

Video dan Foto **wajib** pilih berkas dari dropdown. Kamera Hikrobot dan
Webcam **tidak boleh** punya berkas — layar menolak kombinasi yang salah
sebelum sempat disimpan.

## Menaruh berkas

Berkas video/foto **tidak diunggah dari layar** — sengaja tidak ada tombol
upload. Taruh berkasnya langsung ke folder `media/` di host lewat AnyDesk atau
USB:

- MacBook dev: `<repo>/media/`
- PC pabrik: `/opt/palmgrade/autograde/media/`

Begitu berkas ada di folder itu, dia langsung muncul di dropdown **tanpa
restart apa pun** — daftarnya dibaca ulang tiap kali layar Sumber Kamera
dibuka.

## Menyimpan

Pilih sumber untuk line yang mau diganti, lalu tekan **Simpan & Restart**.

**Hanya line yang setelannya berubah yang direstart** — line lain yang tidak
disentuh terus grading seperti biasa. Restart satu line makan waktu sekitar
10 detik; selama itu line tersebut berhenti sebentar.

## Kalau satu line tidak menjawab

Ini bagian paling penting untuk dipahami, karena kalau terlewat teknisi akan
menekan Simpan berulang-ulang tanpa guna.

**Setelan tetap tersimpan** walau line-nya sedang mati atau tidak menjawab
restart. Layar akan bilang line mana yang belum kena. Line itu akan
**membaca setelan barunya sendiri saat hidup lagi** — tidak perlu menyimpan
ulang, dan tidak perlu menunggu line itu hidup dulu baru menyimpan.

Jadi kalau layar bilang "Line 2 tidak menjawab": setelan Line 2 sudah aman
tersimpan. Begitu Line 2 hidup lagi (kabel dicolok ulang, container
direstart manual, dsb), dia otomatis memakai sumber yang baru dipilih tadi.

## Mencobanya di MacBook (tanpa Docker)

Layar ini bisa dipakai penuh di laptop — kamera Hikrobot memang tidak bisa
(MVS SDK Linux), tapi Video dan Foto jalan lewat jalur native.

```bash
cd autograde
make console        # tab 1 — layar operator di :8100
make line N=2       # tab 2 — line 2, ikut pilihan Line 2 di layar
```

Taruh berkasnya di `autograde/media/`. `make line` membaca `media.env`, jadi
pilihan per-line di layar berlaku di sini juga — bukan cuma di Docker.

⚠️ **`make line` berputar sampai Ctrl-C, dan itu memang perlu.** Restart dari
layar bekerja dengan menyuruh proses line KELUAR; di pabrik `restart:
unless-stopped` milik Docker yang menyalakannya lagi. Jalur native tidak punya
siapa-siapa, jadi loop itu yang menggantikannya. Sesudah Simpan & Restart,
terminalnya mencetak:

```
line-2 keluar atas permintaan konsol — menyalakan ulang dengan setelan baru
```

lalu sekitar 20 detik kemudian kartunya ONLINE lagi dengan sumber baru.

Keluar yang TIDAK normal (berkas media rusak, port dipakai) menghentikan loop
dan mencetak exit code-nya — supaya satu salah setelan tidak jadi gagal-nyala
yang memenuhi layar.

## Jebakan

⚠️ **Jangan menyunting `media.env` dengan tangan saat konsol jalan.** Layar
Sumber Kamera yang menulis berkas ini; simpan berikutnya dari layar akan
menimpa **seluruh isi berkas**, termasuk perubahan tangan yang baru saja
dibuat.

⚠️ **`media.env` tidak ikut git, dan `make` yang membuatkannya.** Berkas ini
keadaan per-mesin, jadi clone bersih dan PC pabrik yang baru `git pull` tidak
punya. Target `make` apa pun (`up`, `restart`, `logs`, `down`, …) membuatnya
dari `media.env.example` kalau belum ada — ketiga line `hikrobot`, bawaan yang
benar untuk pabrik. **Tidak ada langkah manual.**

Kenapa penjaga itu ada: Compose menolak `--env-file` yang berkasnya tidak ada
(exit 1, `couldn't find env file`), persis seperti `env_file:`. Tanpa penjaga,
satu `git pull` di PC pabrik membuat **semua** perintah `make` mati sekaligus —
termasuk `make down` dan `make logs`, yaitu perintah yang dipakai orang untuk
mencari tahu ada apa.

⚠️ **`media.env` diberikan lewat `--env-file`, BUKAN `env_file:` di compose.**
Ini satu-satunya bentuk yang bekerja, dan kenapa penting dipahami sebelum ada
yang "merapikannya" kembali:

Compose menyelesaikan `${LINE_1_CAMERA_TYPE}` di `docker-compose.yml` dari
**environment shell + berkas `--env-file` saja**. `env_file:` menyuntik
environment **container**, dan itu terjadi **sesudah** interpolasi selesai. Jadi
`env_file: media.env` membuat `${LINE_1_CAMERA_TYPE:-hikrobot}` selalu jatuh ke
`hikrobot` betapapun benar isi berkasnya — seluruh fitur ini mati, tanpa satu
pun error, dengan layar yang tetap menerima pilihan dan menyimpannya.

⚠️ **Yang membuktikannya `CAMERA_TYPE`, bukan `LINE_1_CAMERA_TYPE`.** Nama
`LINE_*_` tetap muncul di environment container walau mekanismenya rusak (ikut
terbawa `env_file`), dan itulah yang dulu membuat versi rusak terlihat sehat.
Yang dibaca `core/config.py` cuma `CAMERA_TYPE` / `MEDIA_FILE` /
`CAMERA_VIDEO_LOOP`.

⚠️ **`docker-compose.prod.yml` harus ikut diubah setiap kali.** Berkas itu
memakai `volumes: !override` (MENGGANTI daftar mount, bukan menambah) dan
menulis ulang seluruh blok `environment:` konsol, karena Compose v2.40.3 di PC
Lampung membuang blok dasar begitu override menyebut kunci yang sama
(autograde#120). Mount `./media:/media:ro`, `./media.env:/config/media.env`, dan
variabel `MEDIA_DIR`/`MEDIA_ENV_PATH`/`MEDIA_FILE` **semuanya harus ada di
override itu juga** — kalau tidak, layar Sumber Kamera di pabrik tampil,
menerima pilihan, dan tidak melakukan apa pun: daftar berkasnya kosong
selamanya.

## 🔴 Skrip launcher PC pabrik HARUS diedit tangan

`/opt/palmgrade/autograde.sh` dan `/opt/palmgrade/palmgrade.sh` **hidup di host
PC pabrik, di luar repo ini**, dan mesin itu tidak punya SSH masuk — editnya
lewat AnyDesk. Skrip itu memanggil `docker compose` sendiri, **tidak** lewat
`Makefile`, jadi perbaikan di repo ini **tidak menjangkaunya**.

Selama skrip itu belum diedit, layar Sumber Kamera di Lampung akan tersimpan
tapi tidak berefek — gejalanya sama persis dengan bug yang baru diperbaiki.

Dua perubahan, di **setiap** pemanggilan `docker compose` di kedua skrip:

1. **Tambahkan flag kedua.** Setiap
   `docker compose --env-file "$ENV_FILE" …`
   jadi
   `docker compose --env-file "$ENV_FILE" --env-file "$MEDIA_ENV" …`
   dengan `MEDIA_ENV=/opt/palmgrade/autograde/media.env`.

2. **Buat berkasnya kalau belum ada**, sekali di dekat awal skrip — kalau tidak
   setiap perintah mati dengan `couldn't find env file`:

   ```bash
   MEDIA_ENV=/opt/palmgrade/autograde/media.env
   [ -f "$MEDIA_ENV" ] || cp /opt/palmgrade/autograde/media.env.example "$MEDIA_ENV"
   ```

   (`media.env.example` ikut image/checkout; kalau di PC itu belum ada, tulis
   sembilan barisnya tangan — isinya ada di `media.env.example` repo ini.)

Cara memastikan sudah benar, di PC itu, **sebelum** dianggap selesai:

```bash
cd /opt/palmgrade/autograde
docker compose --env-file .env --env-file media.env \
  -f docker-compose.yml -f docker-compose.prod.yml config \
  | grep -E 'CAMERA_TYPE|MEDIA_FILE'
```

## Terbukti di

✅ **MacBook, 2026-09-21, Docker Compose v5.5.1.** Yang dibuktikan di sini
adalah **mekanismenya** — `--env-file` ikut interpolasi, `env_file:` tidak —
dan itu berlaku sama di v2.x karena urutannya (interpolasi dulu, environment
container kemudian) tidak berubah antar versi.

Sebelum perbaikan, dengan `env_file: media.env` dan `LINE_1_CAMERA_TYPE=opencv`
di berkasnya:

```
ripe-line-1:  CAMERA_TYPE: hikrobot      <-- salah, setelan diabaikan
ripe-line-2:  CAMERA_TYPE: hikrobot
ripe-line-3:  CAMERA_TYPE: hikrobot
```

Sesudah perbaikan (`--env-file .env --env-file media.env`), line-1 video,
line-2 foto, line-3 kamera:

```
ripe-line-1:  CAMERA_TYPE: opencv   MEDIA_FILE: konveyor.mp4  CAMERA_VIDEO_LOOP: "true"
ripe-line-2:  CAMERA_TYPE: photo    MEDIA_FILE: sawit.jpg
ripe-line-3:  CAMERA_TYPE: hikrobot MEDIA_FILE: ""
```

Merged dengan `docker-compose.prod.yml` hasilnya sama, dan keempat service
tetap memegang mount `/media` (konsol plus `/config/media.env`).

Dijaga otomatis oleh `tests/unit/test_compose_sumber_kamera.py`, yang merender
`docker compose config` sungguhan dan membaca nilainya (di-skip kalau `docker`
tidak ada).

⏸️ **Yang MASIH belum dijalankan di mesin pabrik:** edit dua skrip launcher di
atas, lalu `grep` pembuktian di PC Lampung sendiri. Sampai itu dilakukan,
fiturnya bekerja di repo tapi belum bekerja di Lampung. Catat di sini tanggal,
`docker compose version` PC itu, dan output `grep`-nya yang sebenarnya.
