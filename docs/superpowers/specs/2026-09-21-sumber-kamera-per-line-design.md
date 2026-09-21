# Sumber kamera per-line, diatur dari konsol

Tanggal: 2026-09-21
Status: disetujui, siap dibuat rencana kerja

## Masalah

`CAMERA_TYPE` cuma bisa diubah dengan mengedit `.env` di host. Di PC pabrik itu
berarti AnyDesk, edit berkas, restart container. Untuk pekerjaan dev dan demo —
satu-satunya tempat setelan ini benar-benar sering berganti — itu mahal.

Dua hal lain memperburuknya:

1. **Satu `.env` untuk empat container.** Tidak ada cara menjalankan line-1 dari
   video sementara line-2 tetap memakai kamera sungguhan.
2. **Berkas media terikat bind-mount.** `${CAMERA_VIDEO_PATH}:/videos/video-in:ro`
   memilih berkasnya saat container **dibuat**. Ganti berkas berarti
   `docker compose up` ulang, bukan restart — jadi memilih berkas dari layar
   tidak mungkin dilakukan dengan bentuk yang sekarang.

## Yang dibangun

Layar support baru: tiap line dipilih sumbernya sendiri, berkas media dipilih
dari daftar, simpan lalu line yang berubah direstart.

Empat pilihan di layar, memetakan ke tiga nilai `CAMERA_TYPE`:

| Pilihan layar | `CAMERA_TYPE` | Berkas |
|---|---|---|
| Kamera Hikrobot | `hikrobot` | — |
| Webcam | `opencv` | — |
| Video | `opencv` | wajib |
| Foto | `photo` | wajib |

`opencv` melayani dua pilihan karena kelas kameranya memang satu; yang
membedakan cuma ada-tidaknya berkas. Pemisahan itu dilakukan di layar, bukan di
`CAMERA_TYPE`, supaya nilai env-nya tidak berubah arti.

### Yang TIDAK dibangun

Sengaja, supaya ruang lingkupnya tetap satu hal:

- Unggah berkas dari layar. Berkas ditaruh di folder `media/` dari host (AnyDesk,
  salin biasa). Unggah butuh batas ukuran, validasi isi, dan penjagaan disk penuh
  — fitur sendiri.
- Hapus berkas dari layar.
- Pratinjau video sebelum dipilih.
- Ganti sumber tanpa restart (hot-swap). Ditolak sadar; alasannya di
  "Keputusan yang dikunci".

## Bentuknya

```
┌─ host ──────────────────────────────────────────────┐
│  .env          <- rahasia: lisensi, R2, webhook     │
│                   TIDAK pernah ditulis konsol       │
│  media.env     <- setelan sumber, 3 baris per line  │
│                   ditulis konsol                    │
│  media/        <- berkas video & foto               │
│    konveyor-pagi.mp4                                │
│    sample_sawit.jpg                                 │
└─────────────────────────────────────────────────────┘
        │ env_file                    │ mount
        ▼                             ▼
┌─ line-1..3 ──────────┐      ┌─ konsol ─────────────┐
│ baca CAMERA_TYPE     │      │ /media       (ro)    │
│ dari environment     │◀─────│ /config/media.env(rw)│
│ /media       (ro)    │ HTTP │                      │
│ POST /internal/      │      │ layar Support        │
│      restart         │      │                      │
└──────────────────────┘      └──────────────────────┘
```

Konsol menulis berkas, line membacanya lewat environment yang Compose susun dari
berkas itu. Tidak ada jalur langsung konsol → line untuk setelan ini; yang lewat
HTTP cuma perintah restart.

## Keputusan yang dikunci

Enam, masing-masing dengan alasan yang membuatnya sulit dibuka lagi tanpa sebab
baru.

### 1. Simpan ke berkas lalu restart, bukan ganti sumber di tengah jalan

Ganti kamera tanpa restart butuh mesin keadaan tersendiri: putus kamera lama,
bangun yang baru, sambungkan ke `FrameCaptureWorker` yang sedang membaca frame,
tangani gagal-connect (kembali ke sumber lama? diam tanpa kamera?), dan ajari
watchdog membedakan "mati karena ganti sumber" dari "mati beneran".

Semua itu untuk menghemat sepuluh detik pada setelan yang di PC pabrik diubah
sekali seumur pemasangan. Dan gejala gagalnya persis kategori bug termahal di
AutoGrade: line terlihat hidup, log bersih, tidak ada frame masuk. Kita sudah
kena bentuk lain dari gejala yang sama dua kali (container yatim memegang GigE,
`COMPOSE_PROJECT_NAME` bentrok).

Bentuk layar dan jalur simpannya sama untuk kedua pilihan, jadi kalau sepuluh
detik itu ternyata mengganggu, yang diganti cuma apa yang terjadi sesudah
tombol ditekan.

### 2. `media.env` terpisah, bukan `.env` utama

`.env` memuat `LICENSE_TOKEN`, `R2_SECRET_ACCESS_KEY`, dan `WEBHOOK_SECRET`.
Me-mount berkas itu writable ke konsol berarti satu bug penulisan bisa merusak
kredensial produksi, dan satu celah di konsol bisa membacanya.

`media.env` cuma memuat sembilan baris yang memang milik layar ini. Rusak paling
jauh berarti line kembali ke bawaan `hikrobot`.

### 3. Line membaca dari disk, bukan bertanya ke konsol

Setelan grading (`conf_threshold`, `garis_capture`) ditarik line dari konsol
lewat `/internal/setelan` saat boot. Sumber kamera tidak mengikuti pola itu.

Bedanya: setelan grading punya bawaan waras di `.env` — konsol mati berarti line
memakai nilai `.env` dan tetap grading. Sumber kamera tidak punya bawaan yang
bisa menebak; line yang tidak tahu sumbernya tidak bisa jalan sama sekali.
Membuat konsol jadi syarat boot line adalah menukar satu titik gagal dengan
empat.

### 4. Restart lewat HTTP, bukan `docker.sock`

Me-mount `docker.sock` ke konsol memberinya kendali penuh atas setiap container
di PC itu — termasuk menghapusnya. Itu untuk membeli satu kemampuan: merestart
line yang sudah menggantung dan tidak lagi menjawab HTTP.

Line menggantung sudah punya penanganan sendiri (watchdog 10 detik di
`main.py`), dan kalaupun tidak, jalan keluarnya AnyDesk — bukan alasan menaruh
kunci seluruh Docker di layar yang bisa dibuka dari browser.

### 5. Satu `MEDIA_FILE`, bukan `VIDEO_PATH` + `PHOTO_PATH`

Bentuk sekarang punya dua variabel yang **cuma satu terpakai**, tergantung
`CAMERA_TYPE`. Dikalikan tiga line jadi enam variabel, empat di antaranya selalu
mati tapi tetap terbaca di berkas. Mengisi `LINE_1_PHOTO_PATH` saat typenya
`opencv` tidak melakukan apa-apa, tanpa pesan apa pun.

Satu `MEDIA_FILE` yang dibaca sebagai video atau foto tergantung `CAMERA_TYPE`
tidak punya keadaan "terisi tapi diam".

### 6. Gagal sebagian dibiarkan, tidak di-rollback

Kalau line-1 berhasil restart dan line-2 tidak menjawab, `media.env` sudah
terlanjur ditulis untuk keduanya. Rollback berarti menulis berkas lagi dan
merestart lagi — dua langkah yang bisa gagal dengan cara yang sama, meninggalkan
keadaan yang lebih sulit dibaca daripada yang mau diperbaiki.

Line-2 toh akan memakai setelan baru begitu ia hidup lagi, karena ia membacanya
dari disk (keputusan 3). Yang dibutuhkan cuma pesan yang jujur: "Line 2 tidak
menjawab — setelan tersimpan, berlaku saat line 2 hidup lagi."

## Bagian-bagiannya

Empat modul baru, masing-masing satu tugas dan bisa diuji sendiri.

### `domain/sumber_kamera.py` — aturan, tanpa I/O

Meniru `domain/setelan_grading.py` yang sudah ada: konstanta pilihan yang sah,
satu fungsi pembersih, satu kelas galat yang route terjemahkan jadi 400.

Isinya:

- `SUMBER` — empat pilihan layar (`hikrobot`, `webcam`, `video`, `foto`)
- `BUTUH_BERKAS` — himpunan yang wajib punya berkas (`video`, `foto`)
- `bersihkan_sumber(payload)` — validasi satu line, melempar `SumberTidakSah`
- Penjagaan nama berkas: tolak apa pun yang memuat pemisah path atau `..`

Nama berkas disaring, bukan di-escape: berkas media dipilih dari daftar yang
konsol susun sendiri, jadi nilai di luar daftar itu adalah payload yang dibuat
tangan, dan satu-satunya alasan membuatnya adalah keluar dari folder `media/`.

Tanpa import cv2/torch, supaya ikut CI ringan (aturan yang sama dengan
`domain/grade_class.py`).

### `services/media_env_service.py` — baca & tulis `media.env`

Satu-satunya yang tahu bentuk berkas itu.

- `baca()` → setelan tiga line, lengkap dengan bawaan untuk baris yang hilang
- `tulis(setelan)` → menimpa seluruh berkas

Menulisnya lewat berkas sementara di folder yang sama lalu `os.replace` — berkas
setengah tertulis akibat mati listrik akan membuat ketiga line gagal boot, dan
`os.replace` atomik di POSIX.

Baris yang tidak dikenal diabaikan, bukan menggagalkan pembacaan: berkas yang
ditulis versi lebih baru tidak boleh mematikan versi lama.

### `services/media_library.py` — isi folder `/media`

- `daftar_video()` / `daftar_foto()` — nama berkas saja, bukan path
- Disaring ekstensi: `.mp4`/`.avi`/`.mkv` untuk video, `.jpg`/`.jpeg`/`.png` untuk foto

Folder tidak ada atau tidak terbaca → daftar kosong, bukan galat. Layar yang
kosong bisa dibaca ("belum ada berkas"); layar yang gagal dimuat tidak.

### `domain/sumber_kamera_resolver.py` — pilihan → kamera mana

Satu fungsi murni: dari (`pilihan`, `berkas`) menghasilkan kelas kamera mana
yang dipakai dan path apa yang diberikan padanya.

Logika ini sekarang berupa if-else di `main.py:133-157`, terjalin dengan
`connect()`, penanganan galat, dan `set_camera()`. Dipisahkan supaya pemetaannya
bisa diuji tanpa menyalakan aplikasi; `main.py` tinggal memakai hasilnya.

## Alur simpan

1. **Validasi isian** — `bersihkan_sumber` per line
2. **Buktikan berkas terbaca** — konsol membuka berkasnya dengan cv2
3. **Tulis `media.env`** — ketiga line sekaligus, satu berkas
4. **Restart line yang berubah** — `POST /internal/restart`, hanya yang setelannya beda
5. **Laporkan** — line mana yang direstart, line mana yang tidak menjawab

Gagal di 1 atau 2 → tidak menulis apa pun. Setelan lama tetap berlaku.

### Kenapa langkah 2 ada

`OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat berkasnya tidak terbaca —
fail-fast, berbeda dengan `hikrobot` yang cuma memberi peringatan dan membiarkan
worker mencoba lagi (`main.py:150-155`).

Tanpa pembuktian di depan, memilih berkas rusak berarti: line boot, gagal,
mati, `restart: unless-stopped` menyalakannya lagi, gagal lagi — selamanya.
Satu-satunya jalan keluar AnyDesk dan edit `media.env` tangan, yaitu persis
pekerjaan yang fitur ini hapus.

### `POST /internal/restart`

Line menjawab 200 lebih dulu, baru keluar sekitar satu detik kemudian. Keluar
sebelum menjawab membuat konsol melihat koneksi putus dan melaporkannya sebagai
gagal, padahal berhasil.

Diamankan `_verify_internal_secret` seperti route internal lainnya.

## Layar

Tab Support, layar baru "Sumber Kamera".

```
Line 1   (•) Kamera Hikrobot   ( ) Webcam   ( ) Video   ( ) Foto

Line 2   ( ) Kamera Hikrobot   ( ) Webcam   (•) Video   ( ) Foto
         Berkas [ konveyor-pagi.mp4  v ]    [x] Ulang terus

Line 3   ( ) Kamera Hikrobot   ( ) Webcam   ( ) Video   (•) Foto
         Berkas [ sample_sawit.jpg   v ]

         ! Menyimpan akan merestart line yang berubah (~10 detik).

                                        [ Simpan & Restart ]
```

Baris berkas muncul hanya untuk Video dan Foto. Isinya daftar dari
`media_library`, bukan kolom ketik — path yang salah ketik adalah cara paling
mudah membuat line gagal boot, dan daftar menghapus kemungkinannya.

Di Support (`role=support`), bukan Setelan biasa: salah pilih membuat line
berhenti grading.

## Perubahan Compose

Per line:

```yaml
- CAMERA_TYPE=${LINE_1_CAMERA_TYPE:-hikrobot}
- CAMERA_VIDEO_LOOP=${LINE_1_VIDEO_LOOP:-false}
- MEDIA_FILE=${LINE_1_MEDIA_FILE:-}
```

Mount `./media:/media:ro` di keempat service. Konsol mendapat satu tambahan:
`./media.env:/config/media.env` (writable).

Bind-mount lama dibuang:

```yaml
- ${CAMERA_VIDEO_PATH:-/dev/null}:/videos/video-in:ro   # dihapus
```

Ini yang membuat ganti berkas cukup restart, bukan `up` ulang: seluruh folder
sudah terlihat sejak container dibuat.

`env_file: media.env` ditambahkan di keempat service.

⚠️ **`env_file` belum pernah dipakai di berkas ini** — semua variabel disebut satu
per satu. Jadi ini pola baru yang harus dibuktikan di Linux, bukan di MacBook:
Compose di sana v5.5.1 dan berkas yang rusak pun terlihat sehat (sudah terbukti
sekali, autograde#120).

## Kompatibilitas

`.env` lama yang masih menulis `CAMERA_TYPE=hikrobot` (tanpa prefix line) tidak
lagi terbaca — variabelnya berganti nama jadi `LINE_1_CAMERA_TYPE` dan
seterusnya. Bawaan `:-hikrobot` menangkap PC yang belum punya `media.env`, jadi
PC pabrik yang memang memakai `hikrobot` tidak terpengaruh.

Yang perlu perhatian cuma PC yang sengaja menjalankan `opencv` atau `photo` dari
`.env` — sejauh ini hanya MacBook dev dan uji video di Lampung, keduanya
dipindah tangan ke `media.env` sekali.

## Uji

**Unit** (bagian terbesar):

- Aturan: empat pilihan sah, nama berkas ditolak saat memuat `/` atau `..`,
  video/foto tanpa berkas ditolak, hikrobot/webcam dengan berkas ditolak
- `media.env`: berkas tidak ada, baris rusak, baris tak dikenal diabaikan,
  tulis tidak meninggalkan berkas separo
- Daftar berkas: folder kosong, folder tidak ada, ekstensi tersaring
- Resolver: tiap pilihan menghasilkan kamera dan path yang benar

**E2E**:

- Simpan setelan sah → berkas berubah, hanya line yang berubah direstart
- Simpan berkas rusak → ditolak, berkas tidak berubah
- Satu line tidak menjawab → dua lainnya tetap jalan, pesannya menyebut line itu

**Manual, tidak bisa diotomatiskan**:

- Compose benar-benar membaca `media.env` — **di Linux**, dengan Compose yang
  seumur dengan pabrik. MacBook tidak membuktikan apa pun soal ini.
