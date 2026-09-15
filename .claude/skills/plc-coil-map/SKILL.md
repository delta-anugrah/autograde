---
name: plc-coil-map
description: Peta coil & discrete input ODOT CN-8031 (Modbus-TCP) buat autograde — alamat OK/NG/ERROR per line, heartbeat PC, motor fault, E-stop. Pakai kalau sinyal PLC nggak keluar pas grading, alarm "PC mati" nyala terus, coil nyangkut ON, lagi commissioning line baru, atau mau ganti/nambah alamat coil.
---

# Peta Coil PLC — ODOT CN-8031

Referensi lengkap (hardware, wiring, rasional tiap keputusan) ada di
`docs/plc-integration.md`. File ini peta cepat + prosedur lapangan.

## Peta coil (DO) — vision yang nulis, zero-based

| Coil | Alamat PLC | Arti | Ditulis |
|---|---|---|---|
| 0 / 1 / 2 | X0300–X0302 | CAM 1 OK / NG / ERROR | line 1 |
| 3 / 4 / 5 | X0303–X0305 | CAM 2 OK / NG / ERROR | line 2 |
| 6 / 7 / 8 | X0306–X0308 | CAM 3 OK / NG / ERROR | line 3 |
| 9 | X0309 | HEARTBIT PC ON | line 1 saja |
| 10–15 | X030A–X030F | **SPARE — jangan disentuh** | — |

Coil 10–15 udah disepakati sama pak Ocit buat nggak dipakai. Butuh coil baru →
minta alokasi, jangan ambil diam-diam.

## Peta discrete input (DI) — vision yang baca

| DI | Alamat PLC | Arti |
|---|---|---|
| 0–9 | Y0310–Y0319 | MOTOR 1–10 FAULT |
| 10 | Y031A | EMERGENCY STOP |
| 11–15 | Y031B–Y031F | SPARE |

DI dibaca function code `02`. **Ketiga line baca DI yang sama** — itu status
conveyor bersama, bukan per-line. Baca dari luar kontainer lewat
`GET /health/detail` (`inputs[10]` = E-stop).

## Bentuk sinyalnya

- **OK / NG = pulse**, bukan level. `PLC_PULSE_MS=200` ON, lalu `PLC_PULSE_GAP_MS=100`
  OFF wajib, biar PLC lihat rising edge terpisah.
- **ERROR = level**, ditulis cuma pas berubah. Sumbernya `health_check`, **bukan**
  drop pulse — drop itu steady state di bawah beban (kamera ~10 keputusan/detik,
  satu coil muat ~2,5, jeda 100 ms dibulatkan ke tick 200 ms), kalau ikut
  ngangkat ERROR maka coil-nya nyala sepanjang shift dan artinya berubah jadi
  "line ini normal".
- **Heartbeat = ON statis** (`PLC_ALIVE_TOGGLE_MS=0`), ditulis ulang tiap detik.
  Bukan sekali pas start: kalau coupler nge-reset output waktu link putus, coil
  harus naik lagi sendiri tanpa restart.

## Env (`PLC_*`)

Semua dideklarasikan satu blok di `src/palmgrade/core/config.py`
(cari `── PLC / ODOT CN-8031`). Yang sering kepake:

| Var | Default | Catatan |
|---|---|---|
| `PLC_ENABLED` | `false` | Mati by default. Cuma PC pabrik yang nyalain |
| `PLC_HOST` | (kosong) | IP coupler. Kosong + enabled=true → worker nggak jalan, cuma warning |
| `PLC_COIL_BASE` | `0` | **Literal per line di compose**, bukan `.env`: line 1=`0`, line 2=`3`, line 3=`6` |
| `PLC_COIL_ALIVE` | (kosong) | **Literal per line.** Line 1=`9`, line 2 & 3 **kosong** |
| `PLC_ALIVE_TOGGLE_MS` | `0` | `0` = ON statis. `>0` = toggle — **cuma kalau ladder ngitung PERUBAHAN** |
| `PLC_PULSE_MS` | `200` | **Wajib ≥ `PLC_POLL_MS`** |
| `PLC_QUEUE_MAX` | `1` | Ini knob "sinyal boleh sebasi apa", bukan kapasitas. Tiap slot = +(pulse+gap) ms keterlambatan |
| `PLC_POLL_MS` | `200` | Interval `run_once()`, sekaligus keepalive watchdog ODOT **dan resolusi semua timing di atas** |

`PLC_COIL_BASE` dan `PLC_COIL_ALIVE` sengaja **nggak ada di `.env.example`** —
itu properti fisik line, bukan setelan yang boleh beda antar PC. Tempatnya di
`docker-compose.yml` (baris 97/99, 205/207, 313/315).

## Jebakan

- **`PLC_ALIVE_TOGGLE_MS` > 0 tanpa ladder yang ngitung perubahan = alarm "PC
  mati" nyala tiap setengah periode.** Ini pernah kejadian di `v1.3.0`. Ladder
  pak Ocit baca **LEVEL**. Biarin `0` kecuali ladder-nya udah diubah.
- **`PLC_PULSE_MS` < `PLC_POLL_MS` = pulse nggak pernah kelihatan.** ON dan OFF
  jatuh di tick yang sama, nggak ada rising edge. Cuma di-warning, nggak di-clamp.
- **Lisensi habis ⇒ coil alive DIMATIKAN.** Di PLC, "lisensi habis" dan "PC mati"
  kelihatan persis sama — pembedanya cuma layar. Ini disengaja.
- **Line 2 dan 3 nggak punya coil alive.** Kalau `PLC_COIL_ALIVE` keisi di line
  2/3, kamu nabrak SPARE.
- `start_plc_worker` dipanggil dua kali → balik `None` + warning, **bukan** worker
  lama. Dua thread di socket yang sama = transaction id ngawur.

## Diagnosa cepat

```bash
docker ps --format '{{.Names}}'                    # nama asli: ripe_line_1|2|3
docker logs --since 5m ripe_line_1 | grep -iE "PLC (aktif|on):"   # v1.8.0 "PLC aktif: ...", staging "PLC on: ..."
curl -s localhost:<port>/health/detail             # inputs[], dropped_pulses, dropped_submissions
```

Baris log `PLC aktif:` (v1.8.0) / `PLC on:` (staging) nyebut coil OK/NG/ERROR dan
alive yang **beneran kepakai** — itu cara tercepat mastiin `PLC_COIL_BASE` line-nya bener.

| Gejala | Cek dulu |
|---|---|
| Nggak ada sinyal sama sekali | `PLC_ENABLED`, `PLC_HOST` keisi, log `PLC aktif:`/`PLC on:` |
| Sinyal masuk ke line yang salah | `PLC_COIL_BASE` di compose (0/3/6) |
| Alarm PC-mati nyala terus | `PLC_ALIVE_TOGGLE_MS` harus `0`; cek lisensi belum habis |
| Coil nyangkut ON | SIGTERM di tengah pulse — `deenergise()` harusnya nutup ini, cek log shutdown |
| Buah kesortir telat / salah | `PLC_QUEUE_MAX` kegedean; `dropped_pulses` naik = buah lebih cepat dari yang bisa dihitung PLC |

## Kode

`src/palmgrade/plc/` — 4 file, komentarnya udah nyimpen rasional tiap keputusan,
baca itu sebelum ngubah:

- `__init__.py` — 5 fungsi publik + lifecycle (`start_plc_worker`, `shutdown_plc_worker`,
  `submit_grading`, `inputs`, `diagnostics`)
- `worker.py` — satu-satunya thread yang nyentuh socket. `run_once()` ngerakit
  **satu peta `{coil: level}`** per tick baru nulis sekali di akhir (ini yang
  matiin runt pulse secara struktural — jangan dipecah lagi jadi write terpisah)
- `modbus_client.py` — satu-satunya tempat yang nyentuh pymodbus; semua method
  balikin sentinel, nggak pernah raise
- `pulse.py` — penjadwal pulse
