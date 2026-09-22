"""Unit tests binding docker-compose to the settings the console actually reads.

A setting added to `Settings` but not forwarded by the `console` service is
invisible in the container and silently falls back to its default. That is how
ERP_COMPANY shipped unreachable: the code, `.env.example` and the docs all had
it, only compose did not. Reading the two files against each other is the only
check that catches it.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PY = REPO_ROOT / "src" / "palmgrade" / "core" / "config.py"
COMPOSE = REPO_ROOT / "docker-compose.yml"
# ⚠️ `prod` WAJIB ikut diperiksa. Override Compose MENGGANTI blok `environment:`
# dasar, bukan menambahinya, jadi berkas ini bisa lengkap sementara yang benar-
# benar dipakai PC pabrik kehilangan variabel — tanpa satu pun error. Itu yang
# terjadi dengan `LICENSE_ENABLED` di Lampung 2026-09-22: token terpasang, saklar
# tidak ikut, dan layar melapor "Lisensi: Mati" walau langganannya sah.
COMPOSE_PROD = REPO_ROOT / "docker-compose.prod.yml"

# Settings read by the console. Line-only settings (cameras, PLC, uploads) are
# deliberately out of scope: the console service has no business carrying them.
# R2_* is in scope since 2026-09-16: the console's own manifest worker uploads
# per-truck detail pages, independent of the line's batch-upload R2 usage.
CONSOLE_PREFIXES = ("ERP_", "CONSOLE_", "LOG_", "R2_", "MEDIA_", "LICENSE_")


def _settings_env_names() -> set[str]:
    """Env vars `Settings` reads, as spelled in config.py."""
    source = CONFIG_PY.read_text(encoding="utf-8")
    names = set(re.findall(r'os\.getenv\(\s*"([A-Z0-9_]+)"', source))
    return {name for name in names if name.startswith(CONSOLE_PREFIXES)}


def _compose_env_names(service: str, berkas: Path = COMPOSE) -> set[str]:
    """Env vars a compose service declares, list form (`- NAME=${NAME}`).

    Dibaca dari teks, bukan lewat parser YAML: berkas `prod` memakai tag khusus
    Compose (`!override`, `!reset`) yang membuat PyYAML berhenti — dan yang
    diperiksa di sini cuma daftar nama, bukan semantik override-nya.
    """
    teks = berkas.read_text(encoding="utf-8")
    baris = teks.splitlines()

    mulai = next(
        n for n, b in enumerate(baris) if re.match(rf"^\s{{2}}{re.escape(service)}:\s*$", b)
    )
    indent = len(baris[mulai]) - len(baris[mulai].lstrip())

    nama: set[str] = set()
    di_environment = False
    for b in baris[mulai + 1 :]:
        if b.strip() and (len(b) - len(b.lstrip())) <= indent:
            break  # service berikutnya
        if re.match(r"^\s+environment:", b):
            di_environment = True
            continue
        if di_environment:
            if b.strip() and not b.strip().startswith(("-", "#")):
                di_environment = False
                continue
            m = re.match(r"^\s+-\s*([A-Z0-9_]+)=", b)
            if m:
                nama.add(m.group(1))
    return nama


def test_console_service_forwards_every_console_setting():
    missing = _settings_env_names() - _compose_env_names("console")

    assert not missing, f"read by Settings but not forwarded by compose: {sorted(missing)}"


def test_prod_console_forwards_every_console_setting():
    """Yang benar-benar dipakai PC pabrik. Override MENGGANTI blok dasar, jadi
    lengkap di `docker-compose.yml` tidak menjamin apa pun di sini."""
    missing = _settings_env_names() - _compose_env_names("console", COMPOSE_PROD)

    assert not missing, f"dibaca Settings tapi tidak diteruskan compose prod: {sorted(missing)}"


def test_prod_console_membawa_identitasnya_sendiri():
    """`MACHINE_ID` konsol, bukan `LINE_N_MACHINE_ID` yang untuk mencocokkan
    event tiga line. Tanpa ini kolom Machine ID di layar Support kosong."""
    assert "MACHINE_ID" in _compose_env_names("console", COMPOSE_PROD)


def test_settings_env_names_were_actually_found():
    # Guard against the regex silently matching nothing, which would make the
    # test above pass for the wrong reason.
    assert "ERP_URL" in _settings_env_names()
