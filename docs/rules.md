# Rules, conventions and git workflow (full text)

Moved verbatim from `CLAUDE.md` on 2026-09-30. `CLAUDE.md` §3 keeps a one-line index with the
same numbers (0 to 35, plus 1b and 1c); this file is the full text with rationale, dates and the `⚠️` notes.
Rule numbers are cited by tests, `docs/overview.md` and skills: do not renumber. New rules are
appended with the next number in both files. The former `CLAUDE.md` "Pointers" list sits at the
end of this file.

## Critical Rules (full rationale → `docs/overview.md` § Invariants)

0. **Model 4 kelas; kelas BUKAN verdict.** `best.pt` mendeteksi `Ripe`, `Unripe`,
   `JK` (janjang kosong), `TP` (tangkai panjang). Pemetaannya hidup di **satu**
   tempat, `domain/grade_class.py`: `Ripe`→ACC, `Unripe`/`JK`→REJ, `TP`→tidak
   punya verdict (bukan janjang; menempel di `tp_confidence`). Dua hal di hilir
   sengaja tetap biner: **PLC cuma punya dua coil** (OK/NG: kategori ketiga itu
   kabel, bukan kode) dan **AutoERP cuma membukukan tiga kriteria** (`Mentah` /
   `Tangkai Panjang` / `Matang`, kontrak beku). Jadi satu baris membawa
   **keduanya**: `ripeness_status` = verdict yang menggerakkan piston dan dibayar,
   `grade_class` = rincian yang dibaca layar.
   ⚠️ **Angka `JK` sendiri tidak dikirim ke AutoERP, tapi janjangnya IKUT di `Mentah`.**
   Kode hari ini: `Mentah` = semua janjang `REJ` (`erp_messages._grading` memakai `rej`,
   `console_repository` menghitung `ripeness_status = 'REJ'`), dan JK itu REJ. Yang ikut
   juga: buah Ripe yang dipaksa REJ karena bertumpuk/terlalu kecil (aturan 26).
   Rancangan awal (2026-09-16) bilang sebaliknya: JK berhenti di edge karena `Sampah`
   itu **ditimbang** (jawaban Samuel) dan JK di `Mentah` membesarkan porsi mentah yang
   dipotong dari supplier. **Belum diputuskan** mana yang benar (ketahuan 2026-09-28);
   sampai ada keputusan, jangan ubah kodenya dan jangan tulis ulang klaim "JK tidak
   dikirim".
   ⚠️ Kelas dibaca dari **nama**, bukan urutan id. `cls_id in (0, 1)` dulu
   dipakai buat menentukan `area`, dan model yang dilatih ulang boleh menukar
   urutan kelas: `area` jadi 0 untuk buah dan penjaga `MINIMUM_SIZE` berhenti
   bekerja tanpa satu pun error. `domain/rules.py` **pensiun** karena alasan yang
   sama: aturannya mencocokkan substring `"rej"`, yang tidak pernah cocok dengan
   `Unripe` maupun `JK`.

1. **Disk before API**: never POST events directly from a worker; **antrean yang bicara ke
   jaringan, bukan worker deteksi**. `CaptureSaveWorker` (jalur auto) dan `capture_service` (manual)
   menulis WebP + JSON ke `artifacts/results/` lalu **satu baris** ke `outbox.db`
   (`build_event_payload()` dari `domain/vision_event.py`). Dua konsumen mengirimnya:
   - `OutboxRetryWorker` → API **lokal** (`BACKEND_URL`), poll 1 detik. Ini yang bikin operator
     lihat Grading History + gambar seketika, dan satu-satunya jalur yang hidup saat internet mati.
   - `BatchUploadWorker` → R2 + API **cloud** (`UPLOAD_API_URL`), tiap jam. Menemukan item lewat
     `_scan()` folder `results/` (**bukan** outbox), state per-item di `UploadManifest`.

   `event_id` = **uuid5 deterministik** (`machine_id:file_timestamp`) di **semua** jalur, jadi
   kirim ulang dibalas `already_processed`, bukan baris dobel. Jangan pernah pakai uuid4 di sini.

   `image_path` dari kedua worker deteksi **harus relatif** (`captures/results/<tgl>/<file>.webp`);
   api merakitnya jadi `{apiPrefix}/captures/{line_code}/...`. Hanya `BatchUploadWorker` yang
   menukarnya dengan URL R2 absolut, dan itu untuk cloud saja.

   Kelas kegagalan batch bersifat load-bearing: `_PoisonError` → poisoned + **continue** (satu item
   busuk tidak menyandera batch; file TIDAK dihapus); `_RequeueError` → requeue, lalu **break**
   kalau `batch_fatal=True` (jaringan/5xx/429/401/403: kondisi global) tapi **continue** kalau
   `batch_fatal=False` (HTTP 404 = truck belum sinkron, kondisi per-item, break di situ bikin
   antrean `ORDER BY discovered_at ASC` kelaparan di belakangnya).
   Foto bukti atau sidecar 0 byte / sisa `.tmp` (disk dari sebelum batch 2.6) = `_PoisonError`:
   tidak diunggah, tidak disapu retensi, terhitung `rusak` di Cloud Photo; thumbnail 0 byte cuma
   dilewati (WARNING). Sidecar janjang tanpa gambar juga diracun, bukan `done`.
1b. **Thread deteksi tidak pernah menunggu disk** (sejak 2026-09-18). Encode WebP frame sensor penuh
   memakan **~285 ms per gambar**, dan satu janjang menulis tiga gambar + sidecar + baris outbox:
   **~590 ms** diukur di PC Lampung 2026-09-17. Angka itu cocok dengan frame penuh 2448x2048; frame
   yang sampai ke line di Lampung sekarang **1224x1024** (binning 2x2 di `config/camera/hikrobot.mfs`,
   dicek pada foto terbaru 2026-10-05), dan satu janjang di sana 175 ms, 95 ms sejak batch 6.2
   (`scripts/bench_simpan_foto.py --gambar <foto clean>`). Selama itu dulu deteksi BERHENTI, dan tiga akibatnya
   semuanya senyap: `frame_queue` (drop-oldest, nol log) membuang ~12 frame per janjang di kamera 20
   fps, ByteTrack kehilangan jejak lalu memberi track id baru pada janjang yang sama (tonase dobel),
   dan layar operator membeku ~1 detik. Sekarang `FrameProcessingWorker` cuma `submit()` satu
   `SaveJob` ke `CaptureSaveWorker` lalu lanjut ke frame berikutnya.
   **Yang HARUS tetap di jalur deteksi**, jangan dipindah ke penulis: pulse PLC (piston menyortir
   buah yang lewat sekarang, bukan buah setengah detik lalu), penandaan `plc_signalled`/`processed`,
   event ke `event_queue` (angka di layar), dan **penetapan `timestamp`**, nama berkas adalah sumber
   `event_id` uuid5, dan `BatchUploadWorker` menghitung ulang id yang sama dari nama itu berjam-jam
   kemudian. Penulis yang menstempel jamnya sendiri memutus idempotensi dan satu janjang terhitung
   dua kali di angka yang dibayar ke petani.
   `image_url` untuk layar dihitung di depan lewat `CaptureWriter.annotated_url()`, **rumus yang
   sama** yang dikembalikan `write_pair()`, jadi tautan yang tampil dan berkas yang ditulis tidak
   bisa menyimpang (kalau menyimpang: gambar 404 di konsol, nol error di line).
   Antrean **8 dalam, drop yang terbaru + `logger.error`**: menahan deteksi sampai antrean lega akan
   mengembalikan persis lag yang dihilangkan. Angkanya dari dua ukuran: beban nyata **300
   janjang/jam/line** (satu tiap 12 detik, sementara penulis butuh ~0,6 detik, jadi antrean ini
   untuk **lonjakan**, bukan laju rata-rata) dan biaya memorinya: tiap job menahan dua frame (3,6 MB
   masing-masing pada 1224x1024, 14,3 MB tanpa binning), jadi 8 dalam = 60 MB per line (230 MB
   tanpa binning) dari RAM 31 GB. Antrean yang sering penuh
   berarti disk/CPU tidak mengimbangi laju grading, itu yang harus dibaca dari log, bukan ditambal
   dengan antrean lebih dalam lagi. Satu janjang >1 detik diadukan `logger.warning`
   (`tulis … ms, antre … ms, antrean=N`): itu alat ukur lapangannya.
   Tutup line menghabiskan antrean ini dulu (maks 6 detik, `BATAS_KURAS_S`) dan menyebut janjang
   yang tidak sempat ditulis di ERROR `Tutup line: N janjang TIDAK tertulis ...`; `tunggu_kosong`
   menghitung janjang yang sedang dipegang penulis (`unfinished_tasks`).
1c. **TP dipasangkan lewat JARAK, bukan urutan waktu** (sejak 2026-09-18,
   `domain/garis_capture.tp_untuk_janjang`). Saat janjang difoto, TP yang dipakai adalah yang
   pusatnya paling dekat dan masih dalam `_JANGKAUAN_TP` × setengah diagonal janjang,
   ambang RELATIF, karena janjang dekat kamera jauh lebih besar daripada yang di ujung frame.
   TP dikumpulkan di **pra-pindai**, sebelum loop janjang: urutan kotak dalam satu frame tidak
   dijamin, jadi TP yang disebut sesudah janjangnya akan terlewat kalau dibaca sambil jalan.
   ⚠️ **Ambang saja tidak cukup**: dua janjang berdempetan bisa sama-sama berada dalam
   jangkauan TP yang sama, dan yang menang tinggal siapa yang kebetulan diproses lebih dulu.
   Karena itu TP diberikan hanya kalau janjang itu yang **paling dekat di antara semua**
   janjang di frame (`janjang_lain`): tanpa itu janjang B dikreditkan tangkai milik A dan
   tangkai A yang asli tidak tercatat, dan `tp_confidence > 0.8` itu kriteria Tangkai Panjang
   yang dibukukan AutoERP. Janjang yang **sudah difoto** ikut jadi saingan: tangkai milik
   janjang yang baru selesai tidak boleh pindah ke tetangganya.
   ⚠️ **Alur LAMA yang diganti** (jangan dihidupkan lagi): satu slot `_last_tp` berisi "TP
   terakhir yang terlihat", diberikan ke janjang berikutnya yang menyentuh garis, tanpa pernah
   melihat posisi. Dua akibatnya sama-sama salah bayar dan sama-sama senyap: TP milik janjang A
   menempel ke janjang B yang lewat garis lebih dulu, dan TP yang terlihat sesudah janjangnya
   difoto menempel ke janjang berikutnya.
   ⚠️ **TP yang datang SESUDAH janjang terdekatnya difoto memang tidak ikut**, itu harga yang
   sadar dibayar dari "capture apa adanya". Dihitung di `tp_telat` (`/health/detail`) supaya
   keputusan menambah jendela tunggu nanti diambil dari angka Lampung, bukan dugaan. Tiga jalan
   yang sudah ditimbang dan ditunda: tahan simpan ~0,5 dtk, biarkan hilang, atau kirim susulan
   (yang terakhir menyentuh kontrak ingest idempotent + rekap kunjungan AutoERP).
2. **`_processed_objects`**: never `discard()` an active track (single-trigger). Trim only IDs that are inactive (gone from `track_history`) **and** stale >300s.
3. **`state.lock`** around all physical camera access (`FrameCaptureWorker` + `capture_manual_reject`).
4. **MJPEG**: only `DisplayWorker` writes `state.latest_frame`, via `threading.Condition.notify_all()` (multi-viewer). It renders `last_yolo_frame` (paired with results) and runs at `STREAM_FPS` (default 12), decoupled from `CAMERA_FPS`.
   Since batch 6.3 it shrinks the frame to stream size first and draws the boxes on the small frame
   (`draw_boxes(skala=...)`; the sensor frame is never copied or drawn on: the detection thread hands
   the same array to the photo writer as the clean copy). `StreamingService` counts every MJPEG viewer
   in and out (`state.penonton_masuk` / `penonton_keluar`); with nobody counted in, `DisplayWorker`
   renders nothing and sets `latest_frame` back to `None`, so a viewer who returns waits one interval
   for a new picture and is never handed the last one from before the pause. Clearing it is still
   `DisplayWorker` writing, under the same condition. Numbers: `scripts/bench_display.py`.
5. **DI** (`core/dependencies.py`): `@lru_cache` singletons **except** `get_capture_service()` / `get_health_service()` (camera injected at startup). `get_outbox_store()` may cache (SQLite singleton).
6. **Lifespan** (not `@app.on_event`); `repo_root = parents[3]`; every worker `run_loop` wraps `run_once` in `try/except`; `FrameCaptureWorker` needs `device_index` (so line-2/3 reconnect to the correct camera).
7. **`tp_status`: boolean di sidecar, `"PASS"`/`null` di kawat.** Dua kosakata, satu
   fakta (`domain/vision_event.TP_PASS`): DTO palmgrade-api memvalidasi field ini
   dengan `@IsIn(["PASS"])` dan kontrak itu beku, sementara sidecar di disk kita
   sendiri menyimpan `true`/`false`. **Satu janjang = SATU sidecar** (sejak
   2026-09-20): nilai TP (termasuk `tp_bounding_box`, kotak tangkainya) menumpang
   di berkas ripeness-nya, dan `_auto_tp.json` tidak ditulis lagi. Nama lama masih
   dikenali retensi karena berkasnya masih ada di disk pabrik; berhenti mengenalinya
   membuat berkas itu yatim abadi sampai disk penuh.
   ⚠️ **TP cuma dicari untuk janjang ACC.** Unripe dan JK dibuang piston, jadi
   tangkainya tidak dibayar dan tidak dicatat, angka TP karena itu lebih kecil
   daripada sebelum tanggal itu, dan turunnya disengaja.
   **`image_url` = `captures/results/{date}/{HHMMSS}_{plat}_{assign8}/bbox/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp`** (consistent with `/captures` mount): folder KELAS, bukan verdict (sejak 2026-09-20: `acc`/`rej` melebur Unripe dan JK, membuang persis yang dibeli retrain 4 kelas), dan janjang Ripe bertangkai panjang turun satu level lagi ke `Ripe/TP/` supaya mencari hasil TP cukup membuka satu folder. Capture manual → `unknown/` (tidak pernah lewat model). ⚠️ **Tidak ada pembaca yang boleh mematok kedalaman folder**, `Ripe/TP/` satu level lebih dalam, dan `_twin()` yang dulu menganggap verdict tepat di bawah `bbox` mengembalikan `None` untuknya: kembaran yang tidak ketemu adalah kembaran yang tidak dihapus siapa pun, karena `clean/` dan `thumb/` tidak punya baris manifest sendiri. Satu folder per truk, **tiga berkas per janjang**: `bbox/` (bergambar kotak, ini yang ditunjuk `image_path` dan yang naik R2), `clean/` (polos, buat latih model ulang; **tidak** diupload), dan `thumb/` (sejak 2026-09-16: 400px WebP q60 dari frame `bbox/`, naik ke R2 berdampingan dengan `bbox/` (apa yang dimuat grid `viewer.html`). Jam folder pakai `FACTORY_TZ`, **bukan** UTC) folder dibaca manusia, nama berkas dibaca mesin. Truk belum di-assign → `_belum-assign/`. **JSON sidecar-nya TETAP datar di folder tanggal**: `BatchUploadWorker._scan()` mencarinya dengan `glob("*/*_ripeness.json")` (kedalaman dipatok dua), jadi sidecar yang ikut masuk subfolder bikin upload cloud berhenti **tanpa error**. Aturannya di `domain/capture_layout.py` (`CaptureVariant.THUMB`, `twins_of()`), penulisnya `services/capture_writer.py` (satu-satunya yang menulis gambar, dipakai jalur auto maupun manual). Gambar disimpan **WebP** quality 65 (`JPEG_QUALITY_SAVE`), thumbnail quality 60; folder `errors/`, `captures/`, dan `logs/` **sudah tidak ada**, dulu dibuat saat startup tapi tidak pernah ditulis (REJ ditemukan via metadata `ripeness_status`, log ke stdout). Startup cuma membuat `results/`, dijaga `tests/unit/test_artifact_dirs.py`.
8. **Encode atau tulis gagal → `LocalFileStorage.write_image` raises `OSError`** (termasuk `cv2.error`) (no orphaned JSON records pointing at an image that was never written). Kegagalan menulis **`thumb/`** khusus TIDAK melempar, janjang tetap tersimpan tanpa thumbnail, `logger.error` saja (lihat rule 7).
   Foto dan sidecar ditulis utuh-atau-tidak-sama-sekali: `cv2.imencode` di memori lalu `tulis_atomik`
   (temp `.<nama>.<acak>.tmp` + fsync + `os.replace` + fsync folder); listrik padam meninggalkan
   sisa `.tmp` tersembunyi, bukan berkas 0 byte bernama sah.
   Since batch 6.2 the `clean/` copy is written on a helper thread while the `bbox/` copy is
   written on the writer thread (`CaptureWriter.write_pair`): two full-size WebP encodes side by
   side, cv2 releases the GIL. The `bbox/` copy stays on the calling thread because its failure
   is the one that raises. When it fails, the `clean/` copy written beside it is removed again and
   no thumbnail is made: a `clean/` copy has no manifest row (rule 9), so one without its `bbox/`
   twin would never be deleted. Numbers: `scripts/bench_simpan_foto.py`.
   **Nama folder TANGGAL selalu UTC** (`FrameProcessingWorker._save_ripeness`,
   `capture_repository`): pembacanya wajib UTC juga. ⚠️ Yang pakai `FACTORY_TZ`
   cuma **folder truk di dalamnya** (aturan 7); dua zona dalam satu pohon itu
   disengaja, jangan "diseragamkan" ke salah satunya. `datetime.now()` naive di
   `ResultRepository` kebetulan cocok cuma karena container ini kebetulan
   `TZ=UTC`; set `TZ=Asia/Jakarta` dan `/api/results_today` menunjuk folder yang
   belum ada lalu melapor nol hasil. Jangan pernah pakai `datetime.now()` telanjang.
9. **Retention deletes source files**: `BatchUploadWorker._retention()` unlinks **ketiga** WebP (`bbox/` + `clean/` + `thumb/`, dipasangkan `domain/capture_layout.twins_of`) + JSON once an item is `done` and older than `UPLOAD_RETENTION_DAYS` (default 7; PC pabrik 180). Local artifacts are therefore **not** a long-term archive; the cloud + R2 are.
   Umur saja tidak cukup begitu angkanya jadi hitungan bulan, jadi
   `_retention_by_disk()` jadi pagar terakhir: di bawah `UPLOAD_DISK_MIN_FREE_GB`
   (default 20) ia membuang `done` **tertua** lebih awal sampai sisa disk lega.
   Hanya `done` yang pernah disentuh, item lain adalah satu-satunya salinan yang
   ada, jadi kalau `done` habis dan disk masih mepet, penjaga **berhenti dan
   `logger.error`** (antrean upload macet: itu urusan operator, bukan hapus data).
   ⚠️ Seluruh `_retention()` cuma jalan kalau `R2_BUCKET` terisi (`run_batch_once`
   pulang lebih awal tanpanya), jadi dengan R2 mati tidak ada yang membersihkan
   disk sama sekali: dan memang tidak boleh ada, karena tidak ada yang `done`.
   ⚠️ **Salinan `clean/` tidak punya baris manifest sendiri**, dia dihapus di sini
   atau tidak sama sekali. Menambah gambar ketiga tanpa ikut menambahnya ke
   `_delete_item_files` berarti penjaga disk menyapu item `done` sambil cuma
   membebaskan separuh byte-nya, sampai disk penuh dan grading berhenti menyimpan.

10. **Konsol: `work_date` dihitung saat ingest, lalu DISIMPAN** (§6.1). Pabrik jalan ~20
    jam/hari **lewat tengah malam**, jadi batas hari UTC memotong satu shift jadi dua tanggal.
    `domain/working_day.py` menurunkannya dari timestamp event itu sendiri di `FACTORY_TZ`:
    **jangan pernah** dari `now()`, `creation`, atau nama folder. Timestamp cacat → `ValueError`
    → ingest balas **400** → outbox line menahannya dan terus mencoba (jeda sampai 10 menit, tab
    Status → Antrean line); sengaja terlihat gagal daripada mendarat di hari yang salah.
    `python:3.11-slim` butuh `tzdata`
    (sudah di Dockerfile): tanpa itu `ZoneInfo` gagal dan tanggal diam-diam balik ke UTC.
    **Cutoff hari kerja** (batch 5.11, 2026-10-05): support bisa menggeser awal hari kerja dari
    00:00 sampai 23:59 (tab Setelan; lewat 12:00 layar minta konfirmasi dengan contoh efeknya,
    user 2026-10-05; `sync_state` `setelan_cutoff_shift`,
    `services/hari_kerja.py`). `work_date` = tanggal dari `timestamp - cutoff` di `FACTORY_TZ`.
    Satu-satunya jalan menghitung tanggal kerja adalah `HariKerja.untuk` / `kini` (ingest, timbang,
    scan gerbang, "Hari ini"). Bawaan 00:00 = perilaku lama. **Baris yang sudah tersimpan tidak
    pernah dihitung ulang**: perubahan cutoff berlaku untuk baris berikutnya. AutoERP tetap
    menanggali tiket dari tanggal lokal `time_in`, jadi dengan cutoff lewat 00:00 truk yang timbang
    antara 00:00 dan jam cutoff tanggalnya beda di konsol dan di AutoERP (total tidak berubah);
    tab Rekap menulis "(dipotong jam HH:MM <zona>)" di belakang judul hari kerjanya.
11. **Konsol tidak boleh memindai direktori** (§6.2): semua yang dibaca layar operator datang
    dari **index SQLite** `state/console.db`, di **`repositories/console_repository.py`**
    dengan skema dan migrasinya di **`repositories/console_skema.py`** dan akunnya di mixin
    **`repositories/console_akun_repository.py`** (batch 2), dan jam gerbang di mixin
    **`repositories/console_gerbang_repository.py`** (aturan 37). Konvensi sama dengan `OutboxStore`:
    WAL + `synchronous=FULL` + satu lock + `INSERT OR IGNORE`.
    Gambar tetap di disk line-nya, di-mount read-only dan di-serve statis. Polling `listdir`
    tiap 2 detik akan memakan I/O yang dipakai grading.
    Query per penugasan memakai **`idx_inspections_assignment`**: query baru yang berat harus
    menunjukkan `SEARCH`, bukan `SCAN inspections`, di `EXPLAIN QUERY PLAN`
    (`tests/rencana_query.py`, `tests/unit/test_console_store_indeks.py`).
12. **Sumber TBS: edge cuma mencerminkan aturan AutoERP, tidak pernah menebak** (§3.5b). AutoERP
    menurunkannya dari supplier saja (`sumber_for_supplier`: punya supplier = External, tidak
    punya = Internal). `domain/ffb_source.py` mencerminkannya persis: truk ber-supplier →
    External; truk yang **sudah ada di ERP** tanpa supplier → Internal; truk tanpa supplier yang
    belum dilihat ERP → `—`. Semua query store (dan `riwayat_repository`) memakai satu `SOURCE_FACTS`, jadi tidak ada tab
    yang berlabel beda. **Jangan** menurunkan sumber dari nama grup supplier. Grup tetap disimpan
    **mentah** di `suppliers.source_group` karena beda Plasma vs agen hidup di sana; **jangan pernah**
    bikin boolean `is_internal`.
13. **Penugasan truk: line dulu, baru dicatat.** `assign_truck` menunggu line menerima sebelum
    menyimpan. Layar yang menampilkan truk terpasang padahal line tidak tahu apa-apa membuat
    operator mengira sudah beres, dan tandan berikutnya terhitung tanpa truk.
    **Melepasnya juga harus sampai ke line** (`lepas_truk`): penugasan yang tidak pernah
    berakhir bikin tandan truk berikutnya nempel ke truk yang sudah pulang, salah yang tidak
    kelihatan salah di layar. Kontrak `/internal/assignment` beku, jadi kosong dikirim sebagai
    string kosong dan line-lah yang mengubahnya jadi `None` (`schemas/internal_schema.py`);
    `""` yang lolos apa adanya akan ditolak validasi UUID palmgrade-api.
    **Satu pengecualian: Lepas paksa** (keputusan user 2026-10-04,
    `POST /api/console/lines/{line_code}/force-release`, `services/lepas_paksa.py`). Line yang
    mati tidak pernah mendengar Lepas, jadi truknya dulu tertinggal di konsol: Update now berhenti dengan
    `pembaruan_lepas_gagal` (aturan 38; lepas paksa dulu), penugasan otomatis tertahan (aturan 36), dan line yang menyala lagi menarik truk
    yang sudah pulang itu lewat `GET /internal/penugasan`. Tombolnya cuma muncul di kartu yang
    memegang truk selama status line tidak terbaca sama sekali (`sebab_kode` `tak_terjangkau`),
    menggantikan Lepas, dengan konfirmasi. Server yang memutuskan, bukan layar: Lepas biasa dicoba
    dulu (`TIMEOUT_LEPAS_PAKSA_S` 3 detik); line yang menjawab dilepas biasa, line yang menjawab
    dengan **penolakan** (4xx/5xx, kunci salah) **tidak pernah** dipaksa (502), dan hanya line yang
    tidak menjawab apa pun (koneksi ditolak, timeout; `domain/lepas_paksa.boleh_paksa`, aturan yang
    sama dengan `sebab_tak_terbaca`) dilepas di konsol saja, dengan pembukuan yang sama persis
    (`_catat_lepas`: tautan grading ke tiket, satu pesan AutoERP, aturan 18) dan satu WARNING
    menyebut akun, line, dan plat. Tiket dan berat tidak pernah tersentuh.
    **Line yang cuma terputus** (hidup, kabel putus) masih memegang truk itu di memorinya. Konsol
    mengingat tiap Lepas paksa di `sync_state` `lepas_paksa_tertunda` (bertahan restart konsol,
    ikut terhapus Danger Zone), dan `LineStatusWorker` meneruskan tiap status yang terbaca ke
    `cocokkan_lepas_paksa`: line yang menjawab lagi dan `truck_id`-nya masih truk yang dipaksa,
    sementara konsol tidak memasang apa pun di line itu, dikirimi pelepasan sekali lagi (satu
    WARNING); jawaban lain menutup catatannya. Selama `assign_truck` ke line itu berjalan
    (`kunci_line`, dipegang dari panggilan line sampai konsol mencatat) keputusan ditunda ke poll
    berikutnya, supaya kiriman ulang tidak menimpa truk baru yang sudah diterima line tapi belum
    dicatat. ⚠️ Sisa risiko: janjang yang digrading line terputus itu SEBELUM ia menjawab lagi
    tetap distempel truk yang sudah dipaksa lepas; yang menutupnya cuma kiriman ulang begitu status
    terbaca (paling lama sekitar satu detik sesudah line menjawab).
14. **Konsol yang memanggil AutoERP; AutoERP tidak pernah memanggil ke pabrik.** PC pabrik
    tidak punya inbound sama sekali. Kontraknya `autoerp/docs/autograde-integration.md`, dan
    **per janjang tidak pernah dikirim** (§2: *"Not synced: per-bunch rows, images"*): janjang
    dan gambar tetap di edge sebagai bukti. AutoERP menerima tiga hal saja: tarikan master data
    (§4.A), truk baru dari pabrik lewat `upsert_truck` (§4.B), dan satu pesan per kunjungan truk
    lewat `upsert_visit` (§4.C). Semua field yang diminta ke `/api/resource` harus persis milik
    DocType: Frappe membalas 417 untuk satu field asing. `ERP_URL` kosong = semua worker ERP
    mati diam-diam, dan itu default: jalur ini tidak boleh jadi syarat hidupnya layar operator.
    Kolom `inspections.erp_state` sisa jalur per janjang yang dihapus; tidak dipakai.
    **`ErpClient` membalas empat jawaban** (`integrations/erp/client.py`, batch 2.7):
    `ErpRejected` (4xx, AutoERP menolak kiriman ini apa adanya), `ErpServerError` (5xx yang
    membawa amplop galat Frappe sendiri, per pesan, backoff sendiri, batch lanjut),
    `ErpUnavailable` (tidak ada jawaban yang bisa dipakai: jaringan, timeout, gateway
    502/503/504, halaman 5xx yang bukan Frappe, atau 2xx yang isinya bukan objek JSON Frappe,
    dibaca sebagai "tidak terjangkau" oleh Last Sync), dan terkirim (AutoERP menerima). Worker
    antrean mencatat dan mem-backoff SETIAP kegagalan per pesan dan tidak pernah melempar
    (`drain_once` selalu kembali dengan tenang, batch di belakangnya tetap jalan).
18. **Kunjungan truk: satu pesan, dibangun ulang tiap kali, tidak pernah ditambal** (§4.C).
    `ErpQueue` satu-satunya yang merakit pesan, pemicu langsung dan kirim ulang harian memakai
    jalan yang sama, jadi tidak bisa berbeda isi. Tiga pemicunya kejadian yang memang terjadi:
    timbang isi, truk dilepas dari line, timbang kosong. **`stage` diturunkan dari keadaan
    kunjungan**, bukan ditentukan pemanggil. Bagian yang tidak kita punya **tidak dikirim**,
    tiap kiriman mengganti bagian yang dibawanya, jadi bagian kosong menghapus isi ERP.
    Grading kunjungan = **semua** penugasan line yang tertaut ke tiketnya, dijumlah (tabel
    `visit_assignments`, satu baris per penugasan, `grading_counts_for_visit`, 2026-10-01): satu
    truk boleh dibongkar di beberapa line, dan dulu cuma line yang dilepas terakhir yang terhitung.
    Tautannya **ditulis saat truk dilepas**; tanpa tautan itu tiket kedua di hari yang sama
    mewarisi janjang tiket pertama. Kolom lama `weighings.assignment_id` tetap ditulis supaya
    image lama masih jalan setelah rollback. Tiketnya dicari lewat **jendela waktu**
    (`JENDELA_KUNJUNGAN_DETIK`, 12 jam sejak tiket diterima konsol), bukan hari kerja: hari kerja
    berganti pukul 00:00, kunjungan tidak. Timbang kosong melepas semua line truk itu lebih dulu
    dan mengantre kunjungannya **sekali** sesudahnya: AutoERP memfinalisasi tiket begitu bobot dan
    grading sama-sama ada, jadi pesan di antara dua pelepasan akan membukukan sebagian line.
    Kriteria: mentah = REJ, tangkai panjang = ACC dengan `tp_confidence > 0.8`, matang
    diturunkan AutoERP sendiri.
    Karena angka itu dijumlah dari `ripeness_status`, **`ripeness_status` divalidasi saat ingest**
    (`domain/vision_event.verdict_of`, satu kosakata untuk penulis dan pembaca field ini): di luar
    `{ACC, REJ}` → 400, seperti timestamp cacat. Nilai asing dulu ikut `total` tapi tidak masuk
    `acc` maupun `rej`: rekap yang dibayar tidak menjumlah, dan tidak ada yang bilang. `prediction`
    tetap dibawa apa adanya, tapi yang **bertentangan** dengan verdict-nya ikut ditolak.
    ⚠️ AutoERP **mengadopsi tiket terbuka milik truk yang sama** dalam jendela ±2 jam, jadi dua
    kunjungan truk itu di jam yang sama memang mendarat di satu tiket, itu perilaku ERP,
    bukan bug konsol. Dulu adopsi itu bisa **menimpa** bruto, jam masuk, dan nomor timbangan
    kunjungan pertama sampai netonya jadi campuran dua kunjungan; dibuktikan live 2026-09-14.
    **Sudah diperbaiki di AutoERP** (autoerp PR #7, merge 2026-09-16): kunjungan dengan
    `scale_ticket_no` berbeda tidak lagi mengadopsi tiket milik kunjungan lain. Tidak ada yang
    perlu ditambal dari sisi konsol, dulu maupun sekarang.
    **Janjang susulan untuk penugasan yang sudah dilepas mengantre ulang kunjungannya**
    (batch 2.3): cuma pada **insert sungguhan** (`add_inspection` mengembalikan baris baru),
    bukan pada kiriman ulang `event_id` yang sama. Janjang susulan yang tiba SEBELUM baris
    antrean sebelumnya berangkat **menggantikan** baris itu (dan halaman R2-nya), jadi AutoERP
    cuma menerima satu kiriman berisi semua janjang, tidak ada yang ditandai. Janjang susulan
    yang tiba SESUDAH tiket final dijawab AutoERP `revised`, yang **tidak menulis ulang** angka
    yang sudah dibukukan: tab Timbangan menandai baris itu **Cek AutoERP**, dan tab Log mencatat
    satu WARNING `[TIKET_FINAL_BERBEDA]` (tiket dibatalkan → `[TIKET_DIBATALKAN]`)
    (`domain/jawaban_kunjungan.py`), sekali per catatan AutoERP yang berbeda, bukan sekali per
    kirim ulang harian. `visit unchanged` (kirim ulang harian untuk tiket final yang angkanya
    sama) dicatat INFO saja, bukan WARNING.
15. **Timbangan: `net_kg` dihitung, tidak pernah dipercaya mentah** (§3.5c). Pengirim boleh
    menyertakannya; kalau bedanya dari `bruto − tara` lewat `TOLERANSI_NETO_KG` (1 kg) kiriman
    **ditolak 400**. Ini angka yang dibayar ke petani, dua sumber kebenaran yang diam-diam
    berbeda adalah cara paling rapi untuk salah bayar berbulan-bulan.
    Timbang isi dan timbang kosong adalah **dua POST untuk satu baris**, digabung lewat
    `COALESCE` per kolom: kiriman kedua yang cuma membawa tara tidak boleh menghapus bruto.
    Kuncinya `ref` kalau ada, kalau tidak uuid5 dari (plat ternormalisasi + `entered_at`),
    tanpa salah satu dari keduanya kiriman **ditolak**, karena timbang kosong tidak akan bisa
    menemukan barisnya dan satu tiket pecah jadi dua.
    Pemisah ribuan tanpa desimal (`"14.820"` untuk empat belas ton) parse **bersih** jadi
    14,82 dan tidak ada apa pun di payload yang membantahnya, jadi yang menangkapnya lantai
    `MINIMUM_BERAT_KG` pada `gross_kg`/`tare_kg` (sekarang 1 ton, lihat aturan 20), truk kosong
    saja sudah berton-ton.
    ⚠️ Format asli program timbangan **belum diketahui** (`../docs/PERTANYAAN-TERBUKA.md` X1).
    Yang dibekukan di sini bentuk KITA; begitu formatnya turun, yang ditambah **adapter**,
    bukan bongkar tabel.
17. **Rekap: grading dan timbangan dua sumber terpisah, cuma disandingkan.** `rekap()`
    menjumlah `net_kg` per truk **di Python**, bukan mem-JOIN agregat `weighings` ke query
    GROUP BY grading: satu truk bisa punya lebih dari satu tiket sehari, dan join itu
    mengalikan jumlah janjang dengan jumlah tiket. Baris `truck_id IS NULL` **tetap
    ditampilkan** ("Tanpa truk"): janjang yang ter-grading sebelum truk dipasang justru yang
    perlu dilihat operator, bukan yang perlu disembunyikan.
16. **Truk manual naik lewat antrean; truk milik AutoERP read-only.**
    `POST /api/console/trucks` menyimpan lokal (`status='manual'`) lalu menaruh satu baris di
    `erp_outbox` (kontrak §4.B): AutoERP membuat truk **tanpa pemilik**, backoffice yang
    melengkapi supplier dan kelasnya. Id-nya uuid5 plat ternormalisasi, dan **dua ruang id itu
    sengaja bertemu** dengan ERP (aturan normalisasi sama persis), jadi truk hasil tarik
    **mengadopsi** baris yang diketik operator, bukan bikin kembar yang membelah tonase sehari.
    Tarikan tidak pernah mengosongkan `erp_name` (`COALESCE`).
    ⚠️ **Truk yang sudah punya `erp_name` tidak boleh diubah dari konsol** (kontrak §4, FE-1):
    mengetik ulang platnya mengembalikan baris apa adanya. Sebelum ini ketik ulang menghapus
    suppliernya dan diam-diam mengubah label Sumber jadi Internal, termasuk di baris grading
    yang sudah lewat, karena label dibaca dari truk, bukan disalin ke barisnya.
    ⚠️ **Yang di atas cuma berlaku untuk truk yang id-nya sudah turunan plat.** PC pabrik yang
    sudah jalan menyimpan truk ber-id **acak** dari palmgrade-api (`gen_random_uuid()`), dan
    `plate_number` **tidak punya indeks unik**, jadi di PC itu tarikan pertama tetap membuat
    baris kedua. Itu yang dibereskan **OPS-2** (`make rekonsiliasi-truk`,
    `services/rekonsiliasi.py`), dijalankan **sekali saat pasang**, sebelum `ERP_URL` diisi.
    Id acak lama tidak bisa dihitung ulang dari apa pun, jadi jembatannya cuma plat
    ternormalisasi. `pindahkan_truk` memindahkan **tiga** tabel (`inspections`, `assignments`,
    `weighings`) dalam **satu transaksi**: separuh pindah lebih buruk daripada tidak pindah,
    karena baris yang menggantung ke id terhapus hilang dari rekap, dan rekap itu yang
    dibayar. Baris berplat kosong **dilewati dan dicetak**, bukan bikin seluruh rekonsiliasi
    gagal. `trucks_semua()` dipakai, bukan `trucks()`: yang terakhir menyembunyikan baris
    `inactive`, dan baris inactive ber-id lama tetap akan kembar begitu platnya ditarik.
20. **Scan QR: isinya nomor plat, tidak lebih** (keputusan operator 2026-09-15).
    **Empat** tahap scan sejak 2026-09-30 (aturan 37): datang, timbang isi, timbang
    kosong, keluar. Tahap sortir tetap **tidak** di-scan: yang tahu bak sudah kosong itu
    operator line, dan tombol Lepas sudah ada di depan mata operator.
    **QR isinya cuma plat ternormalisasi** (`domain/qr.py`). Bukan seluruh data truk:
    supplier dan nama sopir berubah di ERP **sesudah** QR dicetak, jadi QR yang
    membawanya jadi bohong tanpa ada yang tahu, dan nama sopir itu data pribadi yang
    menempel di kaca truk. Bukan id truk ERP: truk **pinjaman** belum terdaftar, jadi
    belum punya id, jadi tidak bisa di-scan, padahal itu kasus yang mau dipecahkan
    (S4). Nama sopir tetap diambil, tapi dari `Truck.driver_name` di ERP, dan boleh
    ditimpa ketikan operator per kunjungan (`upsert_visit` sudah menerimanya).
    `ScanService` **cuma mencari**: tidak membuat truk (satu QR salah baca akan
    menambah truk hantu yang naik ke AutoERP lewat interface B) dan tidak menulis berat
    (dua penulis untuk angka yang dibayar adalah cara paling rapi untuk salah bayar
    berbulan-bulan). Id truknya diturunkan dari plat, **aturan yang sama** dengan
    `catat_timbangan`: kalau beda, satu kunjungan bisa mendarat di dua truk.
    **Kartu QR dibuat di server, bukan pustaka CDN** (`services/qr_cetak.py`, `segno`
    pure-Python 77 KB): `console.html` nol referensi `https://` dengan sengaja, dan QR
    yang gagal dimuat berarti gerbang timbangan berhenti. Koreksi kesalahan `m` (15%),
    kartunya hidup di kaca truk, dan `l` (7%) terlalu tipis untuk hujan dan debu sawit.
    Kartunya **dipatok putih dengan tulisan hitam**, tidak ikut tema: QR gelap di latar
    gelap tidak terbaca scanner mana pun. Halaman cetak menunggu semua gambar dimuat
    sebelum `print()`: dialog yang muncul terlalu cepat mencetak kotak kosong, dan itu
    setumpuk kertas terbuang yang baru terlihat sesudahnya. `@media print`
    menyembunyikan kamera, tally, tab, dan tabel: tanpa itu puluhan lembar terbuang
    sebelum kartu pertama muncul.
    **Satu kolom scan di tab Timbangan** (sejak 2026-10-07 scan jalan di semua tab, lihat di bawah; user 2026-10-06, menggantikan empat kolom per
    langkah). Markup-nya `hidden`; saklar **Scanner QR** di tab Setelan (support saja, bawaan
    mati, kunci `setelan_scanner_qr` di `sync_state`, 2026-10-05) memunculkannya di semua layar
    lewat polling 2 detik. Daftar plat, **Catat datang**, dan tombol di baris tiket tetap ada.
    Operator tidak memilih kolom: `POST /api/console/scan/auto {qr, at, konfirmasi?}`
    (`services/scan_otomatis.py`) membaca keadaan truk dan mencatat langkah berikutnya
    (`domain/gerbang.putuskan_langkah`): tiket tanpa tara dalam jendela 12 jam = timbang kosong
    (dua tiket = `ganda`, operator memilih di tabel, tidak ditebak); tiket bertara yang belum
    keluar, belum selesai "tanpa scan 4", dan timbang kosongnya kurang dari 2 jam lalu
    (`JENDELA_SCAN_KELUAR`) = keluar (lebih lama = truknya kembali untuk kunjungan baru, jadi
    datang, dan tiket lama selesai tanpa scan 4 tanpa jam keluar karangan); kedatangan yang menunggu = timbang isi;
    selain itu = datang. Ini **bukan** menebak: langkahnya diturunkan dari data yang sudah ada,
    dan QR tetap cuma membawa plat. Datang dan keluar tetap ditulis `GateService`, berat tetap
    ditulis `record_weighing` (aturan 15). Berat diambil dari timbangan live kalau layak
    (aturan 39); kalau tidak, jawabannya `perlu_berat` dan layar membuka popup berat yang sudah
    terisi platnya, operator mengetik angka lalu Enter. Truk yang belum
    terdaftar boleh datang tapi tidak ditimbang (`belum_terdaftar`), truk nonaktif juga tidak
    (`nonaktif`). **Bacaan ganda:** layar membuang QR yang sama dalam 2 detik
    (`JEDA_BACA_ULANG_MS`), dan server menjawab `perlu_konfirmasi` untuk datang, timbang isi,
    atau timbang kosong yang datang kurang dari 3 menit sesudah langkah sebelumnya truk itu
    (`JEDA_SCAN_ULANG`); layar bertanya lewat `tanyaKonfirmasi`, dan cuma "Catat" yang mengirim
    ulang dengan `konfirmasi: true`. Operator menjawab tanpa mouse (user 2026-10-06): scan QR yang
    sama sekali lagi = Catat, tapi baru 2 detik sesudah pertanyaan muncul (`scanUlang`, bacaan
    ganda tidak boleh menjawab pertanyaannya sendiri); QR lain = Batal; Esc = Batal. Tanpa itu satu QR yang terbaca dua kali mencatat timbang
    isi dengan berat apa pun yang sedang di jembatan, atau timbang kosong dengan berat timbang
    isinya sendiri. Keluar tidak pernah ditanya: jam keluar yang terlalu cepat tidak merugikan.
    **Scan dari tab mana pun (user 2026-10-07).** Penangkap tombol fase-capture di
    `document` (`tangkapScan`) mengumpulkan ketikan scanner di tab apa pun, tanpa kolom yang
    harus difokuskan: jeda antar huruf paling lama 100 ms, Enter paling lama 500 ms sesudah
    huruf terakhir, minimal 3 karakter. Larian cepat yang putus di tengah = bacaan gagal
    ("Scan tidak terbaca, ulangi scan"), tidak pernah dikirim setengah. Kolom `#scan-otomatis`
    di tab Timbangan tetap ada untuk mengetik plat dengan tangan dan tetap **memegang fokus**
    selama tab itu terbuka (`jagaFokusScan`, tidak pernah merebut dari kolom ketik lain, daftar
    terbuka, atau dialog), tapi scan tidak bergantung padanya. Spasi+N (Manual Reject) dan P+N (piston) dijaga `ledakanScan()`: baru dianggap
    ketikan scanner kalau sudah ada 3 karakter cepat, jadi plat `B 1995 SME` (ada " 1") tidak
    menembakkan Reject, dan menahan Spasi lalu menekan 1 dengan tangan tetap me-reject. Enter
    datang dari scanner sendiri (terbukti 2026-10-06 dengan CASHCOW HC-4208DB lewat Bluetooth
    di Mac, skill `scanner-qr`). **Hasilnya popup, bukan toast** (`#scan-popup`, `div` bukan
    dialog; latar padat, warna dan nomor langkah sama dengan kolom papan Timbangan: datang abu,
    timbang isi kuning, timbang kosong biru, keluar hijau, gagal merah; Lampung 2026-10-08):
    sukses menutup sendiri dalam 4 detik, gagal dan peringatan 8 detik, isinya
    langkah, plat, berat, supplier, dan line menurut urutan kartu (`teksPopupScan`). Berat yang
    belum bisa diambil dari timbangan (`perlu_berat`) membuka popup berat dengan kolom angka:
    Enter menyimpan, scan QR yang sama = simpan, scan QR lain menutupnya dan mengirim QR itu,
    Esc atau 60 detik tanpa tombol menutupnya; huruf tidak pernah masuk jadi berat. Bar tara
    dan kotak Bruto di tab Timbangan tidak disentuh lagi oleh scan, tetap untuk ketik tangan,
    dan satu pembentuk muatan (`muatanBruto`/`muatanTara`) dipakai bersama. **Hasil scan tidak
    lewat banner global**: `refresh()` membersihkan banner tiap berhasil, jadi pesan di sana
    hilang dalam 2 detik (ketemu di browser); `#scan-otomatis-pesan` tinggal untuk peringatan
    di bawah kolom.
    **`BUKAN_PLAT` kode tersendiri, bukan `PLAT_KOSONG`**: layar menerjemahkan per kode, dan
    QR berisi URL yang dijawab "tidak boleh kosong" adalah pesan salah di depan operator.
    Rute lama `POST /api/console/scan` dan `/scan/keluar` (`ScanService`, cuma mencari) masih
    ada tapi tidak dipakai layar lagi.
    **Tara diisi di bar tara (`#tara-grup`) di bawah kedua form, bukan dialog yang menutup layar**
    (dua kali dilaporkan operator 2026-09-15). `prompt()` bawaan browser ditolak lebih
    dulu: kotaknya kecil untuk jempol bersarung tangan, ukurannya tidak bisa diatur, dan
    menerima teks apa pun tanpa validasi. Lalu dialog sendiri **juga** ditolak, dan
    alasannya lebih penting: lapisan yang menutup layar menghilangkan kamera line dan
    ringkasan hari ini sampai tara selesai diisi, dan di gerbang yang sibuk itu kehilangan
    pandangan justru saat paling butuh. (Ini soal mengisi angka; pertanyaan ya/tidak memakai
    `tanyaKonfirmasi`, coding standard F12.) Bar itu **tersembunyi sampai Timbang kosong ditekan
    di baris tiket**: kolom yang bisa diisi tanpa tiket adalah kolom yang tidak tahu harus menulis ke mana.
    Platnya disebut di sebelahnya: operator melihat beberapa truk sehari sambil memegang
    HP supir. Angkanya divalidasi **di layar** sebelum dikirim, karena bolak-balik
    jaringan untuk hal yang terlihat di tempat itu satu detik yang hilang di gerbang;
    server tetap yang berwenang. Gagal kirim **tidak menutup kolomnya**: angkanya masih
    di situ, jadi bisa dibetulkan tanpa mengetik ulang. Koma diterima sebagai desimal
    (papan ketik Indonesia).
    ⚠️ **`MINIMUM_BERAT_KG` = 1 ton, bukan 100 kg.** Lantai lama meloloskan `100` persis
    (perbandingannya `<`), dan itu mendarat di layar pabrik sebagai tiket sungguhan.
    Truk teringan yang benar-benar datang sekitar 2,5 t kosong, jadi satu ton masih
    melewati setiap timbangan nyata sambil menangkap salah ketik pemisah ribuan.
    **Input manual tetap ada dan tidak boleh dihapus**: truk pinjaman, dan layar HP
    retak / gelap / kena matahari langsung adalah kasus nyata di gerbang.
19. **Login konsol: email + sandi, dua sumber akun, diverifikasi offline** (Fase 4, §6.5).
    Akun datang dari dua tempat dan barisnya menyimpan yang mana (`operators.origin`):
    `erp` ditarik dari DocType **`AutoGrade Operator`** (dibuat 2026-09-15, §4.A,
    `name, email, full_name, active, password_hash, modified`, kursor `erp_cursor_operator`),
    `lokal` ditulis `make operator` di PC itu (akun bawaan + akun support, satu-satunya cara
    membuka pabrik yang belum pernah dapat internet). **Tidak ada yang boleh menimpa milik
    yang lain**: tarikan yang meratakan akun lokal mematikan jalan masuk justru saat internet
    mati, dan CLI yang menimpa akun ERP bikin pabrik beda dengan pembukuan sampai ada yang
    sadar. `active=0` dari ERP → status `off` **dan** sesinya dihapus.
    **`password_hash` sengaja field `Data` yang bisa dibaca REST**, bukan `Password`:
    fieldtype `Password` hidup di `__Auth` yang tidak pernah dilayani REST, jadi tidak ada
    yang bisa ditarik dan login offline mustahil. Yang keluar dari ERP hash, bukan sandi.
    **Dua skema hash hidup bersebelahan**: `pbkdf2_sha256` milik passlib AutoERP (diverifikasi
    pakai `hashlib` saja: tidak ada dependensi baru di pabrik; ⚠️ passlib menulis base64
    dialeknya sendiri, `.` untuk `+` tanpa padding, dan salah decode = separuh akun ditolak
    padahal sandinya benar) dan `scrypt` untuk akun lokal. `_verify_scrypt` **hanya** menerima
    parameter yang ditulis build ini (barisnya data dan bisa diubah); rounds pbkdf2 **diikuti**
    di atas lantai minimum, karena AutoERP yang punya biaya itu dan boleh menaikkannya.
    Sesi di `sesi`, **geser** sejak batch 5.7 (2026-10-05): berakhir 12 jam sesudah aktivitas
    operator terakhir, bukan 12 jam sesudah login (pabrik jalan ±20 jam; sesi tetap 12 jam dulu
    menjatuhkan gerbang login di atas kamera di tengah shift). Aktivitas = sentuhan atau tombol
    keyboard di layar; layar mengirim `POST /api/console/session/renew` paling sering sekali per
    5 menit, dan langsung kalau sisa sesi 15 menit atau kurang (pita kuning di layar). **Polling
    layar tidak pernah memperpanjang**: kalau iya, layar yang ditinggal tidak akan pernah keluar
    sendiri. Sesi yang sudah habis tidak bisa dihidupkan lagi lewat renew. `/me` dan login
    membawa `sisa_detik` (detik, bukan jam: jam browser bisa beda dengan jam konsol), dan renew
    mengirim ulang cookie dengan umur penuh. Hitungan sandi salah di disk (lockout 5× lalu berlipat dua sampai
    15 menit), karena di memori muat-ulang halaman akan mengosongkannya. Reset sandi **dan**
    mematikan operator sama-sama menghapus sesinya, menyaring status saja akan menghidupkan
    token lama begitu akun diaktifkan lagi. Satu jawaban untuk sandi salah / akun tidak ada /
    akun mati, supaya layar bersama tidak bisa dipakai memetakan siapa yang punya akun.
    Sandi minimal 8 karakter, tanpa aturan jenis karakter (aturan yang memaksa simbol di
    layar sentuh luar ruangan berakhir jadi tulisan di monitor).
    **Akun `lokal` diurus dari DUA jalan, dengan aturan yang sama** (`services/operator_admin.py`):
    `make operator` di PC itu, dan sejak 2026-09-26 tab **Akun** (support): tambah, ganti sandi,
    matikan/aktifkan, ubah role. Dulu aturannya "tidak ada lane web untuk membuat akun" (akun
    yang bisa dibuat dari layar = akun yang bisa dibuat siapa pun di LAN pabrik); dibalik atas
    permintaan user supaya support tidak perlu AnyDesk + terminal. Pengamannya: `require_support`
    di keempat rute, dan tiap perubahan satu WARNING menyebut email pelakunya (muncul di tab
    Log, tanpa sandi). Beda layar dengan terminal, sengaja: **Tambah menolak email yang sudah
    ada** (di terminal itu berarti reset; form "akun baru" yang diam-diam mengganti sandi orang
    lain adalah kejutan buruk), **ganti sandi tidak menghidupkan akun yang dimatikan** (di layar
    itu tombol sendiri), dan **akun sendiri tidak bisa dimatikan atau diturunkan role-nya**
    (satu klik salah bisa meninggalkan PC tanpa support). Akun `erp` **tidak disentuh sama
    sekali** dari layar, bahkan matikan (terminal masih bisa, untuk mengusir orang yang keluar
    sebelum tarikan berikutnya).
    ⚠️ **Akun lokal tidak pernah naik ke AutoERP**: arah akun cuma AutoERP → PC. Dan karena
    tarikan tidak menimpa akun lokal, email yang kelak dibuatkan akun di AutoERP tetap memakai
    akun lokalnya di PC ini (sandi lokal, role lokal) sampai akun lokal itu diurus; tidak ada
    pesan apa pun. Pakai email yang tidak dipakai di AutoERP.
    **Dua akun bawaan di tiap image** (`services/akun_bawaan.py`, dipanggil di lifespan
    konsol): `operator@autograde.local` + `support@autograde.local`. Alasannya PC yang baru
    dipasang belum pernah dapat internet, jadi akun AutoERP belum turun, tanpa ini
    konsolnya layar terkunci di hari dia paling dibutuhkan. Email dipatok supaya support
    tidak perlu menebak; **sandi beda per PKS** (keputusan operator 2026-09-15), dibuat
    `make hash-sandi` saat pasang PC. Yang ditanam **hash** lewat build arg
    `CONSOLE_DEFAULT_HASH`/`CONSOLE_SUPPORT_HASH`, **jangan pernah sandi mentah**: PC pabrik
    bisa diakses AnyDesk dan layer image terbaca siapa pun yang pegang image. Hash yang
    tidak berawalan `$pbkdf2-sha256$`/`scrypt$` **ditolak dan di-`logger.error`**, itu yang
    menangkap `$` dimakan compose (`$$` untuk satu `$`) dan sandi mentah yang keliru
    dimasukkan. Seed **cuma bikin kalau email belum ada**: restart tidak boleh memulihkan
    sandi pabrikan di akun yang sandinya sudah diganti, dan tidak boleh menghidupkan akun
    yang sudah sengaja dimatikan.
21. **Lane developer: backend yang menjaga, layar cuma merapikan** (Task 14, 2026-09-15).
    Semua `/api/console/dev/*` (termasuk saklar Scanner QR dan Timbangan dummy) (tabel di `docs/backend-overview.md` § HTTP Surface) lewat
    `require_support`, itu yang
    sebenarnya menolak 403, dan tab developer yang disembunyikan dari operator biasa di
    `console.html` cuma kerapian, bukan pengaman: siapa pun yang tahu URL-nya tetap
    ditolak backend kalau `role` bukan `support`. Elemen `data-dev="1"` dibuang dari DOM
    untuk non-support dan **dikembalikan ke tempatnya** saat akun support masuk di halaman
    yang sama (`aturTabDeveloper`); tab yang diingat tapi sudah dibuang jatuh ke Grading
    (`pastikanTabTersedia`). Dulu cuma dibuang: operator yang mewarisi tab Setelan dapat
    layar kosong, dan support sesudahnya harus memuat ulang halaman (tes staging 2026-09-28).
    **Sembilan tab sejak 2026-09-28** (dulu 15, "tab kebanyakan"): **Rekap** = Rekap + Riwayat
    (dibuka di Hari ini, Per truk), **Status** = lima sub-tab sejak 2026-10-05 (Versi & pembaruan,
    Diagnostik, Antrean line ke konsol, Antrean ERP, Manifest R2; `SUB_STATUS`, diingat
    `subStatus`, satu bagian tampil sekaligus; dulu bertumpuk),
    **Line** = Sumber Kamera + Model Deteksi + Uji PLC + Rekam Video sebagai empat sub-tab
    bergaris bawah (`SUB_LINE`, diingat di localStorage `subLine`, panel `sub-*`). Nama tab lama yang
    masih tersimpan dipetakan `tabDariSimpanan`/`TAB_LAMA`, bukan jatuh ke Grading. Timer ikut
    yang terlihat (`bukaTabDev`): diagnostik 5 s di Status, PLC 1 s dan rekam 3 s cuma di
    pilihan Line-nya, Rekap 15 s (`segarkanRekap`) hanya kalau rentangnya memuat hari ini dan
    tanggal di kotak belum diubah (yang sedang diketik tidak boleh tertimpa).
    **`ERP_ALLOWED_ROLES`** (bawaan `support`) membatasi role mana yang boleh datang
    dari AutoERP (`domain/role.py`, `filter_erp_role`): **satu-satunya rem sisi
    pabrik**: kosongkan lalu restart, dan tidak ada akun ERP yang bisa membuka layar
    developer lagi, tanpa perlu menyentuh AutoERP sama sekali. Akun `lokal` (dibuat
    `make operator` atau tab Akun) tidak lewat penyaring ini.
    **`event_log` cuma menyimpan ERROR dan WARNING**, retensi 180 hari
    (`LOG_RETENSI_HARI`). Pesan identik yang datang dalam 60 detik **digabung** jadi satu
    (sejak batch 3.3 "identik" dihitung sesudah uuid, id hex 8+, desimal lepas, dan bilangan
    6+ digit dinormalkan, `domain/sidik_log.py`; kode HTTP, port, IP, plat TIDAK; dan
    `ringkas_galat` ikut sidik: KELAS = kepala blok traceback pertama (galat berantai: akar
    penyebabnya), kosong kalau detailnya dipotong `potong_detail` (walau kepalanya masih ada),
    satu-satunya bagian yang pernah ditampilkan (Discord); FRAME = frame `palmgrade/` terakhir di seluruh detail,
    tanpa itu frame terakhir, cuma di-hash. Jadi dua 500 uvicorn yang pesannya sama "Exception
    in ASGI application" tapi sebabnya beda tetap dua baris dengan traceback masing-masing,
    galat yang sama dengan plat/jam/jalur berbeda di teksnya tetap satu baris, dan teks pesan
    galat tidak pernah terbaca sebagai kelas. Di belakang `LicenseGuardMiddleware` sebuah 500
    konsol dicetak dengan blok ExceptionGroup lebih dulu, jadi Discord tidak menampilkan
    kelasnya; sidiknya tetap terpisah lewat frame) baris dengan hitungan naik, bukan baris baru per kejadian, tanpa itu satu loop yang
    gagal tiap detik akan memenuhi tabel dalam semenit dan mendorong keluar galat lain
    yang lebih tua. `redaksi()` (`domain/log_redaksi.py`) menyaring rahasia **sebelum**
    baris menyentuh disk, bukan saat ditampilkan: berkasnya dibaca lewat AnyDesk
    berbulan-bulan kemudian, dan sandi/token yang sempat mendarat di disk sudah bocor
    walau layarnya sendiri tidak pernah menampilkannya. Sejak batch 3.2 tabel yang sama
    memuat WARNING/ERROR ketiga line (kolom `line_code`), ditarik konsol tiap 10 detik dari
    `log_line.db` tiap line; baris line tidak ikut digabung dengan pesan konsol.
    **Uji PLC satu-satunya aksi konsol yang menggerakkan hardware fisik**, dan bawa tiga
    pengaman sekaligus: **ditolak selama line itu punya assignment**, dicek di proses
    line yang memegang `RuntimeState`-nya sendiri, **bukan** di konsol, karena konsol
    tidak pernah tahu keadaan line sebenarnya selain lewat jawabannya; **konfirmasi
    ketik**, bukan klik, karena layar sentuh bisa mendaftarkan sentuhan tak sengaja
    sebagai klik tapi tidak akan pernah mengetik kata yang benar tanpa maksud; dan
    **setiap percobaan dicatat WARNING** menyebut operator, coil, dan line, baik
    dipicu maupun ditolak: supaya ada jejak siapa menekan apa kalau ada insiden,
    ditolak atau tidak.
    **PKS tanpa satu pun akun `support` tidak bisa membuka lane developer sama sekali**,
    bukan cuma tab yang hilang, seluruh menunya buntu di 403. Lifespan konsol memeriksa
    ini saat startup dan `logger.warning` kalau kosong, supaya yang pasang PC tahu
    sebelum AnyDesk pertama yang butuh layar ini datang.
    **Di luar tab Log tidak ada teks galat sistem** (keputusan user 2026-10-01, sesudah tes
    PR #200): tidak ada kode HTTP, alamat, teks exception atau jawaban server, nama env atau
    konfigurasi, nama berkas, atau kode galat (`AI_MATI`, `RESTART_LAMA`, ...) di layar mana
    pun selain tab Log; kalimatnya tetap menyebut apa yang terjadi, line mana, sejak kapan, dan
    harus apa. `alasan()` memulangkan kalimat umum untuk kode asing, diawali konteks pemanggil
    (`gagalKarena` untuk awalan): `err_ditolak` (nilai yang ditolak) untuk 4xx tanpa kode kecuali 404,
    `err_umum` untuk 404, 5xx, dan selebihnya, dan `err_konsol_putus` untuk konsol yang tidak menjawab sama
    sekali (`ambil`), tidak pernah `e.message`. Line yang tidak terbaca konsol diklasifikasi
    backend (`domain/line_tak_terbaca.py`, `sebab_kode` di kartu Diagnostik, Antrean line, dan
    snapshot `LineStatusWorker`), kiriman AutoERP/R2 yang tertahan membawa `error_kind` (kolom
    `erp_outbox.error_kind`, ditulis worker-nya, dikosongkan saat diantre ulang, Kirim Ulang,
    atau terkirim; aman untuk mundur versi: build lama mengabaikan kolomnya, dan baris yang ia
    tandai gagal membawa jenis lama sampai diantre ulang), model yang tidak bisa dipakai membawa
    `alasan_kode`, alarm PLC yang tidak dikenal jatuh ke `alarm_lain`; layar menerjemahkan
    semuanya lewat KAMUS dan kode yang tidak dikenal jatuh ke kalimat umum. Satu-satunya
    pengecualian: kalimat info di layar support boleh menyebut folder rekaman (`rekamSelesai`,
    `rekamCatatanRetensi`, `bahayaRekamanTeks`), karena support harus menemukan berkasnya;
    kalimat galat tidak pernah memuat jalur atau perintah. Teks mentahnya ada di tab Log: ketiga
    pembaca line di konsol (`LineStatusWorker`, kartu Diagnostik, Antrean line) memakai satu
    aturan (`domain/episode_tak_terbaca.py`, `services/jejak_tak_terbaca.py`, per line): SATU
    WARNING dengan sebab dan alasan mentah PERTAMA kejadian sesudah tiga poll gagal berturut,
    sebab yang berganti tidak menulis apa pun, SATU WARNING saat pulih dengan lama sejak poll
    gagal pertama, dan 120 detik pertama sesudah konsol menyala (`TENGGANG_START_S`, line masih
    memuat model) tidak menulis awal kejadian. Penolakan operator tanpa kode (`_operator_error`
    dengan ValueError) dicatat WARNING. Penjaga:
    `tests/unit/test_console_html_teks_ramah.py` (KAMUS id/en, teks statis, perilaku lewat
    node) dan `tests/unit/test_console_copy.py` (pesan log juga tanpa em dash).
22. **Lisensi: pabrik MEMERIKSA, AutoERP yang MENERBITKAN** (2026-09-22).
    Token JWS Ed25519 dicetak DocType `AutoGrade Licence` di AutoERP (dulu
    palmgrade-api, yang mati 2026-09-20) dan dipasang teknisi dengan
    `autograde.sh licence <token>`. Repo ini **tidak berubah sedikit pun** di sisi
    verifikasi: kunci publik yang sama, `LicenseManager` yang sama, nol HTTP.
    ⚠️ **Fail closed di tiga titik**, dan ketiganya harus tetap ada: worker deteksi
    (`grading_blocked`, gerbang sesungguhnya), heartbeat PLC (`license_ok`), dan
    middleware HTTP line. Gate login saja tidak cukup, grading jalan di thread
    background yang tidak lewat HTTP, jadi dashboard mati sementara kamera tetap
    menyortir buah.
    **Konsol memverifikasi tokennya SENDIRI**, tidak bertanya ke line: konsol proses
    terpisah tapi memakai `.env` dan image yang sama, jadi sumbernya satu, dan line
    yang sedang restart tidak boleh membuat langganan terlihat rusak.
    `license/summary.py` sengaja modul sendiri dan murni (alasan yang sama dengan
    `gate.py`): aturan yang memutuskan apa yang dibaca operator saat pabrik berhenti
    harus punya test yang benar-benar jalan di CI.
    ⚠️ **Banner operator menumpang `/api/console/state`, BUKAN `/api/console/dev/*`.**
    Yang melihat kamera berhenti itu operator biasa, dan lane dev menjawab 403 untuk
    mereka: layar akan diam persis di saat penjelasan paling dibutuhkan. Yang ikut ke
    operator cuma tingkat keparahan, tanggal, dan nama perusahaan; nomor token tetap support-only, dan
    ada test yang menjaganya.
    Data yang sama ditulis **di kepala layar, di bawah tulisan AutoGrade, untuk semua akun** (2026-09-28,
    `teksInfoSistem`): versi + "Lisensi s/d …", warnanya dari `severity` server, bukan
    dihitung ulang. Klik membuka kotak detail (`barisInfoSistem`), yang berbagi
    `barisLisensi` dengan tab Status (bagian Versi). Fitur lisensi mati = versi saja, supaya kata "mati"
    tidak terbaca sebagai kerusakan di layar operator.
    ⚠️ **Token yang tidak terbaca diperlakukan sama dengan habis.** Kebalikannya
    berarti token rusak = gratis.

23. **Rekam video developer: grading tidak pernah melambat karenanya** (2026-09-22).
    Layar **Rekam Video** (`role=support`) merekam frame kamera ke MP4, satu tombol
    per line, jalan sampai ditekan Stop. Titik sadapnya `FrameCaptureWorker`:
    **sebelum** inference: jadi yang terekam **clean tanpa bbox** tanpa kerja
    tambahan, dan itu memang yang berguna (bbox adalah prediksi model sendiri).
    ⚠️ **Encode WAJIB di thread sendiri, dan antrean penuh MEMBUANG frame.**
    `VideoRecorder.tulis()` dipanggil tiap frame dari thread capture dan harus
    kembali seketika; menahannya akan mengembalikan persis lag ~590 ms yang
    dihilangkan autograde#112. Yang dikorbankan videonya (bolong), bukan
    deteksinya: `frame_dibuang` di layar adalah alat ukurnya. Diukur 2026-09-22:
    fps deteksi **+0,1%** dengan rekaman jalan, `frame_dibuang` nol (diukur di Mac dengan
    video Lampung; belum diukur di PC Lampung sendiri).
    ⚠️ **Recorder yang rusak tidak boleh menjatuhkan line**: panggilannya
    dibungkus `try` di capture worker. Fitur developer tidak boleh bisa
    mematikan produksi.
    **Stop menulis dulu frame yang sudah antre saat Stop ditekan** (2026-09-30), paling
    banyak sebesar antrean (30 frame, isi antrean dihitung saat encoder melihat Stop), jadi
    Stop lebih lama paling banyak 30 frame (di Mac ±0,6 dtk; belum diukur di Lampung). Dulu
    isi antrean dibuang: ekor tiap rekaman hilang, dan encoder yang telat siap menutup berkas
    tanpa satu frame pun. Rem disk tetap berhenti seketika. `POST /internal/rekam/stop` itu
    `def` (threadpool), bukan `async def`: pengurasan itu tidak boleh membekukan event loop
    line (`/health`, MJPEG).
    **Codec `avc1` (H.264), fallback `mp4v`**: diukur 5x lebih kecil (0,48 vs
    2,40 GB/jam pada 1280x1024 @ 5 fps). Fallback-nya bukan hiasan: `avc1` tidak
    ada di setiap build OpenCV, dan `VideoWriter` yang gagal membuka **tidak
    melempar**: tanpa pemeriksaan `isOpened()` hasilnya berkas 0 byte yang baru
    ketahuan berjam-jam kemudian.
    **Setelan (resolusi) hidup di konsol**, satu baris `sync_state`,
    pola yang sama dengan `setelan_grading`, dan dikirim ulang tiap kali mulai.
    Itu yang membuat **restart container = rekaman mati** jadi sifat, bukan kode
    tambahan. Setelan baru sengaja **tidak** menyentuh rekaman yang sedang jalan:
    mengubah resolusi di tengah berkas MP4 menghasilkan berkas rusak.
    ⚠️ **FPS TIDAK datang dari setelan layar** (sejak v1.13.2). Ia datang dari
    laju yang BENAR-BENAR dipakai mengambil frame, dipublikasikan worker ke
    `RuntimeState.camera_fps_terukur`: berkas video memakai laju aslinya
    (`CAMERA_FPS` diabaikan untuk berkas: menyetel `CAP_PROP_FPS` pada berkas
    cuma membuat `get_fps()` membalas angka yang dipaksakan), kamera yang tidak
    bisa melapor memakai `CAMERA_FPS`. Kolom FPS di layar **dicabut 2026-09-25**
    (bersama Bitrate, yang tidak pernah diteruskan ke encoder): `fps` di
    `setelan_rekam.BAWAAN` tinggal cadangan terakhir kalau keduanya tidak ada
    (`CAMERA_FPS=0`). Dua kali salah di sini menghasilkan gejala yang sama dan tidak
    pernah melempar galat: berkas ada, terbuka, isinya lengkap, cuma jamnya
    salah, jadi terbaca seperti kamera lambat, bukan header yang keliru
    (19 detik kejadian jadi berkas 77 detik, Lampung 2026-09-23).
    ⚠️ Dibaca dari `RuntimeState`, **bukan** `_target_fps` milik worker:
    `adopt_camera_frame_rate()` cuma memperbarui `_frame_interval`, jadi
    `_target_fps` tetap nilai `.env` pada kamera yang melapor.
    ⚠️ **`videos/` di luar `artifacts/` dan TIDAK ikut retensi otomatis.**
    `BatchUploadWorker._retention()` menyapu `artifacts/`; rekaman yang duduk di
    sana akan terhapus diam-diam di tengah penelusuran masalah. Harganya:
    berkasnya menumpuk sampai ada yang menghapusnya, karena itu layar
    mengatakannya, dan rekaman berhenti sendiri di bawah
    `UPLOAD_DISK_MIN_FREE_GB` (20 GB). Disk penuh berarti grading berhenti
    menulis, yaitu pabrik berhenti.

24. **Alarm PLC: satu pita untuk seluruh layar, bukan per kartu** (2026-09-23).
    Bit yang dibaca dari PLC (M1100–M1111: motor 1–11 fault, E-stop) dulu berhenti
    di **Uji PLC** (tab Line) yang support-only dan di `/health/detail`, **layar operator
    nol**. Sekarang jalurnya `domain/plc_alarm.py` (bit → kode alarm, logika murni)
    → `/internal/status.alarms` → `LineStatusWorker` → `/api/console/state` →
    `gambarPitaAlarm()`.
    ⚠️ **Satu pita global, dideduplikasi.** Ketiga proses line membaca **blok M yang
    sama** dari satu PLC, jadi motor fault itu keadaan pabrik, bukan keadaan line,
    tanpa dedup satu motor mati terbaca "MOTOR 3 FAULT" tiga kali dan operator
    mengira tiga motor mati. Kunci dedup kode **+ nomor**: kode saja membuat MOTOR 5
    ditelan MOTOR 3.
    **Menumpang `/internal/status`** yang sudah di-poll tiap 1 detik untuk piston,
    nol endpoint baru, nol worker baru. Alasan yang sama dengan banner lisensi
    (aturan 22): yang melihat motor mati itu operator biasa, dan lane `dev/*`
    menjawab 403 untuk mereka.
    **E-stop = TANDA SAJA; grading tidak dihentikan** (keputusan 2026-09-23).
    Menghentikan kamera saat E-stop adalah keputusan keselamatan yang butuh
    konfirmasi tim PLC: tercatat sebagai butir 5 di `docs/plc-mc-handoff.md` bab 5.
    ⚠️ **Polaritas diasumsikan bit ON = fault/ditekan, BELUM dikonfirmasi.** Kalau
    ladder menulis kebalikannya (NC), pita menyala terus saat pabrik sehat. Sengaja
    **tidak** dikompensasi di kode: menebak berarti memilih antara alarm palsu terus
    -menerus atau diam saat E-stop benar-benar ditekan.
    Uji PLC **tidak** menampilkan bit yang dibaca (daftar `M1100 MOTOR 1 = Off`
    per kartu dicabut 2026-09-24: tiga kartu memuat 16 baris yang sama); bit itu
    hanya hidup di pita alarm operator dan `/health/detail`. Yang di tab: tombol coil
    + peta alamat statis di bawahnya.
    **Tersambung di Lampung 2026-09-23** (3 line, M1000/M1001/M1111 terbukti). Tiga
    jebakan yang memakan sore itu, semuanya di luar kode: `docker-compose.yml` hidup di
    HOST (pull tidak menyentuhnya), `.env` menang atas compose, dan **satu Open Setting
    PLC = satu koneksi**: karena itu `PLC_PORT` literal per line 1025/1026/1027, dijaga
    `test_plc_docs_match_compose`. Runbook: `docs/runbooks/2026-09-23-commissioning-plc-lampung.md`.
    ⚠️ **Tiga tambahan 2026-09-23 malam, semuanya tanpa menyentuh jalur yang sudah
    terbukti** (permintaan tim PLC): (a) **`PLC_HOLD_MS`**: 0 = pulse (bawaan),
    > 0 menukar scheduler dengan `HoldScheduler` lewat `build_scheduler()`, coil OK/NG
    ditahan ON dan diperpanjang tiap janjang; **PLC tidak bisa menghitung janjang di mode
    ini**, jadi untuk produksi tetap pulse + latch di ladder. (b) **coil ERROR masuk
    `testable_coils`** supaya M1002/M1005/M1008 bisa dibuktikan terpasang, `PlcWorker`
    melewati penulisan level ERROR selama pulse uji berjalan (`_scheduler_is_active`),
    kalau tidak pulse langsung ditimpa level sehat di tick yang sama. (c) **Uji PLC
    punya timer 1 detik**: sebelumnya `muatPlc()` cuma jalan sekali saat tab dibuka, jadi
    bit motor/E-stop di layar adalah foto lama; terbaca di pabrik sebagai "PLC-nya delay"
    padahal `PlcWorker` membaca blok M tiap 200 ms. (d) **Timer itu memanggil
    `segarkanPlc()`, bukan `muatPlc()`** (Lampung 2026-09-24: "tab PLC Test berkedip").
    `muatPlc()` menulis ulang innerHTML seluruh kartu, jadi tombol kosong sepersekian
    detik tiap detik sampai `/dev/plc` menjawab. `segarkanPlc()` hanya menyegarkan isi
    kartu yang ada lewat `tulisKalauBeda()`, yang membandingkan dengan **string terakhir
    yang ditulis**: bukan `el.innerHTML`, karena browser menyerialkan ulang DOM sehingga
    innerHTML tak pernah sama dengan template dan tombol tetap diganti tiap detik
    (terukur 15×/5 s sebelum diperbaiki, 0× sesudahnya).

25. **Danger Zone: line menghapus datanya SENDIRI, saat BOOT; setelan & lisensi selamat** (2026-09-25).
    Kotak di bawah tab **Setelan** (support): restart semua line, logout paksa, hapus
    rekaman, hapus data transaksi, hapus semua data. Keputusan boleh/tidak di
    `domain/bahaya.py` (layar dan server memakai hasil yang sama), urutan kerjanya di
    `services/bahaya_service.py`. Aturan ini satu-satunya rancangan yang tersisa (spesifikasinya
    dihapus 2026-09-28 sesudah semuanya tercatat di sini).
    ⚠️ **Konsol tidak bisa menghapus foto line**, `artifacts/line-N` di-mount read-only ke
    konsol. Line menulis penanda `artifacts/.hapus-data`, keluar lewat urutan tutup yang sama
    dengan SIGTERM (aturan 29, `os._exit` di ujungnya), dan **awal
    lifespan `main.py`** menghapus isi `artifacts/` (kecuali sisa `license.db*` di PC yang
    belum pindah, lihat aturan pindah DB di bawah, dan kecuali `log_line.db` (sudah terbuka
    sejak proses mulai; konsol tidak menarik ulang baris lama karena kursornya tidak ikut
    dihapus)) + berkas **milik line** di `state/`
    (`MILIK_LINE_DI_STATE`, sejak
    batch 1: `upload_manifest.db*` **dan** `outbox.db*`, yang pindah dari `artifacts/` ke
    `state/` supaya tidak lagi tersaji lewat `/captures`) SEBELUM store mana pun membuka
    berkasnya (SQLite yang sedang dibuka tidak boleh dihapus dari bawah prosesnya). `license.db*`
    di `state/` **tidak** masuk `MILIK_LINE_DI_STATE`: tetap selamat di sana juga, penjaga jam
    lisensi yang sama dengan di `artifacts/`. Penanda dihapus **paling akhir** dan hanya kalau
    semuanya berhasil: boot yang terputus mengulang, bukan meninggalkan separuh data.
    ⚠️ **Penanda di `artifacts/`, dan `state/` TIDAK dikosongkan seluruhnya**: di jalur
    native (`make line` + `make console`) `state/` dipakai BERSAMA konsol dan ketiga line,
    menghapus seluruhnya menghapus `console.db` yang sedang dibuka, dan penanda bersama
    dimakan line pertama yang boot. `artifacts/` selalu milik satu line. Berkas line baru
    di `state/` wajib masuk `MILIK_LINE_DI_STATE` (`test_semua_berkas_db_di_state_digolongkan`).
    ⚠️ **Perintah ke tiga line dikirim BERSAMAAN, dan tidak satu pun menerima = BERHENTI**
    (409 `semua_line_menolak`, konsol tidak disentuh): foto semua line masih utuh, jadi
    index konsol tidak boleh hilang. Konsol cuma dikosongkan kalau **minimal satu** line
    menerima; line yang menolak disebut per line (`versi_lama` = 404, image tanpa rute
    ini; `lisensi` = 403, middleware lisensi line menutup semua `/internal/*`; atau kode
    dari badan 409-nya), dan tombolnya **ditekan lagi** sesudah line itu beres.
    ⚠️ **Konsol MENUNGGU line mati** sebelum mengosongkan datanya sendiri: diam dulu
    selama `jeda_detik` yang dijawab line, lalu `/health` sampai **dua kali berturut-turut**
    tidak menjawab (sekali lewat tenggat = line sibuk menulis foto, bukan mati), maks 12 dtk
    (jeda 1 dtk + urutan tutup line maks 8 dtk + antrean log line dikuras maks 1 dtk (batch
    3.2, `sebelum_keluar`) + 1 dtk margin untuk dua cek `/health` berturut-turut).
    Line mulai menutup 1 detik sesudah menjawab, lalu urutan tutup sendiri maks 8 detik
    (coil mati + antrean simpan habis), lalu antrean log line dikuras maks 1 detik lagi
    sebelum `os._exit` (batch 3.2, `sebelum_keluar`, melewati `atexit`): total maks 10 detik
    dari permintaan, aturan 29. Janjang yang lewat di detik itu masih dikirim
    ke konsol: tanpa menunggu, baris grading yang fotonya sudah hilang tertinggal. Line
    yang tidak kunjung mati dilaporkan `ok:true, kode:"belum_mati"`.
    ⚠️ **Truk tidak bisa dipasang selama penghapusan**, dua penjaga, satu per jendela:
    line menolak `/internal/assignment` selama penandanya ada, dan konsol menolak
    `assign-truck` selama `store.hapus_berjalan` (409 `hapus_berjalan`, dipasang SEBELUM
    pemeriksaan ulang). Truk yang lolos digrading ke penugasan yang barisnya ikut terhapus.
    **Yang TIDAK pernah dihapus tombol ini** (beda dengan `autograde reset-data-fresh`):
    `license.db*` (penjaga jam lisensi: menghapusnya membuat jam bisa dimundurkan) dan
    kunci `sync_state` berawalan `setelan_` (setelan grading yang diam-diam kembali ke
    `.env` menggeser angka yang dibayar). Mode transaksi juga menyisakan truk, supplier,
    akun, sesi, dan kursor tarik AutoERP. Tabel console.db digolongkan di
    `GOLONGAN_TABEL_KONSOL`; tabel baru membuat `test_semua_tabel_konsol_digolongkan` merah.
    **Hambatan (409)**: line mati, truk terpasang, antrean lama line yang gagal dipindah ke
    `state/` (`outbox_lama`, aturan 28), outbox line belum kosong (tak terbaca =
    belum kosong), antrean AutoERP `pending` kalau `ERP_URL` terisi, **tiket timbang
    terbuka hari kerja berjalan atau dalam jendela kunjungan 12 jam** (bruto ada, tara belum =
    truk di tengah kunjungan, juga lewat tengah malam, dan bruto itu yang dibayar), dan (mode semua) tidak ada hash akun **support** yang
    terbaca (`hash_is_usable`, aturan yang sama dengan seed akun bawaan) DAN tidak ada
    AutoERP: tanpa akun support, Danger Zone dan seluruh lane developer terkunci. Line juga
    memeriksa truknya sendiri (409): truk bisa dipasang di antara keduanya.
    **Peringatan (tidak menghambat)**: tiket terbuka dari hari lain (sisa uji coba),
    janjang yang ditolak konsol (`outbox_failed`: selalu 0 pada line versi ini, baris itu kini
    ikut `outbox_pending` dan menahan hapus data; peringatannya tetap ada untuk line yang masih
    di image lama), kiriman AutoERP yang gagal, foto yang belum naik R2.
    Konfirmasi hapus **diketik** (`HAPUS`, huruf besar), walau Uji PLC sudah membuangnya:
    hapus data jarang dipakai dan tidak bisa dibatalkan. Tiap aksi meninggalkan satu
    WARNING `[Danger Zone] … oleh <email>`; untuk hapus data ditulis SESUDAH log
    dikosongkan, jadi ia baris pertama log baru.

26. **Riwayat (tab Rekap sejak 2026-09-28): grading lintas hari, baca saja, di koneksi SQLite sendiri** (2026-09-26).
    Untuk semua operator, bukan support: rentang tanggal kerja **maks 31 hari**
    (`domain/riwayat.py`, satu aturan untuk layar dan CSV), filter line, plat (potongan plat
    ternormalisasi, aturan `normalisasi_plat` yang sama dengan timbangan), dan hasil (Per janjang
    saja), ringkasan periode, tiga tampilan (per hari, per truk, per janjang), dan unduh CSV.
    **Impor CSV (2026-09-27): SUPPORT saja**, unduh tetap untuk semua operator. Yang diterima cuma
    CSV Per janjang buatan konsol sendiri (`KEPALA_CSV` di `domain/riwayat.py`, satu definisi untuk
    ekspor dan impor; id atau en, BOM, `'` pengaman rumus dilepas). Ringkasan per hari/per truk dan
    berkas yang disimpan ulang Excel (pemisah `;`, tanggal diubah, detik hilang) DITOLAK, tidak
    ditebak. Dua langkah: **Periksa** (tidak menyimpan apa pun) lalu **Impor** berkas yang SAMA
    (sidik sha256); satu baris salah menolak seluruh berkas. Janjang **hari ini dan sesudahnya tidak
    diimpor** (masih berjalan dan ikut kunjungan ke AutoERP); janjang impor tidak punya
    `assignment_id`, jadi tidak pernah masuk pesan kunjungan. Dedup per `event_id` (`INSERT OR
    IGNORE`), ditandai `inspections.import_batch`, ditulis per 500 janjang (lock konsol dilepas di
    antaranya), dan satu impor bisa **dibatalkan utuh**. Truk yang belum ada dibuat sebagai truk
    manual (tidak dikirim ke AutoERP, tidak dihapus saat batal); truk warisan ber-id acak dipakai,
    bukan dikembari. Catatannya di tabel `grading_imports` (ikut terhapus saat hapus transaksi).
    ⚠️ TP di CSV cuma "ya": disimpan `tp_confidence = 1.0` supaya hitungan TP sama (> 0,8).
    ⚠️ **Ripe + REJ itu SAH**: line memaksa REJ untuk buah bertumpuk atau terlalu kecil tanpa
    mengubah kelasnya. Yang ditolak cuma Unripe/JK + ACC (tidak pernah ditulis line).
    ⚠️ **Query-nya di `repositories/riwayat_repository.py`, BUKAN `ConsoleStore`**: koneksi
    baca-saja baru per panggilan (WAL: pembaca tidak menahan penulis) dan rute `def` (thread
    pool). Lewat store konsol, query sebulan akan antre di lock yang dipakai ingest janjang dari
    tiga line. **Hitungannya sama persis dengan Rekap** (verdict dari `ripeness_status`, kelas
    dari `grade_class`, TP `tp_confidence > 0.8`): satu hari di Riwayat = hitungan `/api/console/recap` hari itu,
    dijaga `test_satu_hari_di_riwayat_sama_dengan_tab_rekap`. Neto dijumlah di query sendiri
    lalu disandingkan (aturan 17), **tidak dihitung saat disaring per line** (neto itu berat
    truk), dan hari dengan tiket tapi nol janjang tetap satu baris (kamera mati seharian harus
    terlihat). Per hari (maks 31 baris) dan per truk (ribuan baris sebulan) dikirim utuh dan
    dibagi halaman **di layar**; per janjang dibagi halaman di server, urut `work_date DESC,
    timestamp DESC` supaya indeks `(work_date, …)` terpakai. Per truk **dikelompokkan dulu, baru
    digabung** ke truk/supplier. Terukur di 620 ribu janjang (31 hari × 20 ribu): per janjang
    0,09 dtk, per hari 0,7 dtk, per truk 2 dtk, CSV janjang sebulan ~6 dtk; 7 hari: 0,15 dan
    0,4 dtk. `ringkasan=false` saat layar cuma pindah halaman/tampilan. CSV: BOM UTF-8, jam
    pabrik (`FACTORY_TZ`), sel berawalan `= + - @` diberi `'` (nama supplier bisa jadi rumus
    Excel), rasio dibulatkan seperti `Math.round` (bukan pembulatan bankir `round()`). Foto
    yang lewat retensi PC (aturan 9) sudah hilang dari disk: barisnya tetap, gambarnya diganti
    tulisan. Dulu "riwayat lintas hari = urusan cloud"; dibalik atas permintaan user karena
    cloud lama (palmgrade-api) sudah mati dan AutoERP cuma menerima rekap per truk.

27. **Last Sync: satu bagian, dua baris (AutoERP dan Cloud Photo), untuk semua operator** (2026-09-27).
    Dua pil di kepala layar sejak 2026-10-07 (dulu di ujung strip "Hari ini"). Tiap pil menjawab dua hal yang sengaja dipisah: **jam** = kapan
    data terakhir benar-benar tersinkron, **warna** = apakah sambungannya hidup SEKARANG. Foto naik
    ke R2 tiap jam, jadi "13.05" pada pukul 13.50 itu normal; warna **tidak pernah** dihitung dari
    umur jam. Aturannya murni di `domain/sinkron.py`; pencatatnya SATU `StatusSinkron`
    (`services/status_sinkron.py`) yang dibagi semua worker dan layar (`get_console_service`).
    **Yang mencatat, masing-masing sebagai SUMBER sendiri:** `tarik` (data master, 5 menit) dan
    `kirim` (antrean ke AutoERP), `manifest` (R2), dan `cek` dari `CekSinkronWorker` tiap 60 detik
    (`GET /api/method/ping`; `head_object` R2 dengan **404 = tersambung**: kuncinya diterima,
    objeknya saja belum ada). Cek cuma menggerakkan warna, **tidak menggeser jam**. Sambungan putus
    kalau SATU sumbernya sedang gagal, dan tiap sumber pulih sendiri: dulu satu catatan untuk semua
    membuat titiknya berkedip merah-hijau tiap menit (ping 401 = putus, kiriman 401 = "AutoERP
    menjawab"). **Galat jaringan = SETIAP `ErpUnavailable`** (aturan 14, batch 2.7): tanpa jawaban
    atau timeout, gateway 502/503/504, halaman 5xx yang bukan Frappe, atau 2xx yang isinya bukan
    objek JSON Frappe. Dicatat di sumber `jaringan` yang dibersihkan jawaban apa pun dari server:
    kiriman yang gagal diulang sampai sejam kemudian, dan titiknya tidak boleh merah selama itu.
    **Kiriman yang ditolak (417, 404) atau yang memicu 5xx BERAMPLOP FRAPPE (`ErpServerError`) =
    tersambung**: AutoERP menjawab, isi pesan itu yang bermasalah, per pesan, terlihat di Antrean
    ERP (tab Status); **401/403 = putus** (kunci ditolak, tidak ada yang akan sampai). **Tarikan
    data yang gagal = putus** sampai tarikan berikutnya berhasil (data tidak mengalir walau
    server hidup).
    **Cloud Photo = cek R2 konsol + blok `unggah` tiap line** (lewat `/internal/status`). Satu
    sumber gagal cukup untuk merah, `sejak` = yang paling awal. **Line mati atau versi lama TIDAK
    membuat merah**: kartunya sudah menulis OFFLINE, dan baris ini bicara soal cloud. "Menunggu"
    cuma foto `pending`; yang `image_uploaded` sudah aman di R2.
    Jam sinkron disimpan di `sync_state` (`sinkron_autoerp_terakhir`, `sinkron_r2_terakhir`) dan
    dibaca dari sana tiap polling: sesudah restart jamnya tetap, statusnya "memeriksa" sampai cek
    pertama (jam R2 yang tersimpan bukan bukti hidup), dan "hapus semua" di Danger Zone langsung
    mengosongkannya. Jam Cloud Photo tiap line cuma bergerak kalau batch itu benar-benar menaikkan
    foto, bukan karena batch-nya jalan. **Putus dan pulih =
    masing-masing SATU WARNING** di tab Log, termasuk upload foto tiap line (line menulis
    log_sink-nya sendiri ke `log_line.db` sejak batch 3.2, tapi WARNING sisi konsol ini tetap
    dicatat supaya transisinya terbaca dari sudut konsol). **Pesan galat mentah tidak
    dikirim ke layar.** ⚠️ Line yang restart melupakan status gagalnya sampai batch jam berikutnya;
    pulih baru dicatat kalau jam unggahnya benar-benar bergerak. ⚠️ **`UPLOAD_API_URL` yang masih
    menunjuk api lama yang mati** membuat Cloud Photo merah (`POST gagal`): batch berhenti di POST
    pertama yang gagal, jadi foto di belakangnya juga tidak naik ke R2. Kosongkan (Lampung sudah,
    2026-09-23).

28. **Batch 1 keamanan LAN pabrik** (2026-09-28): lubang yang ketahuan audit, ditutup tanpa
    mengubah kontrak §5 line ↔ konsol.
    **Piston butuh sesi operator** (`POST /api/console/lines/{line}/piston`), sama seperti
    manual-reject; tiap penekanan dicatat WARNING menyebut pelakunya di tab Log, dipicu atau
    ditolak (aturan yang sama dengan Uji PLC di aturan 21).
    **Semua pemeriksaan secret mesin constant-time dan fail closed**
    (`domain/rahasia.py`/`routes/penjaga_rahasia.py`): secret yang dikonfigurasi kosong tidak
    pernah membuka lane, baik `x-webhook-secret` (line → konsol, timbangan → konsol) maupun
    `x-internal-secret` (konsol → line).
    **`INTERNAL_SECRET` terpisah dari `WEBHOOK_SECRET`** (lihat `docs/backend-overview.md`
    § Integration Contracts): kosong
    atau sama dengan `WEBHOOK_SECRET` = perintah konsol → line masih memakai kunci yang juga
    dipegang program timbangan pihak ketiga (`.env` lama tetap jalan apa adanya), diisi beda =
    terpisah. Kunci yang beda antara konsol dan satu line membuat kartu line itu menulis "kunci
    ditolak" (`LINE_MENOLAK`), bukan OFFLINE: line hidup dan menjawab, cuma menolak headernya.
    Danger Zone belum ikut membedakannya (masih terbaca "line mati" kalau ditolak saat hapus
    data), follow-up yang sengaja ditunda.
    **Line dan konsol menolak boot di `APP_ENV=production`** kalau `WEBHOOK_SECRET` bawaan
    (`supersecret123`) ATAU kosong (`Settings.validate_secrets()`, dipanggil keduanya: dulu cuma
    line yang menolak). `INTERNAL_SECRET` beda aturannya: **kosong atau tidak diisi cuma warning**
    (jatuh ke `WEBHOOK_SECRET`, itulah yang membuat rilis ini backward compatible), tapi kalau
    **diisi** dan nilainya bawaan atau kosong-sesudah-dipangkas, ikut menolak boot juga.
    **`/captures` di konsol butuh sesi operator** (`CapturesBersesi`, `routes/captures.py`): tanpa
    cookie `konsol_sesi` dijawab 401 `belum_masuk`, sama dengan lane operator lain. `/captures`
    di **line** (port 8001-8003) tetap terbuka seperti sebelumnya, line tidak punya konsep sesi
    dan konsumen lain di LAN memakainya. **Kedua** mount menjawab **404** untuk `.db`/`.sqlite`/
    berkas tersembunyi apa pun sesinya (`domain/berkas_captures.py`, `StaticTanpaDb`): sebelum
    batch ini `outbox.db` dan `license.db` line ikut tersaji apa adanya di `/captures`, siapa pun
    di LAN pabrik bisa mengunduh antrean janjang dan penjaga jam lisensi.
    **`outbox.db` dan `license.db` line pindah ke `state/`** (di luar mount `/captures`, sibling
    `artifacts/`, konsisten dengan `upload_manifest.db` yang sudah di sana). Pemindahan **menyerap
    isi**, bukan memindah berkas (`os.replace` gagal EXDEV lintas bind mount Docker; PC yang
    sempat rollback bisa punya isi di dua tempat): `services/pindah_db_line.py` menyerap
    berdasarkan kunci alami (`event_id` untuk outbox, penanda jam tertinggi untuk lisensi), jadi
    boot yang terputus di tengah menyerap ulang tanpa baris ganda. Kalau `/app/state` bukan mount
    dari host (compose host belum ditambah `./state/line-N:/app/state`), keduanya **tetap** di
    `artifacts/` (tetap tidak tersaji, lihat aturan `berkas_captures` di atas) dan `logger.error`
    mencatat alasannya, bukan menghentikan line. `hapus-data` (Danger Zone) menghapus
    `state/outbox.db*` sebagai berkas milik line (`MILIK_LINE_DI_STATE`, aturan 25) dan tetap
    menyisakan `license.db*` di `state/`, sama dengan bawaan di `artifacts/`.
    ⚠️ **Serapan yang GAGAL tidak boleh terbaca "antrean kosong"** (berkas lama rusak, disk
    `state/` penuh, `MemoryError`; antrean lama dibaca per potongan, `_POTONGAN_SERAP`, satu
    commit): `artifacts/outbox.db` tertinggal dan barisnya tidak dihitung `pending_count()`.
    Tiga penjaga: `/health/detail` melapor `outbox_lama_tertinggal: true` dan `outbox_pending:
    null` (tidak diketahui; `autograde reset-data` di host cuma mengenali angka, jadi ikut
    menolak), Danger Zone menahan dengan hambatan `outbox_lama` yang menyebut line-nya, dan
    hapus-data saat boot tidak menghapus `artifacts/outbox.db*` selama folder DB line bukan
    `artifacts/` (`hapus_kalau_diminta(..., folder_db=get_folder_db_line())`). Boot berikutnya
    menyerap lagi; yang harus dikejar penyebabnya, lewat log line itu.

29. **Batch 2A: line menutup rapi sebelum keluar, dan bukti ditulis utuh** (2026-09-28).
    **Satu urutan tutup** untuk SIGTERM (`docker stop`, `autograde restart`), `/internal/restart`,
    dan `/internal/hapus-data`: mesinnya `services/penutup_line.py` (`PenutupLine`), daftar
    langkahnya `services/langkah_tutup_line.py`. Sampai batch 2.2 ketiga jalan keluar itu berbeda
    nasib: SIGTERM lewat blok lifespan sesudah `yield` (coil dimatikan, antrean simpan dihabiskan),
    sementara `/internal/restart` dan `/internal/hapus-data` memanggil `os._exit` langsung dan
    melewati keduanya, sampai 8 janjang yang sudah dipulse PLC hilang tanpa foto, sidecar, maupun
    baris di konsol, dan coil yang sedang ON tertinggal ON.
    **Tahapnya**, berurutan tapi langkah dalam satu tahap jalan BERSAMAAN: (1) coil PLC dimatikan
    **sejalan** dengan antrean simpan dihabiskan, karena keduanya sumber daya berbeda (jaringan vs
    disk) dan tidak boleh saling menunggu; (2) thread capture dihentikan lalu kamera dilepas
    (tanpa itu thread capture melihat frame kosong dan menyambungkan kamera lagi lewat
    `_try_reconnect`), dan penjadwal upload R2 dihentikan TANPA menunggu batch yang sedang jalan. Batch itu jalan di thread **daemon**
    (`UploadScheduler._jalankan_batch`): thread pool APScheduler bukan daemon, dan dulu SIGTERM
    di tengah batch jam-an membuat proses bertahan sampai SIGKILL `docker stop` (exit 137).
    **Batasnya**: `BATAS_KURAS_S` 6 detik untuk menghabiskan antrean simpan (cukup untuk antrean
    penuh, 8 antre + 1 dipegang penulis, sekitar 5,7 detik dengan fsync), `BATAS_TUTUP_S` 8 detik untuk seluruh
    urutan tutup, keduanya di bawah tenggang `docker stop` bawaan (10 detik sebelum SIGKILL). Line
    uvicorn jalan dengan `--timeout-graceful-shutdown 1`, karena `/api/video_feed` yang masih
    terbuka dulu menahan shutdown sampai SIGKILL; konsol sengaja TANPA batas itu. Anggarannya
    (SIGTERM): 1 + 0,2 + 8 masih di bawah 10 detik `docker stop`; antrean log line (batch 3.2)
    keluar lewat `atexit` di jalur ini, sudah termasuk dalam waktu itu, tanpa budget tambahan.
    `/internal/restart` dan `/internal/hapus-data` menjawab dulu, tunggu 1 detik, lalu urutan
    tutup jalan (maks 8 detik), lalu antrean log line dikuras lewat `sebelum_keluar` (batch 3.2,
    yang melewati `atexit` karena jalur ini berakhir di `os._exit`), maks 1 detik lagi: **maks
    10 detik** dari permintaan sampai proses benar-benar keluar.
    Janjang yang tidak sempat ditulis disebut satu per satu di ERROR `Tutup line: N janjang TIDAK
    tertulis ...`, bukan hilang diam-diam.
    **`os._exit` cuma hidup di `services/penutup_line.py`**, dijaga
    `test_satu_satunya_os_exit_ada_di_penutup_line` (pemindaian AST): jalan keluar baru wajib
    memanggil `get_penutup_line().keluar_nanti(jeda)`, bukan `os._exit` sendiri.
    **Watchdog berhenti menghidupkan ulang worker begitu urutan tutup mulai** (`sedang_menutup`):
    tanpa itu watchdog 10 detik akan menyalakan lagi thread yang sengaja dihentikan di tengah
    penutupan.
    `CaptureSaveWorker.tutup_pintu()` menutup pintu penerimaan **lebih dulu**: janjang yang
    digrading SESUDAH coil dimatikan tidak lagi dipulse, dan yang diserahkan sesudah pintu tertutup
    ditolak, bukan ditulis, dicatat di ERROR saat itu juga.
    Danger Zone konsol menunggu line mati sampai **12 detik** (aturan 25 di atas).
    **Bukti ditulis atomik**, batch 2.6: `integrations/storage/tulis_atomik.py` satu-satunya pola
    temp+fsync+`os.replace`+fsync folder di repo ini, dipakai `media_env_service` dan
    `tulis_penanda` (dulu masing-masing menyalin polanya sendiri). Nama sementara
    `.<nama>.<acak>.tmp` (`domain/berkas_utuh.py`) tersembunyi dari `/captures` dan dari
    `BatchUploadWorker._scan()`; izin berkas mengikuti umask proses, bukan `0600` bawaan
    `tempfile.mkstemp`. Sisa `.tmp` dari listrik padam **tidak dihapus otomatis**, cuma hapus data
    yang menyapunya.
    Aturan uploader: lihat Rule 1 di atas (foto/sidecar 0 byte atau `.tmp` = poisoned, tidak
    diunggah, tidak disapu retensi; thumbnail 0 byte dilewati; sidecar tanpa gambar diracun).

30. **Route konsol yang berat pada SQLite tidak boleh menahan event loop** (batch 2.5).
    Satu event loop melayani layar semua operator (polling `/state` tiap 2 detik) DAN kiriman
    janjang tiga line, jadi `async def` yang memanggil `ConsoleStore` sinkron menahan loop itu
    selama query jalan. Pola tab Rekap (`console_riwayat`, `def`) diperluas: route `def` (FastAPI
    menjalankannya di thread pool), atau kalau route itu juga harus `await` (`console_state`,
    yang menunggu lisensi), panggilan sinkronnya sendiri dibungkus `run_in_threadpool`.
    `login`, `console_history`, `console_trucks`, `console_weighings` (GET), `console_recap`,
    `dev_log`, dan `ingest_event` jadi `def`; rute gerbang dan antrean bongkar
    (`console_arrival`, `console_arrival_cancel`, `console_departure`, `unloading_queue_skip`)
    lahir `def`.
    **Yang sengaja tetap `async`**: route yang menunggu panggilan ke line (`assign`/`release`/
    `manual-reject`/`piston`, `record_weighing`, rekam, model, bahaya, diagnostik), yang cuma
    satu pencarian primary-key (`me`, `operators`, `scan`, `setelan`, `penugasan`, `akun`), dan
    `dev_queue`/`dev_resend` (tiga hitungan terindeks).
    **Thread safety yang membuat pindahan ini aman**: `ErpQueue._visit_lock` dipegang dari
    baca, bangun, sampai antre di `visit()` (aturan 18), urutan kuncinya **visit lock, lalu
    store lock, lalu outbox lock**; event loop boleh menunggu kunci ini beberapa milidetik saja
    (fsync saat antre), bukan lebih. `AuthService` memegang satu `threading.Lock` dari
    pemeriksaan lockout sampai hash sandi sampai pencatatan hitungan gagal (`login`), supaya
    sandi salah yang datang bersamaan tidak lolos dari lockout; harga yang diterima: login
    antre satu per satu, kira-kira satu scrypt tiap kali. `hangatkan_singleton()`
    (`routes/console_deps.py`) memanaskan service yang di-cache sejak boot, supaya permintaan
    pertama yang datang dari loop tidak sempat membangun dua instance yang sama.

31. **Antrean line ke konsol: tanpa batas nyerah** (batch 2.4, 2026-09-28, keputusan user: data
    tidak boleh hilang). `OutboxStore` tidak lagi menulis `failed`: baris cuma keluar saat konsol
    mengonfirmasi. Dulu percobaan ke-50 (±7,3 jam konsol mati) menghentikan baris itu selamanya.
    Baris `failed` tulisan versi lama **dihidupkan di tempat** saat berkas dibuka dan saat antrean
    lama diserap (`_rapikan_baris_lama`, idempoten; hitungan percobaan dan `last_error` tetap, jadi
    janjang baru tetap didahulukan). Kolom `dibuat_at` ditambah di tempat, diisi dari `timestamp`
    payload.
    **Dua jeda, dua arti** (`domain/kirim_antrean_line.py`): baris yang DITOLAK konsol (400, 422)
    mundur sendiri 5 dtk sampai 10 menit dan baris lain jalan terus; KONSOL yang bermasalah
    (tidak terjangkau, 401/403 kunci, 404/405/3xx alamat, 408/429/5xx) menjeda seluruh pengiriman
    5 dtk sampai 30 dtk dengan SATU percobaan per jeda, satu WARNING saat putus dan satu saat pulih.
    Dulu worker mencoba 20 baris tiap detik tanpa jeda begitu antrean menumpuk, tiap percobaan
    satu WARNING. 5xx sengaja dianggap konsol bermasalah, beda dari antrean AutoERP.
    **Kontak pertama sesudah boot dan transisi putus ke tersambung** menjadwalkan semua baris
    sekarang (`kirim_ulang_sekarang`) lalu antrean dikuras dalam putaran yang sama. Saat putus,
    percobaannya memakai baris yang paling jarang dicoba dan mengabaikan jadwal mundur, jadi
    konsol yang hidup lagi ketahuan dalam 30 detik walau pabrik diam.
    **Tab Status → Antrean line** (support): per line jumlah menunggu, umur janjang tertua,
    keadaan (dengan sebab, sejak kapan, dan harus ngapain), galat terakhir, dan tombol **Kirim
    Ulang** (`POST /api/console/dev/antrean/line/{line}/kirim-ulang` → `POST /internal/outbox/requeue`
    line itu: semua baris jatuh tempo sekarang dan worker dibangunkan). Kunci konsol yang ditolak
    line terbaca `line_menolak`, bukan mati.
    ⚠️ `outbox_pending` di `/health/detail` = SEMUA yang belum sampai (`COUNT(*)`), termasuk yang
    dulu menyerah; `outbox_failed` tetap ada di bentuk jawaban tapi selalu 0. Akibatnya host
    `autograde reset-data` dan Danger Zone ikut menahan hapus data selama baris yang ditolak
    konsol masih ada: disengaja, tidak ada janjang yang dibuang tanpa dilihat.
    **Baris yang DITOLAK konsol** (400/422: timestamp cacat, `ripeness_status` asing) tidak akan
    pernah sampai sendiri, jadi tidak boleh terbaca "Sedang dikirim". Line menandainya
    (`outbox_events.ditolak_at`, kolom ditambah di tempat; dikosongkan lagi kalau percobaan
    berikutnya gagal dengan cara lain) dan `/internal/outbox` membawa `ditolak`, `ditolak_at`,
    `ditolak_alasan`; layar menulis keadaan **"N janjang DITOLAK konsol"** dengan jam, alasan, dan
    saran. Konsol mencatat satu WARNING per `event_id` per proses (`ConsoleService.ingest`) supaya
    tab Log menyebutnya: line menulis log_sink-nya sendiri ke `log_line.db` sejak batch 3.2, tapi
    WARNING sisi konsol ini tetap dicatat supaya transisinya terbaca dari sudut konsol.
    **Tetap tidak ada yang dibuang otomatis**:
    cara melihat, menyimpan ke berkas, lalu menghapus satu baris ditolak dengan tangan ada di
    `docs/MANUAL.md` §7.1 (perintahnya dijaga `tests/unit/test_perintah_janjang_ditolak.py`,
    dijalankan lawan `OutboxStore` sungguhan).

32. **AI mati: satu penjaga, tiga pembaca** (batch 2.1, 2026-09-28). Sebelum ini, loop deteksi
    yang melempar exception tiap frame cuma menulis log lalu tidur satu detik selamanya: coil
    ERROR cuma mencerminkan `camera.connected`, `/health` tetap "ok", kartu line konsol tetap
    sehat, dan buah lewat tanpa disortir tanpa satu alarm pun. `services/penjaga_ai.py`
    (`PenjagaAi`, satu objek per proses line, dirakit `main.py`) sekarang jadi satu-satunya
    sumber yang dibaca ketiga pembaca, supaya ketiganya selalu sepakat.
    **AI dinyatakan mati** kalau kamera MENGIRIM gambar tapi tidak ada satu frame pun SELESAI
    digrading selama `AI_MATI_DETIK` (bawaan **30** detik, dijepit **10..600**; nilai yang bukan
    bilangan bulat atau di luar batas dijepit/jatuh ke bawaan dengan WARNING, tidak pernah
    menahan boot, aturan yang sama dengan `_plc_int`).
    **Lima keadaan lain sengaja TIDAK dilaporkan sebagai AI mati**, supaya alarm ini tidak
    pernah berteriak serigala: **baru mulai** (`memulai`, loop deteksi baru jalan atau gambar
    baru mengalir lagi sesudah jeda >5 detik, tenggangnya dihitung dari yang LEBIH BELAKANGAN
    antara loop mulai dan aliran mulai lagi, bukan cuma salah satu); **kamera putus**
    (`kamera_putus`, kartu dan coil ERROR sudah menanganinya sejak dulu); **lisensi habis**
    (`lisensi`, grading memang dihentikan sengaja, banner lisensi yang bicara); **sumber selesai**
    (`sumber_selesai`, video uji tanpa ulang yang habis, sejak batch 3.6; dulu `sumber_diam`);
    **frame berhenti** (`frame_berhenti`, kamera tersambung tapi tidak mengirim: kerusakan
    sendiri, aturan 35); dan model dengan kelas yang
    tidak cocok (inferensi tetap selesai, jadi tetap `sehat`, layar Model Deteksi yang menandai
    merah).
    **Empat stempel monotonic** di `RuntimeState` (`time.monotonic()` lewat `RuntimeState.jam`,
    bukan jam dinding: PC pabrik offline yang melompat jam saat NTP datang tidak boleh terbaca
    sebagai AI mati): `ai_dimulai_at` (ditulis SEKALI per proses, watchdog yang menyalakan ulang
    thread mati tidak memperbaruinya), `frame_terakhir_at`, `aliran_frame_sejak` (reset kalau
    jeda antar-frame >5 detik), dan `inferensi_selesai_at`. ⚠️ **`last_yolo_frame_at` (dipakai
    `DisplayWorker` untuk overlay MJPEG) sengaja TIDAK dipakai di sini**: ia distempel SEBELUM
    loop janjang, jadi exception di tengah loop janjang membuatnya tetap segar tiap detik
    walau tidak ada janjang yang selesai digrading.
    **Tiga pembaca, satu sumber**: coil ERROR PLC (`sehat_untuk_plc()`, naik untuk **kamera
    putus ATAU AI mati ATAU frame berhenti (aturan 35)**, tidak untuk lisensi habis atau sumber selesai, PLC tidak berubah sama
    sekali, no ladder change, tapi **tim PLC harus diberi tahu** M1002/M1005/M1008 sekarang
    bisa naik untuk sebab baru ini); `/health` (503 **hanya** untuk AI mati dan frame berhenti
    (aturan 35); kamera putus, lisensi, dan sumber selesai tetap 200, karena gerbang update
    `autograde.sh` (`wait_healthy`, `curl -f /health`) memundurkan versi yang tidak menjawab 200
    dalam 90 detik, dan tiga keadaan itu bukan salah versi). ⚠️ **Gerbang itu TIDAK menangkap AI yang mati sesudah start**: dia
    selesai pada 200 PERTAMA, dan probe pertama selalu jatuh di dalam tenggang `memulai` 30
    detik (`ai_dimulai_at` distempel di startup yang sama yang membuka `/health`). Rilis yang
    AI-nya mati pada frame sungguhan TIDAK di-rollback: launcher mencatat `OK vX.Y.Z` dan
    membuang image lama. 503 cuma membuat compose healthcheck dan `autograde status` menandai
    line `unhealthy`, dan tidak ada yang bertindak atasnya (lihat autoheal di bawah). Sesudah
    rilis, **lihat kartu line (atau `/health`) paling cepat 30 detik sesudah start**; dan kartu
    line konsol (merah + pita rinci lewat
    `/internal/status.ai` → `LineStatusWorker` → `/api/console/state` → `pitaAi`, `perbaruiAi`
    tiap polling). `/health/detail` **tetap 200 dan `status:"ok"` walau `ai.mati`** (load-bearing:
    `autograde reset-data` di host dan Danger Zone membaca kode HTTP-nya, bukan isinya, untuk
    memutuskan line hidup atau mati). Danger Zone yang menunggu line keluar (aturan 25, 29)
    memang membaca `/health`, jadi `LineClient.hidup()` menghitung 503 dengan `ai.mati` sebagai
    proses yang masih hidup: tanpa itu konsol berhenti menunggu sementara line masih
    menghabiskan antrean simpannya. `ai.galat_terakhir` di `/health/detail` adalah galat
    deteksi TERAKHIR sejak boot, bukan bukti ada galat SEKARANG: baca `galat_at` untuk menilai
    umurnya sebelum menyimpulkan apa pun.
    Seluruh penilaian jalan di **satu lock** (`PenjagaAi._nilai_sekarang`): jam dibaca dan
    dinilai dalam kunci yang sama, supaya PLC (5x/detik) dan HTTP yang membaca bersamaan tidak
    membalik urutan transisi dan mencatat satu kejadian jadi tiga baris log. Transisi dicatat
    sekali per perubahan, bukan tiap panggilan: masuk `ai_mati` → `logger.error`; keluar dari
    `ai_mati` → `logger.warning` **"AI %s tidak lagi dinilai mati (keadaan %s)"** (keluar bisa
    juga ke `kamera_putus`/`lisensi`/`sumber_selesai`, bukan cuma balik `sehat`).
    **Docker healthcheck TIDAK autoheal**: `restart: unless-stopped` tidak bereaksi ke
    `unhealthy`, dan tidak ada autoheal container/label di repo mana pun, jadi AI mati yang
    membuat `/health` 503 membuat line terlihat `unhealthy` di `docker ps` tapi **tidak**
    memicu restart mana pun.
    Gap `sumber_diam` yang dulu sengaja dibiarkan ditutup batch 3.6: lihat aturan 35.

33. **Log dasar: satu pemasangan, baris bertanda, transisi bukan spam** (batch 3.1, 3.3, 3.4,
    2026-09-30). `core/logging.configure_logging` dipakai line (`main.py`, konteks
    `settings.line_code`) DAN konsol (lifespan, konteks `console`, plus `SqliteLogHandler` tab
    Log; dilepas lagi di akhir lifespan). Dulu konsol tidak pernah memanggilnya: INFO dibuang,
    WARNING/ERROR tidak pernah sampai `docker logs`, dan galat 500 uvicorn berhenti di handler
    uvicorn. Format: `2026-09-30T14:03:07.123+07:00 | WARNING | line-2 | palmgrade.x | pesan`.
    **Zona dari `FACTORY_TZ` lewat formatter, JANGAN `TZ` di compose** (aturan 8: `TZ` memindah
    folder hasil); kosong = `+00:00`, salah (termasuk nama folder zona seperti `Asia`) = UTC +
    satu WARNING. **`LOG_LEVEL`** (bawaan INFO, salah ketik = INFO + satu WARNING) cuma mengatur
    keluaran proses: root tidak pernah di atas WARNING, jadi tab Log tetap menerima WARNING.
    `LOG_LEVEL=DEBUG` cuma menyalakan DEBUG untuk logger paket ini (`palmgrade.*`), tidak pernah
    root atau pustaka pihak ketiga; `DEBUG_MODEL_OUTPUT` menumpang lewat filter keluaran
    tersendiri, jadi baris `[MODEL]` tetap lolos apa pun `LOG_LEVEL`-nya. `httpx`/`httpcore`
    dibatasi WARNING apa pun `LOG_LEVEL`-nya, alamat permintaan (webhook Discord, polling status)
    tidak pernah tertulis. Logger `uvicorn*` diarahkan ke root; access log polling yang SUKSES
    (GET/HEAD, < 400) ke jalur di `core/log_akses.JALUR_POLLING_SENYAP` dibisukan, 4xx/5xx dan
    POST tetap tertulis. Jalur polling baru = satu baris di konstanta itu. Baris uvicorn
    "timeout graceful shutdown exceeded" (tiap restart line, karena layar konsol selalu membuka
    video feed) diturunkan ke INFO (`TurunkanTenggangTutup`): tetap di `docker logs`, tidak masuk
    tab Log dan Discord. **Transisi**
    (`domain/transisi.PelacakTransisi`, pola `status_sinkron.py`): PLC putus (klien,
    `plc/jejak_sambungan.py`, satu tracker per alamat koneksi, pulih baru sesudah satu
    baca/tulis berhasil) dan coil yang gagal ditulis (`plc/worker.py` `_tracker_tulis`, satu
    tracker per coil, sengaja terpisah dari tracker klien), kamera berhenti mengirim (mulai
    di 5 grab gagal berturut, alasan dari
    `CameraSource.galat_terakhir`), dan tarikan master data gagal (per jenis: jaringan tanpa
    traceback, lainnya ERROR bertraceback sekali) masing-masing SATU baris saat mulai dan SATU
    saat pulih dengan lamanya; ulangan cuma DEBUG. Awal PLC putus dan coil yang gagal ditulis
    saat tersambung ditulis **ERROR** (pulihnya WARNING): buah lewat tanpa disortir, dan
    ringkasan Discord (aturan 34) cuma membawa ERROR, jadi kabel PLC yang lepas seharian
    sampai ke support di luar pabrik sebagai satu baris. Input PLC yang gagal dibaca tetap
    WARNING (cuma konfirmasi piston, sortir tetap jalan). Kamera yang diam disambung ulang tiap
    ~2 detik selama FRAME_BERHENTI: rincian sambung Hikrobot (perangkat, handle, grabbing) INFO
    cuma di `connect()` pertama objek kamera (satu per line seumur proses), "Camera disconnected"
    DEBUG, laju kamera INFO hanya saat angkanya berubah, dan WARNING "Camera did not report a
    frame rate" sekali per objek kamera. Dulu: PLC dicabut ±10 baris/detik, kamera
    ±10/detik, pabrik offline ±288 traceback/hari. Konsol tetap memasang logging sesudah start
    yang gagal (sengaja): traceback `Application startup failed` uvicorn ikut sampai tab Log.
    ⚠️ Pengecualian tetap: exception deteksi tiap detik saat AI mati belum disaring (ditandai
    penjaga AI, aturan 32).

34. **Log line sampai tab Log, galat penting sampai Discord** (batch 3.2 + 3.5, 2026-09-30).
    Line menulis WARNING/ERROR-nya ke `log_line.db` di folder DB line lewat `SqliteLogHandler`
    yang sama dengan konsol, tapi `write()` cuma menaruh di antrean memori (`AntreanLogLine`,
    maks 1.000) dan thread `log_line` yang menulis ke disk tiap ~0,2 detik: thread deteksi tidak
    pernah menunggu disk log (aturan 1b). Disk yang menolak SEMUA tulisan dicoba lagi dengan jeda
    1 detik berlipat sampai 30 detik, dan dikeluhkan sekali ke stderr per gangguan. Berkas maks 2.000 baris, baris yang paling lama tidak
    berubah dibuang dan dihitung (`dibuang`). Kursor `(generasi, seq)`: `seq` naik tiap baris
    berubah (baru atau digabung), `generasi` acak per berkas, jadi berkas yang direset dibaca dari
    awal. Konsol menariknya tiap 10 detik (`TarikLogLineWorker`, BUKAN `LineStatusWorker`) dan
    menyimpan baris + kursor dalam SATU transaksi di `log_kejadian.db` (`log_line_kursor`): tidak
    hilang dan tidak ganda saat line restart, konsol restart, atau log line direset. Line mati,
    menolak kunci, atau versi lama (404) = diam, dicoba lagi 30 dtk / 5 menit kemudian
    (keadaannya sudah diceritakan `LineStatusWorker`). Yang tidak diceritakan siapa pun dapat
    SATU WARNING saat masuk dan satu "kembali tertarik" saat pulih: 503 `log_line_mati`
    (log_line.db line tidak bisa dibuka), 5xx lain (berkasnya rusak sesudah dibuka), bentuk
    halaman asing (versi konsol dan line berbeda), dan galat tak terduga saat menarik.
    Hitungan Discord untuk ERROR line paling sedikit sekali, dengan dua batas yang sengaja
    diterima (docstring `repositories/log_serap_line.py`): konsol mati di antara meneruskan ke
    Discord dan menyerap = halaman itu diteruskan lagi sesudah start; Danger Zone yang
    mengosongkan `event_log` (atau retensi) lalu baris line yang sama datang lagi = seluruh
    hitungannya diteruskan lagi. Serapan yang GAGAL tanpa konsol mati TIDAK menggandakan:
    hitungan yang sudah diteruskan diingat per line sampai terserap.
    **Lapor Discord** mati kalau `DISCORD_WEBHOOK_URL` kosong (bawaan, keadaan `mati`), bukan
    alamat https dengan host dan port yang bisa dipakai (`url_salah`, diperiksa juga oleh httpx),
    atau antreannya di disk tidak bisa dibuka (`rusak`: pindahkan
    `state/console/lapor_discord.db` lalu `autograde restart`; Setelan tidak me-restart konsol). Nyala:
    semua ERROR konsol + ERROR line yang ditarik antre per jenis di `lapor_discord.db` (jenis =
    pesan yang dinormalkan plus nama kelas galatnya, `dengan_jenis_galat`: "Exception in ASGI
    application (KeyError)"), disusun jadi ringkasan (identitas `ERP_COMPANY` + host + versi,
    hitungan, jam pertama/terakhir, tanpa traceback dan tanpa isi pesan galat, teredaksi,
    dipecah 2.000 karakter) paling cepat 2 menit sesudah galat pertama dan
    paling sering tiap 15 menit, dan tidak ada ringkasan baru selama masih ada pesan yang belum
    terkirim. Jaringan/5xx (`tertahan`): jeda 30 dtk berlipat sampai 15 menit. 429: tunggu
    `retry_after`. 400 (`isi_ditolak`: Discord menolak ISI pesan, alamatnya benar): jeda berlipat,
    dan sesudah 3 kali (`kiriman.isi_ditolak`, cuma penolakan isi; kegagalan jaringan/5xx tidak
    ikut dihitung) pesan itu **disisihkan** (`kiriman.disisihkan_at`, tetap di disk, tidak
    dikirim lagi) supaya satu pesan tidak menahan semua laporan sesudahnya. 4xx lain (`ditolak`,
    webhook salah/dihapus): berhenti sejam, kalimat merah di atas tabel tab Log. Tiap perubahan
    jenis kegagalan satu WARNING dengan sarannya sendiri, pulihnya satu WARNING. Worker lapor
    tidak pernah menulis ERROR (akan melaporkan dirinya sendiri). Alamat webhook itu rahasia:
    tidak pernah dicatat atau dikirim ke layar.

35. **Health jujur + pemantau disk** (batch 3.6 dan 3.7, 2026-09-30). Aturan 32 diperluas,
    bukan diduplikasi: `domain/kesehatan_ai.py` + `services/penjaga_ai.py` yang SAMA.
    **Frame berhenti** (`frame_berhenti`, kode `FRAME_BERHENTI`) = kamera ADA (tersambung
    sekarang, ATAU ada sambung yang berhasil sejak gambar terakhir,
    `RuntimeState.kamera_sambung_ok_sejak_frame`) tapi tidak ada gambar masuk selama
    `AI_MATI_DETIK` sejak yang paling belakangan dari: gambar terakhir, loop mulai, kamera pulih
    dari putus sungguhan (`RuntimeState.kamera_pulih_at`, dicap SEKALI per kejadian: sambung
    berhasil yang pertama sejak gambar terakhir, dan hanya kalau sebelumnya sudah ada yang
    gagal). ⚠️ "Berhasil sejak gambar terakhir", BUKAN "sambung terakhir berhasil": Hikrobot
    yang diam membuat worker memutus dan menyambung lagi tiap lima grab gagal, dan sambungnya bisa
    berselang berhasil dan gagal (MVS atau handle lama yang masih memegang kamera). Menilai dari
    sambung terakhir saja membuat penilaian berkedip antara kamera putus (200) dan frame berhenti
    (503) tiap siklus, dengan ERROR + WARNING tiap 2 sampai 4 detik. Kamera yang SEMUA sambungnya
    sejak gambar terakhir gagal tetap kamera putus. ⚠️ `kamera_pulih_at` TIDAK diperbarui oleh
    sambung berhasil berikutnya dalam kejadian yang sama, kalau tidak tenggangnya diperpanjang
    selamanya dan kamera diam tidak pernah beralarm (pola `ai_dimulai_at`). ⚠️ `connect()`
    menyetel `connected` SEBELUM hasilnya dicatat: `connected` dihitung tersambung hanya kalau
    hasil sambung tercatat bukan gagal (`_tersambung`), dan `main.py` mencatat hasil `connect()`
    saat boot. Tanpa keduanya, tick PLC di sela itu pada akhir putus panjang menulis satu ERROR
    FRAME_BERHENTI palsu tepat saat kameranya kembali, dan ERROR itu sampai ke Discord.
    Frame berhenti menaikkan coil ERROR dan membuat `/health` 503 (`PenilaianAi.gagal`,
    `KEADAAN_GAGAL`), tapi `ai.mati` **tetap AI saja**: konsol versi lama membaca `mati` dan
    menulis "AI berhenti memproses". `LineClient.hidup()` menghitung 503 frame berhenti sebagai
    proses hidup (satu aturan `kode_http_health`). **Sumber selesai** (`sumber_selesai`,
    `camera.exhausted`, video tanpa ulang) dinilai SEBELUM kamera putus (video yang habis
    memutus dirinya sendiri) dan tidak menaikkan apa pun. Kamera putus sungguhan (semua sambung
    ulang sejak gambar terakhir GAGAL) tetap 200 + coil ERROR seperti dulu. `/health/detail` tetap 200 (aturan 32).
    `/health/detail` memuat `fps_kamera` (terukur di `RuntimeState.catat_frame_masuk`, jendela 5
    detik), `fps_deteksi`, keduanya **0 kalau yang terakhir lebih tua dari 5 detik**,
    `frame_umur_detik`, `disk`, `lisensi`, dan `plc.connected` (klien PLC sendiri; kartu
    Diagnostik menggambar ✓ hanya untuk `true`, ✗ untuk `false`, "tidak diketahui" untuk line
    lama tanpa field ini, `-` untuk PLC mati).
    **Pemantau disk** (`domain/kesehatan_disk.py` + `services/pemantau_disk.py`, satu per proses
    line di `RuntimeState.pemantau_disk`): mengukur partisi `artifacts/` DAN folder DB line, yang
    tersempit yang dilapor, **tanpa R2 dan tanpa menghapus apa pun** (tanpa R2, arsip lokal itu
    satu-satunya salinan bukti; TODO L1 soal pembersih tanpa R2 sengaja tetap manual).
    `DISK_PERINGATAN_GB` (15) dan `DISK_KRITIS_GB` (5), histeresis 1 GB. ⚠️ Peringatan wajib di
    BAWAH `UPLOAD_DISK_MIN_FREE_GB` (20): dengan R2 penjaga retensi menjaga sisa disk di sekitar
    lantai itu, jadi ambang setinggi itu = alert permanen (pemantau menulis WARNING saat start).
    Penjaga retensi di `BatchUploadWorker` tidak diubah. Konsol: `LineStatusWorker` membawa
    `disk` + mencatat transisi (`_catat_frame`, `_catat_disk`), layar menggambar SATU pita
    `#pita-disk` per kode untuk seluruh PC (`gabungDisk`/`pitaDisk`, sisa terkecil, daftar line),
    bukan per kartu: ketiga line menulis ke satu disk. Pita cuma menyebut jam, line, dan sisa GB
    (langkah pengosongan ada di MANUAL dan log line); peringatan bisa ditutup 24 jam per browser
    (`localStorage` `pitaDiskDitutupPada`), kritis tidak.
    Fakta milik line (AI mati, frame berhenti, disk) dicatat WARNING/ERROR oleh line dan sampai
    tab Log lewat tarikan log line (aturan 34); cermin `LineStatusWorker` konsol cuma INFO,
    supaya satu kejadian satu baris dan satu kelompok Discord. "Satu kejadian" itu per line:
    satu disk penuh yang ditulisi ketiga line = tiga baris tab Log dan tiga baris di satu
    ringkasan Discord (`line-1`, `line-2`, `line-3`), sengaja tidak digabung di sana. Tiap line
    mengukurnya sendiri dan line bisa ada di disk yang berbeda; menggabung per kode di digest
    akan menyembunyikan line mana yang terkena. Yang digabung cuma layar (satu `#pita-disk`). Baris "Kamera tidak mengirim
    gambar" (aturan 33, mulai 5 grab gagal) dan FRAME_BERHENTI (sesudah `AI_MATI_DETIK`, coil
    ERROR naik) sengaja dua baris: yang pertama menyebut alasan kamera, yang kedua keputusan
    sehat.
    **Kesehatan kamera tanpa sensor suhu** (2026-10-05). Kamera Lampung (MV-CS050-10GC,
    firmware V4.0.43) tidak punya `DeviceTemperature` (akses NI, dicek di kamera), jadi kamera
    yang kepanasan atau rusak dibaca dari kelakuannya, aturannya murni di
    `domain/kesehatan_kamera.py`: **laju tertahan** (fps terukur di bawah 90% target kamera
    `camera_fps_terukur` selama 2 menit; pulih sesudah 1 menit normal, supaya tidak berkedip),
    **frame hilang** (`MV_MATCH_TYPE_NET_DETECT`, selisih hitungan SDK dalam jendela 10 menit,
    bukan total sejak nyala; ada = kuning, mulai 5% = merah; hitungan yang mengecil = handle baru
    sesudah sambung ulang), dan **putus-nyambung** (satu per kejadian "Kamera tidak mengirim
    gambar", jendela 24 jam bergulir, bukan sejak tengah malam; 1-2 kuning, 3 merah). Ditanya
    thread capture tiap `PANTAU_KAMERA_JEDA_DETIK` (10 detik) di bawah kunci kamera (aturan 3),
    bersama suhu. Line yang menilai (`ringkas_kesehatan_kamera`, L4), layar cuma mewarnai, dan
    judul grup Kamera dan gambar menulis "perlu dicek" supaya terlihat walau grupnya tertutup.
    Laju tertahan dan frame hilang ditulis ke tab Log sekali saat mulai dan sekali saat pulih
    (aturan 33). "Laju tertahan" dilapor `false` begitu gambar berhenti: baris gambar terakhir
    sudah merah. Kamera yang menjawab NI untuk `DeviceTemperature` ditanya **sekali per
    sambung** lalu tidak lagi (`suhu_didukung = False`), dan kartu menulis "tidak didukung
    kamera" alih-alih strip yang terbaca seperti kerusakan; NA (ada tapi belum tersedia) tetap
    ditanya.
36. **Penugasan line otomatis: satu truk di line sampai selesai** (keputusan user 2026-10-01).
    Tiap timbang isi dan tiap Lepas memanggil `isi_line_otomatis()`
    (`services/penugasan_otomatis.py`, mixin `ConsoleService`; aturan murni di
    `domain/penugasan_line.py`): truk tertua di **antrean bongkar** (sudah timbang isi, belum
    timbang kosong, belum pernah di line, tidak dilewati, dan tiket terbarunya, terbuka atau
    tertutup: tiket lama yang tertinggal terbuka tidak pernah ditawarkan) dipasang ke line pilihan yang
    bebas, **asalkan** tidak ada line pilihan yang masih memegang truk yang belum timbang
    kosong, atau truk yang timbang kosongnya masih melepas line. Kalau masih ada, truk baru
    menunggu; memasangnya sekarang membuat sisa janjang truk lama tercatat ke truk baru.
    Timbang kosong atau Lepas manual pada line TERAKHIR yang memegang truk memasang truk
    berikutnya. Setelannya di `sync_state` (`setelan_penugasan_line`, selamat dari Danger
    Zone). **Bawaannya NYALA di semua line sejak 2026-10-05** (permintaan user; sebelumnya mati
    sampai support menyalakannya, keputusan D13): konsol yang belum pernah menyimpan saklar ini
    langsung menugaskan truk saat timbang isi. Baris tersimpan yang tidak terbaca dibaca MATI
    (`domain/penugasan_line._tak_terbaca`), bukan bawaan. Selama mati antrean bongkar (di kartu
    truk layar Grading) tidak tampil; selama nyala ia tampil walau kosong. Hanya support yang mengubahnya (`GET/POST /api/console/dev/auto-assign`). Menyimpan
    saklar nyala langsung menjalankan `isi_line_otomatis()` (truk yang sudah menunggu naik
    sekarang); rute itu `async def` karena bertanya ke line (aturan 30). `baca_setelan` tidak pernah melempar (dibaca tiap polling
    `state()`): teks rusak, JSON bukan objek, atau `lines` salah bentuk = bawaan.
    Penugasan tetap lewat `assign_truck` (aturan 13: line menerima dulu, baru dicatat); line
    yang tidak menjawab dilaporkan ke layar (`dipasang[].terpasang: false`) dan tidak pernah
    menggagalkan timbangan. Sebelum tiap line tiketnya dibaca lagi: tiket yang sudah dilewati
    atau sudah bertara tidak dipasang ke line berikutnya. Jalan manual: pemilih truk, Tugaskan,
    dan Lepas di menu ⋯ tiap kartu line (Lepas per truk juga di kartu truk), serta tombol
    **Tugaskan sekarang** dan **Lewati** (dengan konfirmasi) di antrean bongkar (`POST /api/console/unloading-queue/{weighing_id}/assign|skip`, operator).
    **Tugaskan sekarang** hanya memakai line pilihan yang BEBAS (tidak pernah mengambil line
    dari truk lain) dan melewati pemeriksaan satu-truk-satu-waktu; ditolak
    `line_semua_terpakai` kalau tidak ada line pilihan yang bebas ATAU selama timbang kosong
    truk lain masih melepas line, dan `penugasan_tanpa_line` kalau support tidak menyimpan satu
    line pun. **Lewati** ditolak `bukan_antrean` selama truk itu sedang dipasang ke line. Kolom
    `weighings.unloading_queue_skipped_at` menandai truk yang dilewati. Jendela antrean =
    `JENDELA_ANTREAN_BONGKAR`, sama dengan `JENDELA_KUNJUNGAN_DETIK` (12 jam): satu angka
    untuk "berapa lama satu kunjungan". Jawaban rilis dan timbangan membawa `dipasang`; layar
    membaca `antrean_bongkar` dan `penugasan_otomatis` dari `/api/console/state`. Saklar
    nyala: pelepasan otomatis satu timbang kosong diumumkan sebagai SATU toast per truk
    (`pelepasanOtomatisGabung`, tanpa saran "tugaskan lagi" yang akan menimpa truk berikutnya);
    saklar mati: satu toast per line seperti dulu.
    ⚠️ "Antrean bongkar" bukan "Antrean line": yang kedua sudah dipakai untuk antrean janjang
    line ke konsol (aturan 31, tab Status). ⚠️ Selama saklar nyala, satu timbang isi bisa
    menunggu sampai 10 detik per line yang menggantung (pemasangan memanggil tiap line satu
    per satu, 10 detik batas per panggilan). ⚠️ Kalau timbang kosong sebuah truk tidak
    bisa melepas line yang mati, line itu tetap memegang truk yang sudah timbang kosong dan truk
    berikutnya hanya dipasang ke line yang bebas. Line itu (hanya kalau tiket terbaru truknya
    dalam jendela sudah bertara dan platnya diketahui; truk yang dipasang tangan tanpa tiket
    masih disortir dan tidak dilaporkan) dilaporkan di `dipasang` sebagai
    `{terpasang: false, tertahan: true, plate_lama}` dan layar memunculkan toast
    `tugaskanTertahan` dengan kedua plat. Lepas pada line yang mati dijawab 502: begitu line
    itu menjawab lagi, Lepas di kartunya lalu tugaskan truk yang menunggu. Sejak 2026-10-04
    **Lepas paksa** (aturan 13) membebaskan line yang tidak menjawab tanpa menunggunya.

37. **Jam gerbang: scan 1 dan 4 tinggal di PC pabrik** (keputusan user 2026-09-30).
    Scan 1 (truk datang) menulis tabel `arrivals`; scan 4 (truk keluar gerbang) menulis
    `weighings.left_at`. Penulisnya cuma `GateService` (`services/gate_service.py`), dengan
    dua pengecualian: `ConsoleService` menautkan kedatangan ke tiketnya saat timbang isi
    (`arrivals.weighing_id`, `services/gerbang_konsol.py`), dan seeder demo menulis kedua jam
    untuk data demo. `ScanService` tetap cuma mencari dan `record_weighing` tetap satu-satunya
    penulis berat.
    Keduanya **tidak pernah** masuk pesan AutoERP: AutoERP cuma kenal tiga tahap, dan
    `erp_messages` memilih field satu per satu. Tiket BARU mengklaim kedatangan truknya di
    `record_weighing`, bukan di jalur scan, supaya tiket dari dropdown plat atau program
    timbangan juga dapat waktu antrenya. Pencarian pakai jendela 12 jam (`domain/gerbang.py`,
    dari `JENDELA_KUNJUNGAN_DETIK`), bukan hari kerja: antrean bisa lewat tengah malam. Daftar
    menunggu (`waiting`: lencana **Menunggu n**, baris Datang, dan bagian **Menunggu timbang** di
    dropdown langkah 2) memakai jendela yang sama dari jam server, jadi truk yang datang 23:50
    masih menunggu pukul 00:10. Scan 3 (`open_weighings_for_truck`) mencari tiket tanpa tara
    yang timbang isi dalam jendela yang sama sebelum sekarang, dan tabel Timbangan hari ini
    membawa kunjungan hari kerja sebelumnya yang belum keluar gerbang (tanpa tara: dalam jendela
    itu; bertara: 24 jam dari timbang kosong, lihat Tanpa scan 4)
    (`kunjungan_terbawa`, 2026-10-02; sejak batch 5.11 juga dari hari kerja SESUDAHNYA, kalau
    cutoff dinaikkan malam hari): truk 23:50 ditimbang kosong 00:10. Tiketnya tetap
    milik hari kerjanya sendiri; total hari, Rekap, CSV dan AutoERP tidak berpindah hari.
    Scan yang tidak berbentuk plat ditolak `bukan_plat`, kecuali
    platnya milik truk terdaftar (plat dinas, plat lama): truk itu tetap bisa dicatat datang
    dan keluar. Scan 1 **boleh terlewat**: kolom Antre
    menulis "tanpa scan 1", bukan 0 menit, dan Total dihitung dari timbang isi. Menit yang
    kosong tampil strip, bukan 0. Menitnya dihitung backend (`durasi_kunjungan`). Scan 4 atas
    truk yang belum timbang kosong **ditolak dan diperingatkan**, tidak ditulis. Tiap tahap
    punya kolom sendiri karena konsol tidak bisa menebak ini scan ke berapa.
    Tahap tiap tiket (`tahap`: bongkar, timbang_kosong, selesai; kedatangan yang menunggu
    = datang) diputuskan `tahap_tiket` di `domain/gerbang.py`, dikirim backend, dan layar cuma
    mewarnainya (2026-10-02).
    **Batal datang** (2026-10-03): kedatangan yang truknya tidak akan ditimbang (salah pilih,
    ditolak di gerbang) **dibatalkan** lewat `POST /api/console/arrivals/{arrival_id}/cancel`, di bawah
    kunci `GateService`. Cuma yang masih menunggu (`weighing_id` kosong); selain itu dijawab
    `tidak_ada`, bukan galat. **Disimpan sebagai riwayat** (round 4, user 2026-10-03: "riwayat
    pembatalan yang bisa dilihat"): barisnya tidak dihapus, tapi diberi `cancelled_at` (jam server)
    dan `cancelled_by` (email operator), skema `console.db` versi 5. **Nama operator disimpan
    saat itu juga** di `cancelled_by_name` (kolom ketiga di langkah skema 5 yang sama, karena 5
    belum pernah dirilis): panel menampilkan nama, bukan email, dan nama itu salinan saat
    tombol ditekan, tidak dicari ulang dari tabel `operators` saat dibaca. Alasannya: akun lokal
    yang dihapus benar-benar hilang dan akun AutoERP bisa berganti nama lewat sinkron, sedangkan
    riwayat harus tetap menyebut orang yang menekan tombol. Email tetap disimpan sebagai
    identitas; `cancelled_by_name` kosong (nama tak diketahui) = layar menampilkan emailnya.
    Akibatnya setiap pembaca
    kedatangan MENUNGGU wajib menyaring `cancelled_at IS NULL` (`waiting_arrivals`,
    `waiting_arrivals_for_truck`, `claim_arrival`, `jejak_truk` di
    `repositories/console_gerbang_repository.py`; masing-masing punya tes di
    `tests/unit/test_batal_datang_riwayat.py`). Yang dibatalkan tidak pernah tampil di `waiting`,
    tidak pernah diklaim, tidak dihitung "truk datang lagi" (kunjungan lama tetap dapat tombol
    Keluar), dan tidak pernah ke AutoERP. Riwayatnya dibaca lewat `dibatalkan` di
    `GET /api/console/weighings` (hari kerja yang tampil) dan tampil di panel **Kedatangan
    dibatalkan (n)** di bawah tabel Timbangan. Danger Zone dan `make demo-reset` menghapusnya
    bersama kedatangan lain; selain itu tidak ada pembersihan berkala untuk jam gerbang.
    `make demo` menanam dua kedatangan dibatalkan untuk hari ini (`seed_batal_datang`, lewat
    `record_arrival` + `cancel_arrival` milik store) supaya panelnya tampil di site demo; cuma di
    AutoGrade, seeder AutoERP tidak disentuh.
    ⚠️ Image sebelum versi skema 5 (rollback) tidak mengenal kolom itu: kedatangan yang sudah
    dibatalkan terbaca menunggu lagi selama jendela 12 jamnya.
    **Tanpa scan 4** (keputusan user 2026-10-03): tiket bertara yang tidak pernah Keluar
    **dihitung** selesai, tidak ditulis: tidak ada `left_at` karangan. `selesai_tanpa_scan_4`
    memutuskannya kalau timbang kosongnya (`exited_at`, cadangan `entered_at`) lebih dari 24 jam
    lalu (`JENDELA_TANPA_KELUAR_DETIK`), atau kalau truk yang sama sudah datang lagi (kedatangan
    menunggu) atau timbang isi lagi sesudah timbang kosong itu. Barisnya `tahap` selesai dengan
    `tanpa_scan_4: true` dan Total sampai timbang kosong. Tabel hari ini membawa tiket bertara
    yang belum keluar sampai 24 jam dari timbang kosong; tiket tanpa tara tetap 12 jam di mana pun
    (bawa, scan 3, scan 4), supaya tiket kemarin pagi yang terlupa tidak mengambil tara hari ini
    dan membayar neto yang salah. Scan 4 dan tombol Keluar menjawab `sudah_keluar` untuk tiket
    yang sudah selesai tanpa scan 4, jadi Keluar kunjungan baru tidak pernah menutup kunjungan
    lama. Tiket bertara tidak menahan kedatangan baru (`masih_di_dalam` cuma untuk tiket tanpa tara).
    Rute: `POST /api/console/arrivals {qr, at}` dan `POST /api/console/departures
    {qr?, weighing_id?, at}` (Operator); jam salah dijawab 400 `input_tidak_sah`.
    ⚠️ Jam datang dan jam keluar berasal dari jam browser; stempel tanpa zona dibaca sebagai
    UTC, jadi jalur timbangan atau PLC kelak wajib mengirim jam dengan offset. ⚠️ Tulisan
    "menunggu N menit" yang hidup membandingkan jam server dengan jam browser saat datang.
    ⚠️ Tiket yang pertama kali ditulis langsung dengan tara tidak pernah mengklaim
    kedatangannya. Sejak 2026-10-06 scan 1 dan 4 datang dari satu kolom scan yang memilih
    langkahnya dari keadaan truk (aturan 20); kolom itu muncul kalau saklar **Scanner QR**
    (Setelan, support) nyala, bawaan mati.

38. **Update now dari konsol** (batch 4.6, 2026-10-03). Konsol **tidak pernah** menyentuh Docker
    (tanpa `docker.sock`, selamanya). Satu-satunya jalurnya folder `update/` (`UPDATE_DIR`,
    mount `./update:/app/update` di container konsol saja): launcher menulis `status.json`
    (versi terpasang, versi `staged`, `watcher`), konsol menulis `request.json` (tmp lalu
    rename), penunggu systemd di host (sawit `autograde-update.path` +
    `autograde-update.service`, dipasang `pasang-penunggu-update.sh`) menjalankan
    `autograde _update-now` dan menjawab `result.json`. Tombol hanya muncul kalau `watcher` true
    dan versi `staged` lebih baru dari `APP_VERSION` konsol. **Pasang melepas sendiri
    truk di line mana pun** (2026-10-07), termasuk truk yang lupa dilepas sejak hari kerja lalu
    (sumber `assignments`), karena pemasangan me-restart konsol dan ketiga line. Urutannya di
    bawah `pembaruan.kunci`: semua penolakan lain dulu (`periksa`), lalu `release_truck` per line
    (tanpa mengisi line lagi), lalu penanda. Line yang tidak menjawab menghentikan pemasangan:
    409 `pembaruan_lepas_gagal` (`params.line`), tanpa penanda; pakai **Lepas paksa** (aturan 13)
    di line itu lalu tekan Pasang lagi. Line bertruk yang menurut poll status terakhir sudah
    tidak terbaca (`reachable` false) ditolak dengan kode yang sama **sebelum** satu truk pun
    dilepas; kalau line gagal di tengah jalan (termasuk galat tak terduga, tidak pernah 500),
    `params.dilepas` menyebut line yang truknya sudah terlepas dan layar menyuruh menugaskannya lagi. Assign yang masih menunggu line tetap ditolak 409
    `pembaruan_ada_truk`. Sebaliknya assign-truck ditolak 409 `pembaruan_berjalan` selama pemasangan
    berjalan. Penugasan otomatis (aturan 36) memakai kunci yang sama (2026-10-03): selama
    pemasangan truk yang timbang isi tetap di antrean bongkar, **Tugaskan sekarang** ditolak 409
    `pembaruan_berjalan`, dan tiap line yang ditugaskan otomatis lewat `menugaskan` seperti
    tombol manual (`PenugasanOtomatis.pakai_penjaga_pembaruan`, dipasang di
    `console_deps.get_console_service` dengan singleton yang sama). Install memegang `PembaruanService.kunci` (satu `asyncio.Lock`) selama periksa, setiap
    `release_truck`, dan tulis penanda; assign memegangnya cuma untuk mendaftar diri
    (`menugaskan`), lalu memanggil line TANPA kunci, dan line yang assign-nya belum dijawab ikut
    menolak install. Jadi tidak ada celah antara "tidak ada truk" dan penanda mendarat. Harganya:
    selama Update now menunggu line yang diam (sampai batas waktu klien line), assign dan
    penugasan otomatis di line lain antre di belakangnya. Kalau `status.json` berubah antara
    `periksa` dan `pasang` (versi di-stage ulang), truk sudah terlepas dan pemasangan ditolak 409
    `pembaruan_tidak_ada` (jarang, tidak berbahaya). Server mengirim kode line, layar
    menulis nama di kartunya (`namaLineDari`). `rolled_back` menyembunyikan versi itu sampai
    versi yang lebih baru di-stage; `failed` berarti belum dicoba (kunci launcher, promote
    dilewat, skrip terhenti) dan ditawarkan lagi. Penanda tanpa jawaban 20 menit
    (`BATAS_TUNGGU_S`) terbaca `timeout`; hasil tampil 24 jam. Kabar hasil cukup di layar dan
    tab Log (sekali per hasil, `.result-logged.json` bertahan lewat restart; gagal = ERROR
    sampai Discord), tanpa notifikasi desktop (keputusan user 2026-10-02). Rute pasangnya ada di
    `routes/console_pembaruan.py`. **Layarnya (2026-10-07):** tombol Pasang bertanya dulu lewat
    `tanyaKonfirmasi` dengan kalimat yang menyebut tiap truk dan line-nya (tanpa truk: cuma
    kalimat restart). Sesudah 202, **tirai layar penuh**
    `#tirai-pembaruan` menutup semuanya sampai halaman dimuat ulang; tirai itu `div`, bukan
    `dialog.modal`, karena konsol dan line mati di bawahnya dan tidak ada yang boleh ditekan
    (pengecualian F12, dijelaskan di komentarnya). Tirai mengalah pada gerbang login (sesi
    habis di tengah jalan tidak boleh terkunci di belakang tirai). Penandanya
    `sessionStorage` kunci `autograde.pasang` (cadangan di memori kalau penyimpanan ditolak)
    kedaluwarsa 25 menit. **Toast sukses hanya kalau penunggu menjawab `ok` untuk versi
    tujuan itu**; `rolled_back`, `failed`, `timeout`, atau tidak ada jawaban sama sekali =
    toast gagal. Memuat ulang sesudah pasang tetap terjadi dengan tirai terpasang, toastnya
    muncul sesudahnya. Aturan murni:
    `domain/pembaruan.py`; kontrak berkas: `docs/backend-overview.md` § Update now.

39. **Timbangan live: dibaca konsol dari PLC, masuk tiket cuma lewat scan dan kalau layak** (2026-10-06). Angka besar di kartu
    **Timbangan sekarang** (layar Grading; dulu kotak "Data timbangan") adalah berat di jembatan timbang SEKARANG, dibaca
    konsol dari register kata PLC lewat MC Protocol (`plc/pembaca_timbangan.py`, worker
    `workers/timbangan_live_worker.py`, tiap `SCALE_POLL_MS`), di **sambungan sendiri**
    (`SCALE_PLC_PORT`, bawaan 1028; 1025-1027 dipegang tiga line, satu port satu pemakai), bukan
    lewat line. Angka ini mengisi tiket **cuma lewat satu kolom scan** (aturan 20, user
    2026-10-06) dan cuma kalau **layak** (`domain/timbangan_live.berat_layak`): keadaan `stabil`,
    atau `terbaca` dengan kg yang sama minimal 2 detik di antara bacaan pertama dan terakhir
    angka itu (`TAHAN_DETIK`, dihitung `TimbanganLive`, diulang dari nol sesudah putus; satu
    bacaan lalu sambungan macet tidak dihitung tahan), dan minimal 1.000 kg (`MINIMUM_WEIGHT_KG`:
    jembatan kosong terbaca mendekati nol). Bergerak, putus, basi, atau error tidak pernah
    tersimpan; operator mengetik beratnya. Tetap lewat `record_weighing` dengan `net_kg`
    dihitung (aturan 15). Disimpan di memori saja, tidak ada tabel. Semua yang belum
    dijawab tim PLC (register, 16/32-bit, desimal, bit stabil, bit error) adalah `SCALE_PLC_*`
    di `.env`, jadi pabrik menyalakannya tanpa rilis; `SCALE_PLC_REGISTER` kosong atau tidak sah
    = mati, kotak menulis **Belum tersambung**, tanpa socket. 32-bit = kata rendah di `Dn`, kata
    tinggi di `Dn+1` (DINT Mitsubishi). Angka **tidak pernah ditampilkan** saat sambungan putus,
    bacaan lebih tua dari 5 detik (`BASI_DETIK`), atau bit error menyala: strip, bukan angka
    yang membeku dan dicatat operator. Balasan PLC yang terpotong ditolak seperti pembacaan bit
    (`McProtocolPlcClient._terjaga`): socket mati terbaca kata nol, yaitu "jembatan kosong".
    Putus dicatat sekali saat mulai dan sekali saat pulih (aturan 33). Aturan murni:
    `domain/timbangan_live.py`; layar polling `GET /api/console/scale/live` tiap detik di semua
    tab (tiap 30 detik selama `tidak_dipakai`).
    **Timbangan dummy (2026-10-07):** saklar support di Setelan > Mode Developer
    (`GET/POST /api/console/dev/timbangan-dummy`, kunci `setelan_timbangan_dummy` di `sync_state`).
    Menyala = scan timbang isi menyimpan **30.000 kg** dan timbang kosong **10.000 kg**, tanpa
    peduli apa yang dibaca timbangan asli (dummy **menang** atas timbangan live, dan atas
    "tidak layak"), dan baris itu ditandai `dummy: true` di jawaban scan. Datanya **tetap
    dikirim ke AutoERP** (keputusan user 2026-10-07): dummy cuma menggantikan angkanya, bukan
    jalurnya, jadi matikan sebelum kerja sungguhan. Pita oranye `#pita-dummy` di semua tab
    mengingatkannya. Kotak timbangan live menulis **Dummy** hanya selama tidak ada timbangan
    terpasang (`tidak_dipakai`); dengan timbangan terpasang kotak itu tetap menulis keadaan
    timbangannya, tetapi scan tetap menyimpan berat dummy.

---

## Conventions

⚠️ **Env var proses MENANG atas `.env`.** `load_dotenv(override=False)` di
`main.py` dan `console_main.py` berarti apa pun yang sudah ada di lingkungan
tidak akan ditimpa berkas `.env`. Jadi `CAMERA_TYPE=opencv ... uvicorn ...`
mengalahkan `CAMERA_TYPE=hikrobot` di `.env`, dan itu **tidak terlihat** di mana
pun kecuali `/health/detail`. Urutannya: env var proses → `.env` → default di
`core/config.py`. Kalau bingung kenapa setelan tidak berlaku, cek env var proses
lebih dulu.

**Tiga sumber gambar, bukan dua** (`CAMERA_TYPE`): `hikrobot` (kamera GigE
pabrik), `opencv` (file video lewat `CAMERA_VIDEO_PATH`, atau webcam), `photo`
(satu gambar diam, diulang terus). Video pakai **`opencv`**, bukan `photo`.

**`docker-compose.override.yml` tidak ada di repo dan tidak wajib**: dia
`.gitignore`, berkas pribadi per mesin. Compose membacanya otomatis kalau ada dan
menimpa `docker-compose.yml`. ⚠️ **Bukan lagi cara menyetel sumber per line**, itu
sekarang layar Line → Sumber Kamera + `media.env`. Sisakan override untuk hal lain yang
memang khas satu mesin.


- `snake_case` files/functions, `PascalCase` classes, `UPPER_SNAKE` constants (`core/constants.py`) & env vars.
- All paths via `Settings` (`core/config.py`): never hardcode. New env var → add to `core/config.py` with a sane default.
- `CAMERA_TYPE`: `hikrobot` (prod) / `opencv` (dev: webcam or video file) / `photo` (test). Switching needs **no code edit**.
- ROI (`ROI_X1/Y1/X2/Y2`) coordinates are in **settings space** (`STREAM_WIDTH×STREAM_HEIGHT`, default 1280×720), not sensor space.
  Since 2026-10-07 the stream picture keeps the camera's own ratio inside that box (1224×1024 becomes 861×720,
  `domain/skala_tampilan.ukuran_muat`), so `DisplayWorker` maps the stored ROI and capture line onto the picture per axis
  (`draw_roi(skala_setelan=...)`); the stored numbers keep their meaning and nothing is recalibrated.
  Since 2026-10-04 the box can also be set from the console (Settings, Camera & Conveyor), one box for all lines: `RuntimeState.roi_override` wins over `.env`, and `null` (never set, or an older console) leaves each line its own `ROI_*`. Never default it to zeros: that would reset a calibrated box to the full frame.
- **Garis capture (biru, bertanda `CAPTURE`) menentukan KAPAN janjang difoto; ROI menentukan DI MANA.**
  Dua hal berbeda, sengaja dipisah sejak 2026-09-18. Janjang difoto saat kotaknya **menyentuh**
  garis (`domain/garis_capture.menyentuh_garis`): bukan lagi saat titik tengahnya masuk kotak ROI,
  yang memfoto janjang saat separuhnya sudah lewat. ROI tetap menyaring wilayah conveyor, dan `TP`
  tetap dikecualikan dari keduanya.
  **Disetel dari layar support konsol** (Setelan → Garis capture), satu angka untuk semua line,
  berlaku tanpa restart lewat `/internal/setelan`, jalur yang sama dengan `CONF_THRESHOLD` dan
  `MINIMUM_SIZE`. `GARIS_CAPTURE` di `.env` cuma nilai awal, bawaannya **300** (`config.py`, compose, `.env.example`). **`0` = tidak ada
  garis**, dan itu perilaku sebelum fitur ini ada (semua janjang di dalam ROI difoto),
  tetap sah, tapi harus ditulis sendiri sejak bawaannya bukan lagi 0.
  ⚠️ Angkanya ruang **setelan** (`STREAM_WIDTH`, bawaan 1280), diskalakan ke ruang sensor saat
  menyaring (`skala_garis_ke_frame`): melewatkan penskalaan itu bug yang sudah pernah terjadi di
  ROI (`bdcb300`): garis terlihat benar di layar sementara yang menyaring sepertiga frame.
  Kalau capture terasa terlalu cepat, **geser garisnya**, jangan sentuh `CONF_THRESHOLD`.
  **Janjang difoto APA ADANYA begitu menyentuh garis**, ada TP atau tidak (keputusan operator
  2026-09-18): tidak ada penundaan, tidak ada jendela tunggu. Yang menggerakkan mesin (pulse
  PLC) dan yang dilihat operator sama-sama seketika.
  **Arah conveyor** ikut disetel di layar yang sama (`sumbu_garis`): `tegak` = conveyor
  mendatar, garis vertikal, angka px dari **kiri**; `mendatar` = conveyor menurun, garis
  horizontal, angka px dari **atas**. Arah gerak DI DALAM satu sumbu tidak perlu disetel,
  pemicunya perpotongan, jadi conveyor yang membalik arah tetap jalan. ⚠️ Sumbu mendatar
  diskalakan dengan **tinggi** frame, bukan lebar (`skala_garis`): frame kamera (1224x1024, rasio sama dengan sensor 2448x2048) tidak
  persegi, jadi memakai lebar meleset ~19% tanpa satu pun error.
- **Teks layar dan dokumen tanpa em dash (`—`) dan tanpa `" - "` sebagai jeda kalimat** (permintaan user
  2026-09-26: terasa ditulis mesin). Pecah kalimat dengan titik, koma, titik dua, atau kurung.
  Berlaku untuk kamus dua bahasa di `console.html`, teks statis HTML, string JS, pesan
  exception (ada yang tampil apa adanya di layar, ada yang dibaca teknisi di terminal), dan
  semua berkas markdown di luar blok kode dan kode inline (kutipan log dan kode tetap persis).
  Dijaga `tests/unit/test_console_copy.py` + `tests/unit/test_dokumen_tanpa_em_dash.py`;
  komentar, docstring, dan log bebas. ⚠️ Di **frontmatter YAML** (`description:` skill)
  ganti em dash dengan koma, jangan titik dua: `description: A: B` gagal di-parse dan
  skill-nya berhenti termuat tanpa galat. Test yang sama memeriksa frontmatter. Kata kerja
  mengikuti label tombol yang dilihat orang ("Tugaskan" truk, bukan "pasang").
- **Toast konsol menutup sendiri, paling lama 10 detik** (keputusan user 2026-09-29, membalik
  aturan lama "gagal menunggu ditutup"): `sukses`/`peringatan` 5 detik, `gagal` dan setiap
  `toast(..., 0)` 10 detik (`durasiToast`, `TOAST_PALING_LAMA_MS`), dan kursor di atas toast
  menahan hitungannya (`hitungMundurToast`), tapi umur toast dibatasi 30 detik sejak muncul
  (`TOAST_UMUR_MAKS_MS`: kursor yang diparkir di pojok kiosk mendapat `mouseenter` buatan
  browser tiap tata letak berubah). Toast yang tak pernah ditutup menumpuk di layar
  yang dibiarkan menyala berhari-hari. Test: `tests/unit/test_console_html_toast.py`.
  Sejak 2026-10-03 toast bertumpuk ala Sonner, dibuat sendiri karena konsol harus jalan offline:
  terbaru di depan, `TOAST_TERLIHAT` 3 dari `TOAST_MAKS` 4, kursor atau fokus di tumpukan
  membukanya dan menahan SEMUA hitungan (`bukaTumpukanToast`), geser ke kanan membuang
  (`pasangGeserToast`). Test: `tests/browser/test_browser_toast_tumpukan.py`.
- **Line yang direstart dari konsol diberi tanda di kotak kameranya** (2026-09-29): Sumber
  Kamera, Model Deteksi, dan Danger Zone (restart, hapus data) menandai line yang dijawab
  SERVER sudah restart/menerima (`lineDirestart`), bukan yang diklik. Spinner + bar berjalan
  CSS murni tanpa angka (hitungan detik dicabut atas permintaan operator 2026-09-29), lewat
  batas tanda kotak merah "belum kembali" (dulu bertulisan kode `RESTART_LAMA`, sejak 2026-10-01 tanpa kode): 60 detik, **10 menit untuk hapus data** (`RESTART_HAPUS`:
  line menghapus fotonya saat boot sebelum `/health` menjawab). Selama spinner tampil kartu
  diberi kelas `sedang-restart` (`gambarRestart`), yang menyembunyikan "Kamera tidak
  tersambung": `cekKamera` tetap menandai `putus`, tapi tulisannya tidak ikut tembus di balik
  loading. Kotak merah dan tanda yang hilang melepas kelasnya, jadi kamera yang benar-benar
  putus sesudahnya terbaca lagi. Tanda hilang oleh gambar
  (`naturalWidth > 0`, `feedMemuat`) dari stream yang diminta SESUDAH proses lama pasti hilang
  (probe `/health` DITOLAK, atau 12 detik sesudah ditandai; `restartSelesai`). Lewat tenggat
  sengaja tidak dihitung: proses lama yang menguras antrean simpan bisa lambat lalu menjawab
  lagi. Frame terakhir proses lama yang ditahan browser tanpa event apa pun bukan bukti. Tiap
  permintaan stream dicap waktunya (`mintaUlangFeed`, dan `capFeedBaru` sesudah kartu
  digambar ulang: ganti bahasa, daftar truk, login); tanpa cap itu tanda menempel selamanya di
  atas video sehat. Stream diminta ulang (`?t=`) begitu line menjawab, tiap 3 detik sampai
  batas tanda, sesudahnya `cekKamera` (5 detik) yang meneruskan, jadi video kembali tanpa
  muat ulang. Test: `test_console_html_restart.py` + e2e `test_restart_indikator_lane.py`.
  ⚠️ **URL feed di `kartuLine` WAJIB membawa `?t=` unik per render** (`urlFeedBaru`, jam yang
  sama dengan cap `capFeedBaru`). URL telanjang yang sudah pernah dimuat dilayani browser dari
  daftar gambar di memori (Chrome 154, Firefox 155, diuji dengan server MJPEG sungguhan): nol
  permintaan ke line, `load` dalam 2 ms dengan frame LAMA. Akibatnya stream yang sudah putus
  tetap beku sesudah ganti bahasa/daftar truk/login (keluhan awal "harus refresh browser"),
  dan cap render menghapus tanda walau line masih mati.
  ⚠️ Firefox menembakkan `load` untuk TIAP bagian MJPEG, termasuk keep-alive kosong
  (`naturalWidth` 0); Chrome sekali saja, dan keep-alive membuatnya `error`.
  ⚠️ Tandanya hidup di **halaman yang menekan** saja, konsol tidak mencatat restart di
  `/api/console/state`.
- **Label janjang tidak memuat angka confidence** (permintaan operator 2026-09-18): dari beberapa
  meter "54%" terbaca seperti "54% matang", padahal itu keyakinan model dan sudah lolos
  `CONF_THRESHOLD`. Nilainya tetap ditulis ke sidecar dan dikirim ke API.
  **Saklar `mode_dev`** di layar setelan menghidupkannya lagi, untuk support yang sedang
  menyetel ambang, bukan untuk operator. Bawaannya mati.
- **Frame rate hidup di SATU tempat: `config/camera/hikrobot.mfs`.** File itu dikirim ke
  kamera tiap connect, lalu `FrameCaptureWorker.adopt_camera_frame_rate()` menanyakan
  balik laju sebenarnya (`ResultingFrameRate`) dan memakai itu sebagai jeda ambil frame.
  `CAMERA_FPS` **cuma cadangan** untuk sumber yang tidak bisa melapor (webcam, file video).
  Dulu keduanya hidup bersama dan yang lebih kecil menang, menurunkan `.mfs` terasa
  bekerja, menaikkannya tidak, dan itu terbaca berbulan-bulan sebagai "`CAMERA_FPS` mandul".

---

## Git Workflow

- **Judul, isi PR, DAN pesan commit wajib bahasa Inggris** (PR sejak 2026-09-12;
  commit dikoreksi user 2026-09-17 dan lagi 2026-09-26). Format ada di
  `.github/pull_request_template.md`; judul `<type>(<scope>): <ringkas>`, scope juga
  Inggris. ⚠️ **Commit Indonesia TETAP masuk riwayat walau PR-nya Inggris**: repo
  ini squash-merge dengan `squash_merge_commit_message = COMMIT_MESSAGES`, jadi isi
  commit di `staging` adalah daftar pesan commit branch. Tanpa em dash juga, sama
  dengan aturan teks layar di Conventions.
- Default branch `staging`; **PR-only** (main & staging protected). Alur rilis:
  branch baru dari `staging` → PR **squash merge** ke `staging` → PR **merge commit** ke `main`.
  Rilis ke `main` sengaja BUKAN squash: `main` harus menyimpan tiap PR staging sebagai
  commit tersendiri. Karena itu `main` selalu punya merge commit yang tidak ada di
  `staging`: itu normal, bukan divergensi. Cek isinya dengan
  `git diff --stat origin/staging origin/main` (kosong = nol beda), jangan `git cherry`.
- **Tag rilis `vX.Y.Z` menunggu CI hijau di commit tag itu sendiri** (batch 4.1). `deploy.yml`
  memanggil `ci.yml` sebagai job `ci` (`workflow_call`, dari commit yang sama), lalu dua job
  menunggunya: `build-and-push` (image pabrik) dan `demo` (memanggil
  `demo-image.yml`, image `vX.Y.Z-cpu`). CI merah = tidak ada image sama sekali, dan PC pabrik
  tetap di versi lama tanpa error. Tag tidak pernah dipindah, jadi perbaikannya commit baru +
  tag baru; CI yang cuma flaky boleh di-"Re-run failed jobs". Satu rilis kini memakan kira-kira
  3,5 menit CI lebih dulu. `demo-image.yml` tidak lagi jalan sendiri saat tag; jalan manual
  (`workflow_dispatch`) cuma untuk versi yang image pabriknya sudah terbit. Dijaga
  `tests/unit/test_ci_gerbang_rilis.py` dan `tests/integration/test_alur_rilis_integrasi.py`;
  langkah parse skrip dijaga `tests/unit/test_ci_skrip_konsol.py`.
- **Image dicek dulu sebelum dapat tag rilis** (batch 4.2). Build cuma menulis tag sementara
  `candidate-vX.Y.Z` (demo: `candidate-vX.Y.Z-cpu`). Job `smoke` (`image-smoke.yml`, runner
  baru) menarik digest itu dan menjalankan `scripts/smoke_image.py`: label
  `org.opencontainers.image.version` benar (launcher membaca versi dari situ), `main` dan
  `console_main` bisa diimpor (konsol tanpa torch/cv2), konsol nyala tanpa jaringan dan
  `/health` menjawab versi yang benar, dan tiap berkas di `/app/.sidik-image.json` cocok (sejak
  2026-10-05: daftar sidik kode kita yang ditulis `scripts/tulis_sidik_image.py` di akhir
  Dockerfile, dibaca cek keutuhan launcher pabrik `periksa_image` sebelum memasang; listrik
  padam sesudah `docker pull` pernah meninggalkan berkas 0 byte tanpa error); lalu `tests/e2e/test_image_tracker_deps.py` (tracker
  jalan offline) dan, untuk demo, `tests/e2e/test_demo_kit_docker.py`. Baru sesudah lulus job
  `promote` menyalin digest yang sama ke `vX.Y.Z` + `latest` (demo: `vX.Y.Z-cpu`) dengan
  `docker buildx imagetools create`, tanpa build ulang. Smoke gagal = tidak ada tag rilis,
  pabrik tetap di versi lama; tag kandidat tertinggal di registry dan tidak dibaca siapa pun
  (launcher cuma membaca `latest`). Uji coba tanpa rilis (baru bisa sesudah `image-smoke.yml` ada di `main`: branch default repo di GitHub adalah `main`, dan GitHub cuma menawarkan Run workflow untuk workflow di branch default): Actions, **Smoke Test AutoGrade
  Image**, Run workflow, isi image yang sudah ada (misalnya
  `ghcr.io/delta-anugrah/autograde:v1.21.0-cpu`, versi `v1.21.0`, label `v1.21.0-cpu`, centang
  demo); workflow ini cuma membaca, tidak punya izin tulis. Variabel `E2E_WAJIB=1` membuat test
  image yang mestinya dilewati jadi gagal. Dijaga `tests/unit/test_rilis_lewat_smoke.py`,
  `tests/unit/test_smoke_image.py`, `tests/integration/test_alur_rilis_integrasi.py`,
  `tests/e2e/test_smoke_image_docker.py`.
- **CI memparse seluruh `<script>` `console.html`** (batch 4.3) lewat
  `python tests/cek_skrip_konsol.py src/palmgrade/static/console.html`: test konsol lain cuma
  menjalankan fungsi yang diekstrak, jadi syntax error di tingkat atas lolos semua test sementara
  layar operator kosong. Jalankan juga sebelum PR yang menyentuh `console.html`. Langkah
  `pytest tests/unit/` di CI memakai `-rs` seperti e2e dan integration.
- Commit messages: **never** include "Co-Authored-By: Claude" or any AI reference.

---

## Pointers

- **`docs/MANUAL.md`**: manual untuk orang yang ikut memegang AutoGrade, termasuk orang baru: cara pakai konsol, fitur, setup dari nol (laptop + PC pabrik), operasional, troubleshooting, aturan, peta folder dan langkah pertama (§9). PDF-nya `scripts/md_to_pdf.py docs/MANUAL.md` (butuh Chrome + `pip install markdown pypdf`), diagram di `docs/assets/manual/`: blok ```` ```diagram:<nama> ```` di `.md` tetap ASCII, PDF menukarnya dengan `<nama>.svg`, jadi ubah keduanya bersamaan. Skill ringkasnya `.claude/skills/panduan-autograde/` (juga tersambung di `.agents/skills/` untuk Codex).
- **`docs/overview.md`**: deep flows, ASCII diagrams, all invariants with rationale, worker/state model, Docker/SDK/GPU internals, edge cases.
- `docs/backend-overview.md`: satu-satunya tabel lengkap endpoint + event + env var.
- `docs/plc-integration.md`: referensi teknis PLC (env vars, pulse, throughput, commissioning); `docs/plc-mc-handoff.md`: dokumen tim PLC, peta alamat M final (Ocit 2026-09-23); skill `plc-mc-protocol`.
- `docs/SETUP.md`: from-zero setup (NVIDIA toolkit, MVS, camera IP, firewall).
- `docs/runbooks/`: sumber kamera per line, model deteksi per line, commissioning PLC Lampung.
- Skill `compose-host-pabrik`: compose dan launcher di host PC pabrik tidak ikut `autograde pull`; cek sebelum PR yang menambah env var atau mount.
- Skill `konsol-autograde`: peta tab konsol, test per tab, aturan teks layar.
- `deploy/demo/` + `docs/runbooks/2026-09-28-konsol-demo-droplet.md`: konsol demo internet
  (`demo-autograde.smagri.id`) di droplet AutoERP, perintah `demo-autograde`. Image-nya
  `vX.Y.Z-cpu` dari `demo-image.yml`, dipanggil `deploy.yml` sesudah CI hijau (tanpa CUDA/SDK;
  image pabrik 18,2 GB memenuhi disk droplet), dan workflow itu **tidak pernah menulis
  `latest`**: itu penanda updater pabrik.
- Pasang PC pabrik (image produksi), rilis, deploy: skill `install-factory-pc`, `tag-release`, `deploy-production` di workspace `sawit` (bukan di repo ini).
- `../ARCHITECTURE.md`: system architecture.
