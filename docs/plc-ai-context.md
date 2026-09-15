# Context: AutoGrade ↔ PLC (ODOT CN-8031)

Versi 1.0 · 15 September 2026 · sumber: Tim Engineering AutoGrade

## Aturan untuk AI yang membaca dokumen ini

1. Dokumen ini satu-satunya sumber untuk alamat coil, discrete input, dan bentuk sinyal.
2. Dilarang mengarang atau menebak alamat. Kalau sebuah alamat tidak tertulis di sini, jawab "tidak ada di dokumen".
3. Bedakan yang **sudah berjalan** dari yang **masih usulan**; keduanya ditandai di tabel.
4. Kalau ditanya hal di luar dokumen (mekanik piston, merek aktuator, ladder yang sudah ada), jawab tidak tahu dan sarankan bertanya ke tim panel.

## Latar singkat

AutoGrade adalah sistem penilaian mutu tandan buah segar (kelapa sawit) berbasis kamera yang
terpasang di PC pabrik. Untuk setiap tandan yang lewat di bawah kamera, aplikasi memutuskan
diterima (ACC) atau ditolak (REJ), lalu mengirim keputusan itu ke PLC sebagai bit pada coil
remote IO ODOT CN-8031. **Aplikasi tidak punya kabel ke aktuator mana pun** — yang dapat
dilakukan hanya menaikkan dan menurunkan bit. Yang menggerakkan piston, memegang interlock
E-stop, dan memutuskan kapan sebuah gerakan aman, selalu ladder PLC.

Ada tiga proses aplikasi berjalan berdampingan, satu per line kamera (line 1, 2, 3), masing-masing
dengan koneksi Modbus-TCP sendiri ke coupler ODOT CN-8031 di port 502. Aplikasi menulis coil
dengan Modbus function code 05 (FC05) dan membaca discrete input dengan function code 02 (FC02).
Nomor coil dan discrete input di dokumen ini adalah **zero-based** (penomoran Modbus sisi
aplikasi); kolom alamat PLC adalah alamat yang dilihat dari sisi GX Works.

## Peta coil (AutoGrade menulis, FC05, mulai dari 0)

| Coil | Alamat PLC | Arti | Bentuk | Status |
|---|---|---|---|---|
| 0 / 1 / 2 | X0300 / X0301 / X0302 | CAM 1 OK / NG / ERROR | pulse, pulse, level | berjalan |
| 3 / 4 / 5 | X0303 / X0304 / X0305 | CAM 2 OK / NG / ERROR | pulse, pulse, level | berjalan |
| 6 / 7 / 8 | X0306 / X0307 / X0308 | CAM 3 OK / NG / ERROR | pulse, pulse, level | berjalan |
| 9 | X0309 | HEARTBIT PC ON (ditulis line 1) | level, ON terus | berjalan |
| 10 / 11 / 12 | X030A / X030B / X030C | LINE 1 / 2 / 3 piston manual buka | level, 1 = minta buka | usulan |
| 13–15 | X030D–X030F | SPARE, tidak disentuh aplikasi | — | — |

<!-- plc-map: coil_base=0,3,6; coil_alive=9; coil_manual=; di_manual= -->

Catatan penting: coil 10, 11, dan 12 adalah **usulan** yang belum disetujui tim panel. Aplikasi
yang berjalan hari ini **tidak** menulis ketiganya. Coil 13, 14, dan 15 tetap SPARE.

## Peta discrete input (AutoGrade membaca, FC02)

| DI | Alamat PLC | Arti | Status |
|---|---|---|---|
| 0–9 | Y0310–Y0319 | MOTOR 1–10 FAULT | berjalan |
| 10 | Y031A | EMERGENCY STOP | berjalan |
| 11 | Y031B | LINE 1: piston terbuka (konfirmasi PLC) | usulan |
| 12 | Y031C | LINE 2: piston terbuka (konfirmasi PLC) | usulan |
| 13 | Y031D | LINE 3: piston terbuka (konfirmasi PLC) | usulan |
| 14–15 | Y031E–Y031F | SPARE | — |

Aplikasi membaca 16 discrete input sekaligus setiap poll (setelan `PLC_DI_COUNT=16`), jadi DI 11,
12, dan 13 sudah ikut terbaca hari ini — yang belum ada adalah **penafsirannya**. Sampai coil
manual dan ladder terkait disetujui dan dipasang, bit-bit itu tidak dipakai aplikasi untuk apa pun.

## Bentuk sinyal

| Coil | Bentuk | Arti bagi ladder | Status |
|---|---|---|---|
| OK dan NG (coil 0/1, 3/4, 6/7) | Pulse | Satu tepi naik = satu tandan. Yang dihitung ladder adalah tepi naik, bukan lama ON | berjalan |
| ERROR (coil 2, 5, 8) | Level | 1 selama line tidak sehat (kamera terputus / health check gagal), 0 selama sehat. Dievaluasi ulang tiap detik, sehingga naik lagi sendiri setelah gangguan LAN | berjalan |
| HEARTBIT PC (coil 9) | Level, ON terus | 1 selama aplikasi hidup dan berlisensi. 0 berarti PC berhenti **atau** lisensi habis — dua keadaan itu terlihat sama di sisi PLC, sengaja | berjalan |
| Piston manual (coil 10/11/12) | Level | Ditulis sekali saat permintaan berubah, lalu ditahan. Tidak ditulis ulang secara berkala seperti HEARTBIT | usulan |

**Coil ERROR bukan tanda kelebihan beban.** Tandan yang dibuang karena datang terlalu cepat (lihat
bagian kepadatan sinyal di bawah) **tidak** menaikkan coil ERROR — itu keadaan normal saat line
bekerja penuh, bukan kerusakan.

### Angka waktu (berjalan sekarang)

| Besaran | Nilai | Catatan |
|---|---|---|
| Satu tick evaluasi (`PLC_POLL_MS`) | 200 ms | Sekaligus keepalive watchdog coupler dan resolusi waktu seluruh angka di bawah |
| Lebar pulse ON (`PLC_PULSE_MS`) | ≈205 ms | Satu tick |
| Jeda OFF wajib (`PLC_PULSE_GAP_MS`) | ≈205 ms | Jeda 100 ms dibulatkan ke atas menjadi satu tick penuh |
| Satu siklus pulse (ON + jeda) | ≈410 ms | Dua tick |
| Kapasitas satu coil | ≈2,5 pulse per detik | 1 ÷ (2 × 0,205 detik). Ini angka yang berlaku, bukan 3,3 |
| Timeout koneksi socket Modbus | 1 detik | Batas tunggu aplikasi untuk satu operasi baca/tulis ke coupler |

Kamera dapat menghasilkan sampai sekitar 10 keputusan grading per detik per line, jauh di atas
kapasitas satu coil (≈2,5 pulse/detik). Kebijakannya: **buang dan hitung, tidak pernah menunda**.
Kelebihan keputusan dibuang dan dicatat sebagai angka diagnostik (`dropped_pulses`,
`dropped_submissions`); aplikasi tidak menumpuk antrean, karena sinyal yang ditahan akan sampai
terlambat dan menempel pada tandan yang salah. Antrean per coil dibatasi satu (`PLC_QUEUE_MAX=1`).

## Perilaku saat gangguan

| Kejadian | Yang terjadi pada coil | Status |
|---|---|---|
| Kabel LAN coupler dicabut | Seluruh coil AutoGrade padam (termasuk HEARTBIT) lewat *fault action* coupler. Setelah kabel dipasang lagi, HEARTBIT dan coil ERROR naik lagi sendiri dalam ±1 detik, tanpa restart | berjalan |
| PC mati / kehilangan daya | Tidak ada penulisan sama sekali; HEARTBIT padam setelah watchdog coupler kedaluwarsa | berjalan |
| Aplikasi berhenti / di-restart | Aplikasi menulis 0 secara tegas ke coil OK, NG, ERROR, dan HEARTBIT line itu sebelum menutup koneksi — tidak ada coil yang tertinggal ON | berjalan |
| E-stop ditekan | Tidak ada perubahan pada coil manapun. Kamera tetap menilai dan pulse tetap dikirim; interlock sepenuhnya di ladder | berjalan |
| Langganan lisensi habis | Coil HEARTBIT dimatikan sengaja — terlihat persis sama dengan PC mati di sisi PLC | berjalan |
| Koneksi putus saat piston terbuka | Permintaan buka dianggap batal dan **tidak** ditulis ulang setelah koneksi pulih; operator harus menekan tombolnya lagi | usulan |

Dua hal yang sengaja dibuat berbeda: HEARTBIT dan coil ERROR ditulis ulang setiap detik karena
keduanya pernyataan tentang keadaan sekarang (harus bisa pulih sendiri). Permintaan piston manual
justru **tidak pernah** ditulis ulang, karena itu tindakan operator pada satu saat tertentu, bukan
pernyataan keadaan — kalau ditulis ulang otomatis, piston bisa bergerak sendiri tanpa ada yang
memintanya setelah koneksi pulih.

## Piston manual — enam aturan ladder yang diminta (usulan)

Belum ada satu baris pun dari ini di aplikasi yang terpasang. Alurnya: operator menekan "Buka
piston" di layar konsol → aplikasi menaikkan coil manual line itu dari 0 ke 1 dan menahannya →
ladder memeriksa kondisi aman lalu membuka piston → ladder menaikkan discrete input konfirmasi →
operator menekan "Tutup piston" → aplikasi menurunkan coil ke 0 → ladder menutup piston.

| # | Aturan | Kalau tidak dipenuhi |
|---|---|---|
| 1 | Membuka: coil manual 0→1 **dan** kondisi aman (E-stop tidak aktif, motor tidak fault, HEARTBIT ON) → piston buka. Selama piston terbuka, pulse OK/NG line itu diabaikan | Piston terbuka saat tidak aman, atau kamera dan piston manual bertabrakan memerintah aktuator yang sama |
| 2 | Menutup: coil kembali ke 0 → piston tutup, line kembali mengikuti sortir kamera | Piston tertinggal terbuka, seluruh muatan line itu lolos tanpa sortir |
| 3 (**paling penting**) | Tidak boleh membuka sendiri setelah pengaman trip: E-stop ditekan saat piston terbuka → piston tutup. Setelah E-stop dilepas, piston **tetap tertutup** sampai ada perubahan 0→1 baru dari operator | Melepas E-stop membuat piston bergerak sendiri — bahaya bagi orang yang sedang membereskan sangkutan |
| 4 | Discrete input konfirmasi menunjukkan posisi sebenarnya, memakai sensor posisi bila tersedia | Layar menampilkan piston terbuka padahal tidak |
| 5 | Timer maksimum: piston terbuka melampaui batas waktu tertentu → tutup sendiri atau bunyikan alarm | Piston yang terlupakan membuat satu line kehilangan sortir sepanjang sisa shift |
| 6 | Tandan tanpa sinyal = lolos (perilaku default aktuator) | Aturan tandan internal tidak bekerja, dan tandan yang sinyalnya terbuang karena kepadatan justru dibuang secara fisik |

Rekonsiliasi sisi aplikasi (usulan): kalau discrete input konfirmasi tetap menunjukkan tertutup
sementara coil aplikasi masih 1 selama lebih dari ≈2 detik, aplikasi menurunkan coilnya sendiri ke
0, supaya klik berikutnya operator menjadi tepi 0→1 yang baru dan aturan 3 tetap berlaku.

## Tandan internal tidak dibuang (tidak mengubah apa pun di panel)

Untuk tandan REJ milik truk internal (kebun milik sendiri), aplikasi **tidak mengirim pulse sama
sekali** — tidak ada pulse NG, dan tidak ada pulse OK pengganti. Ini murni perilaku sisi aplikasi:
tidak ada coil baru, tidak ada discrete input baru, arti pulse NG (buang) dan pulse OK (loloskan)
tetap sama persis, dan ladder tidak perlu tahu truk mana yang sedang membongkar.

Aturan ini bertumpu pada satu konfirmasi dari tim panel yang **belum didapat**: apakah tandan yang
lewat tanpa sinyal apa pun akan lolos secara default. Kalau ternyata perilaku default aktuator
membuang tandan tanpa sinyal, pendekatan ini menghasilkan kebalikan dari yang dikehendaki.

## Yang belum diputuskan

Tujuh butir berikut menunggu jawaban tim panel. Sampai dijawab, jangan menyimpulkan salah satunya
sebagai "sudah beres":

1. Alokasi coil 10, 11, 12 dan discrete input 11, 12, 13 untuk piston manual.
2. Jumlah piston per line, dan arti "buka" secara fisik (satu bit per line cukup hanya kalau
   "buka" berarti satu keadaan).
3. Konfirmasi: tandan yang lewat tanpa sinyal akan lolos (bukan dibuang).
4. Persetujuan enam aturan ladder di atas, terutama aturan 3.
5. Watchdog coupler diturunkan dari 30 detik ke 2–3 detik.
6. E-stop dikabel ulang menjadi NC (normally closed) — setelan saat ini membuat kabel putus
   terbaca persis sama dengan kondisi aman.
7. Alamat IP coupler dan NIC yang dipakainya — usulan `192.168.100.50`, subnet `255.255.255.0`.

Butir tambahan yang belum jadi permintaan formal: apakah kamera seharusnya ikut berhenti menilai
saat E-stop ditekan. Saat ini **tidak** berhenti — kamera tetap menilai dan pulse tetap dikirim
selama E-stop aktif.

## Glosarium

| Istilah | Arti |
|---|---|
| Coil | Bit keluaran yang dapat ditulis lewat Modbus. Di sistem ini, jalur AutoGrade menuju PLC. Dinomori mulai dari 0 |
| Discrete input | Bit masukan yang hanya dapat dibaca lewat Modbus. Jalur PLC menuju AutoGrade. Dinomori mulai dari 0 |
| FC05 | Modbus function code 05, *write single coil* — dipakai AutoGrade untuk menulis satu coil |
| FC02 | Modbus function code 02, *read discrete inputs* — dipakai AutoGrade untuk membaca blok masukan |
| Tepi naik | Perubahan sebuah bit dari 0 menjadi 1. Untuk coil OK dan NG, satu tepi naik berarti satu tandan |
| Level | Bit yang mempertahankan nilainya selama suatu keadaan berlangsung, bukan berdenyut. Coil ERROR, HEARTBIT, dan coil piston manual (usulan) berbentuk level |
| Pulse | Bit yang naik sesaat lalu turun kembali, dengan jeda wajib sebelum pulse berikutnya pada coil yang sama |
| Watchdog | Pengatur waktu di dalam coupler yang mengharapkan komunikasi datang secara teratur. Bila komunikasi berhenti melebihi batas waktunya, coupler menjalankan *fault action* |
| Fault action | Tindakan coupler saat watchdog kedaluwarsa atau koneksi terputus — pada sistem ini, me-reset output sehingga seluruh coil padam |
| Tandan (janjang) | Satu tandan buah segar kelapa sawit; satuan yang dinilai kamera. Satu tandan menghasilkan paling banyak satu pulse |
| ACC / REJ | Hasil penilaian kamera: diterima atau ditolak. ACC menghasilkan pulse OK, REJ menghasilkan pulse NG |
| Line | Satu conveyor beserta satu kamera dan satu proses aplikasi. Ada tiga line |
| HEARTBIT | Penulisan pada skematik untuk coil 9, menyatakan PC dalam keadaan hidup. Ejaan aslinya dipertahankan agar cocok skematik dan ladder |
| ODOT CN-8031 | Coupler remote IO; sisi aplikasi bicara ke perangkat ini lewat Modbus-TCP port 502 |

## Contoh tanya jawab

**T: Coil berapa yang dipakai untuk hasil OK line 2?**
J: Coil 3, alamat PLC X0303, bentuk pulse, status berjalan. (Line 2 NG di coil 4/X0304, ERROR di
coil 5/X0305.)

**T: Apakah piston manual line 3 sudah bisa dipakai operator sekarang?**
J: Belum. Piston manual (coil 10/11/12 dan discrete input konfirmasi 11/12/13) berstatus usulan —
belum disetujui tim panel dan belum ada satu baris pun di aplikasi yang terpasang. Coil 12 dan DI
13 yang direncanakan untuk line 3 masih menunggu keputusan.

**T: Berapa lama piston sortir menahan tandan sebelum kembali ke posisi semula, dan merek
aktuatornya apa?**
J: Tidak ada di dokumen ini. Dokumen ini hanya mendefinisikan sinyal listrik ke/dari PLC
(alamat coil, bentuk, dan waktunya), bukan mekanik atau merek aktuator piston. Silakan tanyakan ke
tim AutoGrade atau tim panel yang memasang piston.

**T: Kalau kabel LAN coupler putus lalu tersambung lagi, apa yang harus dilihat di ladder?**
J: Seluruh coil AutoGrade akan padam dulu (termasuk HEARTBIT) melalui *fault action* coupler.
Setelah kabel tersambung kembali, HEARTBIT dan coil ERROR akan naik lagi dengan sendirinya dalam
sekitar 1 detik, tanpa perlu ada yang di-restart. Status ini berjalan sekarang, bukan usulan.

**T: Berapa banyak tandan per detik yang bisa ditangani satu coil OK/NG?**
J: Sekitar 2,5 pulse per detik per coil (satu siklus pulse ≈410 ms: ON ≈205 ms + jeda OFF wajib
≈205 ms). Kamera bisa menghasilkan keputusan lebih cepat dari itu; kelebihannya dibuang dan
dihitung sebagai angka diagnostik, tidak diantrekan.
