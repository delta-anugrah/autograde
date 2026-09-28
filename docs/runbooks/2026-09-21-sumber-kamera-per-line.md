# Mengganti sumber kamera satu line

Untuk teknisi di lapangan (AnyDesk ke PC pabrik) yang perlu mengganti sumber
gambar satu line kamera: misalnya kamera lepas kabel dan sementara mau diuji
pakai video rekaman, atau sedang training pakai foto diam.

Layar: konsol → login **support** (bukan operator biasa) → tab **Line** → pilih
**Sumber Kamera**.

## Yang bisa dipilih

| Pilihan | Dipakai untuk | Butuh berkas |
|---|---|---|
| Kamera Hikrobot | produksi | tidak: malah **ditolak** kalau diisi |
| Webcam | dev di laptop | tidak: malah **ditolak** kalau diisi |
| Video | uji ulang rekaman | ya |
| Foto | uji satu frame diam | ya |

Video dan Foto **wajib** pilih berkas dari dropdown. Kamera Hikrobot dan
Webcam **tidak boleh** punya berkas, layar menolak kombinasi yang salah
sebelum sempat disimpan.

## Menaruh berkas

Berkas video/foto **tidak diunggah dari layar**, sengaja tidak ada tombol
upload. Taruh berkasnya langsung ke folder `media/` di host lewat AnyDesk atau
USB:

- MacBook dev: `<repo>/media/`
- PC pabrik: `/opt/palmgrade/autograde/media/`

Begitu berkas ada di folder itu, dia langsung muncul di dropdown **tanpa
restart apa pun**: daftarnya dibaca ulang tiap kali layar Sumber Kamera
dibuka.

## Menyimpan

Pilih sumber untuk line yang mau diganti, lalu tekan **Simpan & Restart**.

**Hanya line yang setelannya berubah yang direstart**: line lain yang tidak
disentuh terus grading seperti biasa. Restart satu line makan waktu sekitar
10 detik; selama itu line tersebut berhenti sebentar.

## Kalau satu line tidak menjawab

Ini bagian paling penting untuk dipahami, karena kalau terlewat teknisi akan
menekan Simpan berulang-ulang tanpa guna.

**Setelan tetap tersimpan** walau line-nya sedang mati atau tidak menjawab
restart. Layar akan bilang line mana yang belum kena. Line itu akan
**membaca setelan barunya sendiri saat hidup lagi**: tidak perlu menyimpan
ulang, dan tidak perlu menunggu line itu hidup dulu baru menyimpan.

Jadi kalau layar bilang "Line 2 tidak menjawab": setelan Line 2 sudah aman
tersimpan. Begitu Line 2 hidup lagi (kabel dicolok ulang, container
direstart manual, dsb), dia otomatis memakai sumber yang baru dipilih tadi.

## Cara kerjanya

Konsol satu-satunya penulis `media.env` (`services/media_env_service.py`), dan
tiap line **membacanya sendiri saat boot** (`Settings.__post_init__`, dari mount
`./media.env:/config/media.env:ro`). Isi berkas **menang** atas environment
container. Itu disengaja: environment container beku sejak container dibuat,
dan Simpan & Restart cuma menyuruh proses line keluar (`/internal/restart`)
lalu `restart: unless-stopped` menyalakan container yang sama.

Makefile dan launcher pabrik tetap memberi berkas yang sama ke Compose lewat
`--env-file`, tapi yang menentukan sumber line adalah berkasnya.

⚠️ **Ukurannya `/health/detail`, bukan `printenv`.** Sesudah ganti sumber,
`docker exec … printenv CAMERA_TYPE` boleh tetap menunjukkan nilai lama; itu
benar. Yang dipakai line:

```bash
curl -s localhost:8001/health/detail | grep -o '"camera_type":"[^"]*"'
```

## Mencobanya di MacBook (tanpa Docker)

Layar ini bisa dipakai penuh di laptop, kamera Hikrobot memang tidak bisa
(MVS SDK Linux), tapi Video dan Foto jalan lewat jalur native.

```bash
cd autograde
make console        # tab 1: layar operator di :8100
make line N=2       # tab 2: line 2, ikut pilihan Line 2 di layar
```

Taruh berkasnya di `autograde/media/`. `make line` membaca `media.env`, jadi
pilihan per-line di layar berlaku di sini juga, bukan cuma di Docker.

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
dan mencetak exit code-nya: supaya satu salah setelan tidak jadi gagal-nyala
yang memenuhi layar.

## Jebakan

⚠️ **Jangan menyunting `media.env` dengan tangan saat konsol jalan.** Layar
Sumber Kamera dan Model Deteksi yang menulis berkas ini; simpan berikutnya dari
layar akan menimpa **seluruh isi berkas**, termasuk perubahan tangan yang baru
saja dibuat.

⚠️ **`media.env` tidak ikut git.** Berkas ini keadaan per-mesin. Di mesin yang
build dari source, target `make` apa pun (`up`, `restart`, `logs`, `down`, …)
membuatnya dari `media.env.example` kalau belum ada, ketiga line `hikrobot`:
tanpa penjaga itu Compose menolak `--env-file` yang berkasnya tidak ada, dan
semua perintah `make` mati sekaligus. Di PC pabrik berkasnya dibuat sekali saat
pasang di `/opt/palmgrade/autograde/media.env`; launcher membawanya kalau ada.

⚠️ **`docker-compose.prod.yml` harus ikut diubah setiap kali.** Berkas itu
memakai `volumes: !override` (MENGGANTI daftar mount, bukan menambah) dan
menulis ulang seluruh blok `environment:` konsol, karena Compose v2.40.3 di PC
Lampung membuang blok dasar begitu override menyebut kunci yang sama
(autograde#120). Mount `./media:/media:ro` dan `./media.env:/config/media.env`,
serta variabel konsol `MEDIA_DIR`/`MEDIA_ENV_PATH`/`MEDIA_FILE`, **harus ada di
override itu juga**: kalau tidak, layar Sumber Kamera di pabrik tampil,
menerima pilihan, dan tidak melakukan apa pun. Compose di PC pabrik hidup di
host dan tidak ikut `autograde pull`.

## Launcher PC pabrik

`/opt/palmgrade/autograde.sh` (dipanggil `autograde`) hidup di host, di luar
repo ini; sumbernya di repo `sawit`, `docs/runbooks/files/autograde.sh`, dan
dipasang tangan lewat AnyDesk. Dua hal di sana yang fitur ini butuhkan, dan
keduanya sudah terpasang di Lampung sejak 2026-09-23:

1. Setiap pemanggilan Compose membawa `--env-file .env` dan
   `--env-file media.env` (yang kedua hanya kalau berkasnya ada).
2. Menyalakan memakai `up -d --force-recreate`: perubahan yang cuma datang dari
   `--env-file` tidak selalu terbaca Compose sebagai perubahan.

## Terbukti di

✅ **Lampung, 2026-09-23, `v1.13.1`.** Ganti Foto ↔ Video ↔ Hikrobot dari layar
akhirnya berlaku sesudah empat bug berantai ditutup: launcher tidak mengirim
`--env-file media.env`, `up -d` tanpa `--force-recreate`, `MEDIA_DIR` cuma
diberikan ke konsol, dan line tidak pernah membaca `media.env` sendiri.

Dijaga otomatis oleh `tests/unit/test_compose_sumber_kamera.py` (merender
`docker compose config` sungguhan; di-skip kalau `docker` tidak ada) dan
`tests/unit/test_line_baca_media_env.py`.
