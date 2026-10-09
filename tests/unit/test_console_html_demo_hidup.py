"""DEMO_MODE in the browser: live camera frames, counters, grading rows and a moving scale.

Only on demo-autograde.smagri.id (`demo_mode: true` in /api/console/state). Everything here
lives in browser memory: nothing is posted, a reload starts again from the seeded numbers.
Rendering in a real browser: `tests/browser/test_browser_demo_hidup.py`.
"""
from __future__ import annotations

import json
import subprocess

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

FUNGSI = ["majuDemo", "terapkanDemoLines", "srcFeedDemo", "idxDemo", "nolDemo"]
SIAP = """
const JEDA_DEMO_MS = 2600, BATAS_BARIS_DEMO = 30;
const demoHidup = { aktif: true, mulai: 0, langkah: 0, idx: {}, tambah: {}, baris: [],
  lines: ["Line 1", "Line 2", "Line 3"],
  frames: ["Ripe", "Ripe", "Unripe", "Unripe", "Ripe"].map((k, i) => ({src: `/demo/frame-${i + 1}.webp`, kelas: [k]})) };
"""
LINES = """[{line_code: "Line 1", ripe: 10, unripe: 1, jk: 0, tp: 0, total: 11, acc: 10, rej: 1},
            {line_code: "Line 2", ripe: 0, unripe: 0, jk: 0, tp: 0, total: 0, acc: 0, rej: 0},
            {line_code: "Line 3", ripe: 0, unripe: 0, jk: 0, tp: 0, total: 0, acc: 0, rej: 0}]"""


def _jalan(isi: str, fungsi: list[str] = FUNGSI, tambahan: str = SIAP):
    return jalankan(fungsi, f"(() => {{ {isi} }})()", tambahan=tambahan)


@butuh_node
def test_each_tick_advances_one_line_and_adds_its_classes():
    out = _jalan(f"""
      for (let i = 0; i < 6; i++) majuDemo(1000 * i);
      const lines = {LINES};
      terapkanDemoLines(lines);
      return lines.map((l) => [l.ripe, l.unripe, l.tp, l.total]);
    """)
    # Line n starts at frame (2n mod 5) and moves one frame per tick, 2 ticks each:
    # line 1 frames 1,2 = Ripe+Unripe; line 2 frames 3,4 = Unripe+Ripe; line 3 frames 0,1 = Ripe+Ripe
    assert out == [[11, 2, 0, 13], [1, 1, 0, 2], [2, 0, 0, 2]]


@butuh_node
def test_ripe_counts_as_acc_and_the_rest_as_rej():
    """The ripe rate on the day strip reads `acc`: the factory rule, only ACC and REJ reach the PLC."""
    out = _jalan(f"""
      for (let i = 0; i < 6; i++) majuDemo(1000 * i);
      const lines = {LINES};
      terapkanDemoLines(lines);
      return lines.map((l) => [l.acc, l.rej]);
    """)
    assert out == [[11, 2], [1, 1], [2, 0]]


@butuh_node
def test_rows_are_capped():
    assert _jalan("for (let i = 0; i < 100; i++) majuDemo(i); return demoHidup.baris.length;") == 30


@butuh_node
def test_feed_points_at_the_current_frame():
    out = _jalan("const awal = ['Line 1', 'Line 2', 'Line 3'].map(srcFeedDemo);"
                 " majuDemo(0); return awal.concat(srcFeedDemo('Line 1'));")
    # Before any tick each line shows a different photo; one tick moves Line 1 on.
    assert out == ["/demo/frame-1.webp", "/demo/frame-3.webp", "/demo/frame-5.webp", "/demo/frame-2.webp"]


@butuh_node
def test_no_lines_yet_means_no_tick():
    out = _jalan("demoHidup.lines = []; majuDemo(0); return [demoHidup.langkah, demoHidup.baris.length];")
    assert out == [0, 0]


def test_simulation_is_off_unless_the_server_says_so():
    assert "aktifkanDemo(s.demo_mode === true)" in HTML


def test_tick_pauses_while_the_tab_is_hidden():
    """A demo tab left open overnight does no work in the background (review focus 3)."""
    awal = HTML.index("async function aktifkanDemo(")
    assert "if (!document.hidden)" in HTML[awal : HTML.index("\n}", awal)]


def test_demo_cards_skip_the_camera_probe_and_keep_one_shape():
    """No line answers /health on the droplet; and five photos of two shapes must not make
    the camera box jump every tick."""
    cek = HTML[HTML.index("async function cekKamera()") :]
    kode = [b.strip() for b in cek.split("\n")[1:] if not b.strip().startswith("//")]
    assert kode[0] == "if (demoHidup.aktif) return;"
    muat = HTML[HTML.index("function feedMemuat(img)") :]
    assert "demoHidup.aktif" in muat[: muat.index("\n}")]


# ── grading table and scale (Task 4) ─────────────────────────────────────


@butuh_node
def test_scale_cycles_like_the_design():
    out = jalankan(["bacaanDemo"], "[0, 3, 8, 15, 16].map((d) => bacaanDemo(d))",
                   tambahan=HTML[HTML.index("const KG_DEMO = ") :].split("\n")[0])
    assert [r["keadaan"] for r in out] == ["stabil", "bergerak", "stabil", "bergerak", "stabil"]
    assert out[2]["kg"] == 21640 and out[0]["kg"] == 0


def test_demo_rows_only_on_page_one_without_a_filter():
    """A filtered table (Line 2, one truck) or page 2 never shows simulated rows (review focus 2)."""
    body = HTML.split("async function muatGrading()")[1].split("\n}\n")[0]
    assert "demoHidup.aktif && gradingOffset === 0 && !adaSaringan()" in body


def test_scale_tile_reads_the_demo_curve_in_demo_mode():
    body = HTML.split("async function muatTimbanganLive() {")[1].split("\n}\n")[0]
    assert body.strip().startswith("if (demoHidup.aktif) {")


@butuh_node
def test_demo_row_has_every_field_the_table_reads():
    out = _jalan("majuDemo(0); return barisDemoGrading()[0];", FUNGSI + ["barisDemoGrading"])
    assert set(out) >= {"timestamp", "line_code", "plate_number", "source_label",
                        "ripeness_status", "grade_class", "image_url", "thumb_url"}
    assert out["plate_number"] == "BE 8605 TSD"
    assert (out["grade_class"], out["ripeness_status"]) == ("Ripe", "ACC")


@butuh_node
def test_only_ripe_is_acc_in_demo_rows():
    """`tagHasil` colours by ripeness_status: a REJ class must not draw green."""
    out = _jalan("for (let i = 0; i < 6; i++) majuDemo(i);"
                 " return barisDemoGrading().map((r) => [r.grade_class, r.ripeness_status]);",
                 FUNGSI + ["barisDemoGrading"])
    assert {tuple(r) for r in out} == {("Ripe", "ACC"), ("Unripe", "REJ")}


@butuh_node
def test_card_photo_strip_leads_with_the_simulated_bunches():
    """The strip and its "Last bunch" clock read `ambilStrip`: in demo mode they move too."""
    skrip = "\n".join([SIAP, """
const STRIP_N = 4;
const paramGrading = () => "";
const api = async () => ({ items: [{ line_code: "Line 1", image_url: "/seed.webp", timestamp: "2026-10-09T01:00:00Z" }] });
""", *(fungsi(n) for n in FUNGSI + ["barisDemoGrading", "ambilStrip"]), """
(async () => { majuDemo(0); const r = await ambilStrip(["Line 1"]);
  console.log(JSON.stringify(r.map((x) => [x.line_code, x.image_url]))); })();
"""])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert json.loads(hasil.stdout) == [["Line 1", "/demo/frame-2.webp"], ["Line 1", "/seed.webp"]]


@butuh_node
@pytest.mark.parametrize("jawaban", [
    '{ ok: false, json: async () => ({ detail: "forbidden" }) }',
    '{ ok: true, json: async () => ({ frames: [] }) }',
])
def test_a_bad_frames_answer_leaves_the_demo_off(jawaban):
    """A proxy refusal with a JSON body must not switch the demo on with no frames: the camera
    boxes would vanish and every tick would throw (final review 2026-10-09)."""
    skrip = "\n".join([SIAP.replace("aktif: true", "aktif: false"), f"""
let dipasang = true;
const document = {{ hidden: false }};
const setInterval = () => 0;
const fetch = async () => ({jawaban});
""", fungsi("aktifkanDemo"), """
(async () => { await aktifkanDemo(true); console.log(JSON.stringify([demoHidup.aktif, demoHidup.memuat])); })();
"""])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert json.loads(hasil.stdout) == [False, False]
