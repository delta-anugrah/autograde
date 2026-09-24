# Model Deteksi per line — layar Support

Dibuat 2026-09-24. Untuk: support dan teknisi yang mengganti model YOLO di satu
line, di laptop pengembang maupun di PC pabrik.

## Kenapa ada

Dulu satu `MODEL_FILE` di `.env` berlaku untuk ketiga line, diedit tangan lewat
AnyDesk. PC Lampung seminggu memuat model 3 kelas lama karena `.env` itu tidak
pernah ikut rilis kode (2026-09-23). Gejalanya senyap: label `ACC/Rej`, `Rej`
berwarna hijau, janjang tidak dihitung dan tidak ke PLC, nol error di layar.

Sekarang model dipilih per line dari konsol, dan layar menunjukkan tiga hal
yang dulu tidak terlihat: kelas di dalam tiap model, ada-tidaknya engine
TensorRT, dan model apa yang **benar-benar** sedang jalan di tiap line.

## Cara pakai

1. Login konsol dengan akun **support**, buka tab **Model Deteksi**.
2. Tiap kartu line menunjukkan **Sedang jalan**: nama model + backend
   (`TensorRT` atau `.pt`). Angka ini dilaporkan line sendiri lewat
   `/health/detail`, bukan disalin dari pilihan yang tersimpan.
3. Pilih model di dropdown. Di bawahnya muncul kelas model itu dan status
   engine-nya.
4. Tekan **Simpan & Restart**. Modal muncul menyebut line yang akan restart,
   model lama → model baru, dan **truk yang sedang diproses** di line itu.
5. **Ganti & Restart** menyimpan lalu merestart line yang berubah saja. **Batal**,
   Esc, atau klik di luar kotak membatalkan tanpa menulis apa pun.

Sekitar 15 detik sesudahnya layar menanyai line lagi. Kalau **Sedang jalan**
sudah menyebut model baru, pilihan itu berlaku.

**Bawaan PC** berarti line memakai `MODEL_FILE` di `.env`. Itu juga cara
rollback: pilih Bawaan PC, simpan.

## Yang disimpan dan siapa yang membacanya

Pilihan mendarat di `media.env`, berkas yang sama dengan layar Sumber Kamera:

```
LINE_2_MODEL_FILE=coba.pt      # kosong = MODEL_FILE di .env
```

- Konsol **satu-satunya penulis** (`services/media_env_service.py`). Simpan
  Sumber Kamera tidak menghapus pilihan model, dan sebaliknya.
- Line membacanya sendiri saat boot (`Settings.__post_init__`), karena
  environment container beku sejak container dibuat.
- Nama berkas yang disunting tangan dan tidak sah (misalnya `../../x.pt`)
  diabaikan dengan WARNING; line tetap boot memakai bawaan PC.

## Aturan di dropdown

| Keadaan model | Tampil | Bisa dipilih |
|---|---|---|
| Kelasnya tepat `Ripe`, `Unripe`, `JK`, `TP` (huruf besar-kecil bebas) | ya | ya |
| Kelas lain, misalnya model lama `ACC`, `Rej`, `TP` | ya, dengan alasannya | **tidak** |
| Berkas rusak atau bukan checkpoint YOLO | ya, "kelas tidak terbaca" | **tidak** |
| Tersimpan tapi berkasnya sudah dihapus dari folder | ya, ditandai | **tidak** |

Server menolak hal yang sama dengan **400**, jadi payload buatan tangan tidak
bisa melewatinya.

Kelas dibaca konsol **tanpa torch**: dari `data.pkl` di dalam zip `.pt` dengan
unpickler yang tidak pernah menjalankan kode dari berkas, dan dari header JSON
engine TensorRT. Lihat `services/model_library.py`.

## Menambah model baru ke PC

1. Salin berkas `.pt` ke `models/release/` di host. Di PC pabrik:
   `/opt/palmgrade/autograde/models/release/`. Layar ini tidak mengunduh apa pun.
2. Buka ulang tab Model Deteksi. Model baru muncul di dropdown dan di tabel
   "Semua model di PC ini".
3. Model baru belum punya engine: line jalan di `.pt`, sekitar 2x lebih lambat,
   tanpa error. Layar menulisnya kuning. Build engine-nya, lihat bagian berikut.

## Engine TensorRT per model

Engine dipilih dari **nama model** (`<stem>.sm<cc>.engine`), jadi tiap model
butuh engine sendiri, sekali per GPU. Tiga line yang memakai model sama berbagi
satu engine.

`scripts/build_engine.py` membangun engine untuk model milik **line yang
menjalankannya**. Jadi pilih model di layar dulu, lalu build lewat service line
itu. Di PC pabrik, dengan line dimatikan supaya build tidak berebut VRAM:

```bash
cd /opt/palmgrade
autograde stop
F=(-f autograde/docker-compose.yml -f autograde/docker-compose.prod.yml)
[ -f autograde/docker-compose.factory.yml ] && F+=(-f autograde/docker-compose.factory.yml)
docker compose --project-directory autograde "${F[@]}" \
  run --rm --no-deps --entrypoint python ripe-line-2 scripts/build_engine.py
ls -la autograde/engines/        # muncul <stem>.sm86.engine
autograde
```

Ganti `ripe-line-2` dengan line yang memakai model itu. Di laptop pengembang:
`make build-engine` membangun untuk line 1.

**Engine basi** ditandai kuning di layar. Dua tanda yang dipakai: engine lebih
tua dari berkas `.pt`-nya, atau kelas engine berbeda dari kelas `.pt`.
⚠️ Model baru berkelas sama yang disalin dengan `cp -p` (mtime lama
dipertahankan) tidak terdeteksi. Kalau isi berkas diganti tanpa ganti nama,
hapus engine-nya sendiri lalu build ulang.

## Sebelum dipakai di PC pabrik

1. **Image konsol dan line harus versi yang memuat fitur ini.** Line versi lama
   tidak membaca `LINE_N_MODEL_FILE` dan tidak melaporkan modelnya; layar
   menulis "tidak dilaporkan (versi line lama)".
2. **Compose di host harus me-mount folder model ke konsol.** Berkas compose PC
   pabrik hidup di host dan tidak ikut `autograde pull`. Di
   `docker-compose.prod.yml` host, blok `volumes: !override` service `console`,
   tambahkan:

   ```yaml
         - ./models:/app/models:ro
         - ./engines:/app/engines:ro
   ```

   Tanpa itu tabel model kosong ("Belum ada berkas .pt") walau folder host
   penuh. Cek sesudah `autograde restart`:

   ```bash
   docker exec palmgrade_console ls /app/models/release /app/engines
   ```

3. Line tidak perlu mount baru: `./models`, `./engines`, dan `media.env` sudah
   di-mount sejak layar Sumber Kamera.

## Jebakan

- **Ganti model = restart line itu, sekitar 10 detik.** Janjang yang lewat
  selama restart tidak dihitung. Tidak diblokir saat truk dibongkar
  (keputusan 2026-09-24, untuk development), tapi modal menyebut truknya: hasil
  truk itu jadi campuran dua model.
- **"Sudah dipilih" bukan "sudah berlaku".** Kalau pilihan tersimpan berbeda dari
  yang dilaporkan line, kartu menulis "Pilihan tersimpan belum berlaku". Untuk
  pilihan Bawaan PC perbandingan ini tidak bisa dibuat, karena konsol tidak
  membaca `.env` line.
- **Line yang tidak menjawab saat simpan** tetap tersimpan. Toast kuning menyebut
  line itu; ia memakai model baru begitu hidup lagi. Jangan tekan Simpan
  berulang-ulang.
- **Kelas model tetap diperiksa line saat boot, untuk dua backend.** Kalau ada
  yang lolos, log line menulis `Kelas model tidak seperti yang diharapkan`.

## Verifikasi dari terminal

```bash
grep MODEL_FILE /opt/palmgrade/autograde/media.env /opt/palmgrade/autograde/.env
docker logs ripe_line_2 2>&1 | grep -iE "kelas model|backend="
curl -s localhost:8002/health/detail | python3 -m json.tool | grep model_
```

Yang benar: `Kelas model terverifikasi: ['JK', 'Ripe', 'TP', 'Unripe']` dan
`model_backend` = `tensorrt` kalau engine-nya ada.
