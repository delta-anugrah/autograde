"""Penjadwal pulse coil — logika murni, tanpa I/O.

Menerjemahkan "satu keputusan grading" jadi satu pulse ON/OFF pada satu coil,
dengan jaminan ada jeda OFF di antara dua pulse pada coil yang sama supaya PLC
selalu melihat tepi naik yang terpisah.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _CoilState:
    on_until: float = 0.0   # waktu pulse aktif harus dimatikan; 0 = sedang OFF
    free_at: float = 0.0    # waktu paling awal pulse berikutnya boleh mulai
    pending: int = 0


@dataclass
class PulseScheduler:
    pulse_s: float
    gap_s: float
    queue_max: int
    dropped: int = 0
    _coils: dict[int, _CoilState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.pulse_s <= 0:
            raise ValueError("pulse_s harus > 0")
        if self.gap_s <= 0:
            raise ValueError(
                "gap_s harus > 0 — tanpa jeda, dua pulse menyatu dan PLC menghitungnya satu"
            )

    def enqueue(self, coil: int) -> bool:
        """Antrekan satu pulse. False = antrean penuh dan pulse ini dibuang."""
        st = self._coils.setdefault(coil, _CoilState())
        if st.pending >= self.queue_max:
            self.dropped += 1
            return False
        st.pending += 1
        return True

    def tick(self, now: float) -> dict[int, bool]:
        """Kembalikan {coil: level} HANYA untuk coil yang levelnya berubah pada tick ini.
        Perlu: `now` dari time.monotonic() (bukan time.time()), karena epsilon 1e-9 scale-dependent."""
        changes: dict[int, bool] = {}
        for coil, st in self._coils.items():
            if st.on_until:
                if now < st.on_until:
                    continue                      # pulse masih jalan, jangan diganggu
                changes[coil] = False
                st.on_until = 0.0
                st.free_at = now + self.gap_s     # gap_s > 0 menjamin ON tidak ikut di tick ini
            # epsilon 1e-9 hanya efektif pada skala kecil (time.monotonic, ULP~1e-15); time.time() punya ULP~4e-7 → nol efek
            if st.pending and now + 1e-9 >= st.free_at:
                st.pending -= 1
                st.on_until = now + self.pulse_s
                changes[coil] = True
        return changes
