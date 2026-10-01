"""`scripts/smoke_image.py`: the check an image passes before it gets its release tag (batch 4.2).

Docker is replaced by a fake runner, so every refusal path is proven without an image.
The same script runs against a real image in `tests/e2e/test_smoke_image_docker.py`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_image.py"
_spec = importlib.util.spec_from_file_location("smoke_image", SCRIPT)
smoke_image = importlib.util.module_from_spec(_spec)
# `dataclass` looks the module up in sys.modules while the class is created.
sys.modules["smoke_image"] = smoke_image
_spec.loader.exec_module(smoke_image)

Result = smoke_image.Result
SmokeFailed = smoke_image.SmokeFailed

IMAGE = "ghcr.io/delta-anugrah/autograde@sha256:abc"
SEHAT = {"status": "ok", "mode": "console", "version": "v1.22.0"}


class DockerPalsu:
    """Answers like docker for a healthy image; each attribute breaks one part."""

    def __init__(self, **ubah):
        self.label = "v1.22.0"
        self.line_exit = 0
        self.console_exit = 0
        self.run_d_exit = 0
        self.health = dict(SEHAT)
        self.health_after = 0  # number of /health polls that fail before it answers
        self.berhenti = False  # container exits right after start
        self.__dict__.update(ubah)
        self.panggilan: list[list[str]] = []
        self._poll = 0

    def __call__(self, args):
        args = list(args)
        self.panggilan.append(args)
        cmd = args[0]
        if cmd == "image":
            if self.label is None:
                return Result(1, "", "Error: No such image")
            return Result(0, json.dumps({smoke_image.VERSION_LABEL: self.label}), "")
        if cmd == "run" and "-d" in args:
            return Result(self.run_d_exit, "c0ffee\n" if self.run_d_exit == 0 else "", "boom")
        if cmd == "run":
            kode = args[-1]
            if kode == smoke_image.IMPORT_LINE:
                return Result(self.line_exit, "", "ModuleNotFoundError: torch")
            return Result(self.console_exit, "", "AssertionError: console imported torch")
        if cmd == "exec":
            self._poll += 1
            if self.berhenti or self._poll <= self.health_after:
                return Result(1, "", "connection refused")
            return Result(0, json.dumps(self.health), "")
        if cmd == "inspect":
            return Result(0, "false\n" if self.berhenti else "true\n", "")
        if cmd == "logs":
            return Result(0, "RuntimeError: WEBHOOK_SECRET is required\n", "")
        if cmd == "rm":
            return Result(0, "", "")
        raise AssertionError(f"unexpected docker call: {args}")

    def dihapus(self) -> bool:
        return ["rm", "-f", "c0ffee"] in self.panggilan


def _jalan(docker, **kw):
    log: list[str] = []
    smoke_image.smoke(docker, IMAGE, "v1.22.0", "v1.22.0", log=log.append)
    return log


def test_image_sehat_lulus_semua_cek_berurutan():
    docker = DockerPalsu()
    assert _jalan(docker) == ["ok   label", "ok   line", "ok   console", "ok   boot"]
    assert docker.dihapus(), "the console container must be removed"


def test_label_versi_salah_ditolak():
    """Launcher pabrik membaca versi dari label ini; label lain = update salah dibaca."""
    with pytest.raises(SmokeFailed, match="label"):
        _jalan(DockerPalsu(label="v1.21.0"))


def test_label_hilang_ditolak():
    with pytest.raises(SmokeFailed, match="label: org.opencontainers.image.version is ''"):
        _jalan(DockerPalsu(label=""))
    with pytest.raises(SmokeFailed, match="not found locally"):
        _jalan(DockerPalsu(label=None))


def test_label_null_tidak_membuat_skrip_mogok():
    """`docker inspect` mencetak `null` untuk image tanpa label sama sekali."""
    docker = DockerPalsu()
    asli = docker.__call__

    def tanpa_label(args):
        if args[0] == "image":
            return Result(0, "null\n", "")
        return asli(args)

    with pytest.raises(SmokeFailed, match="is None"):
        smoke_image.check_label(tanpa_label, IMAGE, "v1.22.0")


def test_line_yang_gagal_import_ditolak_sebelum_konsol_dicoba():
    docker = DockerPalsu(line_exit=1)
    with pytest.raises(SmokeFailed, match="line import: exit 1"):
        _jalan(docker)
    assert not any(a[0] == "run" and "-d" in a for a in docker.panggilan)


def test_konsol_yang_menarik_torch_ditolak():
    with pytest.raises(SmokeFailed, match="console import"):
        _jalan(DockerPalsu(console_exit=1))


def test_import_jalan_tanpa_jaringan():
    """Tanpa `--network none`, Ultralytics bisa `pip install` yang kurang dan menutupinya."""
    docker = DockerPalsu()
    _jalan(docker)
    impor = [a for a in docker.panggilan if a[0] == "run" and "-d" not in a]
    assert len(impor) == 2
    for args in impor:
        assert args[1:4] == ["--rm", "--network", "none"], args


def test_konsol_dinyalakan_mode_konsol_tanpa_jaringan():
    docker = DockerPalsu()
    _jalan(docker)
    start = next(a for a in docker.panggilan if a[0] == "run" and "-d" in a)
    assert ["--network", "none"] == start[2:4]
    assert "APP_MODE=console" in start


def test_konsol_lambat_tetap_ditunggu():
    docker = DockerPalsu(health_after=3)
    tidur: list[float] = []
    smoke_image.check_console_boot(docker, IMAGE, "v1.22.0", sleep=tidur.append)
    assert len(tidur) == 3
    assert docker.dihapus()


def test_konsol_yang_mati_saat_boot_ditolak_tanpa_menunggu_batas_waktu():
    """`validate_secrets` menolak boot: container keluar seketika. Menunggu 120 dtk
    cuma memperlambat job merah."""
    docker = DockerPalsu(berhenti=True)
    tidur: list[float] = []
    with pytest.raises(SmokeFailed, match="console stopped") as err:
        smoke_image.check_console_boot(docker, IMAGE, "v1.22.0", sleep=tidur.append)
    assert tidur == []
    assert "WEBHOOK_SECRET" in str(err.value), "the container log must reach the job log"
    assert docker.dihapus()


def test_konsol_yang_tidak_pernah_menjawab_ditolak_sesudah_batas_waktu():
    docker = DockerPalsu(health_after=10**6)
    jam = iter(range(0, 1000, 10))
    with pytest.raises(SmokeFailed, match="did not answer within 30 s"):
        smoke_image.check_console_boot(
            docker, IMAGE, "v1.22.0", timeout_s=30, sleep=lambda _s: None, clock=lambda: next(jam)
        )
    assert docker.dihapus()


@pytest.mark.parametrize(
    "health",
    [
        {**SEHAT, "version": "v1.21.0"},
        {**SEHAT, "version": "unknown"},
        {**SEHAT, "mode": "line"},
        {**SEHAT, "status": "degraded"},
    ],
)
def test_health_yang_tidak_cocok_ditolak(health):
    docker = DockerPalsu(health=health)
    with pytest.raises(SmokeFailed, match="/health returned"):
        smoke_image.check_console_boot(docker, IMAGE, "v1.22.0")
    assert docker.dihapus()


def test_container_yang_gagal_start_ditolak():
    with pytest.raises(SmokeFailed, match="did not start"):
        smoke_image.check_console_boot(DockerPalsu(run_d_exit=125), IMAGE, "v1.22.0")


def test_main_mengembalikan_kode_keluar(capsys):
    assert smoke_image.main([IMAGE, "--version", "v1.22.0", "--label", "v1.22.0"], run=DockerPalsu()) == 0
    assert smoke_image.main([IMAGE, "--version", "v1.22.0", "--label", "v1.22.0-cpu"], run=DockerPalsu()) == 1
    assert "FAIL label" in capsys.readouterr().err


def test_main_tanpa_versi_ditolak_argparse():
    with pytest.raises(SystemExit) as err:
        smoke_image.main([IMAGE], run=DockerPalsu())
    assert err.value.code == 2
