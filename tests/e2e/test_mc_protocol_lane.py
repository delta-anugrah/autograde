"""End-to-end jalur MC Protocol: keputusan grading -> paket TCP di kabel.

Rantai yang diuji di sini LENGKAP dan tidak ada yang dipalsukan kecuali PLC-nya
sendiri: `PlcWorker` asli -> `McProtocolPlcClient` asli -> `pymcprotocol` asli
-> socket TCP ke server palsu yang membalas seperti CPU Mitsubishi.

Kenapa perlu, padahal unit test klien sudah hijau: unit test memakai pengganti
`Type3E`, jadi ia membuktikan kita memanggil pustaka dengan benar — bukan bahwa
pustaka itu menghasilkan bingkai yang benar untuk alamat yang kita pilih. Salah
paham soal kode device M atau urutan byte alamat lolos dari unit test dan baru
terlihat di pabrik, saat piston menembak janjang yang salah.

`tests/e2e/` karena butuh socket sungguhan dan pustaka pihak ketiga.
"""

from __future__ import annotations

import socket
import threading

import pytest

from palmgrade.plc import build_plc_client
from palmgrade.plc.mc_client import McProtocolPlcClient
from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker

pytest.importorskip("pymcprotocol")


# ── CPU Mitsubishi palsu ─────────────────────────────────────────────────────

#: Subheader balasan 3E biner + rute, lalu panjang dan status.
_BALASAN_KEPALA = bytes.fromhex("d00000ff03ff00")


class _PlcPalsu:
    """Server TCP yang bicara MC Protocol 3E seadanya.

    Cukup untuk membuktikan bingkai kita sah: ia MEMBACA perintah yang masuk,
    menyimpannya mentah-mentah, dan membalas sukses. Bit yang dikembalikan saat
    dibaca bisa diatur dari test.
    """

    def __init__(self, bits: list[int] | None = None) -> None:
        self.paket: list[bytes] = []
        self.bits = bits or []
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._layani, daemon=True)
        self._thread.start()

    def _layani(self) -> None:
        # Melayani koneksi BERULANG: klien menutup dan menyambung lagi setiap
        # kali ada kegagalan I/O, jadi server sekali-pakai akan membuat tick
        # kedua gagal karena harness-nya, bukan karena kode yang diuji.
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            with conn:
                while not self._stop.is_set():
                    try:
                        data = conn.recv(4096)
                    except OSError:
                        break
                    if not data:
                        break
                    self.paket.append(data)
                    try:
                        conn.send(self._balas(data))
                    except OSError:
                        break

    def _balas(self, permintaan: bytes) -> bytes:
        command = int.from_bytes(permintaan[11:13], "little")
        if command == 0x0401:          # batch read bit
            # Tiap byte memuat dua bit: bit ke-4 untuk indeks genap, bit ke-0 ganjil.
            byte_data = bytearray((len(self.bits) + 1) // 2)
            for i, nilai in enumerate(self.bits):
                byte_data[i // 2] |= nilai << (4 if i % 2 == 0 else 0)
            isi = bytes(byte_data)
        else:
            isi = b""
        panjang = 2 + len(isi)          # status + data
        return _BALASAN_KEPALA + panjang.to_bytes(2, "little") + (0).to_bytes(2, "little") + isi

    def close(self) -> None:
        self._stop.set()
        self._srv.close()


@pytest.fixture
def plc():
    palsu = _PlcPalsu()
    yield palsu
    palsu.close()


# ── setelan setara docker-compose line 1 ─────────────────────────────────────


class _CfgLine1:
    """Persis literal `ripe-line-1` di docker-compose.yml, jalur mc."""

    plc_enabled = True
    plc_protocol = "mc"
    plc_device_prefix = "M"
    plc_host = "127.0.0.1"
    plc_unit_id = 1
    plc_pulse_ms = 200
    plc_pulse_gap_ms = 100
    plc_poll_ms = 200
    plc_queue_max = 1
    plc_coil_base = 100
    plc_coil_ok = 100
    plc_coil_ng = 101
    plc_coil_error = 102
    plc_coil_alive = (110,)
    plc_alive_toggle_ms = 500
    plc_coil_manual = 103
    plc_di_base = 200
    plc_di_count = 20
    plc_di_manual = 212


def _worker(plc, cfg=None, **kwargs):
    cfg = cfg or _CfgLine1()
    cfg.plc_port = plc.port
    klien = McProtocolPlcClient(host=cfg.plc_host, port=cfg.plc_port, device_prefix="M")
    return PlcWorker(
        client=klien,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=cfg,
        **kwargs,
    )


def _device_yang_ditulis(paket: bytes) -> list[tuple[int, int]]:
    """Bongkar bingkai tulis jadi [(alamat, nilai)] supaya test bisa menegaskan
    alamat yang BENAR-BENAR keluar, bukan alamat yang kita kira keluar."""
    command = int.from_bytes(paket[11:13], "little")
    if command == 0x1401:                       # batch write bit, alamat berurutan
        alamat = int.from_bytes(paket[15:18], "little")
        jumlah = int.from_bytes(paket[19:21], "little")
        data = paket[21:]
        hasil = []
        for i in range(jumlah):
            byte = data[i // 2]
            nilai = (byte >> 4) & 1 if i % 2 == 0 else byte & 1
            hasil.append((alamat + i, nilai))
        return hasil
    if command == 0x1402:                       # random write bit
        jumlah = paket[15]
        hasil = []
        posisi = 16
        for _ in range(jumlah):
            alamat = int.from_bytes(paket[posisi:posisi + 3], "little")
            nilai = paket[posisi + 4]
            hasil.append((alamat, nilai))
            posisi += 5
        return hasil
    raise AssertionError(f"perintah tak terduga: {command:#06x}")


def _semua_tulisan(plc) -> dict[int, int]:
    """Gabungan semua tulisan yang sampai ke PLC, alamat -> nilai terakhir."""
    hasil: dict[int, int] = {}
    for paket in plc.paket:
        if int.from_bytes(paket[11:13], "little") == 0x0401:
            continue
        hasil.update(dict(_device_yang_ditulis(paket)))
    return hasil


# ── janjang ACC / REJ sampai ke alamat yang benar ────────────────────────────


def test_janjang_acc_menembak_m100_bukan_alamat_lain(plc):
    w = _worker(plc)
    w.submit("acc")
    w.run_once(now=1000.0)

    tulisan = _semua_tulisan(plc)
    assert tulisan.get(100) == 1, f"M100 tidak ON; yang tertulis: {tulisan}"
    assert tulisan.get(101) is None, "M101 (REJ) ikut tertulis — salah piston"


def test_janjang_rej_menembak_m101(plc):
    w = _worker(plc)
    w.submit("rej")
    w.run_once(now=1000.0)

    assert _semua_tulisan(plc).get(101) == 1


def test_pulse_turun_lagi_sesudah_lebar_pulse(plc):
    w = _worker(plc)
    w.submit("acc")
    w.run_once(now=1000.0)      # ON
    w.run_once(now=1000.3)      # sesudah 200 ms -> OFF

    # Ambil tulisan M100 terakhir: harus 0, kalau tidak coil nyangkut ON.
    m100 = [n for paket in plc.paket
            if int.from_bytes(paket[11:13], "little") != 0x0401
            for a, n in _device_yang_ditulis(paket) if a == 100]
    assert m100[-1] == 0, f"M100 tidak pernah turun: {m100}"


def test_tiga_line_memakai_blok_alamat_yang_tidak_bertabrakan(plc):
    """Line 2 dan 3 tidak boleh menyentuh alamat line 1.

    Ini bukan test kosmetik: base 100/120/140 dipilih supaya satu salah ketik
    di compose langsung terlihat, dan kalau blok ternyata tumpang tindih maka
    janjang line 2 akan menggerakkan piston line 1.
    """
    from palmgrade.core.config import Settings

    alamat_per_line = []
    for base in (100, 120, 140):
        import os

        os.environ["PLC_COIL_BASE"] = str(base)
        try:
            s = Settings()
            alamat_per_line.append({s.plc_coil_ok, s.plc_coil_ng, s.plc_coil_error})
        finally:
            del os.environ["PLC_COIL_BASE"]

    gabungan = set().union(*alamat_per_line)
    assert len(gabungan) == 9, "blok alamat antar line bertabrakan"
    assert 110 not in gabungan, "heartbeat M110 bertabrakan dengan alamat line"


# ── heartbeat berkedip: pengganti watchdog coupler ───────────────────────────


def test_heartbeat_benar_benar_berkedip_di_kabel(plc):
    """Tanpa ODOT, kedipan inilah satu-satunya cara ladder tahu PC masih hidup."""
    w = _worker(plc)
    w.run_once(now=1000.0)
    w.run_once(now=1000.6)
    w.run_once(now=1001.2)

    m110 = [n for paket in plc.paket
            if int.from_bytes(paket[11:13], "little") != 0x0401
            for a, n in _device_yang_ditulis(paket) if a == 110]
    assert len(m110) >= 3, f"heartbeat tidak ditulis berulang: {m110}"
    assert len(set(m110)) == 2, f"heartbeat tidak berubah nilai — ladder tak bisa mendeteksi: {m110}"


def test_lisensi_habis_mematikan_heartbeat(plc):
    w = _worker(plc, license_ok=lambda: False)
    w.run_once(now=1000.0)

    assert _semua_tulisan(plc).get(110) == 0


# ── membaca blok M200..M219 ──────────────────────────────────────────────────


def test_membaca_blok_dari_m200_dan_estop_terbaca_di_offset_11():
    bits = [0] * 20
    bits[11] = 1                       # M211 = E-stop
    palsu = _PlcPalsu(bits=bits)
    try:
        w = _worker(palsu)
        w.run_once(now=1000.0)

        assert len(w.inputs) == 20
        assert w.inputs[11] is True, "E-stop (M211) tidak terbaca"
        # Paket baca harus menyebut M200, bukan M0.
        baca = [p for p in palsu.paket if int.from_bytes(p[11:13], "little") == 0x0401]
        assert baca, "tidak ada perintah baca sama sekali"
        assert int.from_bytes(baca[0][15:18], "little") == 200
    finally:
        palsu.close()


def test_konfirmasi_piston_m212_terbaca_lewat_alamat_absolut():
    bits = [0] * 20
    bits[12] = 1                       # M212 = konfirmasi piston line 1
    palsu = _PlcPalsu(bits=bits)
    try:
        w = _worker(palsu)
        w.run_once(now=1000.0)

        assert w.piston_state()["confirmed_open"] is True
    finally:
        palsu.close()


# ── piston manual lewat kabel sungguhan ──────────────────────────────────────


def test_piston_manual_menulis_m103_lalu_batal_tanpa_konfirmasi():
    palsu = _PlcPalsu(bits=[0] * 20)   # konfirmasi TIDAK pernah naik
    try:
        w = _worker(palsu)
        w.request_piston(True)
        w.run_once(now=1000.0)
        assert _semua_tulisan(palsu).get(103) == 1, "permintaan buka tidak sampai"

        # Lewat 2 detik tanpa konfirmasi -> permintaan dibatalkan sendiri,
        # supaya klik berikutnya jadi tepi naik yang baru.
        w.run_once(now=1003.0)
        assert w.piston_state()["requested"] is False
        assert _semua_tulisan(palsu).get(103) == 0, "coil piston nyangkut ON"
    finally:
        palsu.close()


# ── kegagalan jaringan tidak boleh membunuh line ─────────────────────────────


def test_plc_mati_di_tengah_jalan_tidak_melempar(plc):
    w = _worker(plc)
    w.run_once(now=1000.0)
    plc.close()                        # kabel dicabut

    # Tidak boleh melempar: run_loop memanggil ini terus-menerus, dan grading
    # harus tetap jalan walau PLC hilang.
    w.run_once(now=1000.6)
    w.run_once(now=1001.2)


def test_inputs_terakhir_dipertahankan_saat_baca_gagal():
    palsu = _PlcPalsu(bits=[1] + [0] * 19)
    try:
        w = _worker(palsu)
        w.run_once(now=1000.0)
        sebelum = list(w.inputs)
        assert sebelum[0] is True

        palsu.close()
        w.run_once(now=1000.6)
        # Bukan kosong: state terakhir yang sah lebih benar daripada "semua mati",
        # yang akan terbaca sebagai E-stop lepas padahal cuma kabel putus.
        assert w.inputs == sebelum
    finally:
        palsu.close()


# ── build_plc_client memilih klien yang benar ────────────────────────────────


def test_build_plc_client_memilih_mc_secara_bawaan(plc):
    cfg = _CfgLine1()
    cfg.plc_port = plc.port
    assert isinstance(build_plc_client(cfg), McProtocolPlcClient)


def test_build_plc_client_masih_bisa_modbus(plc):
    from palmgrade.plc.modbus_client import ModbusPlcClient

    cfg = _CfgLine1()
    cfg.plc_port = plc.port
    cfg.plc_protocol = "modbus"
    assert isinstance(build_plc_client(cfg), ModbusPlcClient)
