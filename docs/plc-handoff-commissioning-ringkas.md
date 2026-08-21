# Integrasi Palmgrade Vision → PLC (ODOT CN-8031)

**Catatan serah terima untuk commissioning**

| | |
| --- | --- |
| Tanggal catatan | 16 Agustus 2026 |
| Commissioning | Selasa, 18 Agustus 2026 |
| Sisi aplikasi | `palmgrade-vision` (komputer + kamera) |
| Sisi panel | PLC Mitsubishi + remote IO ODOT |
| Rekan PLC | Mas Ocit — PT Nexio Teknologi Otomasi |

---

## 1. Status

Semua yang ada di skematik REMOTE IO sudah dipasang persis di aplikasi, tanpa ada yang diubah:
peta coil, peta discrete input, alamat internal PLC, arah arus sink/source, sampai batas
5 client CN-8031. Kodenya sudah jadi dan sudah lolos pengujian di sisi aplikasi.

**Tapi belum pernah ketemu hardware asli.** Semua pengujian pakai simulasi Modbus. Hari Selasa
nanti benar-benar pertama kalinya aplikasi ini nyambung ke coupler sungguhan.

**Ada enam hal yang masih ditunggu dari sisi panel** — lengkapnya di bagian 7. Yang nomor 4
(IP coupler) paling menghambat: tanpa itu aplikasi tidak bisa nyambung sama sekali.

### Sudah terpasang di komputer pabrik

Aplikasi versi `v1.2.0` — versi yang sudah berisi seluruh bagian PLC ini — **sudah terpasang
dan jalan di komputer pabrik Lampung sejak 16 Agustus 2026**, dan ketiga line sudah dipastikan
jalan normal.

Fitur PLC-nya sendiri **masih dimatikan** (setelan `PLC_ENABLED=false`). Jadi sampai hari
Selasa, aplikasi ini **tidak membuka koneksi Modbus sama sekali** dan **tidak pernah menulis
coil apa pun** — tidak ada risiko coil kesenggol tak sengaja sebelum panel siap.

Artinya pekerjaan hari Selasa di sisi aplikasi tinggal: isi IP coupler, nyalakan satu setelan,
restart. Bukan pasang aplikasi dari nol.

---

## 2. Gambaran singkat

Tiga line jalan sebagai tiga proses terpisah di satu komputer. Masing-masing buka koneksi
Modbus-TCP sendiri ke CN-8031 — jadi 3 dari kuota 5, sisa 2 masih bisa dipakai kalau perlu
colok laptop buat diagnosa.

Kameranya jalan terus, tidak nunggu trigger dari PLC. Tiap buah yang dinilai AI keluar jadi
satu pulse di coil OK atau coil NG milik line itu.

---

## 3. Peta coil (aplikasi yang menulis) — FC05, mulai dari 0

| Coil | Alamat PLC | Fungsi | Line | Bentuk sinyal |
| ---: | --- | --- | --- | --- |
| 0 | X0300 | CAM 1 OK | 1 | Pulse per buah |
| 1 | X0301 | CAM 1 NG | 1 | Pulse per buah |
| 2 | X0302 | CAM 1 ERROR | 1 | Level |
| 3 | X0303 | CAM 2 OK | 2 | Pulse per buah |
| 4 | X0304 | CAM 2 NG | 2 | Pulse per buah |
| 5 | X0305 | CAM 2 ERROR | 2 | Level |
| 6 | X0306 | CAM 3 OK | 3 | Pulse per buah |
| 7 | X0307 | CAM 3 NG | 3 | Pulse per buah |
| 8 | X0308 | CAM 3 ERROR | 3 | Level |
| 9 | X0309 | HEARTBIT PC ON | 1 | **ON terus** selama komputer dan proses line 1 hidup |
| 10–15 | X030A–X030F | Spare | — | Tidak disentuh aplikasi |

---

## 4. Peta discrete input (aplikasi yang membaca) — FC02, mulai dari 0

| DI | Alamat PLC | Fungsi |
| ---: | --- | --- |
| 0–9 | Y0310–Y0319 | MOTOR 1–10 FAULT |
| 10 | Y031A | EMERGENCY STOP |
| 11–15 | Y031B–Y031F | Spare |

Ketiga line baca blok DI yang sama — ini status conveyor bersama, bukan per-line.

---

## 5. Setelan komunikasi

| Parameter | Nilai |
| --- | --- |
| Protokol | Modbus-TCP, port 502 |
| Unit / slave ID | 1 |
| Tulis coil | FC05 (write single coil) |
| Baca input | FC02 (read discrete inputs), 16 titik |
| Penomoran | Mulai dari 0 |
| Polling | 200 ms — sekalian jadi keepalive watchdog |
| Timeout socket | 1 detik |
| Jumlah koneksi | 3 (satu per line) |
| IP coupler | **Belum tersedia** — lihat item 7.4 |

Semua angka timing di atas bisa diubah langsung dari setelan di lapangan. Tidak perlu bongkar
aplikasi, tidak perlu restart panel.

---

## 6. Aturan main sinyalnya — ini yang perlu diketahui ladder

**6.1 Coil OK/NG itu tepi naik, bukan level.** Satu tepi naik = satu buah. Jangan dihitung dari
lamanya coil ON, karena lebar pulse-nya nanti kita setel ulang bareng di lapangan.

**6.2 Coil ERROR itu level, artinya "line ini lagi bermasalah"** — praktiknya kameranya
terputus. Nyala selama masalahnya ada, mati sendiri begitu beres. Coil ini **tidak** ada
hubungannya dengan sinyal yang terbuang di 6.5. Kalau disambungkan ke sana, coil ini bakal
nyala sepanjang shift waktu produksi ramai, dan lama-lama jadi lampu yang diabaikan operator.

**6.3 Coil 9 artinya "line 1 hidup", bukan persis "komputer hidup".** Tiga line itu tiga
proses terpisah di satu komputer, dan yang menulis coil 9 cuma proses line 1. Konsekuensinya
dua arah, dan dua-duanya perlu diketahui panel:

- Kalau **proses line 1** mati sendirian, coil 9 padam padahal komputernya sehat.
- Kalau **proses line 2 atau 3** mati sendirian, coil 9 tetap ON, dan coil CAM 2/3 ERROR-nya
  juga **tidak** akan nyala — yang harusnya menulis coil itu ya proses yang barusan mati.
  Watchdog coupler juga tidak trip karena line 1 masih rajin bicara.

Jadi ada satu lubang yang jujur perlu disebut: **line yang mati sendirian bisa tidak
kelihatan dari PLC.** Sempat ditutup pakai coil 10/11/12 sebagai bit alive per line, tapi
di skematik keenam coil itu ditandai SPARE, jadi sekarang tidak dipakai — mengikuti gambar.
Kalau panel mau lubang ini ditutup, tinggal alokasikan 3 spare, di sisi aplikasi cuma ganti
setelan.

**6.4 Waktu aplikasi di-restart, coil-nya dimatikan dulu.** Restart itu hal rutin — buat
update atau tuning. Karena pulse-nya ON 200 ms dari siklus 300 ms, peluang ada coil yang
*sedang* ON pas perintah berhenti datang itu sekitar 2 dari 3. Jadi sebelum benar-benar
berhenti, aplikasi nulis OFF ke semua coil miliknya. Kalau tidak, coil bisa nyangkut ON
sampai watchdog coupler nyerah.

**6.5 Sebagian keputusan memang akan dibuang — ini disengaja.**

Satu coil cuma muat satu pulse dalam satu waktu. Dengan pulse 200 ms + jeda 100 ms:

```
1 ÷ (0,2 + 0,1) ≈ 3,3 sinyal per detik
```

Sementara kameranya jalan terus dan bisa keluar sampai ~10 keputusan per detik per line kalau
buahnya rapat. Selisihnya dibuang aplikasi, tidak diantrekan.

Alasannya: belt terus jalan. Kalau sinyal ditahan di antrean biar "tidak ada yang hilang",
keluarnya jadi telat, dan yang lewat di depan actuator saat itu sudah buah yang lain. Jadi
antrean panjang bukan bikin aman, malah bikin salah sortir terus-menerus. Lebih baik kehilangan
sebagian sinyal yang tepat, daripada mengirim semua sinyal ke buah yang keliru.

Berapa yang terbuang tetap dihitung aplikasi, dan bisa dibaca kapan saja dari halaman diagnosa
selama produksi jalan. Jadi bukan hilang diam-diam.

**6.6 Perintah tulis coil yang gagal akan diulang aplikasi** di siklus berikutnya. Ini penting
terutama buat perintah OFF di akhir pulse: kalau OFF-nya gagal dan tidak ada yang menagih,
coil itu nyangkut ON selamanya.

**6.7 Kalau koneksi ke coupler putus, kamera tetap jalan.** Kabel lepas, panel dimatikan,
coupler di-restart — apa pun sebabnya, yang terjadi di sisi aplikasi:

| | |
| --- | --- |
| Kamera + penilaian AI | **Tetap jalan normal.** Hasilnya tetap tersimpan dan tetap masuk laporan |
| Koneksi Modbus | Dicoba nyambung ulang sendiri tiap 200 ms, tidak perlu restart aplikasi |
| Sinyal selama putus | **Hilang, tidak diantrekan.** Alasannya sama dengan 6.5 — belt terus jalan |
| Pembacaan E-stop / motor fault | Nilai terakhir dipertahankan, tidak berubah jadi nol |

Yang perlu dicatat ladder: putusnya koneksi **tidak** menyalakan coil ERROR — coil itu hanya
soal kamera (6.2), dan lagipula kalau jaringan putus aplikasi memang tidak bisa menulis apa pun.
Yang memberi tahu PLC adalah coil 9 yang padam sendiri lewat *fault action* coupler.

**6.8 E-stop dan motor fault dibaca aplikasi, tapi belum dipakai buat apa-apa.** Sekarang ini
kedua-duanya cuma tampil di halaman diagnosa. **Kamera tidak berhenti sendiri waktu E-stop
ditekan** — dia tetap menilai buah yang kebetulan diam di depan lensa. Kalau menurut panel
kamera memang harus ikut berhenti, tolong bilang hari Selasa; itu perubahan kecil di sisi
aplikasi, tapi sengaja tidak ditebak-tebak sendiri untuk urusan safety. Lihat item 7.6.

---

## 7. Yang masih ditunggu dari sisi panel

| # | Hal yang ditunggu | Kalau tidak beres |
| ---: | --- | --- |
| 1 | **Lebar pulse dan jeda-nya berapa yang benar.** Angka 200 ms / 100 ms itu cuma patokan awal di aplikasi, bukan angka final. Yang perlu dipastikan: sinyal OK/NG maunya pulse atau level? Satu sinyal itu satu buah atau status batch? Cycle time actuator penyortirnya berapa? | Seluruh hitungan di 6.5 berdiri di atas angka yang belum dipastikan |
| 2 | **Watchdog coupler masih 30 detik**, mohon diturunkan ke 2–3 detik. Aplikasi polling tiap 200 ms, jadi 2–3 detik aman, tidak akan false-trip | Kalau komputer mati mendadak, coil terakhir nyangkut sekitar setengah menit |
| 3 | **E-stop mohon dikabel ulang jadi NC.** CT-122F itu low-aktif, dan setelan `Fault Action for Input: Cleaning Input Value` bikin kabel putus terbaca persis sama dengan kondisi aman | *Fail-to-danger.* Kabel E-stop lepas tidak akan ketahuan. Sengaja tidak diakali dari sisi aplikasi |
| 4 | **IP address coupler dan nyambung ke switch/NIC yang mana.** Usulan dari sisi aplikasi, tinggal disamakan: **`192.168.100.50`** statis, subnet `255.255.255.0`, gateway boleh dikosongkan, kabel LAN masuk ke switch gigabit yang sama dengan tiga kamera. Angka itu dipilih supaya tidak bentrok dengan kamera (`.10`/`.11`/`.12`) maupun NIC komputer (`.100`) — bebas diganti ke `.51`–`.99` asal tetap `192.168.100.x`. Aplikasi sudah disetel ke angka ini dari sekarang, jadi begitu coupler-nya datang tinggal dicocokkan | **Paling menghambat.** Aplikasi tidak bisa nyambung sama sekali |
| 5 | **Kalau ada buah yang lewat tanpa sinyal apa pun, actuator-nya default ngapain?** Ini pertanyaan baru dari sisi aplikasi, belum pernah kita bahas. Karena sebagian keputusan memang dibuang (6.5), pasti ada buah yang lewat tanpa pulse | Menentukan ke arah mana kesalahan sistem ini condong: buah tak tersinyal diloloskan atau dibuang |
| 6 | **Waktu E-stop ditekan, kamera perlu ikut berhenti menilai atau tidak?** Sekarang tidak — lihat 6.8 | Kalau iya dan tidak dipasang, akan ada hasil penilaian yang tercatat padahal line-nya lagi berhenti darurat |

---

Detail teknis lengkapnya ada di `palmgrade-vision/docs/plc-integration.md`.
