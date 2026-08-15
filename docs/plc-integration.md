# PLC Integration — ODOT CN-8031 (Modbus-TCP)

Vision mengirim hasil grading tiap line (ACC / REJ / ERROR) ke PLC Mitsubishi lewat remote
IO **ODOT CN-8031** via Modbus-TCP, dan membaca balik motor fault + E-stop. Dokumen ini
menggantikan skematik PDF *"REMOTE IO — CONVEYOR SAWIT"* (DW.26/07/27 hal. 19–20, PT Nexio
Teknologi Otomasi), yang tidak ada di repo — tabel alamat di bawah disalin apa adanya dari
sana, plus percakapan dengan pak Ocit (PLC engineer).

Seluruh logika terkurung di paket `src/palmgrade/plc/`. Kode di luar paket ini hanya boleh
menyentuh tiga fungsi: `start_plc_worker`, `submit_grading`, `inputs`.

---

## Hardware

| Part number | Peran |
| --- | --- |
| ODOT CN-8031 | Coupler remote IO, sisi kita bicara ke ini via Modbus-TCP (port 502) |
| CT-222F | Modul output, source/PNP, high-active |
| CT-122F | Modul input, NPN, **low-active** |
| CT-5801 | Modul catu daya panel |
| AJ65SBTB1-16D1 | Modul input Mitsubishi (16 titik) — sisi PLC yang menerima dari CT-222F |
| AJ65SBTB1-16T1 | Modul output Mitsubishi (16 titik) — sisi PLC yang mengirim ke CT-122F |

**Catatan sink/source (sudah diverifikasi cocok, tanpa relay):**
CT-222F source/PNP → AJ65SBTB1-16D1, dengan COM di 0V. AJ65SBTB1-16T1 sink (COM di 0V) →
CT-122F low-aktif. Kedua pasangan cocok secara elektris tanpa perlu relay perantara.

**Batas koneksi coupler:** CN-8031 menerima maksimum **5 client Modbus-TCP bersamaan**. Tiga
container line (satu koneksi per proses, tidak ada pooling) memakai 3 dari 5 slot itu.

---

## Coil / DO — vision menulis (zero-based)

| Coil  | Alamat PLC  | Arti         | Ditulis oleh |
| ----- | ----------- | ------------ | ------------ |
| 0     | X0300       | CAM 1 OK     | line 1       |
| 1     | X0301       | CAM 1 NG     | line 1       |
| 2     | X0302       | CAM 1 ERROR  | line 1       |
| 3     | X0303       | CAM 2 OK     | line 2       |
| 4     | X0304       | CAM 2 NG     | line 2       |
| 5     | X0305       | CAM 2 ERROR  | line 2       |
| 6     | X0306       | CAM 3 OK     | line 3       |
| 7     | X0307       | CAM 3 NG     | line 3       |
| 8     | X0308       | CAM 3 ERROR  | line 3       |
| 9     | X0309       | HEARTBEAT PC | line 1       |
| 10    | X030A       | LINE 1 ALIVE | line 1       |
| 11    | X030B       | LINE 2 ALIVE | line 2       |
| 12    | X030C       | LINE 3 ALIVE | line 3       |
| 13–15 | X030D–X030F | SPARE        | —            |

Coil 9 (HEARTBEAT PC) tidak punya writer khusus — ia hidup lewat mekanisme `PLC_COIL_ALIVE`
line 1 (lihat di bawah). Modbus function code `05` (write single coil).

## Discrete input / DI — vision membaca (zero-based)

| DI    | Alamat PLC  | Arti             |
| ----- | ----------- | ---------------- |
| 0–9   | Y0310–Y0319 | MOTOR 1–10 FAULT |
| 10    | Y031A       | EMERGENCY STOP   |
| 11–15 | Y031B–Y031F | SPARE            |

Modbus function code `02` (read discrete inputs). Semua tiga line membaca discrete input yang
sama — itu status bersama conveyor, bukan per-line.

---

## Env vars (`PLC_*`)

Semua field dideklarasikan di `core/config.py` (satu blok berlabel `# ── PLC / ODOT CN-8031
(Modbus-TCP) ──`), bukan config terpisah — konvensi repo ini: satu sumber kebenaran untuk env.

| Variable | Default | Arti |
| --- | --- | --- |
| `PLC_ENABLED` | `false` | Saklar fitur. `false` = default, dipakai cloud dan semua PC dev — lihat "Mati secara default" di bawah |
| `PLC_HOST` | (kosong) | IP coupler ODOT. Kosong + `PLC_ENABLED=true` → worker tidak dijalankan, warning di log |
| `PLC_PORT` | `502` | Port Modbus-TCP standar |
| `PLC_UNIT_ID` | `1` | Modbus unit/slave ID |
| `PLC_COIL_BASE` | `0` | **Literal per line, bukan dari `.env`** — properti fisik line, bukan setelan yang boleh beda antar PC. Line 1 = `0`, line 2 = `3`, line 3 = `6` |
| `PLC_COIL_ALIVE` | (kosong) | **Literal per line.** Daftar coil dipisah koma yang di-toggle tiap detik. Line 1 = `9,10` (9 = HEARTBEAT PC bersama, 10 = ALIVE line 1), line 2 = `11`, line 3 = `12`. Kosong = fitur alive mati |
| `PLC_PULSE_MS` | `200` | Lebar pulse ON untuk satu keputusan OK/NG. **Belum dikonfirmasi pak Ocit** — lihat "Belum diputuskan" |
| `PLC_PULSE_GAP_MS` | `100` | Jeda OFF wajib sebelum pulse berikutnya pada coil yang sama, supaya PLC melihat tepi naik terpisah |
| `PLC_QUEUE_MAX` | `1` | **Berapa banyak keterlambatan yang mau kamu beli**, bukan kapasitas/keandalan. Jumlah pulse yang boleh terutang per coil; tiap slot = `(pulse+gap)` ms sinyal jadi lebih basi. Penuh → drop + hitung, bukan tunggu |
| `PLC_POLL_MS` | `200` | Interval `PlcWorker.run_once()` — sekaligus keepalive watchdog ODOT |
| `PLC_DI_COUNT` | `16` | Jumlah discrete input yang dibaca tiap poll |

`docker-compose.yml` men-set `PLC_COIL_BASE`/`PLC_COIL_ALIVE` sebagai literal per service
(`ripe-line-1/2/3`); variabel lain diinterpolasi dari `.env` dengan fallback default di atas.

---

## Throughput ceiling — DROP adalah steady state normal, bukan pengecualian

Satu coil hanya bisa membawa satu pulse pada satu waktu. Dengan default `PLC_PULSE_MS=200` +
`PLC_PULSE_GAP_MS=100`, kapasitas satu coil adalah:

```
1 / (pulse_s + gap_s) = 1 / (0.2 + 0.1) ≈ 3.3 sinyal/detik
```

Kamera always-ON bisa menghasilkan sampai **~10 keputusan grading/detik** per line. Itu jauh
di atas 3,3/detik yang muat di satu coil OK atau NG. Konsekuensinya: **overflow adalah kondisi
normal di bawah beban, bukan sesuatu yang salah.**

Kebijakannya **DROP dan hitung — tidak pernah nge-lag**. Menahan sinyal di antrean supaya
tidak ada yang hilang justru lebih buruk: sinyal yang telat menempel ke buah yang salah di
belt, karena belt terus berjalan sementara antrean menumpuk. Lebih baik kehilangan sebagian
sinyal yang akurat daripada mengirim semua sinyal yang salah tempat.

`PLC_PULSE_MS` dan `PLC_PULSE_GAP_MS` adalah knob tuning lapangan — **ini yang pertama harus
ditinjau ulang saat commissioning**, setelah kecepatan belt dan actuator sesungguhnya
diketahui (lihat "Belum diputuskan").

### `PLC_QUEUE_MAX` = harga staleness, bukan kapasitas

`PulseScheduler` menguras satu pulse terutang tiap `pulse_s + gap_s` (default 300ms). Jadi
antrean yang penuh berarti **setiap pulse yang diterima PLC mewakili keputusan dari
`queue_max × 300ms` yang lalu**. Dengan `queue_max=20` itu 6 detik — pada belt berjalan, sinyal
itu mendarat di buah yang benar-benar berbeda, terus-menerus, selama produksi normal.

Karena itu defaultnya **1**: paling banyak satu pulse terutang ⇒ staleness ≤ 300ms secara
struktural, tanpa perlu state timestamp/discard tambahan. Menaikkan angka ini **tidak** membuat
sinyal lebih andal — ia menukar drop (jujur, terhitung) dengan sinyal basi (diam-diam salah).

### Dua counter drop yang terpisah, sengaja tidak digabung

- `PlcWorker.dropped_submissions` — dijatuhkan di **antrean ingestion** (`submit()` dari thread
  deteksi), saat `PlcWorker._queue` (maxsize 50) penuh.
- `PulseScheduler.dropped` — dijatuhkan di **antrean per-coil** (`enqueue()`), saat
  `queue_max` (default 1) pada satu coil penuh.

Keduanya overflow yang berbeda titik: satu di depan pintu masuk PLC worker, satu lagi di depan
satu coil spesifik. Digabung jadi satu angka akan menyembunyikan *di mana* penyempitannya
terjadi, jadi keduanya dipertahankan terpisah.

---

## Failed write retry — coil OFF yang gagal tidak boleh nyangkut ON

Setiap tulis coil (pulse, alive toggle, maupun coil ERROR) lewat satu helper internal,
`PlcWorker._write_coil()`. Kalau `client.write_coil()` gagal (link putus, PLC menolak), level
yang gagal itu **disimpan** dan dicoba ulang pada tick berikutnya — bukan dibuang begitu saja.

Ini penting khususnya untuk write OFF di akhir sebuah pulse: `PulseScheduler.tick()` hanya
melaporkan perubahan level *sekali*. Kalau write OFF itu gagal dan tidak ada mekanisme retry,
coil itu akan nyangkut ON selamanya — tidak ada yang menagihnya lagi. Retry di `_write_coil`
menutup celah itu: nilai gagal ikut di-merge ke perubahan tick berikutnya, dan ditimpa oleh
nilai segar kalau coil yang sama berubah lagi sebelum retry-nya sempat jalan.

### Satu peta write per tick — tidak ada runt pulse

`run_once()` tidak menulis coil di beberapa tempat. Ia merakit **satu** `dict[int, bool]` berisi
level yang diinginkan untuk seluruh tick, dengan urutan penyusunan: retry (`_failed_writes`) →
`scheduler.tick()` → toggle alive → level ERROR. Entri belakangan menimpa yang depan, jadi level
segar selalu menang atas level basi pada coil yang sama.

Tanpa ini, retry level basi dan toggle segar pada bit alive ditulis terpisah dengan jarak ~1ms —
PLC melihat pasangan ON/OFF selebar satu milidetik pada bit yang seharusnya kotak 1 detik.
Peta tunggal itu menghilangkan celahnya secara struktural, bukan lewat pengecekan tambahan.

Baca discrete input sengaja terjadi **setelah** flush write: itu round-trip Modbus yang bisa
menggantung sampai timeout socket (1 detik), dan menaruhnya sebelum write akan menunda pulse
selama itu — pulse telat menempel ke buah yang salah.

---

## Shutdown — coil dimatikan, bukan ditinggal ON

`make restart` adalah langkah deploy **dan** langkah tuning lapangan, jadi SIGTERM di tengah
produksi itu rutin. Dengan `PLC_PULSE_MS=200` dalam siklus 300ms, peluang sebuah coil sedang ON
saat sinyal itu tiba kira-kira 2 dari 3.

`shutdown_plc_worker()` (dipanggil `lifespan` sesudah `yield`) menjalankan, berurutan:

1. `PlcWorker.stop()` — set `threading.Event`; `run_loop` mengeceknya tiap tick dan `wait()`
   di antara tick, jadi ia keluar dalam hitungan milidetik, bukan satu poll penuh.
2. `thread.join(timeout=2.0)` — **wajib sebelum langkah 3.** Kalau dibalik, tick terakhir
   balapan dan menyalakan ulang coil yang baru saja dimatikan.
3. `PlcWorker.deenergise()` — tulis `False` ke coil OK, NG, ERROR, dan semua coil `PLC_COIL_ALIVE`
   **tanpa syarat**, mengabaikan bookkeeping `_error_level`/`_failed_writes` (tidak akan ada tick
   berikutnya yang menagih retry). Gagal dicatat di log, tidak di-retry, tidak di-raise.
4. `client.close()` lalu bersihkan singleton modul.

No-op yang aman kalau `PLC_ENABLED=false` atau worker tidak pernah start.

---

## Coil ERROR — self-clearing, bukan latching

Coil ERROR (`plc_coil_error`, = `PLC_COIL_BASE + 2`) berarti **"line ini tidak sehat saat
ini"**, dievaluasi ulang tiap tick — bukan flag yang sekali nyala lalu menetap.

Dua sumber unhealthy, salah satu cukup:

1. **Overflow baru.** `PlcWorker` membandingkan total drop (`scheduler.dropped +
   dropped_submissions`) sekarang vs. nilai yang tercatat di evaluasi sebelumnya. ERROR
   menyala hanya kalau totalnya **naik** sejak evaluasi terakhir. Karena kedua counter itu
   lifetime (tidak pernah direset), kalau dibaca sebagai `> 0` biasa, ERROR akan menyala di
   menit pertama shift lalu tidak pernah padam lagi — self-clearing ini yang mencegah itu.
   Begitu satu interval evaluasi lewat tanpa drop baru, ERROR mereda sendiri.
2. **`health_check()` melaporkan tidak sehat**, atau **exception dari `health_check()` itu
   sendiri** — dianggap tidak sehat (fail-loud). Sumber health yang tidak diketahui statusnya
   tidak boleh dibaca sebagai sehat pada sinyal keselamatan.

---

## Satu buah = satu pulse, walau tulis disk gagal

`FrameProcessingWorker` memakai **dua** flag single-trigger pada track yang sama, dan itu
disengaja:

| Flag | Diset kapan | Kenapa terpisah |
| --- | --- | --- |
| `plc_signalled` | tepat setelah `submit_grading()`, **sebelum** tulis disk | Pulse Modbus tidak punya idempotensi |
| `processed` | setelah file WebP + JSON tersimpan | Diproses ulang itu aman: `event_id` uuid5-nya sama, API membalas `already_processed` |

`_save_ripeness()` melempar `IOError` kalau `cv2.imwrite` gagal — itu perilaku by-design
(Critical Rule #8), pada disk yang repo ini sendiri jalankan retensi untuknya. Kalau kedua
kepentingan itu digabung ke satu flag, kegagalan tulis disk membuat track tetap belum
`processed`, lalu track yang sama masuk lagi ke blok deteksi pada frame berikutnya — 10–16 kali
per detik. Satu buah nyangkut akan menjenuhkan coil OK atau NG tanpa henti dan PLC menghitung
satu buah sebagai berpuluh-puluh.

`submit_grading()` tetap dipanggil **sebelum** tulis disk (itu keputusan latency yang benar —
sinyal tidak boleh menunggu I/O disk); yang diperbaiki hanya supaya ia tidak ikut mewarisi
semantik retry milik jalur disk.

---

## Mati secara default (`PLC_ENABLED=false`)

Ini default di `.env.example` dan yang dijalankan cloud + semua PC dev. Efeknya:

- `start_plc_worker()` mengembalikan `None` sebelum membangun client apa pun — tidak ada
  thread PLC yang start.
- `submit_grading()` mengecek `_worker is not None` dan langsung `return` kalau `None` — satu
  pengecekan Python per buah, nol antrean, nol I/O, nol latency tambahan di jalur deteksi.

Hanya PC pabrik yang benar-benar terhubung ke coupler ODOT yang menyalakan ini.

---

## Peta paket `src/palmgrade/plc/`

```
src/palmgrade/plc/
├── __init__.py        # Permukaan publik: start_plc_worker(), shutdown_plc_worker(),
│                       # submit_grading(), inputs()
│                       # + re-export ModbusPlcClient/PlcWorker/PulseScheduler untuk test
├── modbus_client.py    # ModbusPlcClient — satu-satunya file yang menyentuh pymodbus.
│                        # write_coil/read_discrete_inputs mengembalikan sentinel
│                        # (False/None), tidak pernah raise — worker adalah thread panjang
│                        # yang tidak boleh mati karena kabel dicabut.
├── pulse.py             # PulseScheduler — logika murni, nol I/O. Menjadwalkan satu
│                         # keputusan jadi satu pulse ON/OFF per coil dengan jeda wajib.
└── worker.py             # PlcWorker — satu-satunya thread yang menyentuh socket Modbus.
                           # Menguras antrean submit → pulse, toggle bit alive, baca DI,
                           # evaluasi + tulis coil ERROR.

tests/unit/plc/
├── test_plc_config.py
├── test_plc_pulse.py
├── test_plc_modbus_client.py
└── test_plc_worker.py
```

Kode di luar paket ini hanya boleh menyentuh **empat fungsi** yang diekspor `__init__.py`:
`start_plc_worker(settings, health_check=None)`, `shutdown_plc_worker(thread=None)`,
`submit_grading(status)`, `inputs()`. Semua
yang lain (`ModbusPlcClient`, `PlcWorker`, `PulseScheduler`) di-ekspor juga, tapi hanya untuk
pemanggil yang perlu merakit worker-nya sendiri (mis. test).

---

## Belum diputuskan (open hardware questions)

Empat hal ini ada di sisi pak Ocit (PLC engineer) dan butuh kerja panel + ladder. Vision sudah
punya default yang masuk akal untuk semuanya, jadi ini bukan blocker untuk mulai — tapi wajib
dikonfirmasi sebelum commissioning:

1. **Lebar pulse (`PLC_PULSE_MS`) dan jeda (`PLC_PULSE_GAP_MS`) belum dikonfirmasi terhadap
   kecepatan belt sesungguhnya.** Default 200ms/100ms (~3,3 sinyal/detik) adalah patokan, bukan
   angka final — perlu tahu apakah sinyal OK/NG itu pulse atau level, satu sinyal = satu buah
   atau status batch, dan cycle time actuator penyortir yang sebenarnya.
2. **Watchdog coupler ODOT perlu diturunkan dari 30 detik ke 2–3 detik.** PC polling tiap
   200ms, jadi 2–3 detik aman tanpa false-trip. Dengan 30 detik, PC yang mati membuat coil
   terakhir nyangkut sampai setengah menit — cukup lama untuk menyortir banyak buah pakai
   keputusan basi.
3. **E-stop perlu dikabel ulang jadi NC (normally closed).** CT-122F low-aktif, dan setting
   ODOT saat ini (`Fault Action for Input: Cleaning Input Value`) membuat **kabel putus terbaca
   persis sama dengan "aman"**. Perlu bit ON selama kondisi normal dan OFF saat E-stop ditekan,
   supaya kabel putus jatuh ke sisi aman, bukan sisi berbahaya.
4. **IP address ODOT dan NIC yang dipakainya belum disuplai.** NIC PC pabrik sudah dipakai tiga
   kamera GigE — perlu tahu ODOT nyambung ke switch yang mana dan IP-nya berapa untuk mengisi
   `PLC_HOST`.
