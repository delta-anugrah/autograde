"""Klien MC Protocol untuk CPU Mitsubishi (Q03UDECPU) lewat port Ethernet bawaan.

Menggantikan jalur ODOT CN-8031/Modbus: sejak 2026-09-21 PC bicara LANGSUNG ke
CPU, tanpa remote IO di tengah. Antarmuka kelas ini sengaja identik dengan
`ModbusPlcClient` (`write_coil` / `read_discrete_inputs` / `close`) supaya
`PlcWorker` tidak tahu protokol mana yang sedang dipakai — seluruh logika
pulse, heartbeat, piston dan buah internal tetap satu, teruji, tidak disalin.

Dua beda yang harus dijaga di sini, bukan di pemanggil:

1. **Alamat.** Modbus punya coil bernomor; MC Protocol punya nama device
   (`"M100"`). Worker tetap bicara angka, kelas ini yang menempelkan prefiks.
2. **Kegagalan.** pymodbus mengembalikan reply yang bisa ditanya `isError()`;
   pymcprotocol MELEMPAR exception untuk semua kegagalan, termasuk kode error
   dari PLC. Jadi semua panggilan dibungkus, dan tetap mengembalikan sentinel
   (False/None) supaya thread worker tidak pernah mati karena kabel dicabut.

⚠️ Tidak ada watchdog seperti ODOT di sini. Coupler dulu mereset outputnya
sendiri saat link putus; CPU tidak. Sebuah M yang ditinggal ON saat PC mati
akan tetap ON. Itu sebabnya `PLC_ALIVE_TOGGLE_MS` harus > 0 pada jalur ini dan
ladder wajib memantau PERUBAHAN bit heartbeat — lihat docs/plc-integration.md.

⚠️ **pymcprotocol tidak memeriksa balasan kosong.** Saat socket tertutup di
tengah jalan, `_recv()` mengembalikan `b""`, lalu `recv_data[9:11]` pada bytes
kosong ikut kosong dan ter-decode sebagai status 0 = "sukses". Untuk sebuah
pembacaan, hasilnya bukan error melainkan **deretan bit nol** — E-stop yang
sedang ditekan akan terbaca LEPAS. Karena itu `_periksa_balasan` di bawah
memeriksa panjang balasan sendiri sebelum hasilnya dipercaya.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Detik. Dipakai sebagai `timer_sec` pymcprotocol, yang memasang socket
#: timeout = timer_sec + 1. Bawaan pustakanya 2 detik; pada loop yang bangun
#: tiap 200 ms itu berarti satu panggilan macet membekukan sepuluh tick.
DEFAULT_TIMEOUT_S = 1.0


class McProtocolPlcClient:
    def __init__(
        self,
        host: str,
        port: int = 1025,
        device_prefix: str = "M",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        _client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._prefix = device_prefix
        self._timeout_s = timeout_s
        self._factory = _client_factory or self._default_factory
        self._client: Any = None
        self.connected = False

    def _default_factory(self) -> Any:
        import pymcprotocol

        return pymcprotocol.Type3E()

    def _baca_terjaga(self, headdevice: str, count: int) -> list[int]:
        """`batchread_bitunits` yang menolak balasan terpotong.

        Nilai kembalian pustaka TIDAK bisa dipakai untuk membedakan sukses dari
        kegagalan: ia membangun daftarnya dengan `range(readsize)`, jadi balasan
        0 byte dan balasan sah sama-sama menghasilkan 20 elemen — yang gagal
        berisi nol semua. Terbukti diukur: 21 byte vs 0 byte, hasil identik.

        Satu-satunya tempat bedanya masih terlihat adalah bytes mentah, jadi
        `_recv` dibungkus selama satu panggilan dan panjangnya diperiksa di
        sini. Kalau tidak, kabel putus akan terbaca sebagai "semua input mati"
        — dan E-stop yang sedang DITEKAN terbaca lepas.
        """
        # kepala(9) + status(2); tiap byte data memuat dua bit.
        minimal = 11 + (count + 1) // 2
        terpendek: list[int] = []

        recv_asli = self._client._recv

        def recv_terjaga():
            data = recv_asli()
            terpendek.append(len(data))
            return data

        self._client._recv = recv_terjaga
        try:
            bits = self._client.batchread_bitunits(headdevice=headdevice, readsize=count)
        finally:
            self._client._recv = recv_asli

        if not terpendek or terpendek[0] < minimal:
            diterima = terpendek[0] if terpendek else 0
            raise OSError(
                f"balasan PLC terpotong: {diterima} byte diterima, minimal {minimal}"
            )
        return bits

    def _device(self, address: int) -> str:
        """Angka yang dipakai worker -> nama device yang dimengerti PLC."""
        return f"{self._prefix}{address}"

    def _ensure(self) -> bool:
        if self.connected and self._client is not None:
            return True
        try:
            self._client = self._factory()
            # Dipasang SEBELUM connect: setaccessopt juga menyentuh socket yang
            # sudah ada, tapi urutan ini yang membuat socket pertama pun lahir
            # dengan timeout yang benar.
            self._client.setaccessopt(timer_sec=int(self._timeout_s))
            self._client.connect(self._host, self._port)
            self.connected = True
        except Exception as exc:
            logger.warning("PLC connect ke %s:%s gagal: %s", self._host, self._port, exc)
            self._client = None
            self.connected = False
        return self.connected

    def _drop(self, exc: Exception) -> None:
        """Tandai terputus dan buang socket.

        Wajib menutup socket, bukan cuma menurunkan flag: `_is_connected` di
        dalam pymcprotocol tidak ikut reset sendiri, dan `_send` pada socket
        yang sudah mati melempar selamanya.
        """
        logger.warning("PLC I/O gagal (%s) — menandai terputus, akan reconnect", exc)
        self.connected = False
        try:
            if self._client is not None:
                self._client.close()
        except Exception as close_exc:
            logger.debug("Socket close gagal di _drop: %s", close_exc)
        self._client = None

    def write_coil(self, address: int, value: bool) -> bool:
        """Tulis satu bit. Nama `coil` dipertahankan supaya sebangun dengan
        ModbusPlcClient — worker memanggil keduanya lewat nama yang sama."""
        if not self._ensure():
            return False
        try:
            self._client.batchwrite_bitunits(
                headdevice=self._device(address), values=[1 if value else 0]
            )
        except Exception as exc:
            self._drop(exc)
            return False
        return True

    def write_coils(self, values: dict[int, bool]) -> dict[int, bool]:
        """Tulis beberapa bit yang alamatnya berserakan dalam SATU paket.

        Kembaliannya {alamat: berhasil}. Dipakai worker kalau tersedia: satu
        tick bisa mengubah OK, NG dan heartbeat sekaligus, dan tiga paket
        terpisah berarti tiga round-trip di dalam anggaran 200 ms yang sama.
        Kalau paketnya gagal, SELURUH alamat dilaporkan gagal — tidak ada
        jalan untuk tahu mana yang sempat masuk, dan menebak "sebagian
        berhasil" akan membuat worker berhenti mencoba ulang bit yang
        sebenarnya tidak pernah sampai.
        """
        if not values:
            return {}
        if not self._ensure():
            return dict.fromkeys(values, False)
        devices = [self._device(a) for a in values]
        bits = [1 if v else 0 for v in values.values()]
        try:
            self._client.randomwrite_bitunits(bit_devices=devices, values=bits)
        except Exception as exc:
            self._drop(exc)
            return dict.fromkeys(values, False)
        return dict.fromkeys(values, True)

    def read_discrete_inputs(self, start: int, count: int) -> list[bool] | None:
        """Baca blok bit dari PLC (motor fault, E-stop, konfirmasi piston).

        Namanya warisan Modbus dan sengaja dipertahankan. Di MC Protocol ini
        bukan 'discrete input' terpisah — cuma blok device yang kebetulan
        ditulis ladder dan dibaca kita.
        """
        if not self._ensure():
            return None
        try:
            bits = self._baca_terjaga(self._device(start), count)
        except Exception as exc:
            self._drop(exc)
            return None
        return [bool(b) for b in bits][:count]

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                logger.debug("Socket close gagal: %s", exc)
        self._client = None
        self.connected = False
