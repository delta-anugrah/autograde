"""Runs the real operator console for browser tests, isolated from the developer's machine.

The console runs from a COPY of `src/palmgrade` in a temporary folder:

- `load_dotenv()` climbs from the code's own folder, so a copy outside the repo finds no
  `.env` (a developer's `.env` may point ERP_URL at production or set APP_ENV=production);
- `repo_root` becomes the temporary folder, so `media.env`, `artifacts/` and `state/` land
  there and never in the developer's checkout.

Ports come from the OS and are never 8000/8100/8001-8003, where a developer's own console
and lines may be running.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
PORT_DEVELOPER = frozenset({8000, 8100, 8001, 8002, 8003})
MULAI_MAKS_S = 30.0
BERHENTI_MAKS_S = 10.0
SEED_MAKS_S = 120.0
_JEDA_TANYA_S = 0.2
_TANYA_HEALTH_MAKS_S = 1.0
_BARIS_LOG = 40


def port_bebas() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in PORT_DEVELOPER:
            return port


def jalankan_terbatas(
    perintah: list[str], *, batas_s: float, env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `perintah` to the end within `batas_s`, stdout and stderr together.

    It runs in its own session. One that hangs is killed with its whole process group (the
    console a nested pytest started, its Playwright driver), and the error carries what it
    printed: killing only the parent would leave those running and lose the one clue to why it
    hung. A browser Playwright launched in its own group is not in it; it exits once its driver
    is gone.
    """
    proses = subprocess.Popen(
        perintah,
        env=env,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        keluaran, _ = proses.communicate(timeout=batas_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proses.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # the group ended between the timeout and the kill
        try:
            keluaran, _ = proses.communicate(timeout=BERHENTI_MAKS_S)
        except subprocess.TimeoutExpired as habis:  # a grandchild in its own session holds the pipe
            keluaran = habis.output.decode(errors="replace") if isinstance(habis.output, bytes) else ""
        nama = " ".join(Path(bagian).name for bagian in perintah[:2])
        raise RuntimeError(f"{nama} did not finish within {batas_s:.0f} s:\n{keluaran}") from None
    return subprocess.CompletedProcess(perintah, proses.returncode, keluaran, "")


def _salin_kode(tujuan: Path) -> Path:
    """`src/palmgrade` and the demo seeder under `tujuan`; returns the copied `src`."""
    src = tujuan / "src"
    shutil.copytree(REPO / "src" / "palmgrade", src / "palmgrade", ignore=shutil.ignore_patterns("__pycache__"))
    (tujuan / "scripts").mkdir()
    shutil.copy2(REPO / "scripts" / "seed-console-demo.py", tujuan / "scripts")
    return src


class KonsolUji:
    """One console process: seeded, started, stopped. Never shares state with a real one."""

    def __init__(self, root: Path, port_line: tuple[int, int, int], env: dict[str, str] | None = None) -> None:
        self.root = root
        self.port_line = port_line
        # On top of `_env`, for a console started differently (DEMO_MODE in test_browser_demo_hidup).
        self.env_tambahan = dict(env or {})
        self.port = port_bebas()
        self.src = _salin_kode(root)
        self.state = root / "state"
        self.state.mkdir()
        self.log = root / "konsol.log"
        self._proses: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def pid(self) -> int | None:
        return self._proses.pid if self._proses else None

    def _env(self) -> dict[str, str]:
        # Nothing inherited but PATH and HOME: a shell variable must not steer the test.
        return {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONPATH": str(self.src),
            "PYTHONDONTWRITEBYTECODE": "1",
            "APP_MODE": "console",
            "APP_ENV": "development",
            "STATE_DIR": str(self.state),
            "ERP_URL": "",
            "FACTORY_TZ": "Asia/Jakarta",
            "CONSOLE_LINE_HOST": "http://127.0.0.1",
            # A release number, not `unknown`: Update now (batch 4.6) offers nothing above a
            # version it cannot read.
            "APP_VERSION": "v1.22.0",
            **self.env_tambahan,
        }

    def seed(self, *, hari: int) -> None:
        hasil = jalankan_terbatas(
            [sys.executable, str(self.root / "scripts" / "seed-console-demo.py"), "--hari", str(hari)],
            batas_s=SEED_MAKS_S,
            env=self._env(),
            cwd=self.root,
        )
        if hasil.returncode != 0:
            raise RuntimeError(f"the demo seeder failed:\n{hasil.stdout}")

    def mulai(self) -> None:
        with self.log.open("wb") as log:
            self._proses = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("konsol_uji.py")),
                    "--port",
                    str(self.port),
                    "--port-line",
                    ",".join(map(str, self.port_line)),
                ],
                env=self._env(),
                # Not the checkout: python-dotenv falls back to the working directory
                # under a debugger or coverage, and the checkout sits under a `.env`.
                cwd=self.root,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        batas = time.monotonic() + MULAI_MAKS_S
        while time.monotonic() < batas:
            if self._proses.poll() is not None:
                raise RuntimeError(f"the console exited while starting:\n{self._ekor_log()}")
            try:
                if httpx.get(self.url + "/health", timeout=_TANYA_HEALTH_MAKS_S).status_code == 200:
                    return
            except httpx.HTTPError:
                pass  # not listening yet; the loop asks again until MULAI_MAKS_S
            time.sleep(_JEDA_TANYA_S)
        self.berhenti()
        raise RuntimeError(f"the console did not answer within {MULAI_MAKS_S:.0f} s:\n{self._ekor_log()}")

    def berhenti(self) -> None:
        if self._proses is None or self._proses.poll() is not None:
            return
        self._proses.terminate()
        try:
            self._proses.wait(timeout=BERHENTI_MAKS_S)
        except subprocess.TimeoutExpired:
            self._proses.kill()
            self._proses.wait()

    def _ekor_log(self, baris: int = _BARIS_LOG) -> str:
        return "\n".join(self.log.read_text(errors="replace").splitlines()[-baris:])
