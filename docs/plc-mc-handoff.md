---
judul: AutoGrade ↔ PLC Mitsubishi
subjudul: Peta alamat M, sinyal yang dikirim PC, dan yang diminta dari sisi PLC — untuk commissioning MC Protocol.
label: Internal · Tim Engineering
versi: "1.0"
tanggal: 21 September 2026
klasifikasi: Internal — untuk tim PLC dan tim engineering
pemilik: Tim Engineering AutoGrade
sorotan: Siap di aplikasi = kode MC Protocol sudah jalan dan teruji; Ditunggu dari PLC = 4 butir; Wajib = watchdog heartbeat
---

# AutoGrade ↔ PLC Mitsubishi

## 1. Ringkasan

AutoGrade menilai mutu tandan buah segar (TBS) dengan kamera di PC pabrik. Untuk setiap
janjang, aplikasi memutuskan **diterima (ACC)** atau **ditolak (REJ)**, lalu mengirim
keputusan itu sebagai **pulse** ke sebuah bit di PLC.

Sejak 21 September 2026 jalur ini **langsung dari PC ke CPU Mitsubishi Q03UDECPU** lewat
port Ethernet bawaannya, memakai **MC Protocol** (pustaka `pymcprotocol`, frame 3E biner).
Coupler remote IO ODOT CN-8031 yang dulu direncanakan **dibatalkan** dan tidak lagi dipakai.

Sisi aplikasi **sudah selesai dan teruji**. Yang ditunggu ada di bab 5.

### 1.1 Yang perlu diketahui lebih dulu

| Hal | Nilai |
|---|---|
| Protokol | MC Protocol 3E, biner |
| IP PLC | `192.168.3.39` (dari program uji Mas Viki) |
| Port | `1025` |
| Device | Internal relay `M` |
| Jumlah koneksi | **3** — satu per line kamera |
| Perioda polling PC | 200 ms |

---

## 2. Peta alamat M

Ini **usulan** dari sisi aplikasi. Angkanya dipilih bulat dan berblok supaya mudah dibaca
di ladder; kalau panel butuh angka lain, yang berubah cuma satu baris setelan per line —
tidak ada kode yang ikut berubah.

### 2.1 PC menulis, PLC membaca

| Alamat | Arti | Bentuk sinyal |
|---|---|---|
| **M100** | LINE 1: janjang **ACC** (diterima) | pulse 200 ms |
| **M101** | LINE 1: janjang **REJ** (ditolak) | pulse 200 ms |
| **M102** | LINE 1: kamera **ERROR** | level, 1 = bermasalah |
| **M103** | LINE 1: piston manual buka | level, 1 = minta buka |
| **M110** | **HEARTBEAT PC** — lihat bab 3 | **berkedip 500 ms** |
| **M120** | LINE 2: janjang ACC | pulse 200 ms |
| **M121** | LINE 2: janjang REJ | pulse 200 ms |
| **M122** | LINE 2: kamera ERROR | level |
| **M123** | LINE 2: piston manual buka | level |
| **M140** | LINE 3: janjang ACC | pulse 200 ms |
| **M141** | LINE 3: janjang REJ | pulse 200 ms |
| **M142** | LINE 3: kamera ERROR | level |
| **M143** | LINE 3: piston manual buka | level |

<!-- plc-map: base=100,120,140; alive=110; manual=103,123,143; di_manual=212,213,214; di_base=200; di_count=20 -->

### 2.2 PLC menulis, PC membaca

Dibaca sebagai satu blok **M200–M219** sekali tiap 200 ms.

| Alamat | Arti |
|---|---|
| **M200–M210** | MOTOR 1–11 fault |
| **M211** | EMERGENCY STOP |
| **M212** | LINE 1: konfirmasi piston terbuka |
| **M213** | LINE 2: konfirmasi piston terbuka |
| **M214** | LINE 3: konfirmasi piston terbuka |
| M215–M219 | SPARE |

Bit yang kami baca dipakai untuk **tampilan dan diagnosa**, bukan untuk mengambil
keputusan grading — kecuali M212–M214, yang membatalkan permintaan piston kalau
tidak naik dalam 2 detik.

---

## 3. Yang WAJIB ada di ladder: watchdog heartbeat

**Ini butir terpenting di seluruh dokumen.**

Rencana lama memakai coupler ODOT, yang punya *fault action*: begitu kabel ke PC putus,
coupler **mematikan sendiri seluruh outputnya**. Karena itu heartbeat cukup berupa bit
yang ditahan ON.

**CPU Mitsubishi tidak melakukan itu.** Kalau PC mati atau kabel tercabut tepat saat
M101 (REJ) sedang ON, bit itu **tetap ON selamanya** dan pistonnya terus menembak.

Karena itu, di jalur MC Protocol:

1. PC membuat **M110 berkedip** tiap 500 ms (ON–OFF–ON–OFF).
2. Ladder **menghitung PERUBAHAN** M110, bukan levelnya.
3. Kalau M110 **tidak berubah selama 2–3 detik**, ladder menyimpulkan PC mati dan
   **mematikan sendiri semua bit dari PC** (M100–M103, M120–M123, M140–M143).

⚠️ Ladder **tidak boleh** membaca M110 sebagai level ("ON berarti PC hidup"). Bit yang
berkedip akan terbaca OFF di separuh waktu dan alarm "PC mati" menyala terus-menerus.
Ini pernah terjadi sekali pada versi `v1.3.0` dan terlihat seperti kerusakan PC.

---

## 4. Bentuk sinyal

### 4.1 Pulse ACC / REJ

- Lebar **ON 200 ms**, lalu **OFF minimal 200 ms** sebelum pulse berikutnya di bit yang sama.
- Satu siklus penuh 400 ms ⇒ maksimum **±2,5 pulse per detik per bit**.
- Ladder cukup menghitung **tepi naik** (rising edge).

Kamera bisa menghasilkan ~10 keputusan per detik per line, jauh di atas 2,5. Kelebihannya
**sengaja dibuang dan dihitung**, bukan ditumpuk di antrean — sinyal yang telat akan
mendarat di janjang yang salah di belt. Jadi jumlah pulse di PLC **memang** bisa lebih
kecil dari jumlah janjang di layar saat produksi padat.

### 4.2 Bit ERROR

Level, bukan pulse. Naik kalau kamera atau proses di line itu bermasalah, dan **ditulis
ulang tiap detik** supaya kembali naik sendiri kalau sempat ter-reset.

### 4.3 Piston manual

Level. Operator menekan tombol di layar konsol; bit naik dan **ditahan** sampai operator
menutupnya. **Tidak pernah ditulis ulang otomatis** — kalau koneksi putus, permintaannya
dianggap batal. Ini disengaja: piston tidak boleh bergerak sendiri setelah link pulih.

Kalau konfirmasi (M212–M214) tidak naik dalam 2 detik, PC menurunkan sendiri bitnya.

### 4.4 Buah kebun sendiri tidak dibuang

Untuk truk berstatus **Internal**, janjang REJ **tidak dikirim pulse sama sekali** — tidak
ada REJ, dan juga **tidak ada ACC pengganti**.

⚠️ Aturan ini bergantung pada satu kesepakatan: **buah yang tidak diberi sinyal apa pun
akan LOLOS** (masuk ramp), bukan dibuang. Mohon dikonfirmasi — kalau posisi diam
aktuatornya justru membuang, hasilnya terbalik total. Lihat bab 5.

---

## 5. Yang kami tunggu dari sisi PLC

| # | Butir | Kenapa perlu |
|---|---|---|
| 1 | **Persetujuan peta alamat M** (bab 2), atau angka gantinya | Selama belum ada, setelan kami masih usulan |
| 2 | **Tiga koneksi MC Protocol** di Open Setting GX Works2 | Tiap line kamera membuka socket sendiri; satu port hanya melayani satu koneksi |
| 3 | **Watchdog heartbeat di ladder** (bab 3) | Tanpa ini, bit bisa nyangkut ON saat PC mati |
| 4 | **Konfirmasi: buah tanpa sinyal LOLOS atau DIBUANG?** | Menentukan aturan buah internal benar atau terbalik |

Catatan jaringan: PLC berada di `192.168.3.x`, sedangkan tiga kamera GigE di
`192.168.100.x`. PC pabrik perlu jalan ke keduanya — entah PLC ikut subnet kamera, atau
PC diberi rute tambahan. Mohon dipastikan sebelum pemasangan.

Catatan izin tulis: pastikan **"Enable online change (FTP, MC Protocol)"** tercentang di
Open Setting. Tanpa itu, baca berhasil tapi tulis ditolak — gejalanya mudah disalahartikan
sebagai masalah jaringan.

---

## 6. Cara menguji tanpa menunggu kami

Di layar konsol AutoGrade ada tab **"Uji PLC"** (khusus akun support). Isinya:

- daftar bit yang sedang dibaca dari PLC, per line;
- tombol untuk **memicu satu pulse** pada bit ACC / REJ / piston, satu per satu.

Ini dipakai saat commissioning untuk memastikan kabel dan ladder sudah benar, tanpa perlu
menjalankan kamera atau melewatkan buah. Tombolnya meminta konfirmasi ketik karena
**benar-benar menggerakkan hardware**.

---

## 7. Ringkasan satu halaman

**Yang sudah selesai di AutoGrade:** komunikasi MC Protocol, peta alamat, pulse ACC/REJ,
bit ERROR, heartbeat berkedip, piston manual, aturan buah internal, layar uji, dan
seluruh unit test-nya.

**Yang ditunggu dari sisi PLC:** empat butir di bab 5.

**Yang paling mudah terlewat:** watchdog heartbeat di bab 3. Tanpa itu, sistem tetap
terlihat normal sampai hari PC mati di tengah shift.
