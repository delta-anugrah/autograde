# Commissioning PLC di Lampung — 23 September 2026

Hari pertama AutoGrade bicara ke CPU Mitsubishi Q03UDECPU sungguhan lewat MC Protocol.
Hasil akhir: **tiga line tersambung, M1000/M1001 (PC → PLC) dan M1111 (PLC → PC)
terbukti di GX Works2.** Catatan ini menyimpan urutan kejadiannya apa adanya, karena
tiap hambatan yang muncul gejalanya menyesatkan dan **tidak satu pun ada di kode**.

Yang dipegang tim PLC: `docs/plc-mc-handoff.md` (v1.4). Peta teknis: skill `plc-mc-protocol`.

## Keadaan awal

- PC Lampung `v1.14.0` → ditarik ke `v1.15.0` (`autograde.sh pull`), PLC di `192.168.0.14`
  — satu segmen dengan NIC kamera (`enp3s0` `192.168.0.10/24`), tanpa rute tambahan.
- Ocit sudah membuka port 1025 (MC Protocol, TCP) dan program uji Viki sudah bisa
  nulis/baca M dari laptop.

## Urutan hambatan dan jawabannya

### 1. Image sudah baru, tapi container masih memakai variabel lama

`autograde.sh status` bilang `v1.15.0`, tapi `docker exec ripe_line_1 env | grep PLC`
masih `PLC_PORT=502`, `PLC_COIL_BASE=0`, `PLC_COIL_ALIVE=9`, dan **tidak ada
`PLC_PROTOCOL`** sama sekali. Layar Uji PLC: "PLC is off on this line", tombol abu-abu.

**Sebab:** `docker-compose.yml` hidup di **host** (`/opt/palmgrade/autograde/`), bukan di
image. `pull` menaikkan kode, variabel yang dikirim ke container tetap yang lama. Ini
sudah tercatat di CLAUDE.md sebagai jebakan umum, dan tetap saja memakan waktu.

**Jawab:** tukar blok `PLC_*` di ketiga service dengan skrip (idempoten, bikin cadangan
`docker-compose.yml.bak-<tanggal>`):

```bash
cd /opt/palmgrade/autograde && python3 /tmp/plc-mc.py   # isi skrip: lampiran A
```

### 2. `.env` menimpa compose

`.env` masih memuat `PLC_PORT=502`, `PLC_COIL_BASE=0`, dst. dari era ODOT — dan `.env`
**menang** atas default compose. Dibersihkan sampai tersisa dua baris:

```bash
cp .env .env.bak-$(date +%F)
sed -i -E '/^PLC_(PORT|COIL_BASE|COIL_ALIVE|ALIVE_TOGGLE_MS|DI_COUNT|UNIT_ID)=/d' .env
grep '^PLC_' .env    # PLC_ENABLED=true, PLC_HOST=192.168.0.14 — itu saja
```

Sesudah 1 + 2 dan restart, layar langsung menampilkan `0: MOTOR 1 = Off … 11: E-STOP = On`
dan tombol berbunyi "Test coil 1000/1001". **Jalur baca hidup.**

### 3. Tombol abu-abu walau PLC hidup

Pengaman yang disengaja: uji coil **ditolak selama line punya truk terpasang**. Tekan
**Release** dulu. Kata konfirmasinya **`UJI`** — sempat diketik `TES`, dan selama beberapa
menit dikira "pulse terkirim tapi PLC diam", padahal belum pernah terkirim.

### 4. Baca jalan, tulis ditolak: `mc protocol error: error code 0x0055`

Setiap tulis — M1000, M1002, M1009 — ditolak dengan kode yang sama, tiap 200 ms, sementara
bit motor tetap terbaca mulus. `0x0055` = *write not allowed*: PLC menerima paketnya,
mengerti, lalu menolak. **Bukan** jaringan (baca jalan), **bukan** alamat (kodenya akan
device error).

**Sebab:** *Enable online change (FTP, MC Protocol)* belum tercentang di Open Setting.
Izin baca dan tulis di MC Protocol **terpisah** — inilah alasan butir itu ada di daftar
tunggu sejak awal. **Jawab:** centang → Write to PLC → **reset CPU**.

Retry 200 ms membanjiri log; sementara menunggu: `PLC_ENABLED=false` + restart, grading
nol terpengaruh.

### 5. Sesudah reset CPU: satu line tersambung, dua lainnya `connect timed out`

Log line 1: `PLC connect ke 192.168.0.14:1025 gagal: timed out` tiap ~2 s. Line 3 bersih
dan membaca bit. `0x0055` hilang — centang Ocit **berhasil**, tapi sekarang cuma satu line
yang dapat koneksi.

**Sebab:** **satu Open Setting = satu koneksi TCP.** Tiga line di port 1025 berebut satu
slot; yang dapat acak tiap restart, dua lainnya menunggu selamanya. Ini butir "3 koneksi"
di daftar tunggu.

**Jawab (dua sisi):**

- PC: port literal per line — 1025 / 1026 / 1027 (skrip lampiran B). Sesudah ini
  `PLC_PORT` **tidak boleh** diisi di `.env`.
- PLC: Ocit menambah dua Open Setting (TCP, MC Protocol, 1026 dan 1027).

### 6. Port sudah "ditambah", masih `Connection refused`

`refused` (bukan `timed out`) = PLC menjawab tegas "port ini tidak ada". Ocit **belum
reset CPU** sesudah Write to PLC. Sesudah reset: ketiga line bersih dalam ~30 detik,
**tanpa** restart apa pun di PC — tiap line reconnect sendiri tiap tick.

Cara memastikan, dari luar aplikasi:

```bash
for p in 1025 1026 1027; do
  timeout 2 bash -c "</dev/tcp/192.168.0.14/$p" 2>/dev/null && echo "$p TERBUKA" || echo "$p tertutup"
done
```

## Hasil

| Uji | Hasil |
|---|---|
| Tiga koneksi (1025/1026/1027) | ✅ nol error di log ketiga line |
| M1000, M1001 dari tombol Uji PLC | ✅ terlihat di GX Works2 |
| M1111 (E-stop) dari PLC | ✅ tampil di layar konsol |
| M1009 berkedip 500 ms | jalan, **belum dipantau** Ocit |

## Yang masih terbuka sesudah hari ini

1. **Watchdog heartbeat di ladder** — pantau M1009; diam 2–3 detik ⇒ matikan M1000–M1008.
2. **Polaritas E-stop** — layar menampilkan `On` sepanjang sore. Panelnya memang ditekan?
   Belum ditanyakan. Kalau tidak, ladder NC dan pita alarm akan menyala terus.
3. **"Ditahan terus"** — Ocit minta OK/NG ditahan. Buat tes: `PLC_PULSE_MS=10000` sementara.
   Buat produksi: **jangan** — latch di ladder; PC tidak tahu kecepatan belt.
4. E-stop menghentikan kamera atau cukup pita? Buah tanpa sinyal lolos atau dibuang?

## Perintah yang sering dipakai hari ini

```bash
cd /opt/palmgrade && ./autograde.sh stop && ./autograde.sh          # bukan `restart`
docker exec ripe_line_1 env | grep PLC | sort
for n in 1 2 3; do echo "== line $n =="; docker logs --since 30s ripe_line_$n 2>&1 \
  | grep -iE "connect|0x0055|coil write failed" | tail -1; done       # ketiganya kosong = sehat
```

`autograde.sh restart` sempat melewati satu container yang dianggap "tidak berubah"
(`PLC_ENABLED` di line 2 tidak ikut turun). `stop` lalu start penuh yang meyakinkan.

## Lampiran A — tukar blok PLC di compose (host PC)

```python
import re, shutil, sys
from datetime import date
from pathlib import Path

BASE = {"ripe_line_1": 1000, "ripe_line_2": 1003, "ripe_line_3": 1006}
PORT = {"ripe_line_1": 1025, "ripe_line_2": 1026, "ripe_line_3": 1027}
p = Path("docker-compose.yml"); s = p.read_text(encoding="utf-8")
if "PLC_PROTOCOL" in s:
    print("Sudah versi MC Protocol — tidak ada yang diubah."); sys.exit(0)

def blok(svc, indent):
    base, alive = BASE[svc], "1009" if svc == "ripe_line_1" else ""
    baris = [
        "# PLC — MC Protocol langsung ke CPU Mitsubishi (daftar pak Ocit 2026-09-23).",
        "- PLC_ENABLED=${PLC_ENABLED:-false}", "- PLC_HOST=${PLC_HOST:-}",
        "- PLC_PROTOCOL=${PLC_PROTOCOL:-mc}",
        "# Satu Open Setting PLC = satu koneksi: port literal per line.",
        f"- PLC_PORT={PORT[svc]}", "- PLC_UNIT_ID=${PLC_UNIT_ID:-1}",
        "- PLC_DEVICE_PREFIX=${PLC_DEVICE_PREFIX:-M}",
        f"# OK=M{base}, NG=M{base+1}, ERROR=M{base+2}.", f"- PLC_COIL_BASE={base}",
        f"- PLC_COIL_ALIVE={alive}", "- PLC_COIL_MANUAL=", "- PLC_DI_MANUAL=",
        "- PLC_DI_BASE=${PLC_DI_BASE:-1100}", "- PLC_DI_COUNT=${PLC_DI_COUNT:-16}",
        "- PLC_ALIVE_TOGGLE_MS=${PLC_ALIVE_TOGGLE_MS:-}", "- PLC_PULSE_MS=${PLC_PULSE_MS:-200}",
        "- PLC_PULSE_GAP_MS=${PLC_PULSE_GAP_MS:-100}", "- PLC_QUEUE_MAX=${PLC_QUEUE_MAX:-1}",
        "- PLC_POLL_MS=${PLC_POLL_MS:-200}",
    ]
    return "".join(f"{indent}{b}\n" for b in baris)

baris = s.splitlines(keepends=True); punya, kini = [], None
for ln in baris:
    m = re.match(r"\s*container_name:\s*(\S+)", ln)
    if m: kini = m.group(1)
    punya.append(kini)
keluar, i, diganti = [], 0, []
while i < len(baris):
    ln = baris[i]
    if re.match(r"\s*-\s*PLC_ENABLED=", ln):
        indent = re.match(r"(\s*)", ln).group(1)
        while keluar and re.match(r"\s*#", keluar[-1]) and "PLC" in keluar[-1].upper():
            keluar.pop()
        j = i
        while j < len(baris) and (re.search(r"PLC_", baris[j]) or re.match(r"\s*#", baris[j])):
            j += 1
        svc = punya[i]
        if svc not in BASE: raise SystemExit(f"Blok PLC baris {i+1} bukan line dikenal: {svc}")
        keluar.append(blok(svc, indent)); diganti.append(svc); i = j; continue
    keluar.append(ln); i += 1
if sorted(diganti) != sorted(BASE): raise SystemExit(f"Diharapkan 3 blok, ketemu: {diganti}")
cad = p.with_name(p.name + f".bak-{date.today()}"); shutil.copy2(p, cad)
p.write_text("".join(keluar), encoding="utf-8")
print(f"OK — 3 blok diganti: {', '.join(diganti)}\nCadangan: {cad}")
```

## Lampiran B — cuma port per line (kalau blok sudah versi MC)

```python
import re
from pathlib import Path
p = Path("docker-compose.yml"); s = p.read_text()
port = {"ripe_line_1": "1025", "ripe_line_2": "1026", "ripe_line_3": "1027"}
out, kini = [], None
for ln in s.splitlines(keepends=True):
    m = re.match(r"\s*container_name:\s*(\S+)", ln)
    if m: kini = m.group(1)
    if re.match(r"\s*-\s*PLC_PORT=", ln) and kini in port:
        ln = re.sub(r"PLC_PORT=.*", f"PLC_PORT={port[kini]}", ln)
    out.append(ln)
p.write_text("".join(out)); print("port per line dipasang")
```
