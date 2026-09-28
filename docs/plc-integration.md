# PLC Integration: Mitsubishi Q03UDECPU (MC Protocol) · ODOT (arsip)

> **Status 2026-09-23.** Jalur yang hidup adalah **MC Protocol langsung ke CPU** (`PLC_PROTOCOL=mc`,
> bawaan): PC bicara ke port Ethernet bawaan Q03UDECPU lewat `pymcprotocol`, device **M**, alamat
> dari daftar pak Ocit, camera 1/2/3 base **M1000/M1003/M1006** (+0 OK, +1 NG, +2 ERROR),
> heartbeat **M1009**, blok baca **M1100–M1115** (motor 1–11 fault, **M1111** E-stop). Coupler
> **ODOT CN-8031 dibatalkan** 2026-09-21; jalurnya masih bisa dipilih dengan `PLC_PROTOCOL=modbus`
> untuk site yang terlanjur dikabel begitu. Dokumen untuk tim PLC: **`docs/plc-mc-handoff.md`**
> (+ PDF); skill: `plc-mc-protocol`.
>
> Yang berubah cuma lapisan klien (`plc/mc_client.py` vs `plc/modbus_client.py`, dipilih
> `build_plc_client`). Semua di bawah ini: pulse, antrean, ERROR, piston, buah internal,
> throughput: berlaku untuk **kedua** jalur. Yang khusus coupler ditandai **[modbus saja]**.
>
> **Dua beda yang penting di jalur mc:** (1) tidak ada *fault action* coupler yang mereset output
> saat link putus, jadi heartbeat **wajib berkedip** (`PLC_ALIVE_TOGGLE_MS` bawaan 500) dan
> ladder menghitung PERUBAHAN; (2) `pymcprotocol` mengembalikan **bit nol** (bukan error) saat
> socket tertutup di tengah pembacaan, jadi `McProtocolPlcClient` memeriksa panjang balasan
> mentah sendiri (kalau tidak, E-stop yang ditekan terbaca lepas).

Vision mengirim hasil grading tiap line (ACC / REJ / ERROR) ke PLC Mitsubishi dan membaca
balik motor fault + E-stop. Bagian hardware dan alamat coil di bawah menyalin skematik PDF
*"REMOTE IO: CONVEYOR SAWIT"* (DW.26/07/27 hal. 19–20, PT Nexio Teknologi Otomasi) untuk
jalur ODOT, plus percakapan dengan pak Ocit (PLC engineer).

Seluruh logika terkurung di paket `src/palmgrade/plc/`. Kode di luar paket ini hanya boleh
menyentuh fungsi yang diekspor `__init__.py`: `start_plc_worker`, `shutdown_plc_worker`,
`submit_grading`, `inputs`, `diagnostics`, `request_piston`, `piston_state`, `picu_coil`,
`testable_coils`.

---

## Hardware **[modbus saja]**

Di jalur mc tidak ada satu pun modul di bawah: kabel Ethernet dari NIC PC langsung ke port
bawaan CPU. Tabel ini tinggal untuk site yang masih lewat coupler.

| Part number | Peran |
| --- | --- |
| ODOT CN-8031 | Coupler remote IO, sisi kita bicara ke ini via Modbus-TCP (port 502) |
| CT-222F | Modul output, source/PNP, high-active |
| CT-122F | Modul input, NPN, **low-active** |
| CT-5801 | Modul catu daya panel |
| AJ65SBTB1-16D1 | Modul input Mitsubishi (16 titik): sisi PLC yang menerima dari CT-222F |
| AJ65SBTB1-16T1 | Modul output Mitsubishi (16 titik): sisi PLC yang mengirim ke CT-122F |

**Catatan sink/source (sudah diverifikasi cocok, tanpa relay):**
CT-222F source/PNP → AJ65SBTB1-16D1, dengan COM di 0V. AJ65SBTB1-16T1 sink (COM di 0V) →
CT-122F low-aktif. Kedua pasangan cocok secara elektris tanpa perlu relay perantara.

**Batas koneksi coupler:** CN-8031 menerima maksimum **5 client Modbus-TCP bersamaan**. Tiga
container line (satu koneksi per proses, tidak ada pooling) memakai 3 dari 5 slot itu.

---

## Coil / DO: vision menulis (zero-based)

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
| 9     | X0309       | HEARTBIT PC ON | line 1     |
| 10–15 | X030A–X030F | SPARE          | -          |

Coil 9 tidak punya writer khusus, ia hidup lewat mekanisme `PLC_COIL_ALIVE` line 1
(lihat di bawah). Modbus function code `05` (write single coil).

**Coil 10–15 SPARE dan tidak boleh disentuh.** Implementasi awal memakai 10/11/12 sebagai
bit "line N alive" per proses; itu penambahan kita sendiri, bukan permintaan pak Ocit, dan
skematik REMOTE IO menandai keenamnya SPARE. Konsekuensi yang diterima sadar: kalau proses
satu line mati sendirian, PLC tidak melihatnya, coil `CAM_N_ERROR` line itu justru tidak
akan menyala, karena yang harus menulisnya ya proses yang barusan mati. Butuh deteksi itu →
minta pak Ocit mengalokasikan spare, jangan pakai diam-diam.

## Discrete input / DI: vision membaca (zero-based)

| DI    | Alamat PLC  | Arti                                  |
| ----- | ----------- | ------------------------------------- |
| 0–10  | Y0310–Y031A | MOTOR 1–11 FAULT                      |
| 11    | Y031B       | EMERGENCY STOP                        |
| 12    | Y031C       | LINE 1: piston terbuka (konfirmasi)   |
| 13    | Y031D       | LINE 2: piston terbuka (konfirmasi)   |
| 14    | Y031E       | LINE 3: piston terbuka (konfirmasi)   |
| 15    | Y031F       | SPARE                                 |

Modbus function code `02` (read discrete inputs). Semua tiga line membaca discrete input yang
sama: itu status bersama conveyor, bukan per-line.

⚠️ **Digeser satu pada 2026-09-15: motor jadi 11, bukan 10.** Dulu motor di DI 0–9 dan E-stop di
DI 10. Aplikasi sendiri **tidak pernah menafsirkan index mana pun kecuali `PLC_DI_MANUAL`**,
`run_once` membaca blok 16 DI mentah dan menyimpannya apa adanya, jadi pergeseran ini murni
perubahan env + dokumen, nol perubahan logika. Sisa spare tinggal satu.

---

## Env vars (`PLC_*`)

Semua field dideklarasikan di `core/config.py` (satu blok berlabel `# ── PLC / ODOT CN-8031
(Modbus-TCP) ──`), bukan config terpisah, konvensi repo ini: satu sumber kebenaran untuk env.

| Variable | Default | Arti |
| --- | --- | --- |
| `PLC_ENABLED` | `false` | Saklar fitur. `false` = default, dipakai cloud dan semua PC dev, lihat "Mati secara default" di bawah |
| `PLC_PROTOCOL` | `mc` | `mc` = MC Protocol langsung ke CPU (jalur hidup). `modbus` = lewat coupler ODOT. Nilai asing → jatuh ke `mc` + warning, bukan crash |
| `PLC_HOST` | (kosong) | IP PLC (mc: `192.168.0.14` di Lampung, satu segmen dengan NIC kamera; modbus: IP coupler). Kosong + `PLC_ENABLED=true` → worker tidak dijalankan, warning di log |
| `PLC_PORT` | ikut protokol | **mc: literal per line di compose, 1025/1026/1027.** Satu Open Setting GX Works2 = satu koneksi TCP; tiga line di satu port = dua line tidak pernah tersambung (Lampung 2026-09-23). Kosong = `1025` mc / `502` modbus |
| `PLC_UNIT_ID` | `1` | **[modbus saja]** unit/slave ID. MC Protocol menyapa CPU-nya langsung |
| `PLC_DEVICE_PREFIX` | `M` | **[mc saja]** huruf device yang dipakai semua alamat di bawah. Panel memberi B/Y → ganti ini saja |
| `PLC_COIL_BASE` | `0` | **Literal per line, bukan dari `.env`**: properti fisik line, bukan setelan yang boleh beda antar PC. mc (daftar Ocit): camera 1 = `1000`, 2 = `1003`, 3 = `1006`. modbus: `0` / `3` / `6` |
| `PLC_COIL_ALIVE` | (kosong) | **Literal per line.** Bit heartbeat, dipegang line 1 saja: mc = `1009`, modbus = `9`. Line 2 dan 3 **kosong**. Kosong = fitur alive mati |
| `PLC_ALIVE_TOGGLE_MS` | ikut protokol | Kosong = **`500` untuk mc** (wajib berkedip: tidak ada coupler yang mereset output saat PC mati, kedipan ini satu-satunya yang bisa dipantau ladder, dan ladder harus menghitung PERUBAHAN), **`0` untuk modbus** (ON statis, ladder membaca level; toggle di sini = alarm PC-mati tiap setengah periode, kejadian v1.3.0) |
| `PLC_DI_BASE` | `0` | Awal blok yang dibaca. mc: `1100` (M1100–M1115). modbus: `0` |
| `PLC_PULSE_MS` | `200` | Lebar pulse ON untuk satu keputusan OK/NG. **Wajib >= `PLC_POLL_MS`** (lihat di bawah). **Belum dikonfirmasi pak Ocit**: lihat "Belum diputuskan" |
| `PLC_PULSE_GAP_MS` | `100` | Jeda OFF wajib sebelum pulse berikutnya pada coil yang sama, supaya PLC melihat tepi naik terpisah |
| `PLC_QUEUE_MAX` | `1` | **Berapa banyak keterlambatan yang mau kamu beli**, bukan kapasitas/keandalan. Jumlah pulse yang boleh terutang per coil; tiap slot = `(pulse+gap)` ms sinyal jadi lebih basi. Penuh → drop + hitung, bukan tunggu |
| `PLC_POLL_MS` | `200` | Interval `PlcWorker.run_once()`: **resolusi waktu semua timing di atas** (dan, di jalur modbus, keepalive watchdog coupler) |
| `PLC_DI_COUNT` | `16` | Jumlah bit yang dibaca tiap poll mulai `PLC_DI_BASE`. Bit ke-11 = E-stop di kedua jalur (M1111 / DI 11) |

### `PLC_POLL_MS` adalah resolusi waktu, bukan sekadar keepalive

`PLC_PULSE_MS` dan `PLC_PULSE_GAP_MS` bukan timer sungguhan. `PulseScheduler` cuma
dievaluasi saat `run_loop` bangun, jadi **semua timing dibulatkan ke kelipatan
`PLC_POLL_MS`**. Pulse 200ms dengan poll 200ms artinya "ON di tick ini, OFF di tick
berikutnya": bukan 200ms yang presisi.

Konsekuensinya satu aturan keras:

> **`PLC_PULSE_MS` >= `PLC_POLL_MS`.**

Pulse yang lebih pendek dari satu tick tidak bisa dihasilkan: ON dan OFF-nya jatuh
di evaluasi yang sama, jadi coil-nya tidak pernah benar-benar naik dan PLC tidak
pernah melihat rising edge-nya: buah lewat tanpa sinyal, diam-diam.

Dilanggar → `start_plc_worker()` menulis `logger.warning` saat start dan **tetap
jalan**. Sengaja tidak raise dan tidak di-clamp diam-diam: tuning yang benar
tergantung PLC di lapangan, dan menebak nilai pengganti tanpa bilang-bilang lebih
berbahaya daripada meneruskan apa adanya sambil teriak di log. Kalau memang butuh
pulse lebih sempit dari 200ms, yang diturunkan adalah `PLC_POLL_MS`, bukan cuma
`PLC_PULSE_MS`.

`docker-compose.yml` men-set `PLC_COIL_BASE`/`PLC_COIL_ALIVE` sebagai literal per service
(`ripe-line-1/2/3`); variabel lain diinterpolasi dari `.env` dengan fallback default di atas.

### Salah ketik `PLC_*` tidak boleh mematikan grading

PLC adalah subsistem **opsional** yang default-nya mati, dan knob-nya diedit operator jam 2 pagi
waktu commissioning. Karena itu semua field `PLC_*` diparse **toleran**:

- Field integer lewat `_plc_int()` (`core/config.py`): nilai bukan angka turun ke default dan
  ditulis sebagai `logger.warning` yang menyebut nama variabelnya. Field **non-PLC** sengaja
  tetap fail-fast; kelonggaran ini khusus PLC.
- `parse_coil_list()` mengembalikan `()` + warning kalau rusak. `PLC_COIL_ALIVE=9,10,` (koma
  nyantol) dulu melempar `ValueError` saat konstruksi `Settings()`, kontainer tidak pernah start.
- `start_plc_worker()` dibungkus `try/except` di `lifespan`. `PLC_PULSE_MS=0` lolos `int()` tapi
  ditolak `PulseScheduler.__post_init__`; sebelumnya exception itu menjatuhkan startup.

Efek maksimal dari `PLC_*` yang salah ketik sekarang adalah **PLC mati sambil grading jalan
terus**, bukan line berhenti.

---

## Throughput ceiling: DROP adalah steady state normal, bukan pengecualian

Satu coil hanya bisa membawa satu pulse pada satu waktu. Dengan default `PLC_PULSE_MS=200` +
`PLC_PULSE_GAP_MS=100`, kapasitas satu coil adalah:

```
Satu tick = PLC_POLL_MS. Pulse butuh 1 tick ON, jeda butuh 1 tick penuh
(gap 100 ms dibulatkan ke atas), jadi satu siklus = 2 tick = 400 ms:

  1 / (2 × 0,200 dtk) = 2,5 sinyal/detik
```

Kamera always-ON bisa menghasilkan sampai **~10 keputusan grading/detik** per line. Itu jauh
di atas 2,5/detik yang muat di satu coil OK atau NG. Konsekuensinya: **overflow adalah kondisi
normal di bawah beban, bukan sesuatu yang salah.**

Kebijakannya **DROP dan hitung: tidak pernah nge-lag**. Menahan sinyal di antrean supaya
tidak ada yang hilang justru lebih buruk: sinyal yang telat menempel ke buah yang salah di
belt, karena belt terus berjalan sementara antrean menumpuk. Lebih baik kehilangan sebagian
sinyal yang akurat daripada mengirim semua sinyal yang salah tempat.

`PLC_PULSE_MS` dan `PLC_PULSE_GAP_MS` adalah knob tuning lapangan, **ini yang pertama harus
ditinjau ulang saat commissioning**, setelah kecepatan belt dan actuator sesungguhnya
diketahui (lihat "Belum diputuskan").

### `PLC_QUEUE_MAX` = harga staleness, bukan kapasitas

`PulseScheduler` menguras satu pulse terutang tiap satu siklus tick (400 ms: lihat "Throughput
ceiling" di atas). Jadi antrean yang penuh berarti **setiap pulse yang diterima PLC mewakili
keputusan dari `queue_max × 400 ms` yang lalu**. Dengan `queue_max=20` itu 8 detik, pada
belt berjalan, sinyal itu mendarat di buah yang benar-benar berbeda, terus-menerus, selama
produksi normal.

Karena itu defaultnya **1**: paling banyak satu pulse terutang ⇒ staleness ≤ 400 ms secara
struktural, tanpa perlu state timestamp/discard tambahan. Menaikkan angka ini **tidak** membuat
sinyal lebih andal: ia menukar drop (jujur, terhitung) dengan sinyal basi (diam-diam salah).

### Dua counter drop yang terpisah, sengaja tidak digabung

- `PlcWorker.dropped_submissions`: dijatuhkan di **antrean ingestion** (`submit()` dari thread
  deteksi), saat `PlcWorker._queue` (maxsize 50) penuh.
- `PulseScheduler.dropped`: dijatuhkan di **antrean per-coil** (`enqueue()`), saat
  `queue_max` (default 1) pada satu coil penuh.

Keduanya overflow yang berbeda titik: satu di depan pintu masuk PLC worker, satu lagi di depan
satu coil spesifik. Digabung jadi satu angka akan menyembunyikan *di mana* penyempitannya
terjadi, jadi keduanya dipertahankan terpisah.

---

## Failed write retry: coil OFF yang gagal tidak boleh nyangkut ON

Setiap tulis coil (pulse, bit alive, maupun coil ERROR) lewat satu helper internal,
`PlcWorker._write_coil()`. Kalau `client.write_coil()` gagal (link putus, PLC menolak), level
yang gagal itu **disimpan** dan dicoba ulang pada tick berikutnya, bukan dibuang begitu saja.

Ini penting khususnya untuk write OFF di akhir sebuah pulse: `PulseScheduler.tick()` hanya
melaporkan perubahan level *sekali*. Kalau write OFF itu gagal dan tidak ada mekanisme retry,
coil itu akan nyangkut ON selamanya, tidak ada yang menagihnya lagi. Retry di `_write_coil`
menutup celah itu: nilai gagal ikut di-merge ke perubahan tick berikutnya, dan ditimpa oleh
nilai segar kalau coil yang sama berubah lagi sebelum retry-nya sempat jalan.

### Satu peta write per tick: tidak ada runt pulse

`run_once()` tidak menulis coil di beberapa tempat. Ia merakit **satu** `dict[int, bool]` berisi
level yang diinginkan untuk seluruh tick, dengan urutan penyusunan: retry (`_failed_writes`) →
`scheduler.tick()` → bit alive → level ERROR. Entri belakangan menimpa yang depan, jadi level
segar selalu menang atas level basi pada coil yang sama.

Tanpa ini, retry level basi dan level segar pada bit alive ditulis terpisah dengan jarak ~1ms,
PLC melihat pasangan ON/OFF selebar satu milidetik pada bit yang seharusnya kotak 1 detik.
Peta tunggal itu menghilangkan celahnya secara struktural, bukan lewat pengecekan tambahan.

Baca discrete input sengaja terjadi **setelah** flush write: itu round-trip Modbus yang bisa
menggantung sampai timeout socket (1 detik), dan menaruhnya sebelum write akan menunda pulse
selama itu: pulse telat menempel ke buah yang salah.

---

## Shutdown: coil dimatikan, bukan ditinggal ON

`make restart` adalah langkah deploy **dan** langkah tuning lapangan, jadi SIGTERM di tengah
produksi itu rutin. Dengan `PLC_PULSE_MS=200` dalam siklus 400 ms (2 tick), peluang sebuah coil
sedang ON saat sinyal itu tiba kira-kira 1 dari 2.

`shutdown_plc_worker()` (dipanggil `lifespan` sesudah `yield`) menjalankan, berurutan:

1. `PlcWorker.stop()`: set `threading.Event`; `run_loop` mengeceknya tiap tick dan `wait()`
   di antara tick, jadi ia keluar dalam hitungan milidetik, bukan satu poll penuh.
2. `thread.join(timeout=2.0)`: **wajib sebelum langkah 3.** Kalau dibalik, tick terakhir
   balapan dan menyalakan ulang coil yang baru saja dimatikan.
3. `PlcWorker.deenergise()`: tulis `False` ke coil OK, NG, ERROR, dan semua coil `PLC_COIL_ALIVE`
   **tanpa syarat**, mengabaikan bookkeeping `_error_level`/`_failed_writes` (tidak akan ada tick
   berikutnya yang menagih retry). Gagal dicatat di log, tidak di-retry, tidak di-raise.
4. `client.close()` lalu bersihkan singleton modul.

No-op yang aman kalau `PLC_ENABLED=false` atau worker tidak pernah start.

---

## Coil ERROR: kesehatan line, BUKAN overflow

Coil ERROR (`plc_coil_error`, = `PLC_COIL_BASE + 2`) berarti **"line ini tidak sehat saat
ini"**, dievaluasi ulang tiap tick, bukan flag yang sekali nyala lalu menetap. Ditulis hanya
saat levelnya berubah.

Satu-satunya sumber unhealthy: **`health_check()` melaporkan tidak sehat** (praktiknya:
`camera.connected` false), atau **exception dari `health_check()` itu sendiri**, dianggap tidak
sehat (fail-loud). Sumber health yang tidak diketahui statusnya tidak boleh dibaca sebagai sehat
pada sinyal keselamatan.

**Overflow sengaja TIDAK menaikkan ERROR.** Drop adalah steady state yang dideklarasikan di
bawah beban (lihat "Throughput ceiling" di atas): kamera bisa ~10 keputusan/detik, satu coil muat
~2,5. Kalau drop menggerakkan coil ini, `drop_total` naik hampir tiap tick di bawah beban dan
CAM_N_ERROR menyala sepanjang shift: artinya berubah jadi "line ini jalan normal", yang entah
menghentikan produksi atau bikin coil itu jadi hiasan yang diabaikan operator. `PLC_QUEUE_MAX=1`
justru membuat drop makin sering, jadi menggabungkannya cuma memperparah.

Kedua counter drop tetap dihitung dan tetap punya warning log rate-limited, itu **diagnostik**,
dibaca lewat `GET /health/detail` (`plc.dropped_pulses` / `plc.dropped_submissions`), bukan
sinyal ke PLC.

---

## Satu buah = satu pulse, walau tulis disk gagal

`FrameProcessingWorker` memakai **dua** flag single-trigger pada track yang sama, dan itu
disengaja:

| Flag | Diset kapan | Kenapa terpisah |
| --- | --- | --- |
| `plc_signalled` | tepat setelah `submit_grading()`, **sebelum** tulis disk | Pulse Modbus tidak punya idempotensi |
| `processed` | setelah file WebP + JSON tersimpan | Diproses ulang itu aman: `event_id` uuid5-nya sama, API membalas `already_processed` |

`_save_ripeness()` melempar `OSError` kalau `cv2.imwrite` gagal, itu perilaku by-design
(Critical Rule #8), pada disk yang repo ini sendiri jalankan retensi untuknya. Kalau kedua
kepentingan itu digabung ke satu flag, kegagalan tulis disk membuat track tetap belum
`processed`, lalu track yang sama masuk lagi ke blok deteksi pada frame berikutnya, 10–16 kali
per detik. Satu buah nyangkut akan menjenuhkan coil OK atau NG tanpa henti dan PLC menghitung
satu buah sebagai berpuluh-puluh.

`submit_grading()` tetap dipanggil **sebelum** tulis disk (itu keputusan latency yang benar,
sinyal tidak boleh menunggu I/O disk); yang diperbaiki hanya supaya ia tidak ikut mewarisi
semantik retry milik jalur disk.

---

## Mati secara default (`PLC_ENABLED=false`)

Ini default di `.env.example` dan yang dijalankan cloud + semua PC dev. Efeknya:

- `start_plc_worker()` mengembalikan `None` sebelum membangun client apa pun, tidak ada
  thread PLC yang start.
- `submit_grading()` mengecek `_worker is not None` dan langsung `return` kalau `None`, satu
  pengecekan Python per buah, nol antrean, nol I/O, nol latency tambahan di jalur deteksi.

Hanya PC pabrik yang benar-benar terhubung ke coupler ODOT yang menyalakan ini.

---

## Peta paket `src/palmgrade/plc/`

```
src/palmgrade/plc/
├── __init__.py        # Permukaan publik: start_plc_worker(), shutdown_plc_worker(),
│                       # submit_grading(), inputs(), diagnostics()
│                       # + re-export ModbusPlcClient/PlcWorker/PulseScheduler untuk test
├── modbus_client.py    # ModbusPlcClient — satu-satunya file yang menyentuh pymodbus.
│                        # write_coil/read_discrete_inputs mengembalikan sentinel
│                        # (False/None), tidak pernah raise — worker adalah thread panjang
│                        # yang tidak boleh mati karena kabel dicabut.
├── pulse.py             # PulseScheduler — logika murni, nol I/O. Menjadwalkan satu
│                         # keputusan jadi satu pulse ON/OFF per coil dengan jeda wajib.
└── worker.py             # PlcWorker — satu-satunya thread yang menyentuh socket Modbus.
                           # Menguras antrean submit → pulse, tahan bit alive, baca DI,
                           # evaluasi + tulis coil ERROR.

tests/unit/plc/
├── test_plc_config.py
├── test_plc_pulse.py
├── test_plc_modbus_client.py
└── test_plc_worker.py
```

Kode di luar paket ini hanya boleh menyentuh fungsi yang diekspor `__init__.py`:
`start_plc_worker(settings, health_check=None)`, `shutdown_plc_worker(thread=None)`,
`submit_grading(status)`, `inputs()`, `diagnostics()`, `request_piston(open)`,
`piston_state()`, `picu_coil(coil)`, `testable_coils(settings)`. Semua
yang lain (`ModbusPlcClient`, `PlcWorker`, `PulseScheduler`) di-ekspor juga, tapi hanya untuk
pemanggil yang perlu merakit worker-nya sendiri (mis. test).

---

## Melihat state PLC dari luar: `GET /health/detail`

Tiga angka yang paling dibutuhkan saat commissioning, E-stop, dan kedua counter
drop: sebelumnya cuma bisa dilihat dengan membuka shell Python di dalam
kontainer. Sekarang ketiganya nempel di endpoint health yang sudah ada:

```bash
curl -s localhost:8001/health/detail | jq .plc
{
  "inputs": [false, false, ..., false],   # index 0-9 motor fault, index 10 E-stop
  "dropped_pulses": 0,                    # scheduler.dropped — antrean pulse penuh
  "dropped_submissions": 0                # antrean submit penuh (thread deteksi)
}
```

`"plc": null` artinya `PLC_ENABLED=false` atau worker belum jalan. Itu **keadaan
normal** di cloud dan PC dev, bukan error, endpoint tetap `200`, dan tidak ada
field lain yang berubah. Lihat `plc.diagnostics()`.

Kedua counter **naik monoton** selama proses hidup (tidak pernah di-reset), jadi
yang berarti adalah **selisihnya antar-polling**, bukan nilai absolutnya. Angka
yang bertambah terus saat belt jalan artinya kamera menghasilkan keputusan lebih
cepat daripada yang bisa dikeluarkan `PLC_PULSE_MS + PLC_PULSE_GAP_MS`,
plafon throughput, bukan bug. Baca ulang bagian `PLC_QUEUE_MAX`.

---

## Belum diputuskan (open hardware questions)

**Per 2026-09-23, jalur mc.** Yang masih ditunggu dari tim PLC: (a) **tiga koneksi** MC Protocol
di Open Setting GX Works2, satu port satu koneksi; (b) **watchdog heartbeat di ladder** (M1009
tidak berubah 2–3 dtk → matikan M1000–M1008); (c) butir 5 di bawah; (d) tidak mendesak: piston
manual dialokasikan (usulan M1010–M1012 / M1112–M1114) atau ditiadakan, sekarang **kosong =
fitur mati**. Butir 2 dan 4 di bawah **[modbus saja]**; butir 1, 3, 5, 6 berlaku dua jalur.

Hal-hal ini ada di sisi pak Ocit (PLC engineer) dan butuh kerja panel + ladder. Vision sudah
punya default yang masuk akal untuk semuanya, jadi ini bukan blocker untuk mulai, tapi wajib
dikonfirmasi sebelum commissioning:

1. **Lebar pulse (`PLC_PULSE_MS`) dan jeda (`PLC_PULSE_GAP_MS`) belum dikonfirmasi terhadap
   kecepatan belt sesungguhnya.** Default 200ms/100ms (~2,5 sinyal/detik) adalah patokan, bukan
   angka final: perlu tahu apakah sinyal OK/NG itu pulse atau level, satu sinyal = satu buah
   atau status batch, dan cycle time actuator penyortir yang sebenarnya.
2. **Watchdog coupler ODOT perlu diturunkan dari 30 detik ke 2–3 detik.** PC polling tiap
   200ms, jadi 2–3 detik aman tanpa false-trip. Dengan 30 detik, PC yang mati membuat coil
   terakhir nyangkut sampai setengah menit, cukup lama untuk menyortir banyak buah pakai
   keputusan basi.
3. **E-stop perlu dikabel ulang jadi NC (normally closed).** CT-122F low-aktif, dan setting
   ODOT saat ini (`Fault Action for Input: Cleaning Input Value`) membuat **kabel putus terbaca
   persis sama dengan "aman"**. Perlu bit ON selama kondisi normal dan OFF saat E-stop ditekan,
   supaya kabel putus jatuh ke sisi aman, bukan sisi berbahaya.
4. **IP address ODOT dan NIC yang dipakainya belum dikonfirmasi.** Usulan dari sisi aplikasi
   sudah dipasang di `.env.example`: `PLC_HOST=192.168.100.50` statis, subnet `255.255.255.0`,
   kabel masuk ke switch gigabit yang sama dengan tiga kamera. Dipilih supaya tidak bentrok
   dengan kamera (`.10`/`.11`/`.12`) maupun NIC komputer (`.100`); boleh diganti ke `.51`–`.99`
   asal tetap `192.168.100.x`. **Paling menghambat**: tanpa ini aplikasi tidak bisa nyambung.
5. **Buah yang lewat tanpa sinyal apa pun, aktuatornya default ngapain?** Sebagian keputusan
   memang dibuang saat antrean penuh (lihat *Throughput ceiling* di atas), jadi pasti ada buah
   yang lewat tanpa pulse. Jawabannya menentukan ke arah mana kesalahan sistem ini condong:
   buah tak tersinyal diloloskan atau dibuang.
6. **Saat E-stop ditekan, kamera ikut berhenti menilai atau tidak?** Sekarang tidak. Kalau
   seharusnya iya, akan ada hasil penilaian yang tercatat padahal line sedang berhenti darurat.

### Yang belum terbukti

- **Belum pernah diuji ke coupler fisik**: semua tes memakai simulasi.
- **"Satu buah = satu pulse walau simpan gambar gagal" belum punya tes otomatis.** Bagian itu
  memuat pustaka kamera dan AI yang sengaja tidak dimuat unit test; perbaikannya baru diperiksa
  manual.
- **Celah lama yang belum ditutup:** simpan gambar gagal → buah keluar area pantau → nomor track
  dipakai ulang untuk buah fisik yang sama → secara teori muncul pulse dobel. Perlu diamati saat
  produksi.
- **Hitungan 2,5 vs 10 sinyal per detik** bergantung pada lebar pulse di butir 1. Lebar pulse
  berubah, seluruh hitungan itu ikut berubah.

## Urutan commissioning

Disarikan dari catatan serah terima Agustus 2026, ditulis untuk coupler. Di jalur mc bacanya:
"coil 0" = **M1000**, "coil 9" = **M1009**, "IP coupler" = IP CPU, dan langkah 8 berubah
maknanya: tidak ada *fault action*, jadi yang diuji adalah **ladder** mematikan M1000–M1008
sendiri saat M1009 berhenti berkedip. Pastikan juga *Enable online change (FTP, MC Protocol)*
tercentang: tanpa itu baca jalan, tulis ditolak. Kalau waktu mepet, yang **tidak boleh
dilewat** cuma langkah 3, 4, dan 7.

1. Isi IP coupler, pastikan komputer bisa nyambung.
2. Nyalakan line 1 saja; line 2 dan 3 mati, supaya sumber keanehan kelihatan.
3. Picu satu pulse, lalu **pastikan bersama bahwa coil 0 di aplikasi = X0300 di PLC.** Beda satu
   alamat saja, CAM 1 OK jatuh ke CAM 1 NG.
4. **Ukur lebar pulse yang benar-benar sampai di PLC** (scope atau monitor bit GX Works). Angka
   200 ms harus dibuktikan, bukan dipercaya.
5. Cek coil 9 (HEARTBIT PC) ON. Matikan proses line 1 → coil 9 padam. Matikan line 2 atau 3 →
   coil 9 tetap ON; memang begitu (cuma line 1 yang memegangnya).
6. Picu satu motor fault dari panel, pastikan bit yang berubah di aplikasi nomor motor yang sama.
7. **Cabut kabel E-stop**, lihat pembacaan aplikasi berubah atau tidak. Tidak berubah = bukti
   masalah polaritas di butir 3 di atas, jangan diterima hanya karena bit-nya terbaca aman.
8. Cabut kabel LAN coupler ±10 detik lalu colok lagi: coil 9 harus padam lewat *fault action*
   coupler, lalu ON lagi sendiri tanpa ada yang di-restart.
9. Restart proses line 1 saat pulse sedang jalan, tidak boleh ada coil yang tertinggal ON.
10. Produksi sungguhan ±15 menit di satu line, lalu baca jumlah sinyal terbuang di
    `GET /health/detail`. Angka itu dasar menyetel ulang lebar pulse.
11. Baru nyalakan line 2 dan 3.
