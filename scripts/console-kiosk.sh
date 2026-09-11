#!/bin/sh
# Operator console fullscreen (kiosk) on the factory PC.
#
# A page can't fullscreen itself on load (requestFullscreen() needs a user
# gesture), so the browser launch does it.
#
# Usage: ./scripts/console-kiosk.sh   (or `make kiosk`)
# Autostart on login: scripts/palmgrade-console.desktop
# Exit kiosk: Alt+F4.
set -eu

URL="${CONSOLE_URL:-http://127.0.0.1:8000/console}"
# Must be a persistent profile: operator choices live in its localStorage.
PROFILE="${CONSOLE_PROFILE:-$HOME/.local/share/palmgrade-console}"

BROWSER=""
for b in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done
[ -n "$BROWSER" ] || { echo "console-kiosk: needs Chrome or Chromium, none installed." >&2; exit 1; }

# After a power cut the desktop often logs in before Docker is up, and a kiosk
# stuck on an error page never reloads.
tries=0
while [ "$tries" -lt 60 ]; do
    if curl -fsS -o /dev/null "$URL" 2>/dev/null; then break; fi
    tries=$((tries + 1))
    sleep 2
done

# Never blank: the screen is watched from a distance, untouched for hours.
if [ "${XDG_SESSION_TYPE:-}" = "x11" ] && command -v xset >/dev/null 2>&1; then
    xset s off
    xset s noblank
    xset -dpms
fi

# --noerrdialogs + --disable-session-crashed-bubble: no "Restore pages?" bubble
#   after a power cut that nobody will ever click.
# --disable-features=Translate: the page switches lang on EN/ID, so Chrome would
#   offer to translate.
# --password-store=basic: don't hang waiting for a keyring on a keyboard-less screen.
exec "$BROWSER" \
    --kiosk "$URL" \
    --user-data-dir="$PROFILE" \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-features=Translate,TranslateUI \
    --password-store=basic \
    --no-first-run \
    --no-default-browser-check
