"""DEMO_MODE trucks: today's truck visits computed from the clock, in the browser only.

A truck arrives, weighs in, waits its turn, unloads on every line (automatic assignment puts one
truck on all lines, rule 36), weighs out and leaves. Pure functions of (start of day, now, trucks),
so a reload shows the same trucks at the same stage. Rendering: test_browser_demo_hidup.py.
"""
from __future__ import annotations

import json
import subprocess

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

FUNGSI = ["acakDemo", "kunjunganDemo", "keadaanDemo", "janjangDemo", "janjangHariDemo"]
MENIT = 60_000
AWAL = 1_791_824_400_000  # a local midnight; any fixed number works, the model only adds to it
TRUK = """[{id: "t1", plate_number: "BE 6311 TSA", supplier_name: "KUD Maju", source_label: "External"},
           {id: "t2", plate_number: "BE 1825 TSC", supplier_name: null, source_label: "Internal"},
           {id: "t3", plate_number: "BE 8605 TSD", supplier_name: "CV Sawit", source_label: "External"}]"""
SIAP = HTML[HTML.index("\nconst MENIT_DEMO = ") + 1 :].split("\n")[0] + "\n" + \
    HTML[HTML.index("\nconst JANJANG_MENIT_DEMO = ") + 1 :].split("\n")[0]


def _jalan(isi: str):
    return jalankan(FUNGSI, f"(() => {{ const truk = {TRUK}; {isi} }})()", tambahan=SIAP)


@butuh_node
def test_visits_follow_each_other_in_order():
    v = _jalan(f"return kunjunganDemo({AWAL}, {AWAL} + 14 * 3600000, truk);")
    assert len(v) > 30
    for a, b in zip(v, v[1:], strict=False):
        assert b["mulai"] >= a["selesai"] + MENIT  # one truck on the lines at a time
        assert b["datang"] > a["datang"]
    for k in v:
        assert k["datang"] < k["masuk"] < k["mulai"] < k["selesai"] < k["keluar"] < k["pergi"]
        assert k["bruto"] > k["tara"] > 0


@butuh_node
def test_the_same_clock_gives_the_same_trucks():
    a = _jalan(f"return kunjunganDemo({AWAL}, {AWAL} + 5 * 3600000, truk);")
    b = _jalan(f"return kunjunganDemo({AWAL}, {AWAL} + 5 * 3600000, truk);")
    assert a == b


@butuh_node
def test_no_trucks_means_no_visits():
    assert _jalan(f"return kunjunganDemo({AWAL}, {AWAL} + 3600000, []);") == []


@butuh_node
def test_state_at_any_minute_is_consistent():
    hasil = _jalan(f"""
      const v = kunjunganDemo({AWAL}, {AWAL} + 14 * 3600000, truk);
      const out = [];
      for (let m = 60; m < 14 * 60; m += 7) {{
        const now = {AWAL} + m * {MENIT};
        const k = keadaanDemo(v, {AWAL}, now);
        out.push({{now, diLine: k.diLine, antrean: k.antrean, menunggu: k.menunggu, tiket: k.tiket, tally: k.tally}});
      }}
      return out;
    """)
    pernah_antre = False
    for k in hasil:
        now = k["now"]
        if k["diLine"]:
            assert k["diLine"]["plate_number"]
        for a in k["antrean"]:
            assert a["menit"] >= 0
        pernah_antre = pernah_antre or bool(k["antrean"])
        for m in k["menunggu"]:
            assert m["tahap"] == "datang"
        tahap = {w["tahap"] for w in k["tiket"]}
        assert tahap <= {"bongkar", "timbang_kosong", "selesai"}
        for w in k["tiket"]:
            ditimbang = w["exited_at"] is not None
            assert (w["net_kg"] is not None) == ditimbang
            if ditimbang:
                assert w["net_kg"] == w["gross_kg"] - w["tare_kg"]
        masuk = [w["entered_at"] for w in k["tiket"]]
        assert masuk == sorted(masuk, reverse=True)  # newest first, like the server
        assert k["tally"]["tiket"] == len(k["tiket"])
        assert k["tally"]["neto_kg"] == sum(w["net_kg"] or 0 for w in k["tiket"])
        assert k["tally"]["menunggu_tara"] == sum(1 for w in k["tiket"] if w["exited_at"] is None)
        assert now > 0
    assert pernah_antre, "a queue never forms: the demo would never show the unloading queue"


@butuh_node
def test_only_todays_weigh_ins_are_todays_tickets():
    k = _jalan(f"""
      const v = kunjunganDemo({AWAL}, {AWAL} + 30 * {MENIT}, truk);
      return keadaanDemo(v, {AWAL}, {AWAL} + 30 * {MENIT}).tiket.map((w) => w.entered_at);
    """)
    assert all(e >= "1970" for e in k)
    raw = _jalan(f"""
      const v = kunjunganDemo({AWAL}, {AWAL} + 30 * {MENIT}, truk);
      return [v.filter((x) => x.masuk < {AWAL}).length, keadaanDemo(v, {AWAL}, {AWAL} + 30 * {MENIT}).tiket.length,
              v.filter((x) => x.masuk >= {AWAL} && x.masuk <= {AWAL} + 30 * {MENIT}).length];
    """)
    assert raw[0] > 0  # yesterday's late trucks exist in the chain ...
    assert raw[1] == raw[2]  # ... but only today's weigh-ins are tickets


@butuh_node
def test_bunches_grow_while_unloading_and_stop_after():
    out = _jalan(f"""
      const v = kunjunganDemo({AWAL}, {AWAL} + 6 * 3600000, truk)[10];
      const pada = (t) => [0, 1, 2].map((i) => janjangDemo(v, i, t).total);
      return [pada(v.mulai - 1000), pada(v.mulai + 4 * {MENIT}), pada(v.selesai), pada(v.selesai + 30 * {MENIT}),
              janjangDemo(v, 0, v.selesai)];
    """)
    sebelum, tengah, akhir, sesudah, rinci = out
    assert sebelum == [0, 0, 0]
    assert all(0 < t < a for t, a in zip(tengah, akhir, strict=True))
    assert akhir == sesudah
    assert rinci["ripe"] + rinci["unripe"] + rinci["jk"] == rinci["total"]
    assert rinci["acc"] == rinci["ripe"] and rinci["tp"] <= rinci["total"]


@butuh_node
def test_todays_bunches_per_line_add_up_the_visits():
    out = _jalan(f"""
      const now = {AWAL} + 8 * 3600000;
      const v = kunjunganDemo({AWAL}, now, truk);
      const hari = janjangHariDemo(v, {AWAL}, now, 3);
      const sendiri = [0, 1, 2].map((i) => v.filter((x) => x.mulai >= {AWAL})
        .reduce((n, x) => n + janjangDemo(x, i, now).total, 0));
      return [hari.map((h) => h.total), sendiri];
    """)
    assert out[0] == out[1]
    assert all(n > 0 for n in out[0])


# ── wiring into the screen ───────────────────────────────────────────────

SAMBUNG = FUNGSI + ["terapkanDemoState", "awalHariDemo", "trukDemo", "terapkanDemoLines",
                    "gabungTimbanganDemo", "gabungRiwayatDemo"]


def _layar(isi: str, aktif: bool = True):
    tambahan = SIAP + f"""
let trucks = {TRUK};
const demoHidup = {{ aktif: {str(aktif).lower()}, lines: ["line-1", "line-2", "line-3"], keadaan: null, kunjungan: null }};
let riwayatTampilan = "truk";
let riwayatFilter = {{}};
const AWAL_UJI = {AWAL};
// The tests pass factory midnight in; awalHariDemo itself is tested on its own.
awalHariDemo = () => AWAL_UJI;
"""
    return jalankan(SAMBUNG, f"(() => {{ {isi} }})()", tambahan=tambahan)


@butuh_node
def test_state_gets_one_truck_on_every_line_the_queue_and_todays_weighing():
    out = _layar("""
      const hasil = [];
      const awal = AWAL_UJI;
      for (let m = 9 * 60; m < 9 * 60 + 240; m += 3) {
        const s = { lines: [{line_code: "line-1"}, {line_code: "line-2"}, {line_code: "line-3"}],
                    timbangan: {tiket: 1, menunggu_tara: 0, neto_kg: 1000}, penugasan_otomatis: {aktif: false} };
        terapkanDemoState(s, awal + m * 60000);
        hasil.push(s);
      }
      return hasil;
    """)
    ada_truk = False
    for s in out:
        a = [line["assignment"] for line in s["lines"]]
        assert a[0] == a[1] == a[2]  # automatic assignment: one truck on all lines
        ada_truk = ada_truk or a[0] is not None
        assert s["penugasan_otomatis"]["aktif"] is True
        assert s["timbangan"]["tiket"] >= 1 and s["timbangan"]["neto_kg"] >= 1000
    assert ada_truk
    assert any(s["antrean_bongkar"] for s in out)


@butuh_node
def test_weighbridge_rows_lead_with_the_simulated_visits_only_in_demo_mode():
    out = _layar("""
      demoHidup.keadaan = { tiket: [{id: "demo-w-1"}], menunggu: [{id: "demo-a-2"}] };
      const asli = { items: [{id: 7}], waiting: [], dibatalkan: [] };
      const demo = gabungTimbanganDemo(asli);
      demoHidup.aktif = false;
      return [demo.items.map((w) => w.id), demo.waiting.map((w) => w.id), gabungTimbanganDemo(asli) === asli];
    """)
    assert out == [["demo-w-1", 7], ["demo-a-2"], True]


@butuh_node
def test_rekap_adds_todays_trucks_only_for_today_without_a_filter():
    out = _layar(f"""
      const now = {AWAL} + 11 * 3600000;
      demoHidup.kunjungan = kunjunganDemo({AWAL}, now, trucks);
      const hari = "2026-10-13";
      const r = {{ dari: hari, sampai: hari, hari_ini: hari, items: [], ringkasan: {{total: 0, truk: 0, hari: 0, neto_kg: 0}} }};
      const hariIni = gabungRiwayatDemo(r, now);
      riwayatFilter = {{ plat: "BE" }};
      const disaring = gabungRiwayatDemo(r, now);
      riwayatFilter = {{}};
      const rKemarin = {{ ...r, dari: "2026-10-12" }};
      const kemarin = gabungRiwayatDemo(rKemarin, now);
      return [hariIni.items.length, hariIni.ringkasan.truk, hariIni.items.every((b) => b.truck_id === null),
              hariIni.items.reduce((n, b) => n + b.total, 0) === hariIni.ringkasan.total,
              disaring === r, kemarin === rKemarin];
    """)
    jumlah, truk, tanpa_id, total_cocok, disaring_sama, kemarin_sama = out
    assert jumlah == truk > 0
    assert tanpa_id and total_cocok and disaring_sama and kemarin_sama


def test_refresh_applies_the_simulation_before_anything_is_drawn():
    body = HTML.split("async function refresh() {")[1].split("\n}\n")[0]
    assert body.index("terapkanDemoState(s, Date.now())") < body.index("tulisKepala(s)")


@butuh_node
def test_rekap_summary_is_the_same_in_every_view_and_the_day_row_includes_the_trucks():
    """Switching Per truk / Per hari / Per janjang must not make today's totals jump (review 2026-10-13)."""
    out = _layar(f"""
      const now = {AWAL} + 11 * 3600000;
      demoHidup.kunjungan = kunjunganDemo({AWAL}, now, trucks);
      const r = () => ({{ dari: "2026-10-13", sampai: "2026-10-13", hari_ini: "2026-10-13",
        items: [{{work_date: "2026-10-13", total: 5, ripe: 5, unripe: 0, jk: 0, tp: 0, acc: 5, truk: 1, neto_kg: 100}}],
        ringkasan: {{total: 5, ripe: 5, unripe: 0, jk: 0, tp: 0, acc: 5, truk: 1, hari: 1, neto_kg: 100}} }});
      const hasil = {{}};
      for (const v of ["truk", "hari", "janjang"]) {{ riwayatTampilan = v; hasil[v] = gabungRiwayatDemo(r(), now); }}
      return hasil;
    """)
    ringkas = {v: out[v]["ringkasan"] for v in out}
    assert ringkas["truk"] == ringkas["hari"] == ringkas["janjang"]
    assert ringkas["truk"]["total"] > 5
    hari = out["hari"]["items"]
    assert len(hari) == 1 and hari[0]["total"] == ringkas["hari"]["total"]
    assert hari[0]["truk"] == ringkas["hari"]["truk"]
    assert out["janjang"]["items"] == [{"work_date": "2026-10-13", "total": 5, "ripe": 5, "unripe": 0, "jk": 0,
                                        "tp": 0, "acc": 5, "truk": 1, "neto_kg": 100}]


@butuh_node
@pytest.mark.parametrize("tz_browser", ["UTC", "America/New_York", "Asia/Jakarta"])
def test_the_demo_day_starts_at_factory_midnight_whatever_the_browser_zone(tz_browser):
    """Times on screen and Rekap's date follow the factory zone (`zonaPabrik`), not the visitor's."""
    # 2026-10-13 01:30 in Jakarta (UTC+7) = 2026-10-12 18:30 UTC; factory midnight = 2026-10-12 17:00 UTC.
    out = jalankan(["awalHariDemo"], "awalHariDemo(Date.UTC(2026, 9, 12, 18, 30))",
                   tz=tz_browser, tambahan='let zonaPabrik = "Asia/Jakarta";')
    assert out == _utc(2026, 10, 12, 17, 0)


def _utc(y, mo, d, h, mi):
    from datetime import UTC, datetime
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp() * 1000)


@butuh_node
def test_a_new_truck_from_autoerp_does_not_reshuffle_the_plates():
    """`/api/console/trucks` lists the newest first; a pulled truck must not change which plate is
    on the lines mid-unload (review 2026-10-13)."""
    out = _layar("""
      const a = trukDemo().map((t) => t.plate_number);
      trucks = [...trucks].reverse();
      const b = trukDemo().map((t) => t.plate_number);
      trucks = trucks.concat([{id: "t9", plate_number: "BE 0001 ZZ", status: "inactive"}]);
      return [a, b, trukDemo().map((t) => t.plate_number)];
    """)
    assert out[0] == out[1] == out[2] == sorted(out[0])


@butuh_node
def test_lepas_on_the_demo_shows_one_toast_not_one_per_line():
    """The truck card's Lepas walks every line; on the read-only demo the first refusal is the answer."""
    skrip = "\n".join(["""
const dipanggil = [], toast = [];
const t = (k) => k;
const denganSibuk = async (b, fn) => fn();
const api = async (p) => { dipanggil.push(p); const e = new Error("demo"); e.kode = "mode_demo"; throw e; };
const toastGagal = (x) => toast.push(x);
const gagalKarena = (k, e) => k + ":" + e.kode;
const namaKartuLine = (l) => l;
const refresh = async () => {};
const toastSukses = () => {}, umumkanPasang = () => {};
""", fungsi("lepasTrukSemuaLine"), """
(async () => { await lepasTrukSemuaLine(null, "BE 1", ["line-1", "line-2", "line-3"]);
  console.log(JSON.stringify([dipanggil.length, toast])); })();
"""])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert json.loads(hasil.stdout) == [1, ["gagalLepas:mode_demo"]]
