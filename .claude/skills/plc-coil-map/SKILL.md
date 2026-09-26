---
name: plc-coil-map
description: ARSIP, jalur ODOT dibatalkan 2026-09-21, pakai skill plc-mc-protocol. Peta coil & discrete input ODOT CN-8031 (Modbus-TCP) buat autograde, alamat OK/NG/ERROR per line, heartbeat PC, piston manual, motor fault, E-stop. Pakai kalau sinyal PLC nggak keluar pas grading, alarm "PC mati" nyala terus, coil nyangkut ON, tombol piston nggak jalan, buah internal kebuang padahal harusnya nggak, lagi commissioning line baru, atau mau ganti/nambah alamat coil.
---

# Peta Coil PLC: ODOT CN-8031 (ARSIP)

> ⚠️ **Jalur ini DIBATALKAN 21 September 2026.** Coupler ODOT tidak jadi dipakai;
> PC sekarang bicara langsung ke CPU Mitsubishi lewat MC Protocol.
> **Skill yang berlaku: `plc-mc-protocol`.** Alamat coil di bawah **tidak lagi**
> cocok dengan `docker-compose.yml`. Berkas ini disimpan sebagai riwayat
> keputusan dan untuk site yang terlanjur dikabel lewat coupler
> (`PLC_PROTOCOL=modbus`).

Referensi lengkap (hardware, wiring, rasional tiap keputusan) ada di
`docs/plc-integration.md`. Yang dikasih ke tim panel: `docs/plc-handoff-commissioning.md`
(+ PDF-nya): itu yang jadi sumber kebenaran alamat kalau dokumen dan skill beda.
File ini peta cepat + prosedur lapangan.

## Kelas model → sinyal PLC

Model mendeteksi **4 kelas**, PLC cuma punya **2 coil**. Ini peta lengkapnya,
pertanyaan "kelas X ngirim sinyal apa" dijawab di sini, bukan dengan membaca
kode:

| Kelas model | Verdict | Coil yang dipulse | Piston |
|---|---|---|---|
| `Ripe` | ACC | `PLC_COIL_BASE + 0` | tidak |
| `Unripe` | REJ | `PLC_COIL_BASE + 1` | ya |
| `JK` (janjang kosong) | REJ | `PLC_COIL_BASE + 1` | ya |
| `TP` (tangkai panjang) | **tidak ada** | **tidak ada pulse** | tidak |

⚠️ **`Unripe` dan `JK` tidak bisa dibedakan oleh PLC**, dua-duanya menembak
coil NG yang sama persis. Pistonnya cuma dua (OK/NG), jadi kelas ketiga akan
butuh piston, wiring, dan perubahan ODOT: hardware, bukan software. Bedanya
tetap tersimpan di SQLite dan tampil di konsol, cuma tidak sampai ke panel.

⚠️ **`TP` bukan janjang.** Dia properti dari sebuah janjang (tangkai yang
panjang), jadi tidak punya verdict dan tidak pernah menyentuh PLC. Memulse coil
untuk TP akan membuat PLC menghitungnya sebagai buah.

Sumbernya `domain/grade_class.py` (kelas → verdict) dan `plc/worker.py:_coil_for`
(verdict → coil). Dua jalur yang bisa menimpa kelas sebelum sampai ke sini:
bbox lebih kecil dari `minimum_size`, dan `force_rej_multi`, dua-duanya
memaksa REJ walaupun model bilang `Ripe`.

## Peta coil (DO): vision yang nulis, zero-based

| Coil | Alamat PLC | Arti | Ditulis |
|---|---|---|---|
| 0 / 1 / 2 | X0300–X0302 | CAM 1 OK / NG / ERROR | line 1 |
| 3 / 4 / 5 | X0303–X0305 | CAM 2 OK / NG / ERROR | line 2 |
| 6 / 7 / 8 | X0306–X0308 | CAM 3 OK / NG / ERROR | line 3 |
| 9 | X0309 | HEARTBIT PC ON | line 1 saja |
| 10 / 11 / 12 | X030A–X030C | **Piston manual buka** line 1 / 2 / 3 | line masing-masing |
| 13–15 | X030D–X030F | **SPARE: jangan disentuh** | - |

⚠️ **Coil 10–12 dipakai aplikasi tapi ALOKASINYA BELUM DISETUJUI pak Ocit.**
Dulu 10–15 semua SPARE; kita minta pindah 10, 11, 12 jadi piston manual. Selama
jawabannya belum turun, `PLC_COIL_MANUAL`/`PLC_DI_MANUAL` di compose **memang
sudah keisi**, jadi kalau alokasinya ditolak atau dikasih nomor lain, yang
diubah cuma dua env itu + komentar `plc-map` di dokumen handoff (dijaga
`tests/unit/test_plc_docs_match_compose.py`, jadi nggak bisa lupa salah satu).

Butuh coil baru selain ini → minta alokasi, jangan ambil diam-diam. Sisa spare
tinggal 3.

## Peta discrete input (DI): vision yang baca

| DI | Alamat PLC | Arti |
|---|---|---|
| 0–10 | Y0310–Y031A | MOTOR 1–11 FAULT |
| 11 | Y031B | EMERGENCY STOP |
| 12 / 13 / 14 | Y031C–Y031E | **Konfirmasi piston terbuka** line 1 / 2 / 3 |
| 15 | Y031F | SPARE |

⚠️ **Semua geser satu pada 2026-09-15, motor jadi 11, bukan 10.** Dulu motor
DI 0–9, E-stop DI 10, piston DI 11–13. Kalau ketemu dokumen/catatan lama yang
nulis `inputs[10]` = E-stop, itu yang basi, bukan ini. Sisa spare tinggal **satu**.

DI dibaca function code `02`. **Ketiga line baca DI yang sama**, itu status
conveyor bersama, bukan per-line. Baca dari luar kontainer lewat
`GET /health/detail` (`inputs[11]` = E-stop).

Aplikasi **nggak pernah nafsirin index DI sendiri kecuali `PLC_DI_MANUAL`**,
`run_once` baca blok 16 DI mentah, simpen apa adanya. Jadi geseran kayak gini
murni env + dokumen, nol perubahan logika.

## Bentuk sinyalnya

- **OK / NG = pulse**, bukan level. `PLC_PULSE_MS=200` ON, lalu `PLC_PULSE_GAP_MS=100`
  OFF wajib, biar PLC lihat rising edge terpisah. Jeda 100 ms itu **dibulatkan ke
  atas jadi satu tick penuh 200 ms**, jadi yang beneran keluar: ON 200 ms, OFF
  200 ms, siklus 400 ms ⇒ **±2,5 rising edge/detik per coil**.
- **ERROR = level**, ditulis ulang tiap detik (sama kayak heartbeat). Sumbernya
  `health_check`, **bukan** drop pulse: drop itu steady state di bawah beban
  (kamera ~10 keputusan/detik, satu coil cuma muat ~2,5), kalau ikut ngangkat
  ERROR maka coil-nya nyala sepanjang shift dan artinya berubah jadi "line ini
  normal".
- **Heartbeat = ON statis** (`PLC_ALIVE_TOGGLE_MS=0`), ditulis ulang tiap detik.
  Bukan sekali pas start: kalau coupler nge-reset output waktu link putus, coil
  harus naik lagi sendiri tanpa restart.
- **Piston manual = level**, 1 = minta buka, ditahan sampai operator klik tutup.
  **TIDAK ditulis ulang berkala**: beda sengaja dari ERROR/heartbeat: itu
  pernyataan keadaan, ini tindakan operator pada satu saat. Kalau ditegakkan
  ulang otomatis, piston bisa gerak sendiri habis link pulih. Write ON yang
  gagal langsung **membatalkan** permintaan, bukan di-retry. DI konfirmasi nggak
  naik dalam **2 detik** → coil diturunkan sendiri biar klik berikutnya jadi
  rising edge baru.

## Buah internal: REJ yang sengaja nggak disinyalkan

Truk **Internal** (kebun sendiri): janjang REJ **nggak dikirim pulse sama
sekali**: nggak ada NG, dan **nggak ada OK pengganti**. Aturannya satu tempat:
`domain/plc_signal.py::plc_status_for(ripeness_status, ffb_source)` → `None`
artinya jangan disinyalkan.

Yang gampang salah dipahami:

- **`ripeness_status` tetap REJ** di disk, konsol, dan rekap AutoERP. Yang
  hilang cuma sinyal ke piston. Menukar verdict jadi ACC = memalsukan angka yang
  dibayar ke petani.
- **Nggak ada coil/DI baru** buat ini, dan ladder nggak perlu tahu truk mana
  yang lagi bongkar. Konsekuensinya: aturan ini **bergantung** pada kesepakatan
  bahwa buah tanpa sinyal itu **diloloskan**. Kalau default aktuator ternyata
  buang, hasilnya kebalik total.
- `ffb_source` dikirim konsol sebagai **fakta** (`"Internal"`/`"External"`/`null`),
  bukan boolean. `null` (truk belum dikenal ERP) **tetap dibuang**, truk tak
  dikenal nggak boleh diam-diam lolos.
- Flag `plc_signalled` di `frame_processing_worker` diset **walaupun sinyalnya
  ditahan**: artinya "keputusan PLC udah diambil", bukan "pulse udah dikirim".
  Kalau nggak, satu buah internal REJ yang nyangkut **di garis capture** masuk
  blok itu lagi tiap frame di 10–16 fps.

## Env (`PLC_*`)

Semua dideklarasikan satu blok di `src/palmgrade/core/config.py`
(cari `── PLC / ODOT CN-8031`). Yang sering kepake:

| Var | Default | Catatan |
|---|---|---|
| `PLC_ENABLED` | `false` | Mati by default. Cuma PC pabrik yang nyalain |
| `PLC_HOST` | (kosong) | IP coupler. Kosong + enabled=true → worker nggak jalan, cuma warning |
| `PLC_COIL_BASE` | `0` | **Literal per line di compose**, bukan `.env`: line 1=`0`, line 2=`3`, line 3=`6` |
| `PLC_COIL_ALIVE` | (kosong) | **Literal per line.** Line 1=`9`, line 2 & 3 **kosong** |
| `PLC_COIL_MANUAL` | (kosong) | **Literal per line.** Line 1=`10`, 2=`11`, 3=`12`. Kosong/rusak = piston mati total, grading jalan terus |
| `PLC_DI_MANUAL` | (kosong) | **Literal per line.** Line 1=`12`, 2=`13`, 3=`14`. Konfirmasi dari PLC |
| `PLC_ALIVE_TOGGLE_MS` | `0` | `0` = ON statis. `>0` = toggle: **cuma kalau ladder ngitung PERUBAHAN** |
| `PLC_PULSE_MS` | `200` | **Wajib ≥ `PLC_POLL_MS`** |
| `PLC_QUEUE_MAX` | `1` | Ini knob "sinyal boleh sebasi apa", bukan kapasitas. Tiap slot = +400 ms (satu siklus 2 tick) keterlambatan |
| `PLC_POLL_MS` | `200` | Interval `run_once()`, sekaligus keepalive watchdog ODOT **dan resolusi semua timing di atas** |

Keempat var alamat itu (`PLC_COIL_BASE`, `PLC_COIL_ALIVE`, `PLC_COIL_MANUAL`,
`PLC_DI_MANUAL`) sengaja **nggak ada di `.env.example`**, itu properti fisik
line, bukan setelan yang boleh beda antar PC. Tempatnya di `docker-compose.yml`:
line 1 baris 97–102, line 2 baris 208–213, line 3 baris 319–324.

## Jebakan

- **`PLC_ALIVE_TOGGLE_MS` > 0 tanpa ladder yang ngitung perubahan = alarm "PC
  mati" nyala tiap setengah periode.** Ini pernah kejadian di `v1.3.0`. Ladder
  pak Ocit baca **LEVEL**. Biarin `0` kecuali ladder-nya udah diubah.
- **`PLC_PULSE_MS` < `PLC_POLL_MS` = pulse nggak pernah kelihatan.** ON dan OFF
  jatuh di tick yang sama, nggak ada rising edge. Cuma di-warning, nggak di-clamp.
- **Lisensi habis ⇒ coil alive DIMATIKAN.** Di PLC, "lisensi habis" dan "PC mati"
  kelihatan persis sama: pembedanya cuma layar. Ini disengaja.
- **Line 2 dan 3 nggak punya coil alive.** Kalau `PLC_COIL_ALIVE` keisi di line
  2/3, kamu nabrak coil piston (11/12), bukan SPARE lagi.
- **Jangan bikin piston ditegakkan ulang tiap detik** "biar konsisten sama
  ERROR/heartbeat". Itu justru yang bikin piston buka sendiri habis link pulih,
  dilarang aturan ladder nomor 3 (dokumen handoff bab 5), dan itu aturan
  keselamatan buat orang yang lagi bereskan sangkutan.
- **Label "Piston mati" di konsol nyampur dua sebab**: coil belum diset, dan PLC
  mati total. Belum dipisah; kalau nambah diagnosa, ini tempatnya.
- `start_plc_worker` dipanggil dua kali → balik `None` + warning, **bukan** worker
  lama. Dua thread di socket yang sama = transaction id ngawur.

## Diagnosa cepat

```bash
docker ps --format '{{.Names}}'                    # nama asli: ripe_line_1|2|3
docker logs --since 5m ripe_line_1 | grep -iE "PLC (aktif|on):"   # staging "PLC on: ...", PC Lampung v1.8.0 masih "PLC aktif: ..."
curl -s localhost:<port>/health/detail             # inputs[], piston, dropped_pulses, dropped_submissions
```

Baris log `PLC on:` nyebut coil OK/NG/ERROR dan alive yang **beneran kepakai**,
itu cara tercepat mastiin `PLC_COIL_BASE` line-nya bener. (Image lama di PC
pabrik masih nulis `PLC aktif:`, makanya grep-nya nangkep dua-duanya.)

`/health/detail` → `plc.piston` = status piston line itu; `null` berarti PLC
mati **atau** `PLC_COIL_MANUAL` kosong.

| Gejala | Cek dulu |
|---|---|
| Nggak ada sinyal sama sekali | `PLC_ENABLED`, `PLC_HOST` keisi, log `PLC on:` |
| Sinyal masuk ke line yang salah | `PLC_COIL_BASE` di compose (0/3/6) |
| Alarm PC-mati nyala terus | `PLC_ALIVE_TOGGLE_MS` harus `0`; cek lisensi belum habis |
| Coil nyangkut ON | SIGTERM di tengah pulse: `deenergise()` harusnya nutup ini, cek log shutdown |
| Buah kesortir telat / salah | `PLC_QUEUE_MAX` kegedean; `dropped_pulses` naik = buah lebih cepat dari yang bisa dihitung PLC |
| Tombol piston mati / "Piston mati" | `PLC_COIL_MANUAL` di compose; `plc.piston` di `/health/detail` `null`? |
| Klik buka, piston nggak gerak | Wajar kalau ladder nolak (E-stop/motor fault): DI konfirmasi tetap 0, coil turun sendiri setelah 2 dtk. Cek DI 12/13/14 |
| Buah REJ internal tetap kebuang | Cek `ffb_source` beneran `"Internal"` (bukan `null`) di log `Assignment synced:`; lalu tanya panel apa buah tanpa sinyal emang lolos |

## Kode

`src/palmgrade/plc/`: 4 file, komentarnya udah nyimpen rasional tiap keputusan,
baca itu sebelum ngubah:

- `__init__.py`: 7 fungsi publik (`start_plc_worker`, `shutdown_plc_worker`,
  `submit_grading`, `inputs`, `request_piston`, `piston_state`, `diagnostics`)
- `worker.py`: satu-satunya thread yang nyentuh socket. `run_once()` ngerakit
  **satu peta `{coil: level}`** per tick baru nulis sekali di akhir (ini yang
  matiin runt pulse secara struktural, jangan dipecah lagi jadi write terpisah)
- `modbus_client.py`: satu-satunya tempat yang nyentuh pymodbus; semua method
  balikin sentinel, nggak pernah raise
- `pulse.py`: penjadwal pulse

Di luar `plc/`, yang ikut nentuin apa yang sampai ke PLC:

- `domain/plc_signal.py`: aturan buah internal (logika murni, nol I/O)
- `workers/frame_processing_worker.py`: satu-satunya pemanggil `submit_grading`.
  ⚠️ Pulse PLC **sengaja tetap di thread deteksi** walau tulis disk sudah pindah ke
  `CaptureSaveWorker` (2026-09-18): piston menyortir buah yang lewat **sekarang**, bukan buah
  setengah detik lalu. Jangan "rapikan" dengan memindahkannya ke penulis
- `workers/line_status_worker.py`: konsol nanya status piston tiap line, 1 dtk
- `static/console.html`: tombol piston + pintasan `P` (tahan `P` + angka line,
  `P`+`0` nutup semua)
