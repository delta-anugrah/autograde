"""Unit tests untuk ModbusPlcClient."""

from palmgrade.plc.modbus_client import ModbusPlcClient


class _FakeReply:
    def __init__(self, error, bits=None):
        self._error = error
        self.bits = bits or []

    def isError(self):
        return self._error


class _FakeInner:
    def __init__(self, connect_ok=True, raises=False):
        self._connect_ok = connect_ok
        self._raises = raises
        self.writes: list[tuple[int, bool]] = []
        self.closed = False

    def connect(self):
        return self._connect_ok

    def write_coil(self, address, value, slave=1):
        if self._raises:
            raise OSError("boom")
        self.writes.append((address, value))
        return _FakeReply(error=False)

    def read_discrete_inputs(self, address, count, slave=1):
        return _FakeReply(error=False, bits=[True] + [False] * (count - 1))

    def close(self):
        self.closed = True


def _client(inner):
    return ModbusPlcClient(host="1.2.3.4", port=502, unit_id=1, _client_factory=lambda: inner)


def test_write_coil_forwards_address_and_value():
    inner = _FakeInner()
    assert _client(inner).write_coil(4, True) is True
    assert inner.writes == [(4, True)]


def test_write_coil_returns_false_on_exception_instead_of_raising():
    # Worker loop tidak boleh mati gara-gara kabel dicabut.
    c = _client(_FakeInner(raises=True))
    assert c.write_coil(4, True) is False
    assert c.connected is False


def test_read_discrete_inputs_returns_exactly_count_bits():
    c = _client(_FakeInner())
    assert c.read_discrete_inputs(0, 16) == [True] + [False] * 15


def test_failed_connect_reports_disconnected():
    c = _client(_FakeInner(connect_ok=False))
    assert c.write_coil(0, True) is False
    assert c.connected is False
