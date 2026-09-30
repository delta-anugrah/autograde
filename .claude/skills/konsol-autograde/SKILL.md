---
name: konsol-autograde
description: Use when changing the AutoGrade operator console screen (src/palmgrade/static/console.html) or its /api/console routes, adding a tab or a support screen, touching tab switching, timers, the header, or screen text, or when a user reports a console screen bug. Maps the nine tabs, which role sees them, what loads each, which tests cover them, and the text and safety rules the tests enforce.
---

# Layar konsol AutoGrade

Satu berkas `src/palmgrade/static/console.html`: vanilla JS, tanpa build, tanpa CDN, nol
`https://` (harus jalan saat internet putus). Server: `console_main.py` + `routes/console.py`.

## Sembilan tab (sejak 2026-09-28, dulu 15)

| Tab | Siapa | Pemuat | Isi |
|---|---|---|---|
| Grading | semua | polling `refresh` 2 dtk | 20 grading terakhir hari ini, kartu line merah + pita AI mati dari blok `plc.ai` (`pitaAi`, `perbaruiAi` tiap polling, test `test_console_html_ai_mati.py`); tanda "sedang dinyalakan ulang" di kotak kamera sesudah aksi yang merestart line (`tandaiRestart`, `pantauRestart` 1 dtk, spinner + bar berjalan tanpa hitungan detik, kelas kartu `sedang-restart` menyembunyikan "Kamera tidak tersambung" selama itu, test `test_console_html_restart.py`); strip "Hari ini" berlabel **Data timbangan** (`labelNetoTimbangan`) |
| Truk | semua | `muatTrucks` 60 dtk | master truk, truk manual, kartu QR |
| Timbangan | semua | `muatTimbangan` 15 dtk | tiket, scan masuk/keluar, tara, tanda **Cek AutoERP** untuk janjang susulan pada tiket yang sudah final (`erp_perlu_dicek`, `tests/unit/test_console_html_timbangan_erp.py`) |
| Rekap | semua | `muatRiwayat` (+ `segarkanRekap` 15 dtk) | Rekap + Riwayat: buka di Hari ini, Per truk; Impor CSV support saja |
| Log | support | `muatLog` | ERROR/WARNING 180 hari; pesan identik dalam 60 dtk digabung sesudah id yang berganti (uuid, hex 8+, desimal, bilangan 6+ digit) dinormalkan (`domain/sidik_log.py`, batch 3.3); galat 500 uvicorn konsol (termasuk saat start gagal) kini ikut masuk lewat `configure_logging` (batch 3.1) |
| Status | support | `muatStatus` (diagnostik 5 dtk, antrean line 5 dtk) | Versi, Diagnostik, Antrean line, Antrean ERP + manifest R2 |
| Akun | support | `muatAkun` | akun lokal/AutoERP, tombol aksi berwarna, semua tombol aksi satu lebar (`--lebar-tombol-akun`, satu aturan `#sec-akun :is(...) button`) |
| Line | support | `muatLine` → `MUAT_SUB_LINE[subLine]` | Sumber Kamera, Model Deteksi, Uji PLC (1 dtk), Rekam Video (3 dtk); empat tombol pilihan `#line-sub` = grid 4 kolom selebar panel, 2 x 2 di bawah 600 px |
| Setelan | support | `muatSetelan` | setelan grading, garis capture, Danger Zone. Selalu paling kanan |

- Registri: `TAB_SAH`, `SUB_LINE`, `MUAT_TAB`, `MUAT_SUB_LINE`. Tab lama yang tersimpan di
  localStorage dipetakan `tabDariSimpanan` / `TAB_LAMA` (riwayat → rekap, diagnostik/antrean/versi
  → status, empat layar per line → line + pilihannya).
- Timer cuma untuk yang terlihat: semua dihentikan dan dinyalakan ulang di `bukaTabDev`.
- Peran: elemen `data-dev="1"` dibuang dari DOM untuk non-support dan dikembalikan saat support
  masuk (`aturTabDeveloper`); `pastikanTabTersedia` menjatuhkan tab yang hilang ke Grading.
  Ini cuma kerapian: backend yang menjaga (`require_support`, 403).
- Header: versi + lisensi di bawah AUTOGRADE untuk semua akun (`teksInfoSistem`, data dari
  `/api/console/state`: `versi`, `lisensi`). Nomor token tidak pernah ke layar operator.

## Aturan yang dijaga test (merah kalau dilanggar)

- Tanpa em dash dan tanpa " - " sebagai jeda di teks layar dan KAMUS (`test_console_copy.py`).
- Setiap string layar lewat `KAMUS` dua bahasa, id dan en; kunci tidak boleh dobel.
- Elemen `hidden` yang punya aturan `display` butuh aturan `[hidden]{display:none}`
  (`test_console_html_hidden.py`).
- Setiap POST pengubah data ada di dalam fungsi yang memakai `denganSibuk(` (spinner + tolak klik
  kedua, `test_console_tombol_sibuk.py`).
- Nilai dari server masuk HTML lewat `esc()`.
- Toast menutup sendiri paling lama 10 detik, ditahan selama kursor di atasnya; tidak ada
  lagi toast yang menunggu × (`test_console_html_toast.py`).
- Aksi baru yang merestart line memanggil `tandaiRestart(lineDirestart(jawaban))` dari
  jawaban server; stream kamera diminta ulang lewat `mintaUlangFeed` saja (cap waktu
  `_dimintaPada` yang dipakai `restartSelesai`).
- Isi yang disegarkan tiap polling ditulis lewat `tulisKalauBeda`, bukan membandingkan
  `el.innerHTML` (CLAUDE.md aturan 24(d)).
- Tidak ada `https://` di berkas ini.

## Test per bagian

`tests/unit/test_console_html*.py` (`_riwayat`, `_akun`, `_sinkron`, `_tab_gabung`, `_tab_peran`,
`_info_sistem`, `_model`, `_rekam`, `_sumber`, `_alarm`, ...). Pola: potong fungsi dengan
`_fungsi(nama)` (dari `function nama(` sampai `\n}` pertama) lalu jalankan di `node` dengan stub.
Test yang butuh node melewati dirinya kalau node tidak ada; runner CI punya node dan langkah
unit memakai `-rs`, jadi skip terbaca alasannya. Fungsi yang diekstrak tidak membuktikan
seluruh skrip sehat: sebelum PR jalankan juga
`python tests/cek_skrip_konsol.py src/palmgrade/static/console.html` (langkah CI yang sama,
batch 4.3), yang memparse tiap `<script>` utuh seperti browser.

## Cek di browser (tanpa menyentuh punya user)

Jangan pakai port 8100 atau 8001 (milik `make console` / `make line` user). Worktree terpisah,
konsol uji di 8110/8111 dengan `env -i`, `CONSOLE_LINE_HOST=http://127.0.0.2`, data demo lewat
`scripts/seed-console-demo.py --hari 10`, Playwright dengan Chrome sistem. **Matikan konsol uji
begitu selesai.** Aturan bisnis di balik layar ada di `CLAUDE.md` aturan 19 sampai 27.
