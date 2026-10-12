"""DEMO_MODE trucks: today's truck visits computed from the clock, in the browser only.

A truck arrives, weighs in, waits its turn, unloads on every line (automatic assignment puts one
truck on all lines, rule 36), weighs out and leaves. Pure functions of (start of day, now, trucks),
so a reload shows the same trucks at the same stage. Rendering: test_browser_demo_hidup.py.
"""
from __future__ import annotations

import pytest
from konsol_js import HTML, NODE, jalankan

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
