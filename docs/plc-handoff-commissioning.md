---
judul: Panduan Integrasi AutoGrade ↔ PLC
subjudul: Spesifikasi sinyal coil dan discrete input coupler ODOT CN-8031 — alamat, bentuk, dan trigger ladder yang diminta, untuk commissioning.
label: Internal · Tim Engineering
versi: "3.0"
tanggal: 15 September 2026
klasifikasi: Internal — untuk tim panel dan tim engineering
pemilik: Tim Engineering AutoGrade
sorotan: Berjalan = Coil 0–9, DI 0–11; Siap di aplikasi = Piston manual coil 10–12, DI 12–14 — alokasi menunggu panel; Ditunggu dari panel = 7 butir
---

# Panduan Integrasi AutoGrade ↔ PLC

## 1. Ringkasan

**Status bab: Berjalan sekarang, plus piston manual — siap di aplikasi, alokasi menunggu panel.**

AutoGrade menilai mutu tandan buah segar dengan kamera di PC pabrik. Untuk setiap janjang,
aplikasi memutuskan diterima (ACC) atau ditolak (REJ) dan mengirim keputusan itu sebagai pulse ke
coil remote IO ODOT CN-8031.

**Fakta yang menentukan seluruh dokumen ini: AutoGrade tidak punya kabel ke aktuator mana pun.**
Output coupler ODOT masuk ke modul input PLC. Aplikasi hanya menaikkan dan menurunkan bit; yang
menggerakkan piston, memegang interlock E-stop, dan memutuskan kapan gerakan aman, selalu ladder
PLC.

| Bagian | Status |
|---|---|
| Coil 0–8: hasil grading tiga line (OK / NG / ERROR) | Berjalan |
| Coil 9: HEARTBIT PC ON | Berjalan |
| Discrete input 0–11: motor fault (11 motor) dan E-stop | Berjalan |
| Coil 10–12: piston manual per line | **Siap di aplikasi — alokasi menunggu panel** |
| Discrete input 12–14: konfirmasi piston terbuka | **Siap di aplikasi — alokasi menunggu panel** |

> **Piston manual sudah selesai di sisi aplikasi.** Yang belum beres bukan kode, tapi alokasi:
> selama coil 10, 11, 12 belum resmi disetujui panel, konfigurasi tetap kosong dan fitur ini mati
> total. Alamat di Bab 3 dan 4 adalah usulan kami, bukan yang sudah disepakati.

Yang diminta: persetujuan alokasi coil 10–12 dan DI 12–14, konfirmasi enam aturan ladder di Bab 5,
dan jawaban atas tujuh butir di Bab 8.

## 2. Sambungan

**Status bab: Berjalan sekarang.**

PC pabrik menjalankan tiga proses aplikasi terpisah, satu per line kamera, masing-masing dengan
koneksi Modbus-TCP sendiri ke coupler ODOT CN-8031.

```diagram:topologi Jalur sinyal dari tiga proses line di PC pabrik sampai ke ladder PLC
PC pabrik (3 proses line)  --Modbus-TCP-->  ODOT CN-8031  --kabel-->  PLC Mitsubishi
```

| Parameter | Nilai |
|---|---|
| Protokol | Modbus-TCP |
| Port | 502 |
| Unit / slave ID | 1 |
| Tulis coil | FC05 (write single coil) |
| Baca discrete input | FC02 (read discrete inputs) |
| Penomoran | Zero-based (sisi aplikasi); kolom alamat PLC = alamat GX Works |
| Interval poll | 200 ms |
| Timeout socket | 1 detik |
| Koneksi simultan | 3 (satu per proses line); coupler menerima maksimum 5 client |

Setiap proses hanya menyentuh coil miliknya: line 1 = coil 0, 1, 2, 9; line 2 = coil 3, 4, 5;
line 3 = coil 6, 7, 8. Discrete input dibaca ketiga proses sekaligus — motor fault dan E-stop
adalah status bersama conveyor, bukan status per line. Aplikasi tidak pernah membaca balik coil
yang ditulisnya sendiri, dan tidak pernah menulis ke sisi discrete input.

Perangkat keras (part number lengkap di Lampiran 10.1): pasangan sink/source sudah diperiksa
cocok tanpa relay perantara — CT-222F source/PNP menuju modul input Mitsubishi dengan COM di 0V,
dan modul output Mitsubishi sink dengan COM di 0V menuju CT-122F yang low-active.

## 3. Sinyal yang dikirim AutoGrade (coil)

**Status bab: Coil 0–9 berjalan sekarang. Coil 10–12 siap di aplikasi, alokasi menunggu panel.**

Tabel ini adalah bagian paling penting dalam dokumen. Satu angka yang keliru berarti sinyal CAM 1
OK mendarat di alamat CAM 1 NG, dan buah yang layak dibuang.

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
| **10** | **X030A** | **LINE 1: piston manual buka** | **level, 1 = minta buka** | **line 1** | **Siap, menunggu alokasi** |
| **11** | **X030B** | **LINE 2: piston manual buka** | **level, 1 = minta buka** | **line 2** | **Siap, menunggu alokasi** |
| **12** | **X030C** | **LINE 3: piston manual buka** | **level, 1 = minta buka** | **line 3** | **Siap, menunggu alokasi** |
| 13–15 | X030D–X030F | SPARE, tidak disentuh aplikasi | — | — | — |

<!-- plc-map: coil_base=0,3,6; coil_alive=9; coil_manual=10,11,12; di_manual=12,13,14 -->

Coil 10–15 sebelumnya disepakati sebagai SPARE. Permintaan sekarang memindahkan 10, 11, 12 menjadi
piston manual, menyisakan 13–15 sebagai spare. Aplikasi sudah siap menulis ketiganya; yang menunggu
tinggal persetujuan panel atas pemindahan ini. Konsekuensi yang diterima sadar: kalau proses satu
line berhenti sendirian, PLC tidak melihatnya — coil CAM_N_ERROR line itu justru tidak menyala,
karena yang seharusnya menulisnya adalah proses yang berhenti. Menutup lubang itu perlu coil alive
tersendiri per line, dan itu tidak diminta di sini agar sisa spare tidak habis sekaligus.

### 3.1 OK / NG — trigger: tepi naik

- Pulse. Satu tepi naik (0→1) = satu janjang. ON 200 ms, lalu OFF 200 ms sebelum pulse berikutnya
  pada coil yang sama — keduanya kelipatan tick poll 200 ms, jadi jeda 100 ms yang disetel
  dibulatkan ke atas menjadi satu tick penuh. Kapasitas maksimum ≈2,5 tepi per detik per coil —
  bukan 3,3. Di lapangan angkanya bisa bergeser beberapa milidetik mengikuti jitter loop.
- **Kelebihan dibuang, bukan diantrekan.** Kamera dapat menghasilkan hingga ≈10 keputusan/detik/line,
  jauh di atas kapasitas satu coil. Kelebihan dibuang dengan sengaja — mengantrekan membuat sinyal
  terlambat menempel pada janjang yang salah. Ladder **harus menghitung tepi naik, bukan mengukur
  lama ON**: lebar pulse tetap dan tidak membawa arti tambahan.

### 3.2 ERROR — trigger: level

Level, bukan pulse. ON selama kamera line terputus atau health check gagal; 0 selama sehat.
Ditulis ulang setiap detik agar naik lagi sendiri setelah *fault action* coupler menzerokan output
(mis. gangguan LAN). Tandan yang dibuang karena kepadatan (3.1) **tidak** menaikkan ERROR — itu
keadaan normal saat line bekerja penuh, bukan kerusakan.

### 3.3 HEARTBIT (coil 9) — trigger: level

Level, ON terus, ditulis ulang setiap detik oleh **proses line 1 saja**. **0 berarti PC berhenti
ATAU lisensi habis** — sengaja tidak dapat dibedakan dari sisi PLC. Berhenti diam-diam lebih
berbahaya daripada ambigu: PLC harus tetap mengira ada masalah, bukan mengira semuanya normal
sementara buah lewat tanpa disortir.

### 3.4 Piston manual (coil 10–12) — siap di aplikasi, alokasi menunggu panel

Level, 1 = permintaan buka. Ditulis sekali saat permintaan berubah, lalu ditahan — **tidak**
ditulis ulang berkala seperti HEARTBIT, karena ini tindakan operator pada satu saat, bukan
pernyataan keadaan. Kalau DI konfirmasi tetap tertutup sementara coil masih 1 lebih dari ±2 detik,
aplikasi menurunkan coilnya sendiri ke 0, supaya klik berikutnya menjadi tepi 0→1 baru (aturan 3 di
Bab 5 tetap berlaku). Permintaan buka **tidak bertahan** melewati putusnya koneksi (Bab 7), dan
sebuah write ON yang gagal langsung membatalkan permintaan alih-alih diulang. Selama nomor coil
kosong di konfigurasi, fitur ini mati total — itu satu-satunya yang masih menunggu panel.

## 4. Sinyal yang dibaca AutoGrade (discrete input)

**Status bab: DI 0–11 berjalan sekarang. DI 12–14 siap di aplikasi, alokasi menunggu panel.**

| DI | Alamat PLC | Arti | Status |
|---|---|---|---|
| 0–10 | Y0310–Y031A | MOTOR 1–11 FAULT | Berjalan |
| 11 | Y031B | EMERGENCY STOP | Berjalan |
| **12** | **Y031C** | **LINE 1: piston terbuka (konfirmasi PLC)** | **Siap, menunggu alokasi** |
| **13** | **Y031D** | **LINE 2: piston terbuka (konfirmasi PLC)** | **Siap, menunggu alokasi** |
| **14** | **Y031E** | **LINE 3: piston terbuka (konfirmasi PLC)** | **Siap, menunggu alokasi** |
| 15 | Y031F | SPARE | — |

> **Digeser satu 15 September 2026 atas permintaan tim panel: motor jadi 11, bukan 10.**
> Sebelumnya motor menempati DI 0–9 dan E-stop DI 10. Motor ke-11 mengambil DI 10, jadi E-stop
> dan ketiga konfirmasi piston bergeser satu ke atas. **Sisi coil tidak ikut bergeser** — jumlah
> motor tidak menyentuh apa pun yang ditulis AutoGrade.

Ketiga proses line membaca blok 16 discrete input yang sama pada setiap poll. Aplikasi sudah
menafsirkan DI 12–14 sebagai konfirmasi piston; yang menunggu tinggal alokasi resmi dari panel.

Setelah pergeseran ini **sisa spare tinggal satu (DI 15)**. Motor ke-12 tidak akan muat tanpa
menambah blok discrete input, jadi kalau jumlah motor masih mungkin bertambah, itu perlu
dibicarakan sekarang, bukan saat commissioning.

## 5. Piston manual (siap di aplikasi, alokasi menunggu panel)

**Status bab: Tombol dan logikanya sudah ada di aplikasi. Yang menunggu panel: alokasi coil/DI
dan persetujuan enam aturan ladder di bawah.**

Sudah ada: satu tombol per line di konsol yang menahan piston terbuka sampai operator menutupnya.
AutoGrade hanya menaikkan satu bit permintaan — seluruh gerakan, interlock, dan keselamatan tetap
di ladder.

Alur: operator menekan "Buka piston" → proses line menaikkan coil manual 0→1 dan menahannya →
ladder memeriksa kondisi aman lalu membuka piston → ladder menaikkan DI konfirmasi → konsol
menampilkan "Tutup piston" → operator menekan "Tutup piston" → coil turun ke 0 → ladder menutup
piston, line kembali mengikuti sortir kamera.

```diagram:piston-keadaan Keadaan piston manual per line dan jalur kembali ke tertutup
Tertutup --klik Buka--> Menunggu --DI=1--> Terbuka --klik Tutup--> Tertutup
Terbuka --E-stop--> Tertutup (tidak boleh buka sendiri saat E-stop dilepas)
```

**Enam aturan ladder yang diminta.** Aturan 3 adalah yang paling penting — aturan keselamatan.

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

## 6. Buah internal tidak dibuang

**Status bab: Selesai di aplikasi. Di sisi PLC tidak ada yang berubah — satu konfirmasi diperlukan.**

Untuk truk internal (kebun sendiri), janjang REJ **tidak mengirim pulse sama sekali** — tidak ada
pulse NG, tidak ada pulse OK pengganti. Tidak ada coil baru, tidak ada DI baru; arti pulse NG
(buang) dan OK (loloskan) tetap sama, dan ladder tidak perlu tahu truk mana yang sedang membongkar.

**Satu konfirmasi diminta: buah yang lewat tanpa sinyal apa pun akan lolos.** Kalau perilaku
default aktuator ternyata membuang buah tanpa sinyal, pendekatan ini menghasilkan kebalikan dari
yang dikehendaki. Konfirmasi yang sama berlaku untuk buah yang sinyalnya terbuang karena kepadatan
(3.1). Butir ini ada di Bab 8 nomor 3.

## 7. Perilaku saat gangguan

**Status bab: Baris coil 0–9 berjalan sekarang. Baris piston manual siap di aplikasi, menunggu
alokasi panel.**

| Kejadian | Yang terjadi pada coil | Yang dilihat ladder |
|---|---|---|
| **Kabel LAN coupler dicabut** | Aplikasi tidak dapat menulis apa pun. Coupler menjalankan *fault action* dan me-reset output | Seluruh coil AutoGrade padam, termasuk HEARTBIT. Setelah kabel dipasang lagi, HEARTBIT dan coil ERROR **naik lagi sendiri** dalam ±1 detik tanpa restart |
| **PC mati atau kehilangan daya** | Tidak ada penulisan sama sekali; watchdog coupler kedaluwarsa | HEARTBIT padam. Cepat-lambatnya bergantung pada watchdog coupler — lihat Bab 8 nomor 5 |
| **Aplikasi berhenti atau di-restart** | Aplikasi menjalankan `deenergise()`: coil OK, NG, ERROR, HEARTBIT, dan piston manual (kalau nomornya diisi) ditulis 0 tegas sebelum koneksi ditutup | Tidak ada coil yang tertinggal ON |
| **E-stop ditekan** | Tidak ada perubahan pada coil. Kamera **tetap menilai** dan pulse tetap dikirim | Ladder yang memegang interlock. Perilaku kamera saat E-stop adalah butir terbuka — lihat butir tambahan di akhir Bab 8 |
| **Langganan lisensi habis** | Coil HEARTBIT dimatikan sengaja | Terlihat persis sama dengan PC mati. Yang membedakan hanya layar operator |
| **Koneksi putus saat piston terbuka** | Permintaan buka dianggap batal dan **tidak** ditulis ulang setelah koneksi pulih | Piston tidak terbuka kembali sendiri. Operator harus menekan tombolnya lagi |

HEARTBIT dan coil ERROR ditulis ulang tiap detik karena keduanya pernyataan tentang keadaan
sekarang, jadi harus pulih sendiri setelah coupler me-reset output. Permintaan piston manual justru
**tidak pernah** ditulis ulang — itu tindakan operator pada satu saat, bukan pernyataan keadaan;
kalau ditulis ulang otomatis, piston bisa bergerak sendiri setelah koneksi pulih, persis yang
dilarang aturan ladder nomor 3.

## 8. Yang ditunggu dari panel

**Status bab: Tujuh butir menunggu keputusan tim panel.**

| # | Yang ditunggu | Akibat kalau tidak beres |
|---|---|---|
| 1 | **Alokasi coil 10, 11, 12 dan discrete input 11, 12, 13** untuk piston manual | Fitur piston manual tidak dapat dinyalakan sama sekali |
| 2 | **Jumlah piston per line, dan arti "buka" secara fisik** | Satu bit per line hanya cukup kalau "buka" berarti satu keadaan; lebih dari satu piston berdiri sendiri per line berarti alokasi bit harus dirancang ulang |
| 3 | **Konfirmasi: buah yang lewat tanpa sinyal akan lolos** | Aturan buah internal (Bab 6) menghasilkan kebalikan dari yang dikehendaki |
| 4 | **Persetujuan enam aturan ladder (Bab 5)**, terutama aturan 3 | Tanpa aturan 3, melepas E-stop membuat piston bergerak sendiri |
| 5 | **Watchdog coupler diturunkan dari 30 detik ke 2–3 detik** (permintaan lama) | PC yang mati membuat coil terakhir tertinggal sampai setengah menit — cukup lama untuk menyortir banyak buah dengan keputusan basi. Aplikasi poll tiap 200 ms, jadi 2–3 detik aman dari false trip. Timeout socket Modbus aplikasi 1 detik (Bab 2); satu round-trip yang menggantung dapat merenggangkan jeda antar-tulis mendekati satu detik — tim panel yang menilai margin 2–3 detik dengan angka itu |
| 6 | **E-stop dikabel ulang menjadi NC (normally closed)** (permintaan lama) | CT-122F low-active dan setelan coupler saat ini membuat **kabel putus terbaca persis sama dengan kondisi aman** |
| 7 | **Alamat IP coupler dan NIC yang dipakainya** — usulan `192.168.100.50`, subnet `255.255.255.0` (permintaan lama) | **Paling menghambat.** Tanpa ini aplikasi tidak dapat tersambung sama sekali. Usulan dipilih agar tidak bentrok dengan tiga kamera (`.10`–`.12`) maupun NIC komputer (`.100`); boleh diganti ke `.51`–`.99` asalkan tetap `192.168.100.x` |

Butir tambahan, belum formal: **apakah kamera seharusnya ikut berhenti menilai saat E-stop
ditekan?** Saat ini tidak berhenti — hasil penilaian tetap tercatat saat line sedang berhenti
darurat.

## 9. Urutan uji di lapangan

**Status bab: Langkah 1–12 (Bagian A) menguji yang berjalan sekarang. Langkah 13–19 (Bagian B)
menguji piston manual — siap dijalankan begitu coil dialokasikan dan ladder-nya siap; aplikasi
sudah menunggu di sisi ini.**

Satu line dulu, satu perubahan dalam satu waktu. **Tidak boleh dilewat: langkah 3, 4, 8, dan 9.**

**Bagian A — yang berjalan sekarang**

1. Isi alamat IP coupler pada konfigurasi aplikasi, lalu pastikan PC dapat menjangkaunya.
2. Jalankan **line 1 saja**; line 2 dan line 3 dibiarkan mati.
3. **Picu satu pulse, lalu pastikan bersama bahwa coil 0 di aplikasi benar-benar X0300 di PLC.**
   Beda satu alamat saja membuat CAM 1 OK jatuh di CAM 1 NG, tanpa terlihat dari layar mana pun.
4. **Ukur lebar pulse yang benar-benar sampai di PLC**, memakai osiloskop atau monitor bit GX
   Works. Angka 200 ms harus dibuktikan, bukan dipercaya.
5. Periksa coil 9 (HEARTBIT PC) ON. Hentikan proses line 1 → coil 9 padam. Hentikan line 2 atau
   line 3 → coil 9 **tetap ON**; memang begitu, hanya line 1 yang memegangnya.
6. Picu satu motor fault dari panel, pastikan bit yang berubah di aplikasi adalah nomor motor yang
   sama.
7. Putuskan koneksi kamera line 1, pastikan coil 2 (CAM 1 ERROR) naik. Sambungkan kembali, pastikan
   coil itu turun.
8. **Cabut kabel E-stop**, lihat apakah pembacaan aplikasi berubah. **Tidak berubah adalah bukti
   masalah polaritas** dari Bab 8 nomor 6 — jangan diterima hanya karena bitnya terbaca aman.
9. **Cabut kabel LAN coupler ±10 detik, lalu pasang kembali.** Coil 9 padam via *fault action*
   coupler, lalu **ON lagi sendiri** tanpa restart. Kalau coil 2 sedang menyala saat kabel dicabut,
   coil itu juga naik lagi sendiri dalam ±1 detik. Ini sekaligus menguji penegakan ulang berkala
   dari Bab 7.
10. Restart proses line 1 saat pulse sedang berjalan — tidak boleh ada coil yang tertinggal ON.
11. Jalankan produksi sungguhan ±15 menit pada satu line, baca jumlah sinyal terbuang dari layar
    diagnosa (Bab 10.2). Angka itu menjadi dasar menyetel ulang lebar pulse.
12. Baru nyalakan line 2 dan line 3, ulangi langkah 3 untuk coil 3 dan coil 6.

**Bagian B — piston manual, setelah coil dialokasikan dan ladder siap**

13. Isi nomor coil dan discrete input piston pada konfigurasi aplikasi, lalu restart proses line.
14. Tekan "Buka piston" pada line 1 dari konsol. Berurutan: coil 10 naik ke 1, piston membuka, DI
    12 naik, layar konsol berubah menjadi "Tutup piston".
15. Selama piston terbuka, jalankan buah melewati kamera. Pulse OK dan NG line itu harus
    **diabaikan** ladder dan tidak menggerakkan aktuator sortir.
16. Tekan "Tutup piston". Coil 10 turun ke 0, piston menutup, DI 12 turun, line kembali mengikuti
    sortir kamera.
17. **Uji E-stop saat piston terbuka.** Buka piston line 1, tekan E-stop — piston harus menutup.
    Lepaskan E-stop dan jangan menyentuh apa pun: piston harus **tetap tertutup**. Kalau piston
    membuka sendiri saat E-stop dilepas, aturan ladder nomor 3 belum terpasang dan **pengujian
    tidak boleh dilanjutkan** sampai diperbaiki.
18. Uji penolakan: minta buka dalam kondisi yang membuat ladder menolak (mis. motor fault aktif).
    DI konfirmasi tetap 0, dan setelah ±2 detik aplikasi menurunkan coilnya sendiri. Setelah kondisi
    normal kembali, klik berikutnya harus membuka piston seperti biasa.
19. Ulangi langkah 14–17 untuk line 2 (coil 11, DI 13) dan line 3 (coil 12, DI 14).

## 10. Lampiran

**Status bab: Berjalan sekarang.**

### 10.1 Perangkat keras

| Part number | Peran |
|---|---|
| ODOT CN-8031 | Coupler remote IO; Modbus-TCP port 502 |
| CT-222F | Modul output, source/PNP, high-active |
| CT-122F | Modul input, NPN, low-active |
| CT-5801 | Modul catu daya panel |
| AJ65SBTB1-16D1 | Modul input Mitsubishi 16 titik — menerima dari CT-222F |
| AJ65SBTB1-16T1 | Modul output Mitsubishi 16 titik — mengirim ke CT-122F |

### 10.2 Layar diagnosa `GET /health/detail`

Line 1: `curl -s localhost:8001/health/detail` (line 2 port 8002, line 3 port 8003). Bagian `plc`
pada jawabannya:

| Field | Arti |
|---|---|
| `dropped_pulses` | Sinyal dibuang karena antrean satu coil penuh |
| `dropped_submissions` | Keputusan dibuang sebelum sempat masuk penjadwal pulse |

`plc` kosong berarti fitur PLC mati. Kedua angka kumulatif sejak proses start — yang berarti
selisih dua kali baca, bukan nilai mutlaknya.

### 10.3 Glosarium

| Istilah | Arti dalam dokumen ini |
|---|---|
| **Coil** | Bit keluaran yang dapat ditulis lewat Modbus. Jalur AutoGrade menuju PLC. Dinomori mulai dari 0 |
| **Discrete input** | Bit masukan yang hanya dapat dibaca lewat Modbus. Jalur PLC menuju AutoGrade. Dinomori mulai dari 0 |
| **FC05** | Modbus function code 05, *write single coil* |
| **FC02** | Modbus function code 02, *read discrete inputs* |
| **Tepi naik** | Perubahan bit dari 0 menjadi 1. Untuk coil OK dan NG, satu tepi naik = satu janjang — bukan lama ON-nya |
| **Level** | Bit yang mempertahankan nilainya selama suatu keadaan berlangsung, bukan berdenyut. Coil ERROR, HEARTBIT, dan coil piston manual berbentuk level |
| **Pulse** | Bit yang naik sesaat lalu turun kembali, dengan jeda wajib sebelum pulse berikutnya pada coil yang sama |
| **Watchdog** | Pengatur waktu di dalam coupler yang mengharapkan komunikasi datang teratur. Komunikasi berhenti melebihi batas waktu → coupler menjalankan *fault action* |
| **Fault action** | Tindakan coupler saat watchdog kedaluwarsa atau koneksi terputus — pada sistem ini, me-reset output sehingga seluruh coil padam |
| **Janjang** | Satu tandan buah segar kelapa sawit; satuan yang dinilai kamera. Satu janjang menghasilkan paling banyak satu pulse |
| **ACC / REJ** | Hasil penilaian kamera: diterima atau ditolak. ACC menghasilkan pulse OK, REJ menghasilkan pulse NG |
| **Line** | Satu conveyor beserta satu kamera dan satu proses aplikasi. Terdapat tiga line |
| **HEARTBIT** | Penulisan pada skematik untuk coil 9, menyatakan PC dalam keadaan hidup. Ejaan aslinya dipertahankan agar cocok dengan skematik dan ladder |
