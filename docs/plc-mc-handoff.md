---
judul: AutoGrade ↔ PLC Mitsubishi
subjudul: Peta alamat M, sinyal yang dikirim PC, dan yang diminta dari sisi PLC — untuk commissioning MC Protocol.
label: Internal · Tim Engineering
versi: "1.3"
tanggal: 23 September 2026
klasifikasi: Internal — untuk tim PLC dan tim engineering
pemilik: Tim Engineering AutoGrade
sorotan: Alamat = daftar pak Ocit 23 Sep, sudah dipasang; Ditunggu dari PLC = 5 butir; Wajib = watchdog heartbeat
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
| IP PLC | `192.168.0.14` (dari tim PLC, 23 Sep) |
| Port | `1025` |
| Device | Internal relay `M` |
| Jumlah koneksi | **3** — satu per line kamera |
| Perioda polling PC | 200 ms |

---

## 2. Peta alamat M

Alamat di bawah adalah **daftar dari Pak Ocit (23 September 2026)** dan **sudah dipasang**
di aplikasi persis seperti itu. Polanya sama dengan skema ODOT yang lama — coil 0–9 dan
DI 0–11 — dipindah ke M1000 dan M1100.

### 2.1 PC menulis, PLC membaca

| Alamat | Arti | Bentuk sinyal |
|---|---|---|
| **M1000** | CAMERA 1: janjang **OK** (diterima) | pulse 200 ms |
| **M1001** | CAMERA 1: janjang **NG** (ditolak) | pulse 200 ms |
| **M1002** | CAMERA 1: **ERROR** | level, 1 = bermasalah |
| **M1003** | CAMERA 2: janjang OK | pulse 200 ms |
| **M1004** | CAMERA 2: janjang NG | pulse 200 ms |
| **M1005** | CAMERA 2: ERROR | level |
| **M1006** | CAMERA 3: janjang OK | pulse 200 ms |
| **M1007** | CAMERA 3: janjang NG | pulse 200 ms |
| **M1008** | CAMERA 3: ERROR | level |
| **M1009** | **HEARTBIT PC** — lihat bab 3 | **berkedip 500 ms** |

<!-- plc-map: base=1000,1003,1006; alive=1009; manual=; di_manual=; di_base=1100; di_count=16 -->

**Piston manual belum ada di daftar** — sama seperti di skema ODOT dulu. Fiturnya di
aplikasi **dimatikan** sampai panel mengalokasikan bitnya; grading tidak terpengaruh.
Kalau masih diinginkan, usulan yang mengikuti pola daftar ini: **M1010 / M1011 / M1012**
(minta buka, per camera) dan **M1112 / M1113 / M1114** (konfirmasi terbuka).

### 2.2 PLC menulis, PC membaca

Dibaca sebagai satu blok **M1100–M1115** sekali tiap 200 ms.

| Alamat | Arti |
|---|---|
| **M1100–M1110** | MOTOR 1–11 FAULT |
| **M1111** | E-STOP OP PANEL |
| M1112–M1115 | belum dialokasikan (usulan: konfirmasi piston, lihat atas) |

Bit yang kami baca dipakai untuk **tampilan dan diagnosa**, bukan untuk mengambil
keputusan grading.

Yang dilihat operator: begitu salah satu bit M1100–M1111 ON, layar konsol menampilkan
**pita merah besar** di atas kartu line — "MOTOR 3 FAULT", "E-STOP DITEKAN" — dan hilang
sendiri saat bitnya OFF. Grading **tidak dihentikan** oleh E-stop; kamera tetap menilai
(lihat bab 5, butir konfirmasi).

⚠️ **Polaritas diasumsikan bit ON = fault / ditekan.** Kalau ladder menulis kebalikannya
(ON = normal, OFF = fault, seperti kabel NC), mohon kabari — sisi aplikasi tinggal membalik
satu tempat.

---

## 3. Yang WAJIB ada di ladder: watchdog heartbeat

**Ini butir terpenting di seluruh dokumen.**

Rencana lama memakai coupler ODOT, yang punya *fault action*: begitu kabel ke PC putus,
coupler **mematikan sendiri seluruh outputnya**. Karena itu heartbeat cukup berupa bit
yang ditahan ON.

**CPU Mitsubishi tidak melakukan itu.** Kalau PC mati atau kabel tercabut tepat saat
M1001 (NG) sedang ON, bit itu **tetap ON selamanya** dan pistonnya terus menembak.

Karena itu, di jalur MC Protocol:

1. PC membuat **M1009 berkedip** tiap 500 ms (ON–OFF–ON–OFF).
2. Ladder **menghitung PERUBAHAN** M1009, bukan levelnya.
3. Kalau M1009 **tidak berubah selama 2–3 detik**, ladder menyimpulkan PC mati dan
   **mematikan sendiri semua bit dari PC** (M1000–M1008).

⚠️ Ladder **tidak boleh** membaca M1009 sebagai level ("ON berarti PC hidup"). Bit yang
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

Kalau bit konfirmasi tidak naik dalam 2 detik, PC menurunkan sendiri bitnya.

**Saat ini fitur ini mati** karena bitnya belum dialokasikan panel (bab 2).

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
| 1 | **Tiga koneksi MC Protocol** di Open Setting GX Works2 | Tiap camera membuka socket sendiri; satu port hanya melayani satu koneksi |
| 2 | **Watchdog heartbeat di ladder** (bab 3) | Tanpa ini, bit bisa nyangkut ON saat PC mati |
| 3 | **Konfirmasi: buah tanpa sinyal LOLOS atau DIBUANG?** | Menentukan aturan buah internal benar atau terbalik |
| 4 | **Polaritas M1100–M1111: ON = fault/ditekan?** | Pita alarm operator dibaca dari bit ini apa adanya; kalau terbalik, pita menyala terus saat pabrik sehat |
| 5 | **Saat E-stop, kamera ikut berhenti menilai?** Sekarang tidak — cuma pita. | Kalau harus berhenti, ada hasil grading yang tercatat selama line berhenti darurat |
| — | Piston manual: mau dialokasikan (usulan bab 2) atau ditiadakan? | Tidak mendesak; fiturnya sudah mati dengan aman |

Peta alamat **sudah selesai** — daftar 23 September dipakai apa adanya.

Catatan jaringan: `192.168.0.14` **satu segmen dengan NIC kamera PC pabrik**
(`192.168.0.10/24`), jadi PLC cukup dicolok ke switch gigabit kamera — tidak perlu rute
tambahan. Mohon pastikan `.14` tidak dipakai salah satu kamera.

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

**Yang ditunggu dari sisi PLC:** lima butir di bab 5 (dua terakhir konfirmasi, bukan pekerjaan).

**Yang paling mudah terlewat:** watchdog heartbeat di bab 3. Tanpa itu, sistem tetap
terlihat normal sampai hari PC mati di tengah shift.
