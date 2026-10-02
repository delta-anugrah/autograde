"""One button component (user 2026-10-02): "button batal dibuat warna merah (cek semua button
kalo ada yg seperti batal, cancel, delete, reset) ... pake component button ya supaya seragam".

Every button that cancels, deletes, resets, undoes, releases or signs out carries the danger
variant `button.bahaya`; the final irreversible run carries `bahaya pekat`. Read as text from
`console.html`, static markup and the template strings in the script alike, so a new Batal
button without the class turns this red. The step actions keep their own looks: Keluar on a
Timbangan row is the truck leaving the gate (step 4), not a danger.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()

#: KAMUS keys whose button means cancel, delete, reset, undo, release or sign out.
KUNCI_BAHAYA = frozenset({
    "btnBatal", "imporBatal", "btnLepas", "tombolKeluar",
    "bahayaRestartTombol", "bahayaLogoutTombol", "bahayaRekamanTombol",
    "bahayaTransaksiTombol", "bahayaSemuaTombol",
})
#: Attributes that mark such a button where its label is built elsewhere.
ATRIBUT_BAHAYA = (
    "data-akun-batal", "data-bahaya-batal", "data-batal=", "data-bahaya-buka=",
    "data-bahaya-jalankan=", 'data-aksi="lepas"',
)
#: Never danger: the steps of a truck visit and the grading actions keep their meaning.
KUNCI_BUKAN_BAHAYA = frozenset({"btnPergi", "btnTimbangKosong", "btnDatang", "btnMasuk", "btnSimpanTara"})

_TOMBOL = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.S)
_KUNCI = re.compile(r'data-t="(\w+)"|t\("(\w+)"\)')


def _kelas(atribut: str) -> set[str]:
    """The words of the `class` attribute. A class built in a template
    (`${awas ? "bahaya pekat" : "utama"}`) counts with every word it can take: the quote
    that ends the attribute is the first one outside a `${...}`."""
    awal = atribut.find('class="')
    if awal < 0:
        return set()
    isi, dalam = [], 0
    for i, c in enumerate(atribut[awal + len('class="'):]):
        if c == '"' and dalam == 0:
            break
        if c == "{" and isi and isi[-1] == "$":
            dalam += 1
        elif c == "}" and dalam:
            dalam -= 1
        isi.append(c)
    return set(re.findall(r"[\w-]+", "".join(isi))) - {"awas"}


def _tombol() -> list[tuple[str, str, set[str], set[str]]]:
    """(attributes, content, KAMUS keys, classes) for every button in the file."""
    hasil = []
    for cocok in _TOMBOL.finditer(HTML):
        atribut, isi = cocok.group(1), cocok.group(2)
        kunci = {a or b for a, b in _KUNCI.findall(atribut + isi)}
        if 'bahayaJalankan_" +' in isi:
            kunci.add("bahayaJalankan_")
        hasil.append((atribut, isi, kunci, _kelas(atribut)))
    return hasil


def _bermakna_bahaya(atribut: str, kunci: set[str]) -> bool:
    return bool(kunci & KUNCI_BAHAYA) or "bahayaJalankan_" in kunci or any(a in atribut for a in ATRIBUT_BAHAYA)


def test_varian_bahaya_satu_aturan_dari_token_bahaya():
    aturan = re.search(r"\n  button\.bahaya \{([^}]*)\}", HTML)
    assert aturan, "button.bahaya belum didefinisikan"
    for token in ("--danger-bg", "--danger-line", "--danger-fg"):
        assert token in aturan.group(1), token
    assert re.search(r"button\.bahaya:hover:not\(:disabled\)", HTML)
    assert re.search(r"button\.bahaya\.pekat:disabled", HTML)


def test_aturan_danger_zone_tidak_bocor_ke_tombol_bahaya():
    """`.bahaya { margin; border }` tanpa nama elemen memberi setiap tombol Batal bingkai
    Danger Zone."""
    assert not re.search(r"\n  \.bahaya \{", HTML)
    assert "details.bahaya {" in HTML


def test_setiap_tombol_batal_hapus_reset_lepas_memakai_varian_bahaya():
    tombol = [t for t in _tombol() if _bermakna_bahaya(t[0], t[2])]
    # Static: tara, akun, PLC, model, keluar, five Danger Zone rows. Templates: akun, two in
    # Danger Zone, impor, Lepas, the Danger Zone run button.
    assert len(tombol) >= 16, [t[0] for t in tombol]
    tanpa = [(atribut.strip(), sorted(kunci)) for atribut, _, kunci, kelas in tombol if "bahaya" not in kelas]
    assert not tanpa, f"cancel/delete buttons without class bahaya: {tanpa}"


@pytest.mark.parametrize("id_", ["tara-batal", "akun-tambah-batal", "plc-konfirmasi-batal", "model-modal-batal", "keluar"])
def test_tombol_batal_yang_dikenal_berkelas_bahaya(id_):
    tag = re.search(rf'<button\b[^>]*\bid="{id_}"[^>]*>', HTML)
    assert tag, id_
    assert "bahaya" in _kelas(tag.group(0)), tag.group(0)


def test_langkah_kunjungan_tidak_pernah_bahaya():
    for atribut, _, kunci, kelas in _tombol():
        if kunci & KUNCI_BUKAN_BAHAYA:
            assert "bahaya" not in kelas, (atribut, kunci)
    for aksi in ("pergi", "keluar", "tugaskan"):
        for tag in re.findall(rf'<button\b[^>]*data-aksi="{aksi}"[^>]*>', HTML):
            assert "bahaya" not in _kelas(tag), tag


def test_eksekusi_danger_zone_dan_konfirmasi_impor_memakai_pekat():
    jalankan = re.search(r"<button\b[^>]*data-bahaya-jalankan=[^>]*>", HTML).group(0)
    assert {"bahaya", "pekat"} <= _kelas(jalankan), jalankan
    assert 'classList.add("yakin", "pekat")' in HTML
    assert 'classList.remove("yakin", "pekat")' in HTML


def test_catat_datang_memakai_varian_utama_seperti_timbang_isi():
    """User 2026-10-02: "Catat datang tolong pake component button yg sama supaya seragam"."""
    for id_ in ("datang", "masuk", "tara-simpan"):
        tag = re.search(rf'<button\b[^>]*\bid="{id_}"[^>]*>', HTML).group(0)
        assert "utama" in _kelas(tag), tag
