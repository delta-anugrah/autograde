# PLC Integration: Mitsubishi Q03UDECPU (MC Protocol)

> **Status 2026-09-23: tersambung di Lampung.** PC bicara langsung ke port Ethernet bawaan
> Q03UDECPU lewat **MC Protocol** (`PLC_PROTOCOL=mc`, bawaan; pustaka `pymcprotocol`, frame 3E
> biner). Tiga line tersambung di `192.168.0.14` port 1025/1026/1027; **M1000/M1001** (PC → PLC)
> dan **M1111** (PLC → PC) terbukti di GX Works2. Dokumen untuk tim PLC:
> **`docs/plc-mc-handoff.md`** (+ PDF). Kronologi commissioning:
> `docs/runbooks/2026-09-23-commissioning-plc-lampung.md`. Skill: `plc-mc-protocol`.
>
> **Dua hal yang wajib dijaga di jalur mc:** (1) tidak ada coupler yang mereset output saat
> link putus, jadi heartbeat **wajib berkedip** (`PLC_ALIVE_TOGGLE_MS`, bawaan 500 untuk mc)
> dan ladder menghitung PERUBAHAN; (2) `pymcprotocol` mengembalikan **bit nol** (bukan error)
> saat socket tertutup di tengah pembacaan, jadi `McProtocolPlcClient` memeriksa panjang
> balasan mentah sendiri (kalau tidak, E-stop yang ditekan terbaca lepas).

Vision mengirim hasil grading tiap line (ACC / REJ / ERROR) ke PLC dan membaca balik motor
fault + E-stop. Alamatnya daftar pak Ocit (PLC engineer), 23 September 2026.

Seluruh logika terkurung di paket `src/palmgrade/plc/`. Kode di luar paket ini hanya boleh
menyentuh fungsi yang diekspor `__init__.py`: `start_plc_worker`, `shutdown_plc_worker`,
`submit_grading`, `inputs`, `diagnostics`, `request_piston`, `piston_state`, `fire_test_coil`,
`testable_coils`.

---

## Peta alamat

Literal per line di `docker-compose.yml` (properti fisik line, bukan setelan `.env`).
Peta untuk tim PLC, bentuk sinyal, dan uji dari layar: `docs/plc-mc-handoff.md` §2 dan §4;
`tests/unit/test_plc_docs_match_compose.py` mengikat angka di sana ke compose.

**PC menulis, PLC membaca**

| Line | Port | OK | NG | ERROR |
| --- | --- | --- | --- | --- |
| 1 | 1025 | M1000 | M1001 | M1002 |
| 2 | 1026 | M1003 | M1004 | M1005 |
| 3 | 1027 | M1006 | M1007 | M1008 |

- OK/NG = pulse (`PLC_PULSE_MS`), ERROR = level (lihat "Coil ERROR" di bawah).
- **M1009** = HEARTBIT PC, berkedip 500 ms. Compose memberikannya ke line 1 saja (lihat
  catatan ⚠️ di tabel env).
- Piston manual **belum dialokasikan** panel: `PLC_COIL_MANUAL` / `PLC_DI_MANUAL` kosong =
  fitur mati, grading tidak terpengaruh.

**PLC menulis, PC membaca**: blok **M1100–M1115**, dibaca tiap poll oleh ketiga line (status
conveyor bersama, bukan per line).

| Offset | Alamat | Arti |
| --- | --- | --- |
| 0–10 | M1100–M1110 | MOTOR 1–11 FAULT |
| 11 | M1111 | E-STOP OP PANEL |
| 12–15 | M1112–M1115 | belum dialokasikan |

`inputs` di `/health/detail` adalah **offset**, bukan alamat. Aplikasi hanya menafsirkan
offset 0–11 untuk pita alarm di konsol (`domain/plc_alarm.py`) dan offset `PLC_DI_MANUAL`
untuk konfirmasi piston; keputusan grading tidak pernah membaca blok ini.

### Jalur modbus (coupler ODOT, dibatalkan)

`PLC_PROTOCOL=modbus` masih didukung kode (`plc/modbus_client.py`, Modbus-TCP port 502,
`PLC_UNIT_ID`) untuk site yang terlanjur dikabel lewat coupler remote IO ODOT CN-8031. Coupler
itu dibatalkan 2026-09-21 dan tidak dipakai di Lampung; tabel coil/DI dan pertanyaan
hardware-nya dihapus dari dokumen ini (ada di riwayat git). Beda perilaku yang tersisa di kode:
heartbeat modbus bawaannya ON statis (`PLC_ALIVE_TOGGLE_MS=0`), karena coupler punya *fault
action* yang mematikan output sendiri saat link putus.

---

## Env vars (`PLC_*`)

Semua field dideklarasikan di satu blok PLC di `core/config.py`, bukan config terpisah:
konvensi repo ini, satu sumber kebenaran untuk env.

| Variable | Default | Arti |
| --- | --- | --- |
| `PLC_ENABLED` | `false` | Saklar fitur. `false` = default, dipakai semua PC dev; lihat "Mati secara default" di bawah |
| `PLC_PROTOCOL` | `mc` | `mc` = MC Protocol langsung ke CPU. `modbus` = coupler ODOT lama. Nilai asing → jatuh ke `mc` + warning, bukan crash |
| `PLC_HOST` | (kosong) | IP PLC (Lampung: `192.168.0.14`, satu segmen dengan NIC kamera). Kosong + `PLC_ENABLED=true` → worker tidak dijalankan, warning di log |
| `PLC_PORT` | ikut protokol | **Literal per line di compose, 1025/1026/1027. Jangan diisi di `.env`.** Satu Open Setting GX Works2 = satu koneksi TCP; tiga line di satu port = dua line tidak pernah tersambung (Lampung 2026-09-23). Tanpa compose: `1025` mc / `502` modbus |
| `PLC_UNIT_ID` | `1` | Modbus saja |
| `PLC_DEVICE_PREFIX` | `M` | mc saja: huruf device semua alamat. Panel memberi B/Y → ganti ini saja |
| `PLC_COIL_BASE` | `1000` | **Literal per line**: `1000` / `1003` / `1006`. OK = base, NG = base+1, ERROR = base+2 |
| `PLC_COIL_ALIVE` | `1009` | **Literal per line**: line 1 = `1009`, line 2 dan 3 ditulis kosong. ⚠️ Nilai kosong saat ini jatuh ke bawaan `1009` (`os.getenv(...) or "1009"` di `core/config.py`), jadi line 2 dan 3 ikut mengedipkan M1009. Tercatat 2026-09-28, belum diperbaiki di kode |
| `PLC_ALIVE_TOGGLE_MS` | ikut protokol | Kosong = **`500` untuk mc** (wajib berkedip, ladder menghitung PERUBAHAN), **`0` untuk modbus** (ON statis). Lisensi kedaluwarsa menahan heartbeat OFF |
| `PLC_DI_BASE` | `1100` | Awal blok yang dibaca (M1100) |
| `PLC_DI_COUNT` | `16` | Jumlah bit yang dibaca tiap poll mulai `PLC_DI_BASE`. Offset 11 = E-stop |
| `PLC_COIL_MANUAL` / `PLC_DI_MANUAL` | (kosong) | Piston manual per line. Kosong = fitur mati; tidak ada bawaan, karena menebak alamat berarti menulis ke bit milik orang lain |
| `PLC_PULSE_MS` | `200` | Lebar pulse ON untuk satu keputusan OK/NG. **Wajib >= `PLC_POLL_MS`** (lihat di bawah) |
| `PLC_PULSE_GAP_MS` | `100` | Jeda OFF wajib sebelum pulse berikutnya pada coil yang sama, supaya PLC melihat tepi naik terpisah |
| `PLC_QUEUE_MAX` | `1` | **Berapa banyak keterlambatan yang mau kamu beli**, bukan kapasitas. Jumlah pulse yang boleh terutang per coil; tiap slot = `(pulse+gap)` ms sinyal jadi lebih basi. Penuh → drop + hitung |
| `PLC_HOLD_MS` | `0` | `0` = pulse (jalur yang terbukti). `> 0` = mode tahan, lihat di bawah |
| `PLC_POLL_MS` | `200` | Interval `PlcWorker.run_once()`: **resolusi waktu semua timing di atas** |

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

`docker-compose.yml` men-set `PLC_PORT`/`PLC_COIL_BASE`/`PLC_COIL_ALIVE`/`PLC_COIL_MANUAL`/
`PLC_DI_MANUAL` sebagai literal per service (`ripe-line-1/2/3`); variabel lain diinterpolasi
dari `.env` dengan fallback default di atas.

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

### Mode tahan (`PLC_HOLD_MS > 0`)

Diminta tim PLC 2026-09-23 untuk uji di panel, karena pulse 200 ms tidak terlihat mata di lampu.
`HoldScheduler` (`plc/hold.py`) memegang coil OK/NG ON sekian milidetik, dan janjang berikutnya
yang datang saat coil masih ON **memperpanjang** tahanannya (tidak ada antrean, tidak ada yang
bisa penuh). ⚠️ Di mode ini PLC **tidak bisa menghitung janjang**: dua janjang berurutan jadi
satu sinyal panjang tanpa tepi turun. Untuk produksi biarkan `0` dan latch di ladder.

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

Baca blok input sengaja terjadi **setelah** flush write: itu round-trip ke PLC yang bisa
menggantung sampai timeout socket (1 detik), dan menaruhnya sebelum write akan menunda pulse
selama itu: pulse telat menempel ke buah yang salah.

---

## Shutdown: coil dimatikan, bukan ditinggal ON

`autograde restart` / `make restart` adalah langkah deploy **dan** langkah tuning lapangan, jadi
SIGTERM di tengah produksi itu rutin. Dengan `PLC_PULSE_MS=200` dalam siklus 400 ms (2 tick),
peluang sebuah coil sedang ON saat sinyal itu tiba kira-kira 1 dari 2.

`shutdown_plc_worker()` (dipanggil urutan tutup line, `services/langkah_tutup_line.py`, untuk
SIGTERM DAN `/internal/restart` + `/internal/hapus-data`, bersamaan dengan antrean simpan
dihabiskan; batas urutan tutup 8 detik, ditambah jeda 1 detik sebelum urutan itu mulai untuk
`/internal/restart` dan `/internal/hapus-data`) menjalankan, berurutan:

1. `PlcWorker.stop()`: set `threading.Event`; `run_loop` mengeceknya tiap tick dan `wait()`
   di antara tick, jadi ia keluar dalam hitungan milidetik, bukan satu poll penuh.
2. `thread.join(timeout=2.0)`: **wajib sebelum langkah 3.** Kalau dibalik, tick terakhir
   balapan dan menyalakan ulang coil yang baru saja dimatikan.
3. `PlcWorker.deenergise()`: tulis `False` ke coil OK, NG, ERROR, dan semua coil `PLC_COIL_ALIVE`
   **tanpa syarat**, mengabaikan bookkeeping `_error_level`/`_failed_writes` (tidak akan ada tick
   berikutnya yang menagih retry). Gagal dicatat di log, tidak di-retry, tidak di-raise.
4. `client.close()` lalu bersihkan singleton modul.

No-op yang aman kalau `PLC_ENABLED=false` atau worker tidak pernah start. Shutdown yang rapi ini
tidak menolong kalau PC mati mendadak atau kabel dicabut: itu tugas watchdog heartbeat di ladder
(`docs/plc-mc-handoff.md` §3).

Sebelum batch 2.2, restart yang diminta dari konsol (`/internal/restart`, `/internal/hapus-data`)
melewati fungsi ini sama sekali: `os._exit` langsung, coil yang sedang ON tertinggal ON sampai
line hidup lagi.

---

## Coil ERROR: kesehatan line, BUKAN overflow

Coil ERROR (`plc_coil_error`, = `PLC_COIL_BASE + 2`) berarti **"line ini tidak sehat saat
ini"**, dievaluasi ulang tiap tick, bukan flag yang sekali nyala lalu menetap. Ditulis saat
levelnya berubah dan ditulis ulang tiap detik. Selama pulse uji dari layar sedang jalan di coil
ini, level kesehatan menunggu sampai pulse selesai.

Satu-satunya sumber unhealthy: **`health_check()` melaporkan tidak sehat**, atau **exception dari
`health_check()` itu sendiri**, dianggap tidak sehat (fail-loud). Sumber health yang tidak
diketahui statusnya tidak boleh dibaca sebagai sehat pada sinyal keselamatan.

Sejak batch 2.1 (2026-09-28), `health_check()` = `PenjagaAi.sehat_untuk_plc()`
(`services/penjaga_ai.py`): tidak sehat berarti **kamera putus ATAU AI mati** (kamera mengirim
gambar tapi tidak ada frame yang selesai digrading selama `AI_MATI_DETIK`, bawaan 30 detik).
Sejak batch 3.6 ditambah **frame berhenti**: kamera tersambung (atau ada sambung ulang yang
berhasil sejak gambar terakhir) tapi tidak ada gambar masuk selama `AI_MATI_DETIK`. Buah lewat tanpa disortir persis
seperti AI mati; sebelum ini coil-nya malah berkedip (kamera putus dan sumber diam bergantian
tiap sambung ulang). Lisensi habis dan **sumber selesai** (video uji tanpa ulang yang habis)
**sengaja tidak** menaikkan ERROR: yang pertama sudah punya sinyalnya sendiri (banner lisensi,
alive bit mati), yang kedua bukan kerusakan line. PLC tidak berubah; tim PLC perlu tahu
M1002/M1005/M1008 sekarang juga naik untuk kamera yang diam. Overflow (di bawah) tetap tidak menaikkannya, tidak berubah.

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

## Satu buah = satu pulse

`FrameProcessingWorker` memakai **dua** flag single-trigger pada track yang sama, dan itu
disengaja:

| Flag | Diset kapan | Kenapa terpisah |
| --- | --- | --- |
| `plc_signalled` | tepat setelah keputusan PLC diambil (`submit_grading()`, atau sinyal sengaja ditahan untuk REJ truk Internal), **sebelum** gambar diserahkan ke penulis | Pulse ke PLC tidak punya idempotensi |
| `processed` | setelah `SaveJob` diserahkan ke `CaptureSaveWorker` (sejak 2026-09-18; dulu setelah file tersimpan) | Idempotensi ke konsol dipegang nama file (`event_id` uuid5), bukan urutan tulis |

Kalau blok deteksi gagal di antara keduanya, track yang sama masuk lagi pada frame berikutnya,
10–16 kali per detik. Dengan satu flag saja, satu buah nyangkut akan menjenuhkan coil OK atau
NG tanpa henti dan PLC menghitung satu buah sebagai berpuluh-puluh. `submit_grading()` tetap
dipanggil **sebelum** apa pun yang menyentuh gambar: sinyal tidak boleh menunggu I/O.

---

## Mati secara default (`PLC_ENABLED=false`)

Ini default di `.env.example` dan yang dijalankan semua PC dev. Efeknya:

- `start_plc_worker()` mengembalikan `None` sebelum membangun client apa pun, tidak ada
  thread PLC yang start.
- `submit_grading()` mengecek `_worker is not None` dan langsung `return` kalau `None`, satu
  pengecekan Python per buah, nol antrean, nol I/O, nol latency tambahan di jalur deteksi.

Hanya PC pabrik yang benar-benar terhubung ke PLC yang menyalakan ini.

---

## Peta paket `src/palmgrade/plc/`

```
src/palmgrade/plc/
├── __init__.py        # Permukaan publik (lihat atas) + build_plc_client(), yang
│                       # memilih klien dari PLC_PROTOCOL
├── mc_client.py        # McProtocolPlcClient: satu-satunya file yang menyentuh
│                        # pymcprotocol. Menempelkan prefiks device (M1000), menjaga
│                        # panjang balasan, tidak pernah raise ke worker.
├── modbus_client.py    # ModbusPlcClient: jalur coupler ODOT lama (pymodbus).
├── pembaca_timbangan.py # PembacaTimbangan: berat jembatan timbang dari register D,
│                        # dipakai KONSOL saja (aturan 39, bagian Timbangan live).
├── pulse.py            # PulseScheduler: logika murni, nol I/O. Satu keputusan jadi
│                        # satu pulse ON/OFF per coil dengan jeda wajib.
├── hold.py             # HoldScheduler: mode tahan (PLC_HOLD_MS > 0), antarmuka sama.
└── worker.py           # PlcWorker: satu-satunya thread yang menyentuh socket PLC.
                         # Kuras antrean submit → pulse, kedipkan heartbeat, baca blok
                         # input, tulis coil ERROR, piston manual.

tests/unit/plc/
├── test_plc_config.py
├── test_plc_hold.py
├── test_plc_mc_client.py
├── test_pembaca_timbangan.py
├── test_plc_modbus_client.py
├── test_plc_piston.py
├── test_plc_pulse.py
└── test_plc_worker.py
```

Kedua klien memberi antarmuka yang sama (`write_coil` / `read_discrete_inputs` / `close`) dan
mengembalikan sentinel (`False`/`None`) alih-alih melempar: worker adalah thread panjang yang
tidak boleh mati karena kabel dicabut. Kelas klien, `PlcWorker`, `PulseScheduler`, dan
`HoldScheduler` diekspor juga, tapi hanya untuk pemanggil yang merakit worker sendiri (test).

---

## Timbangan live (konsol, 2026-10-06)

Berat di jembatan timbang masuk ke PLC, dan **konsol** (bukan line) membacanya dari register
kata lewat MC Protocol, lalu menampilkannya di kotak **Data timbangan** (aturan 39). Sambungan
sendiri: satu Open Setting satu pemakai, dan 1025-1027 dipegang tiga line, jadi panel perlu
membuka port keempat (bawaan **1028**, Write to PLC + reset CPU saat line berhenti).

Semua yang ditanyakan ke Pak Ocit (pertanyaan terbuka X1 di workspace sawit) adalah `.env`; begitu
dijawab, pabrik mengisi lalu `autograde restart`, tanpa rilis:

| Env | Bawaan | Isi |
|---|---|---|
| `SCALE_PLC_REGISTER` | kosong = mati | register berat, mis. `D100` (D/W/R/ZR) |
| `SCALE_PLC_HOST` | ikut `PLC_HOST` | IP PLC |
| `SCALE_PLC_PORT` | `1028` | port Open Setting khusus konsol |
| `SCALE_PLC_WORDS` | `2` | 2 = 32-bit (kata rendah `Dn`, tinggi `Dn+1`); 1 = 16-bit, mentok 32.767 kg |
| `SCALE_PLC_DECIMALS` | `0` | desimal tersirat: 1 berarti `123456` dibaca 12.345,6 kg |
| `SCALE_PLC_STABLE_BIT` | kosong | bit "berat stabil", mis. `M2000`; kosong = layar tidak bisa bilang Stabil/Bergerak |
| `SCALE_PLC_ERROR_BIT` | kosong | bit "timbangan error"; menyala = angka disembunyikan |
| `SCALE_POLL_MS` | `500` | seberapa sering konsol bertanya (minimal 200) |

Variabel ini harus ada di blok `console:` compose host pabrik (skill `compose-host-pabrik`).
Nilai yang tidak sah mematikan fitur dengan satu WARNING, tidak menghentikan konsol. Cek dari
luar: `curl -b <cookie> :8100/api/console/scale/live` → `{keadaan, kg, umur_detik}`.

---

## Melihat state PLC dari luar

Konsol: tab **Line → Uji PLC** (akun support) menampilkan blok input, tombol per coil bernama
("Kamera 1 OK / M1000"), dan peta alamat lengkap. Uji coil ditolak selama line itu punya truk
terpasang. Motor fault dan E-stop tampil sebagai pita merah di atas kartu line.

Dari terminal, `GET /health/detail`:

```bash
curl -s localhost:8001/health/detail | jq .plc
{
  "inputs": [false, false, ..., false],   # 16 bit mulai PLC_DI_BASE: offset 0-10 motor, 11 E-stop
  "dropped_pulses": 0,                    # scheduler.dropped: antrean pulse penuh
  "dropped_submissions": 0,               # antrean submit penuh (thread deteksi)
  "piston": null                          # null = piston manual tidak dikonfigurasi
}
```

`"plc": null` artinya `PLC_ENABLED=false` atau worker belum jalan. Itu **keadaan normal** di PC
dev, bukan error, endpoint tetap `200`, dan tidak ada field lain yang berubah. Lihat
`plc.diagnostics()`.

Kedua counter **naik monoton** selama proses hidup (tidak pernah di-reset), jadi yang berarti
adalah **selisihnya antar-polling**, bukan nilai absolutnya. Angka yang bertambah terus saat belt
jalan artinya kamera menghasilkan keputusan lebih cepat daripada yang bisa dikeluarkan
`PLC_PULSE_MS + PLC_PULSE_GAP_MS`: plafon throughput, bukan bug. Baca ulang bagian
`PLC_QUEUE_MAX`.

---

## Belum diputuskan

Per 2026-09-23 (rinciannya untuk tim PLC di `docs/plc-mc-handoff.md` §5). Vision sudah punya
default yang masuk akal untuk semuanya, jadi ini bukan blocker, tapi wajib dijawab sebelum
produksi penuh:

1. **Watchdog heartbeat di ladder.** M1009 tidak berubah 2–3 detik → ladder mematikan sendiri
   M1000–M1008. Satu-satunya pekerjaan panel yang tersisa; tanpa itu bit bisa nyangkut ON saat
   PC mati.
2. **Polaritas M1100–M1111.** Aplikasi mengasumsikan ON = fault / ditekan. Layar menampilkan
   E-stop `On` sepanjang uji 23 Sep; belum ditanyakan apakah panelnya memang ditekan. Kalau
   terbalik (kabel NC), pita alarm menyala terus saat pabrik sehat.
3. **Saat E-stop ditekan, kamera ikut berhenti menilai?** Sekarang tidak, cuma pita merah.
4. **Buah yang lewat tanpa sinyal apa pun: lolos atau dibuang?** Sebagian keputusan memang
   dibuang saat antrean penuh (lihat *Throughput ceiling*), dan REJ truk Internal sengaja tidak
   dikirim. Jawabannya menentukan aturan buah Internal benar atau terbalik.
5. **Lebar pulse terhadap kecepatan belt.** 200 ms/100 ms (~2,5 sinyal/detik) adalah patokan,
   bukan angka final. Tim PLC sempat meminta OK/NG "ditahan terus"; untuk uji ada mode tahan,
   untuk produksi sarannya latch di ladder.
6. (tidak mendesak) Piston manual dialokasikan (usulan M1010–M1012 / M1112–M1114) atau
   ditiadakan.

### Yang belum terbukti

- **Heartbeat M1009** berkedip sejak tersambung, tapi belum dipantau di GX Works2; coil ERROR
  (M1002/M1005/M1008) baru bisa dipicu dari layar sejak 23 Sep malam.
- **"Satu buah = satu pulse" belum punya tes otomatis.** Bagian itu memuat pustaka kamera dan AI
  yang sengaja tidak dimuat unit test; perbaikannya baru diperiksa manual.
- **Celah lama yang belum ditutup:** buah keluar area pantau → nomor track dipakai ulang untuk
  buah fisik yang sama → secara teori muncul pulse dobel. Perlu diamati saat produksi.
- **Hitungan 2,5 vs 10 sinyal per detik** bergantung pada lebar pulse di butir 5.

---

## Urutan commissioning

Untuk panel baru. Kalau waktu mepet, yang **tidak boleh dilewat** cuma langkah 3, 4, dan 7.
Hambatan yang sudah pernah terjadi dan jawabannya: runbook commissioning Lampung (di atas).

1. **Di PLC:** tiga Open Setting TCP MC Protocol (1025/1026/1027), centang *Enable online
   change (FTP, MC Protocol)* (tanpa itu baca jalan, tulis ditolak `0x0055`), lalu **Write to
   PLC + reset CPU** (tanpa reset, port baru menjawab `connection refused`).
2. **Di PC:** `.env` cukup `PLC_ENABLED=true` dan `PLC_HOST`; jangan isi `PLC_PORT` /
   `PLC_COIL_*` (literal compose yang berlaku). Nyalakan line 1 saja dulu, supaya sumber
   keanehan kelihatan.
3. Lepas truk dari line 1, picu satu pulse dari tab **Line → Uji PLC**, lalu **pastikan bersama
   bahwa tombol "Kamera 1 OK" = M1000 di monitor GX Works2.** Beda satu alamat saja, OK jatuh
   ke NG.
4. **Ukur lebar pulse yang benar-benar sampai di PLC** (monitor bit GX Works2). Angka 200 ms
   harus dibuktikan, bukan dipercaya.
5. Pastikan M1009 berkedip. Matikan proses line → watchdog ladder mematikan M1000–M1008 dalam
   2–3 detik (perhatikan catatan ⚠️ `PLC_COIL_ALIVE` di atas: selama line 2/3 ikut berkedip,
   uji ini perlu ketiga line dimatikan).
6. Picu satu motor fault dari panel, pastikan offset yang berubah di aplikasi nomor motor yang
   sama.
7. **Cabut kabel E-stop**, lihat pembacaan aplikasi berubah atau tidak. Tidak berubah = bukti
   masalah polaritas di butir 2 di atas, jangan diterima hanya karena bit-nya terbaca aman.
8. Restart proses line 1 saat pulse sedang jalan, tidak boleh ada coil yang tertinggal ON.
9. Produksi sungguhan ±15 menit di satu line, lalu baca jumlah sinyal terbuang di
   `GET /health/detail`. Angka itu dasar menyetel ulang lebar pulse.
10. Baru nyalakan line 2 dan 3.
