#!/usr/bin/env python3
"""Fill the operator console with demo data for a showcase.

    make demo                  a week of history, then the accounts to sign in with
    make demo HARI=3           fewer days
    make demo AKSI=reset       delete what this script made, then build it again
    make demo-off              delete what this script made, and stop there

DEV AND DEMO ONLY — never on the factory PC. It writes grading events and weighbridge
tickets into the console database, and on a real mill that is the operator's own day
mixed with invented bunches. It refuses to run unless the database is empty of real
data, or `PAKSA=1` is set.

It writes to SQLite directly instead of posting to the API, so nothing needs to be
running and no secret has to be passed on the command line. The earlier version needed
`WEBHOOK_SECRET`, three machine ids and an operator password just to start.

The plates are the same ten as AutoERP's seeder (`erpnext/palm_mill/demo.py`). That is
the point: seed both sides and one truck is the same truck on both screens, so the
demo can show a visit at the mill and then the ticket it became in the ERP. Change a
plate here and change it there in the same pull request.

Every id is a uuid5 of its natural key, so re-running adds nothing new.
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# scripts/ is not a package and the image sets no PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.domain.capture_layout import (  # noqa: E402
    CaptureVariant,
    image_relative_path,
    truck_folder_name,
)
from palmgrade.domain.operator_auth import hash_password, operator_id_for  # noqa: E402
from palmgrade.domain.plate import normalisasi_plat, truck_id_for  # noqa: E402
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT  # noqa: E402
from palmgrade.domain.working_day import work_date_for  # noqa: E402
from palmgrade.repositories.console_repository import ConsoleStore  # noqa: E402

# Must match PLATES in autoerp/erpnext/palm_mill/demo.py.
PLATES = (
    "BE 6311 TSA",
    "BE 1825 TSC",
    "BE 8605 TSD",
    "BE 9698 TSD",
    "BE 1473 TSE",
    "BE 5585 TSE",
    "BE 9874 TSE",
    "BG 9911 ZA",
    "BG 7742 ZB",
    "BG 3308 ZC",
)

# Same two accounts AutoERP's CONSOLE_USERS carries, so a demo that pulls master data
# from AutoERP shows the same people it would have created on its own.
DEMO_PASSWORD = "sawit2026"
ACCOUNTS = (
    ("operator@demo.autoerp.test", "Operator Line", ROLE_OPERATOR),
    ("support@demo.autoerp.test", "Support AutoGrade", ROLE_SUPPORT),
)

LINES = ("line-1", "line-2", "line-3")
DAYS = 7
VISITS_PER_DAY = (4, 7)
BUNCHES_PER_VISIT = (28, 64)
SEED = 20260917

# A bunch is ~20 kg; a visit nets a few tonnes. Gross/tare are drawn, net follows.
GROSS_RANGE = (9000, 24000)
TARE_RANGE = (4000, 8000)

# Share of bunches the line rejects, and — among the rejects — how many are Janjang
# Kosong rather than Unripe. Both are drawn so the demo shows the grade-class column
# filled; a screen where JK is always zero hides a miswired class.
REJ_SHARE = (0.03, 0.14)
JK_SHARE_OF_REJ = 0.2

DEMO_TAG = "demo:"  # every seeded id is uuid5 of a string starting with this

# Ukuran gambar sintetis. Kecil disengaja: 500 janjang demo × 3 line harus tetap
# murah di disk, dan kolom FOTO di tab Grading menampilkannya ~48 px.
DEMO_IMAGE_SIZE = (320, 240)  # lebar, tinggi

# Warna latar per kelas, BGR (cv2), bukan RGB. Dibedakan supaya satu layar penuh
# gambar sintetis masih terbaca sebagai tiga kelas yang berbeda dari kejauhan.
DEMO_IMAGE_BG = {
    "Ripe": (38, 74, 40),
    "Unripe": (96, 104, 48),
    "JK": (58, 58, 104),
}


def _uid(kind: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{DEMO_TAG}{kind}:{key}"))


def jalur_gambar_demo(artifacts_dir: Path, line_code: str, image_path: str) -> Path:
    """Di mana berkas untuk satu `image_path` harus berada di disk.

    Kebalikan dari `_capture_url` di `services/console_service.py`, dan harus
    tetap kebalikannya. Konsol memasang `/captures/{line_code}` dari
    `artifacts/{line_code}` (`console_main`), jadi berkasnya ada di bawah folder
    per-line — bukan di `artifacts/results/`. Menaruhnya satu tingkat lebih
    tinggi menyimpan gambar berukuran benar yang tetap dijawab 404, jebakan yang
    sama dengan `ARTIFACTS_DIR` di jalur native.
    """
    rel = image_path.lstrip("/").removeprefix("captures/").lstrip("/")
    return artifacts_dir / line_code / rel


def tulis_gambar_demo(tujuan: Path, *, label: str, nomor: int) -> None:
    """Gambar sintetis satu janjang: latar per kelas + label + nomor urut.

    Dipakai sebagai cadangan kalau tidak ada capture nyata untuk disalin — di
    mesin yang belum pernah menjalankan line, termasuk PC baru dan CI. Sengaja
    tidak berusaha terlihat seperti janjang: yang dibuktikan kolom FOTO adalah
    bahwa tautannya hidup, dan gambar palsu yang menyamar lebih buruk daripada
    gambar palsu yang mengaku.

    Pakai cv2, bukan Pillow: `opencv-python` ada di `requirements.txt`, Pillow
    cuma kebetulan ikut terpasang lewat dependency lain dan bisa hilang kapan
    saja tanpa ada yang tahu sampai `make demo` gagal.

    Import-nya di dalam fungsi, dan itu disengaja: suite unit jalan di CI yang
    **tidak** memasang cv2 maupun numpy (`ci.yml` pasang deps ringan pure-Python
    saja). Mengangkatnya ke atas modul bikin seluruh berkas ini gagal diimpor di
    sana, termasuk untuk test yang cuma memeriksa aritmetika path.
    """
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:  # pragma: no cover - lingkungan tanpa cv2
        raise RuntimeError(
            "gambar demo sintetis butuh opencv-python + numpy "
            "(`pip install -r requirements.txt`). Kalau `artifacts/` sudah punya "
            "capture nyata, seeder menyalinnya dan tidak butuh keduanya."
        ) from exc

    lebar, tinggi = DEMO_IMAGE_SIZE
    img = np.zeros((tinggi, lebar, 3), dtype=np.uint8)
    img[:] = DEMO_IMAGE_BG.get(label, (60, 60, 60))

    # Kotak tipis sebagai pengganti bbox, supaya bentuknya mengingatkan pada
    # capture beranotasi tanpa mengaku sebagai deteksi model.
    cv2.rectangle(img, (18, 18), (lebar - 18, tinggi - 18), (210, 210, 210), 1)
    cv2.putText(img, label, (30, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (245, 245, 245), 2)
    cv2.putText(img, f"#{nomor:04d}", (30, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    cv2.putText(img, "DEMO", (30, tinggi - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (170, 170, 170), 1)

    tujuan.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(tujuan), img):
        raise RuntimeError(f"gagal menulis gambar demo: {tujuan}")


def kumpulkan_capture_nyata(artifacts_dir: Path) -> dict[str, list[Path]]:
    """Capture beranotasi yang sudah ada di disk, dikelompokkan per verdict.

    Dipakai lebih dulu daripada gambar sintetis: satu demo ke klien jauh lebih
    meyakinkan dengan foto janjang sungguhan. Yang diambil hanya `bbox/` —
    `clean/` adalah calon data latih dan tidak pernah jadi bukti di layar, dan
    `thumb/` terlalu kecil untuk lapisan foto.

    ACC dan REJ dipisah karena verdict adalah folder, bukan field
    (`capture_layout` aturan 3). Foto REJ yang dipakai untuk baris ACC membuat
    demo menceritakan hal yang salah tentang mesinnya sendiri.
    """
    per_verdict: dict[str, list[Path]] = {"acc": [], "rej": []}
    if not artifacts_dir.exists():
        return per_verdict
    for verdict in per_verdict:
        # <line>/results/<hari>/<truk>/bbox/<verdict>/<berkas>.webp
        ditemukan = sorted(artifacts_dir.glob(f"*/results/*/*/bbox/{verdict}/*.webp"))
        per_verdict[verdict] = [p for p in ditemukan if p.stat().st_size > 0]
    return per_verdict


def sediakan_gambar(
    tujuan: Path,
    *,
    label: str,
    nomor: int,
    rejected: bool,
    nyata: dict[str, list[Path]],
) -> str:
    """Isi satu kolom FOTO. Mengembalikan `"nyata"` atau `"sintetis"`.

    Sudah ada berkasnya = tidak ditulis ulang: `make demo` dijalankan berkali-kali
    dan menyalin ratusan gambar tiap kali itu pemborosan tanpa hasil berbeda.
    """
    if tujuan.exists() and tujuan.stat().st_size > 0:
        return "nyata" if nyata.get("acc") or nyata.get("rej") else "sintetis"

    sumber = nyata.get("rej" if rejected else "acc") or []
    if sumber:
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        # Bergilir, bukan acak: dua baris berurutan dengan gambar sama terlihat
        # seperti layar yang macet.
        tujuan.write_bytes(sumber[nomor % len(sumber)].read_bytes())
        return "nyata"

    tulis_gambar_demo(tujuan, label=label, nomor=nomor)
    return "sintetis"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hari", type=int, default=DAYS, help="days of history (default 7)")
    ap.add_argument("--reset", action="store_true", help="delete demo rows first")
    ap.add_argument(
        "--hapus",
        action="store_true",
        help="delete the demo rows and stop — leaves real data alone",
    )
    ap.add_argument("--paksa", action="store_true", help="run even on a non-empty database")
    args = ap.parse_args(argv[1:])

    settings = Settings()
    store = ConsoleStore(settings.console_db_path)
    tz = ZoneInfo(settings.factory_tz)
    # Printed every time: writing demo data into the wrong database is the one mistake
    # this script could make silently.
    print(f"Database konsol: {settings.console_db_path}")

    if args.hapus:
        # Hapus lalu BERHENTI. Dipakai sesudah demo supaya layar konsol kembali
        # berisi data sungguhan saja: janjang seeder berstempel sampai ~20 jam ke
        # depan, jadi selama masih ada dia selalu menutupi baris yang baru digrading.
        print(f"  dihapus: {wipe(store)} baris demo")
        print("  data demo dibersihkan; data sungguhan tidak disentuh")
        return 0

    if args.reset:
        print(f"  dihapus: {wipe(store)} baris demo")

    if not args.paksa:
        refused = guard(store)
        if refused:
            print(f"\nBERHENTI: {refused}", file=sys.stderr)
            print("Pakai PAKSA=1 kalau memang mau menimpa.", file=sys.stderr)
            return 1

    artifacts_dir = settings.artifacts_dir
    made = seed(store, tz, artifacts_dir, days=max(1, args.hari))
    print(f"  {made['trucks']} truk, {made['visits']} kunjungan, {made['bunches']} janjang")
    # Disebut eksplisit: kalau nol, kolom FOTO berisi gambar sintetis dan itu
    # keputusan yang harus dilihat sebelum demo ke klien, bukan kejutan di layar.
    if made["capture_nyata"]:
        print(f"  foto: disalin dari {made['capture_nyata']} capture nyata di {artifacts_dir}")
    else:
        print(f"  foto: gambar sintetis (tidak ada capture nyata di {artifacts_dir})")
    print(f"  {made['accounts']} akun")
    print()
    print(f"  Masuk konsol dengan sandi: {DEMO_PASSWORD}")
    for email, full_name, role in ACCOUNTS:
        print(f"    {email:<30} {full_name:<20} [{role}]")
    return 0


def guard(store: ConsoleStore) -> str | None:
    """Refuse to touch a database that already holds somebody's real day.

    A mill PC is the one place this script must never run, and the operator who runs it
    there will not have read the docstring. Demo rows do not count — re-seeding a demo
    is the normal case.
    """
    for row in store.trucks_semua():
        if row["id"] != truck_id_for(row["plate_number"] or ""):
            return "database ini punya truk yang bukan buatan demo"
    real = [op for op in store.operators() if op["origin"] == "erp"]
    if real:
        return f"database ini punya {len(real)} akun dari AutoERP"
    return None


def wipe(store: ConsoleStore) -> int:
    """Delete only what this script wrote, found by the plates it owns."""
    ids = {truck_id_for(p) for p in PLATES}
    removed = 0
    with store._lock, store._db:  # noqa: SLF001 — no public bulk-delete; this is a dev tool
        for table, column in (
            ("inspections", "truck_id"),
            ("weighings", "truck_id"),
            ("assignments", "truck_id"),
        ):
            cur = store._db.execute(  # noqa: SLF001
                f"DELETE FROM {table} WHERE {column} IN ({','.join('?' * len(ids))})", tuple(ids)
            )
            removed += cur.rowcount
        cur = store._db.execute(  # noqa: SLF001
            f"DELETE FROM trucks WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)
        )
        removed += cur.rowcount
        for email, _name, _role in ACCOUNTS:
            cur = store._db.execute(  # noqa: SLF001
                "DELETE FROM operators WHERE id = ?", (operator_id_for(email),)
            )
            removed += cur.rowcount
    return removed


def seed(store: ConsoleStore, tz, artifacts_dir: Path, days: int = DAYS) -> dict[str, int]:
    accounts = seed_accounts(store)
    trucks = seed_trucks(store)
    # Dipindai sekali untuk seluruh seed: satu glob, bukan satu per janjang.
    nyata = kumpulkan_capture_nyata(artifacts_dir)
    visits, bunches = seed_visits(store, tz, artifacts_dir, nyata, days=days)
    return {
        "accounts": accounts,
        "trucks": trucks,
        "visits": visits,
        "bunches": bunches,
        "capture_nyata": len(nyata["acc"]) + len(nyata["rej"]),
    }


def seed_accounts(store: ConsoleStore) -> int:
    """The two demo logins. Written as `lokal`, like `make operator` does — an `erp`
    row would be overwritten by the first pull from AutoERP."""
    made = 0
    for email, full_name, role in ACCOUNTS:
        if store.operator_by_email(email) is not None:
            continue
        store.upsert_operator_manual(
            {
                "email": email,
                "full_name": full_name,
                "password_hash": hash_password(DEMO_PASSWORD),
                "role": role,
            }
        )
        made += 1
    return made


def seed_trucks(store: ConsoleStore) -> int:
    for plate in PLATES:
        store.upsert_truck(
            {
                "id": truck_id_for(plate),
                "plate_number": plate,
                "supplier_id": None,
                "capacity": None,
                "status": "active",
                # Left empty on purpose: `erp_name` is written by the pull from AutoERP.
                # Filling it here would fake a link that was never made, and the console
                # would then believe a truck is synced when it is not.
                "erp_name": None,
            }
        )
    return len(PLATES)


def seed_visits(
    store: ConsoleStore, tz, artifacts_dir: Path, nyata: dict, days: int = DAYS
) -> tuple[int, int]:
    now = datetime.now(tz)
    visits = bunches = 0

    for back in range(days - 1, -1, -1):
        day = now - timedelta(days=back)
        date_key = day.strftime("%Y%m%d")
        rng = random.Random(f"{SEED}:{date_key}")
        for i in range(rng.randint(*VISITS_PER_DAY)):
            # Seeded per visit, so a day that is partly present already fills in the
            # rest with the same numbers it would have had.
            vrng = random.Random(f"{SEED}:{date_key}:{i}")
            plate = PLATES[vrng.randrange(len(PLATES))]
            n = _seed_one_visit(store, tz, day, i, plate, vrng, artifacts_dir, nyata)
            visits += 1
            bunches += n
    return visits, bunches


def _seed_one_visit(
    store: ConsoleStore, tz, day, i: int, plate: str, rng, artifacts_dir: Path, nyata: dict
) -> int:
    truck_id = truck_id_for(plate)
    line = LINES[i % len(LINES)]
    key = f"{day:%Y%m%d}:{i:03d}"
    assignment_id = _uid("assignment", key)

    # A visit occupies one slot in the working day, from 07:00 on.
    start = day.replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(
        minutes=(i * 97) % 600
    )
    work_date = work_date_for(start.isoformat(), tz)
    # Folder truk yang sama dengan yang ditulis line sungguhan, jadi demo dan
    # produksi punya satu bentuk folder — bukan dua yang harus diingat terpisah.
    truck_folder = truck_folder_name(start, plate=plate, assignment_id=assignment_id, tz=tz)

    gross = float(rng.randrange(*GROSS_RANGE, 10))
    tare = float(rng.randrange(TARE_RANGE[0], min(int(gross) - 2500, TARE_RANGE[1]), 10))
    store.upsert_weighing(
        {
            "id": _uid("weighing", key),
            "ref": f"TKT-{day:%y%m%d}-{i:03d}",
            "plate_number": plate,
            "plate_norm": normalisasi_plat(plate),
            "truck_id": truck_id,
            "work_date": work_date,
            "gross_kg": gross,
            "tare_kg": tare,
            "net_kg": gross - tare,
            "entered_at": start.isoformat(),
            "exited_at": (start + timedelta(hours=1)).isoformat(),
        }
    )
    store.link_weighing_to_assignment(_uid("weighing", key), assignment_id)

    total = rng.randint(*BUNCHES_PER_VISIT)
    rej_share = rng.uniform(*REJ_SHARE)
    for j in range(total):
        ts = start + timedelta(seconds=j * 20)
        rejected = rng.random() < rej_share
        # Among rejects, a few are Janjang Kosong rather than Unripe, so the grade-class
        # column on screen is not one repeated value.
        grade_class = ("JK" if rng.random() < JK_SHARE_OF_REJ else "Unripe") if rejected else "Ripe"
        # Layout resmi, lewat `capture_layout` — bukan path rakitan sendiri. Baris
        # demo yang tersimpan flat di folder hari akan luput dari retensi dan dari
        # pemindai batch-upload, yang keduanya mengandalkan kedalaman folder.
        image_path = "captures/results/" + image_relative_path(
            date_folder=work_date,
            truck_folder=truck_folder,
            variant=CaptureVariant.ANNOTATED,
            ripeness_status="REJ" if rejected else "ACC",
            filename=f"{ts:%Y-%m-%d_%H%M%S}_{j:06d}_auto.webp",
        )
        store.add_inspection(
            {
                "event_id": _uid("bunch", f"{key}:{j}"),
                "machine_id": line,
                "line_code": line,
                "work_date": work_date,
                "timestamp": ts.isoformat(),
                "prediction": "Rej" if rejected else "Acc",
                "ripeness_status": "REJ" if rejected else "ACC",
                "grade_class": grade_class,
                "ripeness_confidence": round(rng.uniform(0.70, 0.79 if rejected else 0.98), 2),
                # Long stalks are only judged on fruit that was accepted; a rejected
                # bunch never reaches that check, so the column stays empty for it.
                "tp_status": None if rejected else ("FAIL" if rng.random() < 0.06 else "PASS"),
                "tp_confidence": None,
                "capture_type": "manual" if j == 3 else "auto",
                "image_path": image_path,
                "truck_id": truck_id,
                "assignment_id": assignment_id,
            }
        )
        sediakan_gambar(
            jalur_gambar_demo(artifacts_dir, line, image_path),
            label=grade_class,
            nomor=j,
            rejected=rejected,
            nyata=nyata,
        )
    return total


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
