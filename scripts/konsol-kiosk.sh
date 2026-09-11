#!/bin/sh
# Konsol operator layar penuh (kiosk) di PC pabrik.
#
# Layar penuh TIDAK BISA datang dari console.html: browser mewajibkan
# requestFullscreen() dipanggil dari gestur pengguna, jadi tidak ada halaman web
# yang boleh memfullscreen dirinya sendiri saat dimuat. "Langsung penuh begitu
# nyala" harus datang dari cara browsernya dijalankan - berkas ini.
#
# Pakai: ./scripts/konsol-kiosk.sh   (atau `make kiosk`)
# Otomatis saat login: scripts/palmgrade-konsol.desktop
# Keluar dari kiosk: Alt+F4.
set -eu

URL="${KONSOL_URL:-http://127.0.0.1:8000/console}"
# Profil terpisah, dan wajib PERMANEN: pilihan operator (tema, bahasa, urutan
# kamera, jumlah kolom, tab terakhir) hidup di localStorage profil ini. Profil
# sementara atau --incognito = semuanya balik ke bawaan tiap pagi.
PROFIL="${KONSOL_PROFIL:-$HOME/.local/share/palmgrade-konsol}"

BROWSER=""
for b in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done
[ -n "$BROWSER" ] || { echo "konsol-kiosk: butuh Chrome atau Chromium, tidak ada yang terpasang." >&2; exit 1; }

# Sesudah listrik mati, sesi desktop sering login duluan sebelum Docker selesai
# menghidupkan konsol. Tanpa tunggu ini kiosk mendarat di halaman error browser
# dan TIDAK pernah memuat ulang sendiri - layar mati sampai ada yang sadar.
tunggu=0
while [ "$tunggu" -lt 60 ]; do
    if curl -fsS -o /dev/null "$URL" 2>/dev/null; then break; fi
    tunggu=$((tunggu + 1))
    sleep 2
done

# Layar tidak boleh tidur. Seluruh gunanya konsol ini adalah dilihat dari jauh
# tanpa ada yang menyentuh keyboard berjam-jam, jadi screensaver dan DPMS bawaan
# justru mematikan fungsinya.
if [ "${XDG_SESSION_TYPE:-}" = "x11" ] && command -v xset >/dev/null 2>&1; then
    xset s off
    xset s noblank
    xset -dpms
fi

# --noerrdialogs + --disable-session-crashed-bubble: setelah listrik mati Chrome
#   menandai sesinya "crash" dan menutupi layar dengan gelembung "Restore pages?"
#   yang tidak akan pernah ada yang mengklik.
# --disable-features=Translate: halaman ini dwibahasa dan lang-nya berganti saat
#   operator menekan EN/ID, jadi Chrome akan menawarkan terjemahan.
# --password-store=basic: tanpa ini Chrome bisa menggantung menunggu keyring
#   dibuka, di layar yang tidak ada papan ketiknya.
exec "$BROWSER" \
    --kiosk "$URL" \
    --user-data-dir="$PROFIL" \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-features=Translate,TranslateUI \
    --password-store=basic \
    --no-first-run \
    --no-default-browser-check
