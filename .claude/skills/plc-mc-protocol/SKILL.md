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

**Sebelum menyalakan:**
1. `ping -c3 192.168.3.39` dari PC pabrik.
2. Pastikan **"Enable online change (FTP, MC Protocol)"** tercentang di Open Setting
   GX Works2. Tanpa itu baca berhasil tapi tulis ditolak — gejalanya mudah disalahartikan
   sebagai masalah jaringan.
3. Pastikan ada **3 koneksi** di Open Setting (satu per line).
4. `sed -i 's|^PLC_ENABLED=.*|PLC_ENABLED=true|' .env` → `autograde.sh restart`.
5. `docker exec ripe_line_1 env | grep PLC_ENABLED` untuk membuktikan env-nya sampai.

**Uji tanpa kamera:** tab **Uji PLC** di konsol (akun support) memicu satu pulse per bit,
dengan konfirmasi ketik karena benar-benar menggerakkan hardware.

## Yang masih ditunggu dari tim PLC

Peta alamat **sudah beres** (daftar Ocit 2026-09-23). Sisanya:

1. **Tiga koneksi MC Protocol** di Open Setting.
2. **Watchdog heartbeat di ladder** — paling mudah terlewat, paling mahal kalau lupa.
3. **Buah tanpa sinyal itu LOLOS atau DIBUANG?** Menentukan aturan buah internal benar
   atau terbalik total. Pertanyaan ini sudah menggantung sejak era ODOT dan **belum
   terjawab**.
4. (tidak mendesak) Piston manual dialokasikan atau ditiadakan?

Jaringan: PLC di `192.168.3.x`, kamera GigE di `192.168.100.x`. PC butuh jalan ke
keduanya — PLC ikut subnet kamera, atau PC diberi rute tambahan. Belum diputuskan.

## Test yang menjaga jalur ini

| Berkas | Menjaga |
|---|---|
| `tests/unit/plc/test_plc_mc_client.py` | terjemahan alamat, kegagalan jadi sentinel, balasan terpotong |
| `tests/unit/plc/test_plc_config.py` | pilihan protokol, port & heartbeat turunan, env kosong diam |
| `tests/unit/plc/test_plc_piston.py` | alamat absolut vs indeks blok |
| `tests/e2e/test_mc_protocol_lane.py` | worker → klien → pustaka asli → socket: bingkai yang benar-benar keluar |
| `tests/unit/test_plc_docs_match_compose.py` | dokumen tim PLC ≡ `docker-compose.yml` |

⚠️ Test terakhir membaca komentar `<!-- plc-map: ... -->` di `docs/plc-mc-handoff.md`.
Ganti alamat di compose tanpa mengganti dokumen = test merah. Itu disengaja: dokumen yang
dipegang tim panel tidak boleh diam-diam berbeda dari yang dipakai aplikasi.

Terkait: skill `plc-coil-map` (jalur ODOT lama, arsip), `spek-pc-pabrik`,
`install-factory-pc`.
