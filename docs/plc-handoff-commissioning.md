---
judul: Panduan Integrasi AutoGrade ↔ PLC
subjudul: Peta coil dan discrete input coupler ODOT CN-8031, bentuk sinyal, aturan ladder yang diminta, dan urutan uji di lapangan.
label: Internal · Tim Engineering
versi: "2.0"
tanggal: 15 September 2026
klasifikasi: Internal — untuk tim panel dan tim engineering
pemilik: Tim Engineering AutoGrade
sorotan: Berjalan = Coil 0–9 · Usulan = Piston manual 10–12 · Butuh keputusan panel = 7 butir
---

# Panduan Integrasi AutoGrade ↔ PLC

Dokumen ini ditujukan bagi tim panel yang menulis ladder untuk line sortir kelapa sawit, dan
bagi tim engineering AutoGrade yang mendampingi commissioning. Isinya dua hal: apa yang **sudah
berjalan** hari ini di alamat coil yang sudah disepakati, dan apa yang **diusulkan** sebagai
alokasi baru agar operator dapat membuka piston sortir dari layar konsol.

Setiap bab diberi penanda status. Penanda itu bukan hiasan: separuh dokumen ini menjelaskan
perilaku yang dapat diukur di panel hari ini, dan separuh lagi menjelaskan permintaan yang belum
memiliki satu baris ladder pun.

## 1. Ringkasan dan status

**Status bab: Berjalan sekarang (v1.8.0) dan usulan, dibedakan per baris.**

AutoGrade adalah sistem penilaian mutu tandan buah segar berbasis kamera yang terpasang di PC
pabrik. Untuk setiap janjang yang melintas di bawah kamera, aplikasi menghasilkan satu keputusan:
diterima (ACC) atau ditolak (REJ). Keputusan itu disampaikan ke PLC sebagai pulse pada coil remote
IO ODOT CN-8031, dan PLC-lah yang menggerakkan aktuator penyortir.

**Fakta yang menentukan seluruh rancangan ini: AutoGrade tidak memiliki kabel ke aktuator mana
pun.** Output coupler ODOT masuk ke modul input PLC. Yang dapat dilakukan aplikasi hanyalah
menaikkan dan menurunkan bit. Yang menggerakkan piston, yang memegang interlock E-stop, dan yang
memutuskan kapan sebuah gerakan aman, selalu ladder PLC.

| Bagian | Status | Keterangan |
|---|---|---|
| Coil 0–8: hasil grading tiga line (OK / NG / ERROR) | Berjalan (v1.8.0) | Terpasang dan berjalan di PC pabrik |
| Coil 9: HEARTBIT PC ON | Berjalan (v1.8.0) | Ditulis oleh proses line 1 saja |
| Discrete input 0–10: motor fault dan E-stop | Berjalan (v1.8.0) | Dibaca ketiga proses line |
| Coil 10–12: piston manual per line | **Usulan** | Belum dialokasikan, belum ada di aplikasi |
| Discrete input 11–13: konfirmasi piston terbuka | **Usulan** | Belum dialokasikan, belum ada di aplikasi |

> **Piston manual belum ada di aplikasi yang terpasang.** Versi v1.8.0 yang berjalan di PC pabrik
> hari ini tidak menulis coil 10, 11, maupun 12, dan tidak membaca discrete input 11, 12, maupun
> 13. Seluruh Bab 5 adalah permintaan alokasi. Aplikasi baru akan menulis coil tersebut setelah
> alokasinya disetujui dan nomornya dimasukkan ke konfigurasi; selama nomor itu kosong, fitur
> piston mati sepenuhnya dan tidak ada satu pun bit tambahan yang tersentuh.

Yang diminta dari dokumen ini ada tiga: persetujuan atas alokasi coil 10–12 dan discrete input
11–13, konfirmasi enam aturan ladder di Bab 5, dan jawaban atas tujuh butir di Bab 8.

## 2. Gambaran sistem

**Status bab: Berjalan sekarang (v1.8.0).**

PC pabrik menjalankan tiga proses aplikasi yang saling terpisah, satu untuk setiap line kamera.
Masing-masing membuka koneksi Modbus-TCP sendiri ke coupler ODOT CN-8031 pada port 502. Coupler
meneruskannya ke PLC Mitsubishi lewat kabel.

```diagram:topologi Jalur sinyal dari tiga proses line di PC pabrik sampai ke ladder PLC
PC pabrik (3 proses line)  --Modbus-TCP-->  ODOT CN-8031  --kabel-->  PLC Mitsubishi
```

Beberapa sifat topologi ini perlu diketahui sebelum menyentuh panel:

- **Tiga koneksi, bukan satu.** Setiap proses line memegang satu koneksi Modbus sendiri, tanpa
  pooling. Coupler CN-8031 menerima maksimum lima client bersamaan, jadi tiga dari lima slot itu
  terpakai AutoGrade. Perangkat lunak diagnostik yang ikut menempel ke coupler saat commissioning
  memakai sisa slot tersebut.
- **Setiap proses hanya menyentuh coil miliknya.** Proses line 1 menulis coil 0, 1, 2, dan 9.
  Proses line 2 menulis coil 3, 4, 5. Proses line 3 menulis coil 6, 7, 8. Tidak ada proses yang
  menulis coil milik line lain.
- **Discrete input dibaca ketiga proses.** Motor fault dan E-stop adalah status bersama conveyor,
  bukan status per line, sehingga ketiga proses membaca blok yang sama.
- **Arah data satu-satu.** AutoGrade menulis coil dengan function code 05 dan membaca discrete
  input dengan function code 02. Aplikasi tidak pernah membaca kembali coil yang ditulisnya, dan
  tidak pernah menulis ke sisi input.

**Perangkat keras yang terpasang**

| Part number | Peran |
|---|---|
| ODOT CN-8031 | Coupler remote IO; sisi AutoGrade bicara ke perangkat ini lewat Modbus-TCP port 502 |
| CT-222F | Modul output, source/PNP, high-active |
| CT-122F | Modul input, NPN, low-active |
| CT-5801 | Modul catu daya panel |
| AJ65SBTB1-16D1 | Modul input Mitsubishi 16 titik — menerima dari CT-222F |
| AJ65SBTB1-16T1 | Modul output Mitsubishi 16 titik — mengirim ke CT-122F |

Pasangan sink/source sudah diperiksa cocok tanpa relay perantara: CT-222F source/PNP menuju
AJ65SBTB1-16D1 dengan COM di 0V, dan AJ65SBTB1-16T1 sink dengan COM di 0V menuju CT-122F yang
low-active.

## 3. Peta coil dan discrete input

**Status bab: Coil 0–9 dan discrete input 0–10 berjalan sekarang (v1.8.0). Coil 10–12 dan
discrete input 11–13 adalah usulan, menunggu persetujuan panel.**

Tabel ini adalah bagian paling penting dalam dokumen. Satu angka yang keliru di sini berarti
sinyal CAM 1 OK mendarat di alamat CAM 1 NG, dan buah yang layak justru dibuang. Nomor coil
ditulis **zero-based**, sesuai penomoran Modbus yang dipakai aplikasi; kolom alamat PLC adalah
alamat yang dilihat dari sisi GX Works.

### 3.1 Coil — AutoGrade menulis (FC05)

| Coil | Alamat PLC | Arti | Bentuk sinyal | Ditulis oleh | Status |
|---|---|---|---|---|---|
| 0 | X0300 | CAM 1 OK | pulse | line 1 | Berjalan |
| 1 | X0301 | CAM 1 NG | pulse | line 1 | Berjalan |
| 2 | X0302 | CAM 1 ERROR | level | line 1 | Berjalan |
| 3 | X0303 | CAM 2 OK | pulse | line 2 | Berjalan |
| 4 | X0304 | CAM 2 NG | pulse | line 2 | Berjalan |
| 5 | X0305 | CAM 2 ERROR | level | line 2 | Berjalan |
| 6 | X0306 | CAM 3 OK | pulse | line 3 | Berjalan |
| 7 | X0307 | CAM 3 NG | pulse | line 3 | Berjalan |
| 8 | X0308 | CAM 3 ERROR | level | line 3 | Berjalan |
| 9 | X0309 | HEARTBIT PC ON | level, ON terus | line 1 | Berjalan |
| **10** | **X030A** | **LINE 1: piston manual buka** | **level, 1 = minta buka** | **line 1** | **Usulan** |
| **11** | **X030B** | **LINE 2: piston manual buka** | **level, 1 = minta buka** | **line 2** | **Usulan** |
| **12** | **X030C** | **LINE 3: piston manual buka** | **level, 1 = minta buka** | **line 3** | **Usulan** |
| 13–15 | X030D–X030F | SPARE, tidak disentuh aplikasi | — | — | — |

<!-- plc-map: coil_base=0,3,6; coil_alive=9; coil_manual=; di_manual= -->

### 3.2 Discrete input — AutoGrade membaca (FC02)

| DI | Alamat PLC | Arti | Status |
|---|---|---|---|
| 0–9 | Y0310–Y0319 | MOTOR 1–10 FAULT | Berjalan |
| 10 | Y031A | EMERGENCY STOP | Berjalan |
| **11** | **Y031B** | **LINE 1: piston terbuka (konfirmasi PLC)** | **Usulan** |
| **12** | **Y031C** | **LINE 2: piston terbuka (konfirmasi PLC)** | **Usulan** |
| **13** | **Y031D** | **LINE 3: piston terbuka (konfirmasi PLC)** | **Usulan** |
| 14–15 | Y031E–Y031F | SPARE | — |

Aplikasi membaca 16 discrete input sekaligus pada setiap poll, sehingga menambah arti pada DI 11,
12, dan 13 tidak memerlukan perubahan pembacaan — yang berubah hanya penafsiran bit yang memang
sudah ikut terbaca.

### 3.3 Catatan alokasi

Coil 10–15 sebelumnya disepakati bersama sebagai SPARE dan **tidak disentuh** aplikasi. Kesepakatan
itu masih berlaku sampai dokumen ini dijawab. Permintaan sekarang adalah memindahkan tiga di
antaranya, yaitu 10, 11, dan 12, menjadi coil piston manual per line.

Konsekuensi yang diterima sadar: setelah alokasi ini, coil spare tersisa 13, 14, dan 15 saja.
Akibatnya satu lubang lama tetap terbuka — kalau proses satu line berhenti sendirian, PLC tidak
melihatnya, karena coil CAM_N_ERROR line itu justru tidak akan menyala; yang seharusnya menulisnya
adalah proses yang barusan berhenti. Menutup lubang itu memerlukan coil alive tersendiri per line,
dan itu **tidak** diminta dalam dokumen ini agar sisa spare tidak habis sekaligus.

## 4. Bentuk sinyal

**Status bab: Berjalan sekarang (v1.8.0).**

### 4.1 Tiga bentuk yang dipakai

| Coil | Bentuk | Arti bagi ladder |
|---|---|---|
| OK dan NG | **Pulse** | Satu tepi naik = satu janjang. Yang dihitung ladder adalah tepi naik, bukan lama ON |
| ERROR | **Level** | 1 selama line tidak sehat, 0 selama sehat. Dievaluasi ulang setiap tick |
| HEARTBIT PC | **Level, ON terus** | 1 selama aplikasi hidup dan berlisensi. 0 berarti PC berhenti |

**Pulse OK dan NG.** Setiap keputusan grading menghasilkan satu pulse pada satu coil: ACC ke coil
OK, REJ ke coil NG. Aplikasi menjamin ada jeda OFF di antara dua pulse pada coil yang sama,
sehingga PLC selalu melihat tepi naik yang terpisah. Ladder yang menghitung tepi naik akan
mendapatkan hitungan janjang yang benar; ladder yang mengukur lama ON tidak akan mendapatkan
informasi tambahan apa pun, karena lebar pulse bersifat tetap dan tidak membawa arti.

**Coil ERROR adalah kesehatan line, bukan tanda kelebihan beban.** Nilainya 1 ketika kamera line
tersebut terputus atau pemeriksaan kesehatan line gagal. Sinyal yang dibuang karena buah datang
terlalu cepat **tidak** menaikkan coil ERROR. Alasannya ada di bagian 4.3: pembuangan adalah
keadaan normal di bawah beban, dan kalau hal itu menyalakan coil ERROR, lampu tersebut akan
menyala sepanjang shift dan artinya berubah menjadi "line ini sedang bekerja normal".

**HEARTBIT PC.** Coil 9 ditahan ON oleh proses line 1 dan ditulis ulang setiap detik. Penulisan
ulang itu disengaja: kalau coupler me-reset output karena koneksi terputus, coil harus naik lagi
sendiri begitu tersambung, tanpa menunggu siapa pun me-restart apa pun.

> **Satu hal yang perlu diketahui tim panel:** ketika langganan lisensi AutoGrade habis, coil
> HEARTBIT **dimatikan** secara sengaja. Di sisi PLC, "lisensi habis" dan "PC mati" karena itu
> terlihat persis sama. Ini pilihan sadar: berhenti secara diam-diam jauh lebih berbahaya, karena
> PLC akan mengira semuanya normal sementara buah lewat tanpa disortir.

### 4.2 Angka waktu yang berlaku sekarang

Aplikasi mengevaluasi seluruh penjadwalan pulse pada satu putaran loop yang bangun setiap
**200 ms**. Angka itu adalah resolusi waktu yang sesungguhnya, bukan sekadar interval keepalive.
Akibatnya semua durasi dibulatkan ke kelipatan satu tick.

| Besaran | Nilai | Catatan |
|---|---|---|
| Satu tick evaluasi | 200 ms | Sekaligus keepalive watchdog coupler |
| Lebar pulse ON | **±205 ms** | Satu tick |
| Jeda OFF wajib | **±205 ms** | Jeda 100 ms dibulatkan ke atas menjadi satu tick penuh |
| Satu siklus pulse | **±410 ms** | Dua tick: satu ON, satu jeda |
| Kapasitas satu coil | **±2,5 pulse per detik** | 1 ÷ (2 × 0,205 detik) |

Angka **2,5 pulse per detik** itu yang berlaku, bukan 3,3. Perbedaannya berasal dari pembulatan
jeda: jeda 100 ms tidak dapat terjadi dalam separuh tick, sehingga ia menempati satu tick penuh.
Nilai ini diperiksa dengan menjalankan penjadwal pulse aplikasi pada 14 September 2026 dan
menghitung tepi naik yang dihasilkannya.

### 4.3 Kebijakan buang-dan-hitung

Kamera yang menyala terus dapat menghasilkan sampai **sekitar 10 keputusan grading per detik**
per line. Satu coil hanya memuat **±2,5 pulse per detik**. Selisih itu bukan kelainan yang perlu
diperbaiki, melainkan sifat yang dideklarasikan.

**Kebijakannya: buang dan hitung, tidak pernah menunda.** Ketika buah datang lebih cepat daripada
yang muat di satu coil, kelebihan keputusan dibuang dan pembuangan itu dicatat sebagai angka
diagnostik. Aplikasi **tidak** menumpuknya di antrean.

Alasannya ada pada belt yang terus berjalan. Sinyal yang ditahan di antrean akan sampai terlambat,
dan sinyal yang terlambat menempel pada buah yang salah — aktuator bergerak untuk janjang yang
sudah lewat. Kehilangan sebagian sinyal yang akurat lebih baik daripada mengirim seluruh sinyal di
tempat yang salah. Antrean per coil karena itu dibatasi satu, sehingga sinyal yang sampai ke PLC
paling lama berumur satu siklus, yaitu ±410 ms.

Jumlah sinyal yang terbuang dibaca dari layar diagnosa aplikasi (Bab 10), dan angkanya menjadi
dasar untuk menyetel ulang lebar pulse setelah kecepatan belt sesungguhnya diketahui.

**Butir yang perlu dikonfirmasi tim panel:** karena sebagian buah pasti lewat tanpa pulse, perilaku
default aktuator terhadap buah tanpa sinyal menentukan ke arah mana kesalahan sistem ini condong.
Butir ini ada di Bab 8 nomor 3.

## 5. Piston manual (usulan)

**Status bab: Usulan, menunggu persetujuan panel. Belum ada satu baris pun di aplikasi yang
terpasang.**

### 5.1 Yang diminta dan mengapa

Ketika buah tersangkut atau operator perlu meloloskan muatan tanpa sortir, saat ini tidak ada cara
membuka piston sortir dari layar konsol. Permintaannya: satu tombol per line di layar operator,
yang menahan piston terbuka sampai operator menutupnya kembali.

Karena AutoGrade tidak memiliki kabel ke piston, yang dapat dilakukan aplikasi hanya menaikkan satu
bit permintaan. Seluruh gerakan, seluruh interlock, dan seluruh tanggung jawab keselamatan tetap
berada di ladder.

### 5.2 Alur satu permintaan

1. Operator menekan tombol "Buka piston" pada kartu line di layar konsol; layar meminta konfirmasi.
2. Konsol meneruskan permintaan ke proses line yang bersangkutan.
3. Proses line menaikkan coil manual miliknya dari 0 ke 1, dan menahannya di 1.
4. Ladder melihat perubahan 0 → 1, memeriksa kondisi aman, lalu membuka piston.
5. Ladder menaikkan discrete input konfirmasi, menandakan piston benar-benar terbuka.
6. Layar konsol berubah menjadi "Tutup piston" dan menampilkan pita peringatan bahwa sortir
   otomatis pada line itu sedang berhenti.
7. Operator menekan "Tutup piston"; aplikasi menurunkan coil ke 0; ladder menutup piston dan line
   kembali mengikuti sortir kamera.

```diagram:piston-keadaan Keadaan piston manual per line dan jalur kembali ke tertutup
Tertutup --klik Buka--> Menunggu --DI=1--> Terbuka --klik Tutup--> Tertutup
Terbuka --E-stop--> Tertutup (tidak boleh buka sendiri saat E-stop dilepas)
```

### 5.3 Enam aturan ladder yang diminta

Keenam aturan berikut adalah inti permintaan kepada tim panel. Aturan nomor 3 adalah yang paling
penting.

| # | Aturan | Kalau tidak dipenuhi |
|---|---|---|
| 1 | **Membuka.** Coil manual berubah 0 → 1 **dan** kondisi aman terpenuhi (E-stop tidak aktif, motor tidak fault, HEARTBIT ON) → piston buka. Selama piston terbuka, pulse OK/NG line itu diabaikan | Piston terbuka saat kondisi tidak aman, atau kamera dan piston manual saling bertabrakan memerintah aktuator yang sama |
| 2 | **Menutup.** Coil kembali ke 0 → piston tutup, line kembali mengikuti sortir kamera | Piston tertinggal terbuka dan seluruh muatan line itu lolos tanpa sortir |
| 3 | **Tidak boleh membuka sendiri setelah pengaman trip.** E-stop ditekan saat piston terbuka → piston tutup. Setelah E-stop dilepas, piston **tetap tertutup** sampai ada perubahan 0 → 1 yang baru dari operator | **Melepas E-stop membuat piston bergerak sendiri.** Ini bahaya bagi orang yang sedang membereskan sangkutan — justru pekerjaan yang membuat E-stop ditekan |
| 4 | **Discrete input konfirmasi menunjukkan posisi sebenarnya**, memakai sensor posisi bila tersedia | Layar menampilkan piston terbuka padahal tidak, dan operator mengira muatan sedang lolos padahal sedang disortir |
| 5 | **Timer maksimum.** Piston terbuka melampaui batas waktu tertentu → tutup sendiri atau bunyikan alarm | Piston yang terlupakan membuat satu line kehilangan sortir selama sisa shift tanpa ada yang menyadarinya |
| 6 | **Buah tanpa sinyal = lolos.** Perlu ditegaskan sebagai perilaku default aktuator | Aturan buah internal di Bab 6 tidak bekerja, dan sebagian buah yang sinyalnya terbuang justru dibuang secara fisik |

Aturan 5 diajukan sebagai usulan; tim panel yang paling memahami batas waktu yang masuk akal bagi
aktuator di lapangan.

### 5.4 Yang dilakukan AutoGrade di sisinya

Bagian ini mendeskripsikan perilaku yang akan dibangun setelah alokasi disetujui, agar tim panel
mengetahui apa yang akan terlihat di bus.

- **Coil manual adalah level, bukan pulse.** Aplikasi menulisnya sekali saat permintaan berubah,
  lalu menahannya. Aplikasi tidak menulis ulang coil ini secara berkala, berbeda dengan HEARTBIT.
- **Rekonsiliasi dengan discrete input.** Kalau discrete input konfirmasi tetap menunjukkan
  tertutup sementara coil aplikasi masih 1 selama lebih dari ±2 detik, aplikasi menurunkan coilnya
  sendiri ke 0. Dengan begitu klik berikutnya dari operator menjadi perubahan 0 → 1 yang baru, dan
  aturan 3 tetap dapat bekerja. Tanpa penurunan itu, coil yang tertinggal di 1 membuat klik
  berikutnya tidak menghasilkan tepi apa pun.
- **Permintaan buka tidak bertahan melewati putusnya koneksi.** Lihat Bab 7.
- **Selama nomor coil belum diisi, fitur ini mati total.** Aplikasi dapat dipasang lebih dulu tanpa
  menyentuh satu bit tambahan pun, dan dinyalakan belakangan dengan mengisi nomor coil ketika
  ladder sudah siap.

## 6. Buah internal tidak dibuang

**Status bab: Di sisi PLC tidak ada yang berubah. Satu konfirmasi diperlukan.**

Sebagian truk yang membongkar di pabrik adalah truk internal, yaitu kebun milik sendiri. Untuk
truk semacam itu, buah yang dinilai REJ tidak perlu dikembalikan; buah tetap masuk ke ramp.

Aturan ini dijalankan **sepenuhnya di sisi AutoGrade**, dengan cara yang paling sederhana:
untuk janjang REJ milik truk internal, aplikasi **tidak mengirim pulse sama sekali**. Tidak ada
pulse NG, dan tidak ada pulse OK pengganti.

**Yang tidak berubah di sisi panel:**

- Tidak ada coil baru dan tidak ada discrete input baru untuk keperluan ini.
- Arti pulse NG tetap sama persis: buang.
- Arti pulse OK tetap sama persis: loloskan.
- Ladder tidak perlu mengetahui truk mana yang sedang membongkar, apalagi sumbernya. PLC memang
  tidak memiliki informasi itu.

**Satu hal yang diminta: konfirmasi bahwa buah yang lewat tanpa sinyal apa pun akan lolos.**
Seluruh aturan ini bertumpu pada perilaku itu. Kalau perilaku default aktuator ternyata membuang
buah yang tidak bersinyal, maka meniadakan pulse justru menghasilkan kebalikan dari yang
dikehendaki, dan pendekatan ini harus dirancang ulang memakai coil tambahan.

Konfirmasi yang sama juga menentukan nasib buah yang sinyalnya terbuang karena kepadatan (bagian
4.3), sehingga jawabannya berlaku untuk dua hal sekaligus. Butir ini tercatat di Bab 8 nomor 3.

Catatan bagi tim engineering: hasil penilaian tidak diubah. Janjang REJ tetap tercatat REJ pada
data dan foto di pabrik; yang tidak dikirim hanyalah sinyal ke PLC.

## 7. Perilaku saat gangguan

**Status bab: Baris coil 0–9 berjalan sekarang (v1.8.0). Baris piston manual adalah usulan.**

| Kejadian | Yang terjadi pada coil | Yang dilihat ladder |
|---|---|---|
| **Kabel LAN coupler dicabut** | Aplikasi tidak dapat menulis apa pun. Coupler menjalankan *fault action* miliknya dan me-reset output | Seluruh coil AutoGrade padam, termasuk HEARTBIT. Setelah kabel dipasang lagi, HEARTBIT dan coil ERROR **naik lagi sendiri** dalam ±1 detik tanpa restart |
| **PC mati atau kehilangan daya** | Tidak ada penulisan sama sekali; watchdog coupler kedaluwarsa | HEARTBIT padam. Cepat-lambatnya bergantung pada watchdog coupler — lihat Bab 8 nomor 5 |
| **Aplikasi berhenti atau di-restart** | Aplikasi menjalankan `deenergise()`: coil OK, NG, ERROR, dan HEARTBIT milik line itu ditulis 0 secara tegas sebelum koneksi ditutup | Tidak ada coil yang tertinggal ON. Ini penting karena peluang sebuah coil sedang ON saat perintah berhenti tiba kira-kira satu berbanding dua |
| **E-stop ditekan** | Tidak ada perubahan pada coil. Kamera **tetap menilai** dan pulse tetap dikirim | Ladder yang memegang interlock. Perilaku kamera saat E-stop adalah butir terbuka — Bab 8 nomor 7 |
| **Langganan lisensi habis** | Coil HEARTBIT dimatikan secara sengaja | Terlihat persis sama dengan PC mati. Disengaja: berhenti secara diam-diam lebih berbahaya. Yang membedakan hanya layar operator |
| **Koneksi putus saat piston terbuka** (usulan) | Permintaan buka dianggap batal dan **tidak** ditulis ulang setelah koneksi pulih | Piston tidak terbuka kembali dengan sendirinya. Operator harus menekan tombolnya lagi |

Dua perilaku di tabel itu berpasangan dan sengaja dibuat berbeda, sehingga perlu ditegaskan:

- **HEARTBIT dan coil ERROR ditulis ulang setiap detik.** Keduanya adalah pernyataan tentang
  keadaan sekarang, jadi keduanya harus dapat pulih sendiri setelah coupler me-reset output.
  Khusus coil ERROR, penegakan ulang berkala ini baru ditambahkan pada branch yang menghasilkan
  dokumen ini; sebelumnya coil ERROR hanya ditulis saat nilainya berubah, sehingga setelah LAN
  terputus dan tersambung kembali coil itu tetap 0 walaupun kameranya masih terputus. Artinya
  di bus, kedua coil tersebut sekarang akan terlihat ditulis berkala, bukan hanya sesekali.
- **Permintaan piston tidak pernah ditulis ulang.** Ini kebalikannya, dan juga disengaja. Perintah
  membuka adalah tindakan operator pada satu saat tertentu, bukan pernyataan tentang keadaan. Coil
  yang naik lagi sendiri setelah koneksi pulih berarti piston bergerak tanpa ada orang yang
  memintanya — persis yang dilarang aturan ladder nomor 3.

## 8. Yang ditunggu dari panel

**Status bab: Tujuh butir menunggu keputusan tim panel.**

| # | Yang ditunggu | Akibat kalau tidak beres |
|---|---|---|
| 1 | **Alokasi coil 10, 11, 12 dan discrete input 11, 12, 13** untuk piston manual | Fitur piston manual tidak dapat dinyalakan sama sekali. Aplikasi dapat dipasang, tetapi tombolnya mati dan tidak ada bit yang ditulis |
| 2 | **Jumlah piston per line, dan arti "buka" secara fisik** | Satu bit per line hanya cukup kalau "buka" berarti satu keadaan. Kalau satu line punya lebih dari satu piston yang berdiri sendiri, alokasi bitnya harus dirancang ulang sebelum ladder ditulis |
| 3 | **Konfirmasi: buah yang lewat tanpa sinyal akan lolos** | Aturan buah internal (Bab 6) menghasilkan kebalikan dari yang dikehendaki, dan setiap sinyal yang terbuang karena kepadatan berubah menjadi buah yang dibuang secara fisik |
| 4 | **Persetujuan enam aturan ladder (bagian 5.3)**, terutama aturan 3 | Tanpa aturan 3, melepas E-stop membuat piston bergerak sendiri — tepat saat ada orang yang membereskan sangkutan |
| 5 | **Watchdog coupler diturunkan dari 30 detik ke 2–3 detik** (permintaan lama) | PC yang mati membuat coil terakhir tertinggal sampai setengah menit. Cukup lama untuk menyortir banyak buah memakai keputusan yang sudah basi. Aplikasi melakukan polling tiap 200 ms, jadi 2–3 detik aman dari false trip |
| 6 | **E-stop dikabel ulang menjadi NC (normally closed)** (permintaan lama) | CT-122F low-active dan setelan coupler saat ini membuat **kabel putus terbaca persis sama dengan kondisi aman**. Kegagalan kabel jatuh ke sisi berbahaya, bukan sisi aman |
| 7 | **Alamat IP coupler dan NIC yang dipakainya** — usulan `192.168.100.50`, subnet `255.255.255.0` (permintaan lama) | **Paling menghambat.** Tanpa ini aplikasi tidak dapat tersambung sama sekali. Usulan dipilih agar tidak bentrok dengan tiga kamera (`.10`, `.11`, `.12`) maupun NIC komputer (`.100`); boleh diganti ke `.51`–`.99` asalkan tetap `192.168.100.x` |

Butir tambahan yang belum menjadi permintaan formal, tetapi jawabannya memengaruhi rancangan:
**apakah kamera seharusnya ikut berhenti menilai saat E-stop ditekan?** Saat ini tidak berhenti,
sehingga akan tercatat hasil penilaian pada saat line sedang berhenti darurat.

## 9. Urutan uji di lapangan

**Status bab: Langkah 1–12 (Bagian A) menguji yang berjalan sekarang (v1.8.0). Langkah 13–19
(Bagian B) baru dapat dijalankan setelah coil piston dialokasikan dan ladder-nya siap.**

Urutan ini disusun agar sumber setiap keanehan tetap terlihat: satu line dulu, satu perubahan
dalam satu waktu. Kalau waktu commissioning mepet, yang **tidak boleh dilewat** adalah langkah 3,
4, 8, dan 9.

**Bagian A — yang berjalan sekarang**

1. Isi alamat IP coupler pada konfigurasi aplikasi, lalu pastikan PC dapat menjangkaunya.
2. Jalankan **line 1 saja**; line 2 dan line 3 dibiarkan mati.
3. **Picu satu pulse, lalu pastikan bersama bahwa coil 0 di aplikasi benar-benar X0300 di PLC.**
   Beda satu alamat saja membuat CAM 1 OK jatuh di CAM 1 NG, dan kesalahan itu tidak terlihat dari
   layar mana pun.
4. **Ukur lebar pulse yang benar-benar sampai di PLC**, memakai osiloskop atau monitor bit GX
   Works. Angka ±205 ms harus dibuktikan, bukan dipercaya.
5. Periksa coil 9 (HEARTBIT PC) dalam keadaan ON. Hentikan proses line 1 → coil 9 padam. Hentikan
   line 2 atau line 3 → coil 9 **tetap ON**; memang begitu, karena hanya line 1 yang memegangnya.
6. Picu satu motor fault dari panel, lalu pastikan bit yang berubah di aplikasi adalah nomor motor
   yang sama.
7. Putuskan koneksi kamera line 1 (atau matikan kameranya), lalu pastikan coil 2 (CAM 1 ERROR)
   naik. Sambungkan kembali, dan pastikan coil itu turun.
8. **Cabut kabel E-stop**, lalu lihat apakah pembacaan aplikasi berubah. **Tidak berubah adalah
   bukti masalah polaritas** dari Bab 8 nomor 6 — jangan diterima hanya karena bitnya terbaca
   aman.
9. **Cabut kabel LAN coupler selama ±10 detik, lalu pasang kembali.** Yang harus terlihat: coil 9
   padam melalui *fault action* coupler, lalu **ON lagi dengan sendirinya** tanpa ada yang
   di-restart. Kalau coil 2 sedang menyala saat kabel dicabut, coil itu juga harus naik lagi
   sendiri dalam ±1 detik. Langkah ini sekaligus menguji penegakan ulang berkala dari Bab 7.
10. Restart proses line 1 saat pulse sedang berjalan — tidak boleh ada coil yang tertinggal ON.
11. Jalankan produksi sungguhan ±15 menit pada satu line, lalu baca jumlah sinyal terbuang dari
    layar diagnosa (Bab 10). Angka itu menjadi dasar menyetel ulang lebar pulse.
12. Baru nyalakan line 2 dan line 3, lalu ulangi langkah 3 untuk coil 3 dan coil 6.

**Bagian B — piston manual, setelah ladder siap**

13. Isi nomor coil dan discrete input piston pada konfigurasi aplikasi, lalu restart proses line.
14. Tekan "Buka piston" pada line 1 dari konsol. Yang harus terjadi berurutan: coil 10 naik ke 1,
    piston membuka, discrete input 11 naik, dan layar konsol berubah menjadi "Tutup piston".
15. Selama piston terbuka, jalankan buah melewati kamera. Pastikan pulse OK dan NG line itu
    **diabaikan** ladder dan tidak menggerakkan aktuator sortir.
16. Tekan "Tutup piston". Coil 10 turun ke 0, piston menutup, discrete input 11 turun, dan line
    kembali mengikuti sortir kamera.
17. **Uji E-stop saat piston sedang terbuka.** Buka piston line 1, lalu tekan E-stop. Piston harus
    menutup. Kemudian **lepaskan E-stop dan jangan menyentuh apa pun**: piston harus **tetap
    tertutup**. Kalau piston membuka sendiri saat E-stop dilepas, aturan ladder nomor 3 belum
    terpasang dan pengujian tidak boleh dilanjutkan sampai hal itu diperbaiki.
18. Uji penolakan: minta buka dalam kondisi yang membuat ladder menolak (misalnya motor fault
    aktif). Discrete input konfirmasi tetap 0, dan setelah ±2 detik aplikasi menurunkan coilnya
    sendiri. Sesudah kondisi normal kembali, klik berikutnya harus dapat membuka piston seperti
    biasa.
19. Ulangi langkah 14 sampai 17 untuk line 2 (coil 11, DI 12) dan line 3 (coil 12, DI 13).

## 10. Lampiran

**Status bab: Berjalan sekarang (v1.8.0), kecuali dua baris yang ditandai usulan.**

### 10.1 Daftar konfigurasi `PLC_*`

Seluruh setelan berikut dibaca aplikasi saat proses line dijalankan. Mengubahnya memerlukan
restart proses line yang bersangkutan.

| Nama | Nilai bawaan | Arti |
|---|---|---|
| `PLC_ENABLED` | `false` | Saklar fitur. Hanya PC pabrik yang benar-benar tersambung ke coupler yang menyalakannya |
| `PLC_HOST` | (kosong) | Alamat IP coupler ODOT. Kosong sementara fitur menyala → worker tidak dijalankan, dan peringatan ditulis di log |
| `PLC_PORT` | `502` | Port Modbus-TCP standar |
| `PLC_UNIT_ID` | `1` | Modbus unit / slave ID |
| `PLC_COIL_BASE` | `0` | Coil OK line ini; NG dan ERROR mengikuti sebagai `+1` dan `+2`. Literal per line: line 1 = `0`, line 2 = `3`, line 3 = `6` |
| `PLC_COIL_ALIVE` | (kosong) | Coil yang ditahan ON. Line 1 = `9` (HEARTBIT PC); line 2 dan line 3 kosong. Kosong berarti fitur alive mati |
| `PLC_ALIVE_TOGGLE_MS` | `0` | `0` berarti ON statis, sesuai skematik dan ladder yang berlaku ("coil OFF berarti PC mati"). Nilai lebih besar dari nol mengubahnya menjadi toggle, dan **hanya boleh dipakai bila ladder menghitung perubahan** |
| `PLC_PULSE_MS` | `200` | Lebar pulse ON satu keputusan. Wajib tidak lebih kecil dari `PLC_POLL_MS` |
| `PLC_PULSE_GAP_MS` | `100` | Jeda OFF wajib sebelum pulse berikutnya pada coil yang sama; dibulatkan ke atas menjadi satu tick |
| `PLC_QUEUE_MAX` | `1` | Jumlah pulse yang boleh terutang per coil. Penuh berarti dibuang dan dihitung, bukan ditunggu |
| `PLC_POLL_MS` | `200` | Interval putaran loop — sekaligus keepalive watchdog coupler **dan resolusi waktu seluruh angka di atas** |
| `PLC_DI_COUNT` | `16` | Jumlah discrete input yang dibaca setiap poll |
| `PLC_COIL_MANUAL` | (kosong) | **Usulan.** Coil piston manual line ini: line 1 = `10`, line 2 = `11`, line 3 = `12`. Kosong berarti fitur piston mati |
| `PLC_DI_MANUAL` | (kosong) | **Usulan.** Discrete input konfirmasi piston line ini: line 1 = `11`, line 2 = `12`, line 3 = `13`. Kosong berarti status yang ditampilkan adalah status yang diminta, ditandai belum dikonfirmasi PLC |

Satu aturan keras di antara angka-angka itu: **`PLC_PULSE_MS` tidak boleh lebih kecil dari
`PLC_POLL_MS`.** Pulse yang lebih pendek dari satu tick tidak dapat dihasilkan, karena ON dan
OFF-nya jatuh pada evaluasi yang sama dan PLC tidak pernah melihat tepi naiknya — buah lewat tanpa
sinyal, secara diam-diam. Kalau memang diperlukan pulse lebih sempit dari 200 ms, yang diturunkan
adalah `PLC_POLL_MS`, bukan hanya `PLC_PULSE_MS`.

### 10.2 Membaca layar diagnosa `GET /health/detail`

Angka-angka yang paling dibutuhkan saat commissioning dibaca dari satu alamat di PC pabrik. Untuk
line 1 (line 2 dan line 3 memakai port 8002 dan 8003):

```
curl -s localhost:8001/health/detail
```

Bagian `plc` pada jawabannya berisi:

| Field | Arti |
|---|---|
| `inputs` | Potret terakhir discrete input. Indeks 0–9 motor fault, indeks 10 E-stop |
| `dropped_pulses` | Jumlah sinyal yang dibuang karena antrean satu coil penuh |
| `dropped_submissions` | Jumlah keputusan yang dibuang sebelum sempat masuk ke penjadwal pulse |

Dua hal yang perlu diketahui saat membacanya:

- **`plc` bernilai kosong berarti fitur PLC sedang mati** atau worker belum berjalan. Itu keadaan
  normal di PC pengembangan, bukan kesalahan.
- **Kedua penghitung naik terus selama proses hidup** dan tidak pernah di-reset. Yang berarti
  adalah **selisihnya antara dua kali pembacaan**, bukan nilai mutlaknya. Angka yang terus
  bertambah saat belt berjalan menunjukkan kamera menghasilkan keputusan lebih cepat daripada yang
  muat di satu coil — itu plafon yang dijelaskan di bagian 4.3, bukan kerusakan.

### 10.3 Glosarium

| Istilah | Arti dalam dokumen ini |
|---|---|
| **Coil** | Bit keluaran yang dapat ditulis lewat Modbus. Di sistem ini, coil adalah jalur AutoGrade menuju PLC. Dinomori mulai dari 0 |
| **Discrete input** | Bit masukan yang hanya dapat dibaca lewat Modbus. Di sistem ini, jalur PLC menuju AutoGrade. Dinomori mulai dari 0 |
| **FC05** | Modbus function code 05, *write single coil*. Perintah yang dipakai AutoGrade untuk menulis satu coil |
| **FC02** | Modbus function code 02, *read discrete inputs*. Perintah yang dipakai AutoGrade untuk membaca blok masukan |
| **Tepi naik** | Perubahan sebuah bit dari 0 menjadi 1. Untuk coil OK dan NG, satu tepi naik berarti satu janjang — bukan lama ON-nya |
| **Level** | Bit yang mempertahankan nilainya selama suatu keadaan berlangsung, bukan berdenyut. Coil ERROR, HEARTBIT, dan coil piston manual berbentuk level |
| **Pulse** | Bit yang naik sesaat lalu turun kembali, dengan jeda wajib sebelum pulse berikutnya pada coil yang sama |
| **Watchdog** | Pengatur waktu di dalam coupler yang mengharapkan komunikasi datang secara teratur. Bila komunikasi berhenti melebihi batas waktunya, coupler menjalankan *fault action* |
| **Fault action** | Tindakan coupler ketika watchdog kedaluwarsa atau koneksi terputus — pada sistem ini, me-reset output sehingga seluruh coil padam |
| **Janjang** | Satu tandan buah segar kelapa sawit; satuan yang dinilai kamera. Satu janjang menghasilkan paling banyak satu pulse |
| **ACC / REJ** | Hasil penilaian kamera: diterima atau ditolak. ACC menghasilkan pulse OK, REJ menghasilkan pulse NG |
| **Line** | Satu conveyor beserta satu kamera dan satu proses aplikasi. Terdapat tiga line |
| **HEARTBIT** | Penulisan pada skematik untuk coil 9, yang menyatakan PC dalam keadaan hidup. Ejaan aslinya dipertahankan agar cocok dengan skematik dan ladder |

### 10.4 Riwayat dokumen

| Versi | Tanggal | Perubahan |
|---|---|---|
| 2.0 | 15 September 2026 | Penulisan ulang. Koreksi kapasitas coil menjadi ±2,5 pulse per detik (sebelumnya 3,3), penambahan usulan piston manual coil 10–12 dan discrete input 11–13, penambahan bab buah internal, serta pencatatan penegakan ulang berkala coil ERROR |
