"""Unit tests untuk McProtocolPlcClient (Mitsubishi MC Protocol, device M).

Bentuk test-nya sengaja dibuat sama dengan test_plc_modbus_client.py: dua klien
ini mengisi lubang yang sama di PlcWorker, jadi kalau salah satu punya perilaku
yang tidak dimiliki yang lain, itu harus kelihatan sebagai test yang tidak
punya pasangan.
"""


from palmgrade.plc.mc_client import McProtocolPlcClient


class _FakeInner:
    """Pengganti pymcprotocol.Type3E.

    Beda penting dari pymodbus: MC Protocol MELEMPAR exception untuk semua
    kegagalan (lihat mcprotocolerror.check_mcprotocol_error), tidak ada
    reply.isError() yang bisa diperiksa.
    """

    def __init__(self, connect_raises=False, io_raises=False):
        self._connect_raises = connect_raises
        self._io_raises = io_raises
        self.writes: list[tuple[str, list[int]]] = []
        self.random_writes: list[tuple[list[str], list[int]]] = []
        self.closed = False
        self.connected_to: tuple[str, int] | None = None
        self.access_opts: dict = {}
        self._readsize = 0

    def connect(self, ip, port):
        if self._connect_raises:
            raise OSError("no route to host")
        self.connected_to = (ip, port)

    def setaccessopt(self, **kwargs):
        self.access_opts = kwargs

    def batchwrite_bitunits(self, headdevice, values):
        if self._io_raises:
            raise OSError("boom")
        self.writes.append((headdevice, list(values)))

    def randomwrite_bitunits(self, bit_devices, values):
        if self._io_raises:
            raise OSError("boom")
        self.random_writes.append((list(bit_devices), list(values)))

    def _recv(self):
        # Panjang balasan sah untuk `readsize` bit: kepala(9) + status(2) +
        # ceil(readsize/2) byte data. Klien memeriksa ini untuk membedakan
        # balasan sungguhan dari socket yang tertutup di tengah.
        return b"\x00" * (11 + (self._readsize + 1) // 2)

    def batchread_bitunits(self, headdevice, readsize):
        if self._io_raises:
            raise OSError("boom")
        self._readsize = readsize
        self._recv()
        return [1] + [0] * (readsize - 1)

    def close(self):
        self.closed = True


def _client(inner, **kwargs):
    return McProtocolPlcClient(
        host="192.168.0.14", port=1025, _client_factory=lambda: inner, **kwargs
    )


# ── penerjemahan alamat: angka -> nama device M ──────────────────────────────


def test_write_coil_menerjemahkan_angka_jadi_device_m():
    # Worker tetap bicara angka (plc_coil_ok = 100); klien ini yang tahu
    # bahwa angka itu berarti "M100".
    inner = _FakeInner()
    assert _client(inner).write_coil(100, True) is True
    assert inner.writes == [("M100", [1])]


def test_write_coil_off_mengirim_nol():
    inner = _FakeInner()
    _client(inner).write_coil(101, False)
    assert inner.writes == [("M101", [0])]


def test_read_discrete_inputs_membaca_blok_m_dan_mengembalikan_bool():
    inner = _FakeInner()
    hasil = _client(inner).read_discrete_inputs(200, 20)
    assert hasil == [True] + [False] * 19
    assert all(isinstance(b, bool) for b in hasil)


def test_prefix_device_bisa_diganti():
    # Kalau Viki mengalokasikan device selain M (mis. B atau Y), yang berubah
    # cuma satu setelan — bukan pemanggil.
    inner = _FakeInner()
    _client(inner, device_prefix="B").write_coil(100, True)
    assert inner.writes == [("B100", [1])]


# ── kegagalan tidak boleh membunuh loop ──────────────────────────────────────


def test_write_coil_mengembalikan_false_saat_exception():
    c = _client(_FakeInner(io_raises=True))
    assert c.write_coil(100, True) is False
    assert c.connected is False


def test_read_mengembalikan_none_saat_exception():
    c = _client(_FakeInner(io_raises=True))
    assert c.read_discrete_inputs(200, 20) is None
    assert c.connected is False


def test_connect_gagal_dilaporkan_terputus_bukan_raise():
    c = _client(_FakeInner(connect_raises=True))
    assert c.write_coil(100, True) is False
    assert c.connected is False


def test_reconnect_sesudah_kegagalan_io():
    inner = _FakeInner(io_raises=True)
    c = _client(inner)
    assert c.write_coil(100, True) is False
    # socket lama WAJIB ditutup: pymcprotocol._send melempar
    # "socket is not connected" selamanya kalau state internalnya tidak direset.
    assert inner.closed is True


def test_socket_timeout_dipasang_lebih_pendek_dari_default_dua_detik():
    # Loop bangun tiap 200 ms. Timeout bawaan pymcprotocol 2 detik berarti satu
    # kabel kecantol membekukan sepuluh tick.
    inner = _FakeInner()
    c = _client(inner, timeout_s=1.0)
    c.write_coil(100, True)
    assert inner.access_opts.get("timer_sec") == 1


def test_close_aman_walau_belum_pernah_connect():
    c = _client(_FakeInner())
    c.close()  # tidak boleh melempar
    assert c.connected is False


# ── tulis banyak bit dalam satu paket ────────────────────────────────────────


def test_write_coils_mengirim_satu_paket_untuk_alamat_berserakan():
    inner = _FakeInner()
    hasil = _client(inner).write_coils({100: True, 102: False, 110: True})
    assert hasil == {100: True, 102: True, 110: True}
    assert inner.random_writes == [(["M100", "M102", "M110"], [1, 0, 1])]


def test_write_coils_kosong_tidak_menyentuh_socket():
    inner = _FakeInner()
    assert _client(inner).write_coils({}) == {}
    assert inner.random_writes == []
    assert inner.connected_to is None


def test_write_coils_gagal_melaporkan_semua_alamat_gagal():
    # Tidak ada cara tahu mana yang sempat masuk. Melaporkan sebagian berhasil
    # akan membuat worker berhenti mencoba ulang bit yang tidak pernah sampai.
    c = _client(_FakeInner(io_raises=True))
    assert c.write_coils({100: True, 101: False}) == {100: False, 101: False}


# ── balasan terpotong: kegagalan yang MENYAMAR sebagai sukses ───────────────


class _InnerBalasanTerpotong:
    """Meniru pymcprotocol saat socket tertutup di tengah pembacaan.

    Diukur dari pustaka aslinya: `_recv()` mengembalikan b"" dan
    `batchread_bitunits` tetap membangun daftar sepanjang `readsize` berisi nol
    — panjangnya benar, isinya palsu. Jadi satu-satunya pembeda ada di panjang
    bytes mentah, dan itulah yang dijaga klien kita.
    """

    def __init__(self, panjang_balasan: int):
        self._panjang = panjang_balasan
        self.closed = False

    def connect(self, ip, port):
        pass

    def setaccessopt(self, **kwargs):
        pass

    def _recv(self):
        return b"\x00" * self._panjang

    def batchread_bitunits(self, headdevice, readsize):
        self._recv()
        return [0] * readsize

    def close(self):
        self.closed = True


def test_balasan_kosong_jadi_kegagalan_bukan_deretan_nol():
    # Kalau ini bocor, kabel putus terbaca sebagai "semua input mati" dan
    # E-stop yang sedang DITEKAN terbaca lepas.
    c = _client(_InnerBalasanTerpotong(0))
    assert c.read_discrete_inputs(200, 20) is None
    assert c.connected is False


def test_balasan_setengah_jalan_juga_ditolak():
    # kepala(9) + status(2) + 10 byte data = 21 untuk 20 bit; 15 itu terpotong.
    c = _client(_InnerBalasanTerpotong(15))
    assert c.read_discrete_inputs(200, 20) is None


def test_balasan_lengkap_diterima():
    c = _client(_InnerBalasanTerpotong(21))
    assert c.read_discrete_inputs(200, 20) == [False] * 20


def test_recv_dikembalikan_seperti_semula_sesudah_pembacaan():
    # Klien membungkus `_recv` selama satu panggilan. Kalau bungkusnya tidak
    # dilepas, tiap pembacaan menumpuk satu lapis lagi sampai stack habis.
    inner = _InnerBalasanTerpotong(21)
    asli = inner._recv
    c = _client(inner)
    c.read_discrete_inputs(200, 20)
    assert inner._recv == asli
