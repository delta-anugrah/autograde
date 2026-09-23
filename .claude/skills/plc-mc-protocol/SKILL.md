---
name: plc-mc-protocol
description: Jalur AutoGrade → PLC Mitsubishi lewat MC Protocol (pymcprotocol, device M) — peta alamat M, pilihan protokol mc/modbus, heartbeat berkedip, jebakan balasan terpotong, dan apa yang ditunggu dari tim PLC. Pakai kalau sinyal tidak sampai ke PLC, alamat M mau diganti, alarm "PC mati" nyala terus, konfirmasi piston tidak pernah datang, E-stop terbaca lepas padahal ditekan, lagi commissioning, atau mau tahu beda jalur ini dengan ODOT yang dibatalkan.
---

# AutoGrade ↔ PLC Mitsubishi (MC Protocol)

Sejak **2026-09-21** PC bicara **langsung ke CPU Mitsubishi Q03UDECPU** lewat port
Ethernet bawaannya. Coupler ODOT CN-8031 **dibatalkan** — keputusan tim PLC (Mas Viki),
bukan kegagalan teknis.

Dokumen untuk tim PLC: `docs/plc-mc-handoff.md` (+ PDF). Itu sumber kebenaran alamat
kalau dokumen dan skill ini berbeda. Jalur ODOT lama diarsipkan di
`docs/plc-handoff-commissioning.md` — jangan dipakai untuk alamat.

## Yang berubah dan yang TIDAK

**Berubah — satu lapisan saja:** `plc/mc_client.py` menggantikan `plc/modbus_client.py`
sebagai pengirim. Keduanya punya tiga method yang sama persis (`write_coil`,
`read_discrete_inputs`, `close`), dan `build_plc_client(settings)` memilih salah satunya
dari `PLC_PROTOCOL`.

**TIDAK berubah:** `PlcWorker`, `PulseScheduler`, `domain/plc_signal.py`,
`domain/grade_class.py`, aturan buah internal, piston manual, layar Uji PLC. Worker tidak
pernah tahu protokol mana yang sedang dipakai — itu yang membuat perpindahan ini kecil.

## Peta alamat M — daftar pak Ocit, 2026-09-23, SUDAH dipasang

Polanya persis skema ODOT lama (coil 0–9, DI 0–11) dipindah ke M1000 / M1100.

**PC menulis:**

| Alamat | Arti | Bentuk |
|---|---|---|
| M1000 / M1001 / M1002 | CAMERA 1 OK / NG / ERROR | pulse / pulse / level |
| M1003 / M1004 / M1005 | CAMERA 2 OK / NG / ERROR | sama |
| M1006 / M1007 / M1008 | CAMERA 3 OK / NG / ERROR | sama |
| **M1009** | **HEARTBIT PC** | **berkedip 500 ms** |

**PC membaca** — satu blok M1100–M1115 tiap 200 ms:

| Alamat | Arti |
|---|---|
| M1100–M1110 | MOTOR 1–11 FAULT |
| M1111 | E-STOP OP PANEL (`inputs[11]`) |
| M1112–M1115 | belum dialokasikan |

Bit ini sampai ke operator lewat `domain/plc_alarm.py` → `/internal/status.alarms` →
`LineStatusWorker` → `/api/console/state` → `gambarPitaAlarm()` (satu pita global, bukan
per kartu — semua line membaca blok yang sama, jadi daftarnya digabung dan dideduplikasi).
Tab Uji PLC menamai tiap bit lewat `namaBitPlc()`, cermin dari modul domain yang sama.
E-stop = **tanda saja**, grading tidak berhenti (keputusan 2026-09-23; menghentikan butuh
konfirmasi Ocit). ⚠️ Polaritas diasumsikan **ON = fault** — belum dikonfirmasi; kalau
ladder menulis kebalikannya, pita menyala terus saat pabrik sehat.

`PLC_COIL_BASE` = 1000 / 1003 / 1006 per line; offset +0 OK, +1 NG, +2 ERROR — struktur
yang sama dengan jalur Modbus, cuma angkanya pindah.

⚠️ **Piston manual TIDAK ada di daftar Ocit** (di ODOT dulu juga "menunggu alokasi").
`PLC_COIL_MANUAL` / `PLC_DI_MANUAL` di compose sengaja **kosong** = fitur mati, tombolnya
tidak muncul, grading jalan terus. Usulan yang mengikuti pola daftarnya kalau nanti
dialokasikan: M1010/M1011/M1012 (minta buka) + M1112/M1113/M1114 (konfirmasi). Jangan isi
sendiri — bit yang belum dialokasikan panel bisa milik orang lain di ladder.

⚠️ **Alamat di compose dan dokumen semuanya ABSOLUT** (M1111, bukan "offset 11").
`PlcWorker._input_at()` yang mengurangi `PLC_DI_BASE` supaya jadi indeks blok. Kalau
suatu saat ada yang mengindeks `self.inputs` langsung dengan `plc_di_manual`, konfirmasi
piston berhenti datang **tanpa satu pun error** — itu bug nyata yang sempat ada dan
dikunci oleh `test_konfirmasi_piston_dibaca_dari_alamat_absolut_bukan_indeks`.

## Kenapa heartbeat WAJIB berkedip di jalur ini

Coupler ODOT punya *fault action*: link putus → outputnya mati sendiri. **CPU Mitsubishi
tidak.** Bit NG yang ditinggal ON saat PC mati akan **tetap ON** dan pistonnya menembak
terus.

Jadi:
- `PLC_ALIVE_TOGGLE_MS` bawaannya **500 di jalur mc**, **0 di jalur modbus** — diturunkan
  dari protokol di `config.py`, bukan angka tetap.
- Ladder wajib menghitung **PERUBAHAN** M1009, bukan level, lalu mematikan semua bit dari
  PC kalau tidak berubah 2–3 detik.
- ⚠️ Ladder yang membaca M1009 sebagai **level** akan menyalakan alarm "PC mati" tiap
  setengah periode. Ini pernah terjadi di `v1.3.0`.

## Jebakan pustaka: balasan terpotong = "semua input mati"

**Ini jebakan paling mahal di jalur ini dan tidak kelihatan dari nilai kembalian.**

`pymcprotocol._recv()` mengembalikan `b""` saat socket tertutup di tengah. Slicing bytes
kosong tetap menghasilkan `b""`, ter-decode sebagai status `0` = **sukses**, dan
`batchread_bitunits` membangun daftarnya dengan `range(readsize)` — jadi balasan 0 byte
dan balasan sah **sama-sama** menghasilkan 20 elemen. Yang gagal isinya nol semua.

Akibatnya kalau dibiarkan: **kabel putus terbaca sebagai E-stop lepas** padahal sedang
ditekan.

Diukur langsung: balasan sah 21 byte, balasan mati 0 byte, hasil keduanya identik.
Satu-satunya pembeda ada di bytes mentah, jadi `McProtocolPlcClient._baca_terjaga()`
membungkus `_recv` selama satu panggilan dan memeriksa panjangnya
(`11 + ceil(count/2)`). Dikunci oleh `test_balasan_kosong_jadi_kegagalan_bukan_deretan_nol`.

⚠️ Jangan "rapikan" bungkus itu jadi pemeriksaan `len(bits)` — panjang daftarnya selalu
benar, justru itu masalahnya.

## Setelan

| Env | Bawaan | Catatan |
|---|---|---|
| `PLC_PROTOCOL` | `mc` | `modbus` untuk site yang terlanjur dikabel lewat coupler |
| `PLC_PORT` | ikut protokol | mc 1025, modbus 502. Kosongkan supaya ikut |
| `PLC_DEVICE_PREFIX` | `M` | kalau panel memberi B atau Y, ganti ini saja |
| `PLC_DI_BASE` | `1100` | awal blok yang dibaca |
| `PLC_DI_COUNT` | `16` | |
| `PLC_ALIVE_TOGGLE_MS` | ikut protokol | mc 500, modbus 0. Kosongkan supaya ikut |

⚠️ Env PLC yang **kosong** berarti "ikut bawaan", bukan nilai rusak — `_plc_int` sengaja
diam untuk string kosong, karena compose menulis `${PLC_PORT:-}` dan tiga container akan
meneriakkan warning palsu tiap start.

⚠️ **`docker-compose.yml` menyebut env satu per satu, tidak ada `env_file:`.** Tiap
menambah env PLC baru di kode, compose di PC pabrik WAJIB ikut diperbarui. Cek dengan
`docker exec ripe_line_1 env | grep PLC`.

## Prosedur lapangan

**TERSAMBUNG di Lampung 2026-09-23** — 3 line, M1000/M1001 (PC→PLC) dan M1111 (PLC→PC)
terbukti. Runbook lengkapnya `docs/runbooks/2026-09-23-commissioning-plc-lampung.md`.
Ringkasan yang harus diingat, urut seperti kejadiannya:

1. 🔴 **`docker-compose.yml` hidup di HOST PC pabrik, bukan di image.** `autograde.sh pull`
   menaikkan kode tapi tidak menyentuh variabel container. Gejala: image `v1.15.0` tapi
   `docker exec env` masih `PLC_PORT=502`, `PLC_COIL_BASE=0`, **nol `PLC_PROTOCOL`** ⇒
   layar "PLC is off on this line". Blok PLC ketiga service harus ditukar tangan (skrip di
   runbook, idempoten, bikin cadangan).
2. ⚠️ **`.env` MENANG atas compose.** `PLC_PORT=502` sisa ODOT di `.env` menimpa default yang
   benar. Sisakan cuma `PLC_ENABLED` dan `PLC_HOST` di `.env`.
3. ⚠️ Tombol Uji PLC **abu-abu selama line punya truk** — Release dulu. Kata kuncinya **`UJI`**,
   bukan `TES` (sempat dikira "pulse terkirim tapi PLC diam").
4. 🔴 **Baca jalan, tulis ditolak `mc protocol error 0x0055`** = *Enable online change (FTP,
   MC Protocol)* belum dicentang. Izin baca/tulis **terpisah**. Perlu Write to PLC + **reset
   CPU**. Retry 200 ms membanjiri log — `PLC_ENABLED=false` sementara kalau menunggu lama.
5. 🔴 **Satu Open Setting = SATU koneksi TCP.** Tiga line di port 1025 ⇒ satu line dapat,
   dua lainnya `connect timed out`. Sekarang **port literal per line: 1025/1026/1027**
   (compose + dokumen + test pengikat). `Connection refused` sesudah Ocit "menambah port" =
   **belum reset CPU**.
6. Sesudah PLC beres, PC **tidak perlu restart** — tiap line reconnect sendiri tiap tick.

**Menyalakan di PC baru:** `PLC_ENABLED=true` + `PLC_HOST` di `.env` → `autograde.sh stop`
lalu start (bukan `restart`: yang ini kadang melewati container yang dianggap "tidak
berubah") → `for n in 1 2 3; do docker logs --since 30s ripe_line_$n 2>&1 | grep -iE
"connect|0x0055|coil write failed" | tail -1; done` — ketiganya **kosong** = tersambung.

**Uji tanpa kamera:** tab **Uji PLC** di konsol (akun support) memicu satu pulse per bit.
Sejak 2026-09-23 malam yang bisa diuji: **OK, NG, dan ERROR** per line
(1000/1001/**1002**, 1003/1004/**1005**, 1006/1007/**1008**) + piston kalau dialokasikan.
Heartbeat **tidak pernah** masuk daftar — memicunya bikin panel mengira PC mati.

⚠️ ERROR itu **level** yang dikemudikan `health_check()`, bukan pulse. `PlcWorker`
melewati penulisan levelnya selama pulse uji berjalan (`_scheduler_is_active`) — tanpa itu
pulse naik lalu ditimpa level sehat pada tick yang sama, coil bergerak beberapa milidetik
dan tidak ada yang melihatnya di panel. Levelnya pulih sendiri di tick sesudahnya;
`_error_level` sengaja tidak diperbarui saat dilewati.

Pulse 200 ms — pantau dari **monitor bit GX Works2**, lampu panel terlalu cepat.

**Mode TAHAN (`PLC_HOLD_MS`, bawaan 0 = pulse).** > 0 menukar `PulseScheduler` dengan
`HoldScheduler` lewat `build_scheduler()`: coil OK/NG dipegang ON sekian ms dan
**diperpanjang** tiap janjang berikutnya, tidak pernah membuang. Diminta tim PLC untuk uji
di panel. ⚠️ **PLC tidak bisa menghitung janjang di mode ini** — dua janjang berurutan jadi
satu sinyal panjang. Keduanya berbagi antarmuka (`enqueue`/`tick`/`dropped`/`is_active`),
jadi `PlcWorker` tidak tahu mana yang terpasang — pola yang sama dengan `build_plc_client`.

## Yang masih ditunggu dari tim PLC

Peta alamat **sudah beres** (daftar Ocit 2026-09-23). Sisanya:

1. **Watchdog heartbeat di ladder** (pantau M1009 berkedip) — satu-satunya pekerjaan panel
   yang tersisa; paling mudah terlewat, paling mahal kalau lupa.
1b. **Mode tahan dipakai atau tidak di produksi?** Opsinya sudah ada (`PLC_HOLD_MS`), tapi
   saran kami tetap pulse + latch di ladder. Belum diputuskan bersama.
2. **Polaritas E-stop**: layar menampilkan `M1111 = On` sepanjang uji 23 Sep — **belum
   ditanyakan** apakah panelnya memang ditekan. Kalau tidak, ladder terbalik (NC).
3. **Saat E-stop, kamera berhenti menilai?** Sekarang cuma pita.
4. **Buah tanpa sinyal itu LOLOS atau DIBUANG?** Menggantung sejak era ODOT, **belum terjawab**.
5. **"OK/NG ditahan terus"** yang diminta Ocit: buat tes boleh (`PLC_PULSE_MS`), buat produksi
   **tidak** — latch di ladder. Belum diputuskan bersama.
6. (tidak mendesak) Piston manual dialokasikan atau ditiadakan?

Jaringan: PLC `192.168.0.14` **satu segmen dengan NIC kamera PC Lampung**
(`enp3s0` = `192.168.0.10/24`, skill `spek-pc-pabrik`) — dicolok ke switch kamera, tanpa
rute tambahan. ⚠️ `docs/SETUP.md` menulis `192.168.100.x`; itu template pasang-dari-nol,
bukan Lampung. Pastikan `.14` tidak dipakai kamera (IP kamera Lampung belum tercatat).

## Test yang menjaga jalur ini

| Berkas | Menjaga |
|---|---|
| `tests/unit/plc/test_plc_mc_client.py` | terjemahan alamat, kegagalan jadi sentinel, balasan terpotong |
| `tests/unit/plc/test_plc_config.py` | pilihan protokol, port & heartbeat turunan, env kosong diam |
| `tests/unit/plc/test_plc_piston.py` | alamat absolut vs indeks blok |
| `tests/e2e/test_mc_protocol_lane.py` | worker → klien → pustaka asli → socket: bingkai yang benar-benar keluar |
| `tests/unit/test_plc_alarm.py` | bit → alarm: motor dinomori dari 1, E-stop offset 11, bit belum dialokasikan diabaikan |
| `tests/e2e/test_internal_status_alarm.py` | `/internal/status` membawa `alarms`; PLC mati = `[]`, bukan error |
| `tests/unit/test_line_status_alarm.py` | worker menyimpan `alarms`; line versi lama tanpa field = `[]`; line mati tidak punya alarm palsu |
| `tests/unit/test_console_html_alarm.py` | pita ada & digambar tiap refresh, terjemahan dua bahasa, **dedup `gabungAlarm` dijalankan lewat node** |
| `tests/unit/test_plc_docs_match_compose.py` | dokumen tim PLC ≡ `docker-compose.yml` |

⚠️ Test terakhir membaca komentar `<!-- plc-map: ... -->` di `docs/plc-mc-handoff.md`.
Ganti alamat di compose tanpa mengganti dokumen = test merah. Itu disengaja: dokumen yang
dipegang tim panel tidak boleh diam-diam berbeda dari yang dipakai aplikasi.

Terkait: skill `plc-coil-map` (jalur ODOT lama, arsip), `spek-pc-pabrik`,
`install-factory-pc`.
