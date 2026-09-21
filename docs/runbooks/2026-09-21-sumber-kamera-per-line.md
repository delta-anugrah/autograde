# Mengganti sumber kamera satu line

Untuk teknisi di lapangan (AnyDesk ke PC pabrik) yang perlu mengganti sumber
gambar satu line kamera — misalnya kamera lepas kabel dan sementara mau diuji
pakai video rekaman, atau sedang training pakai foto diam.

Layar: konsol → login **support** (bukan operator biasa) → tab **Sumber Kamera**.

## Yang bisa dipilih

| Pilihan | Dipakai untuk | Butuh berkas |
|---|---|---|
| Kamera Hikrobot | produksi | tidak — malah **ditolak** kalau diisi |
| Webcam | dev di laptop | tidak — malah **ditolak** kalau diisi |
| Video | uji ulang rekaman | ya |
| Foto | uji satu frame diam | ya |

Video dan Foto **wajib** pilih berkas dari dropdown. Kamera Hikrobot dan
Webcam **tidak boleh** punya berkas — layar menolak kombinasi yang salah
sebelum sempat disimpan.

## Menaruh berkas

Berkas video/foto **tidak diunggah dari layar** — sengaja tidak ada tombol
upload. Taruh berkasnya langsung ke folder `media/` di host lewat AnyDesk atau
USB:

- MacBook dev: `<repo>/media/`
- PC pabrik: `/opt/palmgrade/autograde/media/`

Begitu berkas ada di folder itu, dia langsung muncul di dropdown **tanpa
restart apa pun** — daftarnya dibaca ulang tiap kali layar Sumber Kamera
dibuka.

## Menyimpan

Pilih sumber untuk line yang mau diganti, lalu tekan **Simpan & Restart**.

**Hanya line yang setelannya berubah yang direstart** — line lain yang tidak
disentuh terus grading seperti biasa. Restart satu line makan waktu sekitar
10 detik; selama itu line tersebut berhenti sebentar.

## Kalau satu line tidak menjawab

Ini bagian paling penting untuk dipahami, karena kalau terlewat teknisi akan
menekan Simpan berulang-ulang tanpa guna.

**Setelan tetap tersimpan** walau line-nya sedang mati atau tidak menjawab
restart. Layar akan bilang line mana yang belum kena. Line itu akan
**membaca setelan barunya sendiri saat hidup lagi** — tidak perlu menyimpan
ulang, dan tidak perlu menunggu line itu hidup dulu baru menyimpan.

Jadi kalau layar bilang "Line 2 tidak menjawab": setelan Line 2 sudah aman
tersimpan. Begitu Line 2 hidup lagi (kabel dicolok ulang, container
direstart manual, dsb), dia otomatis memakai sumber yang baru dipilih tadi.

## Jebakan

⚠️ **Jangan menyunting `media.env` dengan tangan saat konsol jalan.** Layar
Sumber Kamera yang menulis berkas ini; simpan berikutnya dari layar akan
menimpa **seluruh isi berkas**, termasuk perubahan tangan yang baru saja
dibuat.

⚠️ **`media.env` tidak ikut git.** PC baru (atau checkout bersih) butuh:

```bash
cp media.env.example media.env
```

sekali saat pemasangan. Tanpa langkah ini ketiga line jatuh ke bawaan
`hikrobot` — yang **benar** untuk pabrik, jadi kelalaiannya tidak terlihat
sampai ada yang mencoba mode Video atau Foto dan bingung kenapa pilihannya
tidak tersimpan / tidak berefek.

⚠️ **`docker compose config` di MacBook tidak membuktikan apa pun** soal
Compose di PC pabrik. Versi Compose beda jauh (MacBook ini v5.5.1, PC pabrik
v2.40.3), dan berkas yang sebenarnya rusak untuk pabrik bisa terlihat sehat
sempurna di MacBook — sudah pernah kejadian (autograde#120, soal blok
`environment:` konsol yang tertimpa `docker-compose.prod.yml`). Kalau perlu
membuktikan urusan `env_file`/`media.env` tergabung dengan benar, buktikan di
mesin Linux dengan Compose seumur pabrik, bukan di laptop.

## Terbukti di

⏸️ **Belum dijalankan.** Langkah ini butuh mesin Linux dengan Docker Compose
v2.x (seumur pabrik) — MacBook ini tidak punya Compose v2.x, jadi pembuktian
di bawah **belum dieksekusi** dan masih pending. Jangan dianggap sudah lolos
sampai ada yang benar-benar menjalankannya dan mencatat hasilnya di sini.

Langkah yang harus dijalankan, dari clone bersih di mesin Linux itu:

```bash
docker compose version   # pastikan v2.x, bukan v1 legacy
cp media.env.example media.env
printf 'LINE_2_CAMERA_TYPE=photo\nLINE_2_MEDIA_FILE=sawit.jpg\n' >> media.env
docker compose config | grep -A2 'CAMERA_TYPE'
```

Yang dianggap **berhasil**: output menunjukkan `ripe-line-2` memakai
`CAMERA_TYPE=photo`, sementara `ripe-line-1` dan `ripe-line-3` tetap
`CAMERA_TYPE=hikrobot`. Itu artinya `env_file: media.env` per service
tergabung dengan benar oleh Compose v2.x, sesuai yang diasumsikan Task 11.

Kalau hasilnya **berbeda** dari itu — misalnya `env_file` tidak tergabung
sama sekali, atau ketiga line memakai nilai yang sama — **berhenti dan
laporkan**: berarti seluruh pendekatan `media.env` terpisah perlu bentuk lain
(menulis nilai langsung ke `.env` utama, bukan berkas `env_file` terpisah).

Begitu langkah ini dijalankan, catat di sini: tanggal, versi
`docker compose version` yang dipakai, dan hasil `grep`-nya (tempel output
sebenarnya, bukan ringkasan).
