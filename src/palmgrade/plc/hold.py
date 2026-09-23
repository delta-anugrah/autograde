"""Penjadwal TAHAN — coil dipegang ON selama N detik, bukan pulse 200 ms.

Diminta tim PLC 2026-09-23 ("dibuat tahan terus"), sebagai **opsi**, bukan
pengganti: bawaannya tetap `PulseScheduler` dan `PLC_HOLD_MS=0`.

Antarmukanya sama persis dengan `PulseScheduler` (`enqueue` / `tick` /
`dropped` / `is_active`) supaya `PlcWorker` tidak perlu tahu mana yang
terpasang — jalur pulse yang sudah terbukti di lapangan tidak disentuh sama
sekali oleh keberadaan berkas ini.

Satu beda perilaku yang disengaja: janjang berikutnya yang datang **saat coil
masih ON memperpanjang** tahanannya, tidak mengantre dan tidak dibuang. Itulah
arti "kirim terus selama buah masih lewat". Karena itu juga tidak ada
`queue_max` di sini — tidak ada yang bisa penuh.

⚠️ **PLC tidak bisa menghitung janjang di mode ini.** Dua janjang berurutan
dalam jendela tahan terbaca sebagai SATU sinyal panjang: tidak ada tepi turun
di antaranya. Untuk produksi yang menghitung, tetap pakai pulse dan latch di
ladder. Mode ini untuk uji di panel, atau untuk ladder yang memang cuma
membaca level.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HoldScheduler:
    hold_s: float
    #: Selalu 0 — tidak ada yang dibuang di sini. Ada supaya `diagnostics()`
    #: dan `PlcWorker` bisa membaca field yang sama seperti pada PulseScheduler.
    dropped: int = 0
    #: coil -> waktu monotonic saat tahanan berakhir. 0 = sedang OFF.
    _sampai: dict[int, float] = field(default_factory=dict)
    #: coil yang sudah diminta tapi belum sempat dinyalakan oleh tick berikutnya.
    _minta: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.hold_s <= 0:
            raise ValueError("hold_s harus > 0 (PLC_HOLD_MS=0 berarti pakai PulseScheduler)")

    def enqueue(self, coil: int) -> bool:
        """Minta coil ditahan ON. Selalu True: tidak ada antrean yang bisa penuh."""
        self._minta.add(coil)
        return True

    def tick(self, now: float) -> dict[int, bool]:
        """{coil: level} HANYA untuk coil yang levelnya berubah pada tick ini."""
        ubah: dict[int, bool] = {}

        for coil in self._minta:
            if not self._sampai.get(coil):
                ubah[coil] = True          # baru menyala
            # Sudah ON: perpanjang saja, tanpa tepi apa pun.
            self._sampai[coil] = now + self.hold_s
        self._minta.clear()

        for coil, sampai in list(self._sampai.items()):
            if sampai and now >= sampai and coil not in ubah:
                ubah[coil] = False
                self._sampai[coil] = 0.0
        return ubah

    def is_active(self, coil: int) -> bool:
        """Coil ini sedang ditahan, atau sudah diminta dan menunggu tick."""
        return coil in self._minta or bool(self._sampai.get(coil))
