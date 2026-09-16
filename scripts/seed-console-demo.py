"""Fill the local operator console with fake data so all four tabs have content.

DEV ONLY - never run this against the factory PC. It posts grading events and
weighbridge tickets straight into `state/console/console.db`, and on a real mill
that is the operator's own day mixed with invented bunches.

Set SEED_CONFIRM=1 to run. Every id is a deterministic uuid5 of "seed:<i>:<j>",
so re-running adds nothing new and the rows stay recognisable afterwards.

    WEBHOOK_SECRET=$(docker exec palmgrade_console printenv WEBHOOK_SECRET) \\
    LINE_1_MACHINE_ID=$(docker exec palmgrade_console printenv LINE_1_MACHINE_ID) \\
    LINE_2_MACHINE_ID=$(docker exec palmgrade_console printenv LINE_2_MACHINE_ID) \\
    LINE_3_MACHINE_ID=$(docker exec palmgrade_console printenv LINE_3_MACHINE_ID) \\
    CONSOLE_EMAIL=operator@pks.test CONSOLE_SANDI=<sandi> \\
    SEED_CONFIRM=1 python3 scripts/seed-console-demo.py

Since Fase 4 the console API needs a session. Make the operator first with
`make operator`; the seed signs in as them and never creates an account itself.
"""
import http.cookiejar, json, os, sys, urllib.request, uuid
from datetime import datetime, timedelta, timezone

if os.environ.get("SEED_CONFIRM") != "1":
    sys.exit(__doc__)


BASE = os.environ.get("CONSOLE", "http://localhost:8000")
SECRET = os.environ["WEBHOOK_SECRET"]
MACHINES = [os.environ[f"LINE_{n}_MACHINE_ID"] for n in (1, 2, 3)]


# One cookie jar for the whole run: the session cookie from sign-in rides along.
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def post(path, body, secret=False):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 **({"x-webhook-secret": SECRET} if secret else {})})
    with OPENER.open(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def get(path):
    with OPENER.open(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def sign_in():
    email = " ".join(os.environ.get("CONSOLE_EMAIL", "").split()).lower()
    sandi = os.environ.get("CONSOLE_SANDI", "")
    if not (email and sandi):
        sys.exit("Set CONSOLE_EMAIL and CONSOLE_SANDI - make the operator first: make operator")
    post("/api/console/login", {"email": email, "sandi": sandi})


sign_in()


PLATES = ["BE 8821 KL", "B 1234 XY", "KT 2509 ABC"]
trucks = {p: post("/api/console/trucks", {"plate_number": p})["id"] for p in PLATES}

now = datetime.now(timezone.utc)
n = 0
for i, (plate, truck_id) in enumerate(trucks.items()):
    for j in range(12 + i * 4):
        rej = j % 5 == 0
        ts = now - timedelta(minutes=(i * 30 + j * 2))
        post("/api/v1/internal/vision/events", {
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"seed:{i}:{j}")),
            "machine_id": MACHINES[i],
            "timestamp": ts.isoformat(),
            "prediction": "Rej" if rej else "Acc",
            "ripeness_status": "REJ" if rej else "ACC",
            "ripeness_confidence": 0.72 if rej else 0.93,
            "tp_status": None if rej else "PASS",
            "capture_type": "manual" if j == 3 else "auto",
            "image_path": f"captures/results/{ts:%Y-%m-%d}/seed_{i}_{j}.webp",
            "truck_id": truck_id,
            "assignment_id": None,
            "bounding_box": {"x_min": 10, "y_min": 20, "x_max": 300, "y_max": 400},
        }, secret=True)
        n += 1

# One bunch with no truck assigned yet - the row the recap must not drop.
ts = now - timedelta(minutes=4)
post("/api/v1/internal/vision/events", {
    "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "seed:orphan")),
    "machine_id": MACHINES[2], "timestamp": ts.isoformat(),
    "prediction": "Acc", "ripeness_status": "ACC", "ripeness_confidence": 0.88,
    "tp_status": "PASS", "capture_type": "auto",
    "image_path": f"captures/results/{ts:%Y-%m-%d}/seed_orphan.webp",
    "truck_id": None, "assignment_id": None,
    "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
}, secret=True)
n += 1

# Two tickets for one truck in a day - proves the recap sums neto instead of
# multiplying the bunch count by the ticket count.
for ref, bruto in (("TKT-1001", 12480), ("TKT-1002", 11950)):
    post("/api/v1/internal/scale/weighing", {
        "ref": ref, "plate_number": "BE 8821 KL",
        "entered_at": (now - timedelta(hours=2)).isoformat(),
        "gross_kg": bruto, "tare_kg": 5120,
    }, secret=True)
post("/api/v1/internal/scale/weighing", {
    "ref": "TKT-1003", "plate_number": "B 1234 XY",
    "entered_at": (now - timedelta(hours=1)).isoformat(),
    "gross_kg": 9870.5, "tare_kg": 4200,
}, secret=True)

state = get("/api/console/state")
recap = get("/api/console/recap")
print(f"{n} grading + 3 weighing tickets seeded, work date {state['work_date']}")
for r in recap["items"]:
    print(f"  {r['plate_number'] or '(no truck)':<14} total={r['total']:<4} "
          f"acc={r['acc']:<4} rej={r['rej']:<3} net={r['net_kg']}")
