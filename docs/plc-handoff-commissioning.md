# Integrasi Palmgrade Vision → PLC (ODOT CN-8031)

**Catatan serah terima untuk commissioning**

| | |
| --- | --- |
| Tanggal catatan | 16 Agustus 2026 |
| Commissioning | Selasa, 18 Agustus 2026 |
| Sisi kami | `palmgrade-vision` (komputer + kamera) |
| Sisi panel | PLC Mitsubishi + remote IO ODOT |
| Rekan PLC | Mas Ocit — PT Nexio Teknologi Otomasi |

---

## 1. Status

Semua yang ada di skematik REMOTE IO sudah kami pasang persis, tanpa ada yang kami ubah:
peta coil, peta discrete input, alamat internal PLC, arah arus sink/source, sampai batas
5 client CN-8031. Kodenya sudah jadi dan sudah lolos pengujian di sisi kami.

**Tapi belum pernah ketemu hardware asli.** Semua pengujian kami pakai simulasi Modbus.
Hari Selasa nanti benar-benar pertama kalinya program ini nyambung ke coupler sungguhan.

**Ada enam hal yang masih kami tunggu dari sisi panel** — lengkapnya di bagian 7. Yang nomor 4
(IP coupler) paling menghambat: tanpa itu kami tidak bisa nyambung sama sekali.

### Sudah terpasang di komputer pabrik

Program versi `v1.2.0` — versi yang sudah berisi seluruh bagian PLC ini — **sudah kami pasang
dan jalankan di komputer pabrik Lampung tanggal 16 Agustus 2026**, dan sudah kami pastikan
ketiga line jalan normal.

Fitur PLC-nya sendiri **kami matikan dulu** (setelan `PLC_ENABLED=false`). Jadi sampai hari
Selasa, program ini **tidak membuka koneksi Modbus sama sekali** dan **tidak pernah menulis
coil apa pun** — tidak ada risiko coil kesenggol tak sengaja sebelum panel siap.

Artinya pekerjaan hari Selasa di sisi kami tinggal: isi IP coupler, nyalakan satu setelan,
restart. Bukan pasang program dari nol.

---

## 2. Gambaran singkat

Tiga line jalan sebagai tiga program terpisah di satu komputer. Masing-masing buka koneksi
Modbus-TCP sendiri ke CN-8031 — jadi 3 dari kuota 5, sisa 2 masih bisa dipakai kalau perlu
colok laptop buat diagnosa.

Kameranya jalan terus, tidak nunggu trigger dari PLC. Tiap buah yang dinilai AI keluar jadi
satu pulse di coil OK atau coil NG milik line itu.

---

## 3. Peta coil (kami yang menulis) — FC05, mulai dari 0

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
| 9 | X0309 | HEARTBEAT PC | 1 | **Toggle 1 Hz** (lihat bagian 8) |
| 10 | X030A | LINE 1 ALIVE | 1 | Toggle 1 Hz |
| 11 | X030B | LINE 2 ALIVE | 2 | Toggle 1 Hz |
| 12 | X030C | LINE 3 ALIVE | 3 | Toggle 1 Hz |
| 13–15 | X030D–X030F | Spare | — | Tidak kami sentuh |

---

## 4. Peta discrete input (kami yang membaca) — FC02, mulai dari 0

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
| IP coupler | **Belum kami punya** — lihat item 7.4 |

Semua angka timing di atas bisa diubah langsung dari setelan di lapangan. Tidak perlu bongkar
program, tidak perlu restart panel.

---

## 6. Aturan main sinyalnya — ini yang perlu diketahui ladder

**6.1 Coil OK/NG itu tepi naik, bukan level.** Satu tepi naik = satu buah. Jangan dihitung dari
lamanya coil ON, karena lebar pulse-nya nanti kita setel ulang bareng di lapangan.

**6.2 Coil ERROR itu level, artinya "line ini lagi bermasalah"** — praktiknya kameranya
terputus. Nyala selama masalahnya ada, mati sendiri begitu beres. Coil ini **tidak** ada
hubungannya dengan sinyal yang terbuang di 6.5. Kalau disambungkan ke sana, coil ini bakal
nyala sepanjang shift waktu produksi ramai, dan lama-lama jadi lampu yang diabaikan operator.

**6.3 Bit ALIVE sengaja dipisah per line.** Tiga line itu tiga program terpisah. Kalau yang
mati cuma program line 2, coil CAM 2 ERROR-nya justru **tidak** akan nyala — yang harusnya
menulis coil itu ya program yang barusan mati. Watchdog coupler juga tidak akan trip, karena
line 1 dan 3 masih rajin bicara. Jadi PLC bisa buta terhadap satu line yang mati diam-diam.
Bit 10/11/12 ini penutup lubang itu. Saran kami, ladder cukup cek "kalau bit ini tidak berubah
selama 3 detik, berarti ada masalah".

**6.4 Waktu program di-restart, coil-nya kami matikan dulu.** Restart itu hal rutin — buat
update atau tuning. Karena pulse-nya ON 200 ms dari siklus 300 ms, peluang ada coil yang
*sedang* ON pas perintah berhenti datang itu sekitar 2 dari 3. Jadi sebelum benar-benar
berhenti, programnya nulis OFF ke semua coil miliknya. Kalau tidak, coil bisa nyangkut ON
sampai watchdog coupler nyerah.

**6.5 Sebagian keputusan memang akan dibuang — ini disengaja.**

Satu coil cuma muat satu pulse dalam satu waktu. Dengan pulse 200 ms + jeda 100 ms:

```
1 ÷ (0,2 + 0,1) ≈ 3,3 sinyal per detik
```

Sementara kameranya jalan terus dan bisa keluar sampai ~10 keputusan per detik per line kalau
buahnya rapat. Selisihnya kami buang, tidak kami antrekan.

Alasannya: belt terus jalan. Kalau sinyal ditahan di antrean biar "tidak ada yang hilang",
keluarnya jadi telat, dan yang lewat di depan actuator saat itu sudah buah yang lain. Jadi
antrean panjang bukan bikin aman, malah bikin salah sortir terus-menerus. Lebih baik kehilangan
sebagian sinyal yang tepat, daripada mengirim semua sinyal ke buah yang keliru.

Berapa yang terbuang tetap kami hitung, dan bisa dibaca kapan saja dari halaman diagnosa
selama produksi jalan. Jadi bukan hilang diam-diam.

**6.6 Perintah tulis coil yang gagal akan kami ulang** di siklus berikutnya. Ini penting
terutama buat perintah OFF di akhir pulse: kalau OFF-nya gagal dan tidak ada yang menagih,
coil itu nyangkut ON selamanya.

**6.7 Kalau koneksi ke coupler putus, kamera tetap jalan.** Kabel lepas, panel dimatikan,
coupler di-restart — apa pun sebabnya, yang terjadi di sisi kami:

| | |
| --- | --- |
| Kamera + penilaian AI | **Tetap jalan normal.** Hasilnya tetap tersimpan dan tetap masuk laporan |
| Koneksi Modbus | Dicoba nyambung ulang sendiri tiap 200 ms, tidak perlu restart program |
| Sinyal selama putus | **Hilang, tidak diantrekan.** Alasannya sama dengan 6.5 — belt terus jalan |
| Pembacaan E-stop / motor fault | Nilai terakhir dipertahankan, tidak berubah jadi nol |

Yang perlu dicatat ladder: putusnya koneksi **tidak** menyalakan coil ERROR — coil itu hanya
soal kamera (6.2), dan lagipula kalau jaringan putus kami memang tidak bisa menulis apa pun.
Yang memberi tahu PLC adalah bit ALIVE yang berhenti bergoyang, plus watchdog coupler sendiri.

**6.8 E-stop dan motor fault kami baca, tapi belum kami pakai buat apa-apa.** Sekarang ini
kedua-duanya cuma tampil di halaman diagnosa kami. **Kamera tidak berhenti sendiri waktu E-stop
ditekan** — dia tetap menilai buah yang kebetulan diam di depan lensa. Kalau menurut panel
kamera memang harus ikut berhenti, tolong bilang hari Selasa; itu perubahan kecil di sisi kami,
tapi kami sengaja tidak menebak-nebak sendiri untuk urusan safety. Lihat item 7.6.

---

## 7. Yang masih kami tunggu dari sisi panel

| # | Hal yang ditunggu | Kalau tidak beres |
| ---: | --- | --- |
| 1 | **Lebar pulse dan jeda-nya berapa yang benar.** Angka 200 ms / 100 ms itu patokan kami, bukan angka final. Yang perlu kami tahu: sinyal OK/NG maunya pulse atau level? Satu sinyal itu satu buah atau status batch? Cycle time actuator penyortirnya berapa? | Seluruh hitungan di 6.5 berdiri di atas angka yang belum dipastikan |
| 2 | **Watchdog coupler masih 30 detik**, mohon diturunkan ke 2–3 detik. Kami polling tiap 200 ms, jadi 2–3 detik aman, tidak akan false-trip | Kalau komputer mati mendadak, coil terakhir nyangkut sekitar setengah menit |
| 3 | **E-stop mohon dikabel ulang jadi NC.** CT-122F itu low-aktif, dan setelan `Fault Action for Input: Cleaning Input Value` bikin kabel putus terbaca persis sama dengan kondisi aman | *Fail-to-danger.* Kabel E-stop lepas tidak akan ketahuan. Sengaja tidak kami akali dari sisi software |
| 4 | **IP address coupler dan nyambung ke switch/NIC yang mana.** NIC komputer sudah kepakai tiga kamera GigE | **Paling menghambat.** Kami tidak bisa nyambung sama sekali |
| 5 | **Kalau ada buah yang lewat tanpa sinyal apa pun, actuator-nya default ngapain?** Ini pertanyaan baru dari kami, belum pernah kita bahas. Karena sebagian keputusan memang dibuang (6.5), pasti ada buah yang lewat tanpa pulse | Menentukan ke arah mana kesalahan sistem ini condong: buah tak tersinyal diloloskan atau dibuang |
| 6 | **Waktu E-stop ditekan, kamera perlu ikut berhenti menilai atau tidak?** Sekarang tidak — lihat 6.8 | Kalau iya dan tidak kami pasang, akan ada hasil penilaian yang tercatat padahal line-nya lagi berhenti darurat |

---

## 7b. Yang perlu siap sebelum hari Selasa

Supaya waktu di lapangan tidak habis buat urusan kabel:

| Siapa | Yang disiapkan |
| --- | --- |
| Panel | IP coupler sudah di-set dan sudah dicatat (item 7.4) |
| Panel | Watchdog coupler sudah diturunkan ke 2–3 detik (item 7.2), atau minimal sudah disepakati akan diturunkan |
| Panel | Kabel LAN dari coupler ke ruang komputer, plus port kosong di switch |
| Kami | Komputer sudah siap (**sudah beres**, lihat bagian 1) |
| Kami | Port jaringan kedua di komputer buat ke coupler — **ini yang perlu dipastikan bareng**, karena port yang ada sekarang sudah dipakai tiga kamera GigE |
| Bersama | Alat buat mengukur lebar pulse: scope atau monitor bit di GX Works |

---

## 8. Satu hal yang kami ubah dari skematik — mohon dikonfirmasi

Di skematik, coil 9 tertulis **"HEARTBEAT PC ON"**. Kami implementasikan sebagai
**toggle 1 Hz**, bukan ON terus.

Alasannya: kalau cuma ON statis, PLC tidak bisa membedakan "komputer hidup" dengan "komputer
hidup tapi programnya nge-hang" — dua-duanya kelihatan sama, coil-nya tetap ON. Dengan toggle,
ladder cukup cek ada tidaknya perubahan.

Kalau menurut mas Ocit ON statis lebih cocok dengan desain panelnya, tinggal bilang — buat kami
itu perubahan kecil.

---

## 9. Urutan yang kami usulkan hari Selasa

1. Isi IP coupler, lalu pastikan komputer bisa nyambung ke situ.
2. Nyalakan line 1 dulu, line 2 dan 3 dimatikan — biar kalau ada yang aneh kelihatan sumbernya.
3. Picu satu pulse, lalu **pastikan bareng-bareng bahwa coil 0 di sisi kami = X0300 di sisi PLC.** Jangan diasumsikan — beda satu alamat saja artinya CAM 1 OK jatuh ke CAM 1 NG.
4. Ukur lebar pulse yang **sebenarnya** sampai di PLC, pakai scope atau monitor. Angka 200 ms itu perlu dibuktikan, bukan dipercaya.
5. Cek bit ALIVE 10 bergoyang 1 Hz. Lalu matikan program line 1 — bit itu harus berhenti bergoyang, sementara bit line 2 dan 3 tetap jalan.
6. Picu satu motor fault dari sisi panel, pastikan bit yang berubah di sisi kami memang nomor motor yang sama. Cukup satu-dua motor buat membuktikan urutannya, tidak perlu sepuluh-sepuluhnya.
7. **Cabut kabel E-stop**, lalu lihat pembacaan kami berubah atau tidak. Kalau tidak berubah, itu bukti masalah polaritas di item 7.3 — jangan diterima cuma karena bit-nya kebaca aman.
8. **Cabut kabel LAN ke coupler** sekitar 10 detik, lalu colok lagi. Yang harus terlihat: bit ALIVE berhenti bergoyang lalu jalan lagi sendiri, tanpa ada yang perlu me-restart apa pun (6.7).
9. Restart program line 1 pas pulse lagi jalan, pastikan tidak ada coil yang tertinggal ON.
10. Jalankan produksi beneran sekitar 15 menit di satu line, lalu baca berapa sinyal yang terbuang dari halaman diagnosa. Angka itu yang jadi dasar buat menyetel ulang lebar pulse.
11. Baru nyalakan line 2 dan 3.

Kalau waktunya mepet, yang **tidak boleh dilewat** cuma tiga: langkah 3 (cocokkan alamat coil),
langkah 4 (ukur lebar pulse beneran), dan langkah 7 (polaritas E-stop). Sisanya boleh menyusul.

---

## 10. Terus terang, ini yang belum kami buktikan

- **Belum pernah diuji ke coupler fisik.** Semua tes kami pakai simulasi.
- **Pengaman "satu buah tetap satu pulse walau simpan gambar gagal" belum punya tes otomatis.** Bagian program itu memuat pustaka kamera dan AI yang berat, dan pipeline tes kami memang sengaja tidak memuat itu. Perbaikannya sudah kami periksa manual, tapi jujur saja belum ada jaring pengaman otomatisnya.
- **Ada celah lama yang sudah ada sebelum pekerjaan ini, dan belum kami tutup:** kalau simpan gambar gagal, lalu buahnya keluar dari area pantau, lalu nomor pelacakan objek dipakai ulang buat buah fisik yang sama — secara teori bisa muncul pulse dobel. Perlu kami amati waktu produksi beneran.
- **Hitungan 3,3 vs 10 sinyal per detik** bergantung pada lebar pulse yang belum dipastikan (item 7.1). Kalau lebar pulse-nya berubah, hitungan itu ikut berubah semua.

---

Detail teknis lengkapnya ada di `palmgrade-vision/docs/plc-integration.md`.
