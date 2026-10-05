"""Console commands → camera line (PalmOS plan §4).

Same direction as palmgrade-api → vision, so the contract is kept exactly as
is: the same `x-internal-secret` header and the same body, so the line's own
`routes/internal.py` needs no change at all.

Split out from `ConsoleService` because this is the only part that knows about
HTTP: the service only needs to know "tell this line to assign a truck", not
the URL, headers, timeout, or the shape of an httpx error. The most useful
side effect: a test can swap out one collaborator instead of patching a
private method on the service.

Pattern and location follow `webhook_client.py` in the same folder.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from ...core.config import LineEndpoint, Settings
from ...domain.kesehatan_ai import kode_http_health
from ...domain.operator_error import (
    KAMERA_TANPA_SAMBUNG_ULANG,
    LINE_MENOLAK,
    LINE_TIDAK_MENJAWAB,
    OperatorError,
)
from ..klien_http import KlienBersama

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0
#: `hidup()` is asked every quarter second while the console waits for a line to exit; a
#: line that is going down is expected not to answer.
_TIMEOUT_HIDUP_S = 0.5
#: `setelan_aktif()` is read when support opens Settings.
_TIMEOUT_SETELAN_S = 2.0
#: The line answers a reconnect request before it touches the camera, so the button
#: never waits on the camera itself; a line that needs longer than this is not answering.
TIMEOUT_SAMBUNG_ULANG_S = 5.0


class LineUnavailable(OperatorError, RuntimeError):
    """Camera line did not answer — the operator must see this, not silence."""


class LinePlcTolak(RuntimeError):
    """Line answered but refused the PLC coil command (409 busy, 422 unknown coil).

    Kept separate from `LineUnavailable`: those two codes are the dev screen's
    own safety guards echoed back from the line, not "the line is down" —
    DevService needs the real status_code to answer the console the same way.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class KameraTanpaSambungUlang(OperatorError):
    """The line's image source is a video file or a photo: nothing to reconnect (409).

    Not a `ValueError` on purpose: the console route answers 404 for those (unknown line).
    """


def _kode_line(res: httpx.Response) -> str | None:
    """`detail.kode` of a line refusal (`{"detail": {"kode": ..., "pesan": ...}}`), or None."""
    try:
        isi = res.json()
    except ValueError:
        return None
    detail = isi.get("detail") if isinstance(isi, dict) else None
    return detail.get("kode") if isinstance(detail, dict) else None


def _503_dari_penjaga(res: httpx.Response) -> bool:
    """Badan `/health` line menyebut 503-nya dari penjaga (routes/health_ringan.py):
    AI mati (batch 2.1) atau frame berhenti (batch 3.6). Aturannya satu dengan
    yang menjawab 503 itu, supaya keadaan baru tidak lupa ditambahkan di sini."""
    try:
        isi = res.json()
    except ValueError:
        return False
    ai = isi.get("ai") if isinstance(isi, dict) else None
    return isinstance(ai, dict) and kode_http_health(ai) == 503


class LineClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        # One client for every call to every line (batch 6.5). Each call passes its own
        # timeout; `_TIMEOUT_S` only covers a call that forgets to. Tests swap the network
        # through `transport`, like ErpClient.
        self._http = KlienBersama(timeout=_TIMEOUT_S, transport=transport)

    async def aclose(self) -> None:
        """Close the kept HTTP client (console shutdown)."""
        await self._http.tutup()

    async def assign_truck(
        self,
        line: LineEndpoint,
        *,
        assignment_id: str,
        truck_id: str,
        assigned_at: str,
        ffb_source: str | None = None,
        plate: str | None = None,
    ) -> None:
        await self._post(
            line,
            "/internal/assignment",
            {
                "machine_id": line.machine_id,
                "assignment_id": assignment_id,
                "truck_id": truck_id,
                "assigned_at": assigned_at,
                # An old line ignores unknown fields (pydantic extra=ignore), so
                # it is safe to send this to an image that does not know it yet.
                "ffb_source": ffb_source,
                # Label only — names the capture folder. `truck_id` above stays
                # the key for every number that matters.
                "plate": plate,
            },
        )

    async def manual_reject(
        self, line: LineEndpoint, *, assignment_id: str, requested_by: str, requested_at: str
    ) -> None:
        await self._post(
            line,
            "/internal/manual-reject",
            {
                "machine_id": line.machine_id,
                "assignment_id": assignment_id,
                "requested_by": requested_by,
                "requested_at": requested_at,
            },
        )

    async def set_piston(
        self, line: LineEndpoint, *, open: bool, requested_by: str, requested_at: str
    ) -> None:
        await self._post(
            line,
            "/internal/piston",
            {
                "machine_id": line.machine_id,
                "open": open,
                "requested_by": requested_by,
                "requested_at": requested_at,
            },
        )

    async def reconnect_camera(self, line: LineEndpoint, *, requested_by: str) -> None:
        """Ask `line` to reconnect its camera (the button on every line card).

        The line only raises a flag and answers 202; its capture thread reconnects on the
        next turn. Every refusal becomes a code the screen words: 409 with the line's code
        = `KameraTanpaSambungUlang` (a video or photo source), 401/403 = `LINE_MENOLAK`
        (the INTERNAL_SECRET differs), anything else or no answer = `LINE_TIDAK_MENJAWAB`.
        """
        url = f"{self._settings.console_line_host}:{line.port}/internal/camera/reconnect"
        try:
            res = await self._http.ambil().post(
                url,
                json={"requested_by": requested_by},
                headers={"x-internal-secret": self._settings.internal_secret},
                timeout=TIMEOUT_SAMBUNG_ULANG_S,
            )
        except httpx.HTTPError as exc:
            logger.warning("Camera reconnect on %s failed: %s", line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc
        if res.status_code < 400:
            return
        logger.warning(
            "Camera reconnect refused by %s: HTTP %s %s", line.line_code, res.status_code, res.text[:200]
        )
        if res.status_code == 409 and _kode_line(res) == KAMERA_TANPA_SAMBUNG_ULANG:
            raise KameraTanpaSambungUlang(
                KAMERA_TANPA_SAMBUNG_ULANG, f"{line.line_code} has no camera to reconnect", line=line.name
            )
        raise LineUnavailable(
            LINE_MENOLAK if res.status_code in (401, 403) else LINE_TIDAK_MENJAWAB,
            f"{line.line_code} answered: HTTP {res.status_code} {res.text[:200]}",
            line=line.name,
            status=res.status_code,
        )

    async def plc_state(self, line: LineEndpoint) -> dict[str, Any]:
        """DI snapshot + testable coils for the commissioning test screen.

        Read-only lane; same short timeout as `status()` — this backs a
        polling screen, not a once-a-shift diagnostic read.
        """
        return await self._get_json(line, "/internal/plc", timeout_s=2.0)

    async def plc_coil(self, line: LineEndpoint, *, coil: int, requested_by: str) -> dict[str, Any]:
        """Fire one PLC coil on `line` for a wiring test. Raises on 4xx/5xx —
        the caller (DevService) must see the reason, not a silent no-op."""
        url = f"{self._settings.console_line_host}:{line.port}/internal/plc/coil"
        try:
            res = await self._http.ambil().post(
                url,
                json={"machine_id": line.machine_id, "coil": coil, "requested_by": requested_by},
                headers={"x-internal-secret": self._settings.internal_secret},
                timeout=_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            logger.warning("PLC test coil %s to %s failed: %s", coil, line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc
        if res.status_code >= 400:
            # 409 busy / 422 unknown coil are the line's own safety answers, not
            # "unreachable" — raised distinctly so DevService can echo the same
            # status back to the console instead of collapsing both into 502.
            raise LinePlcTolak(res.status_code, res.text[:200])
        return res.json()

    async def kirim_setelan(
        self,
        line: LineEndpoint,
        *,
        conf_threshold: float,
        minimum_size: int,
        garis_capture: int = 0,
        sumbu_garis: str = "tegak",
        mode_dev: bool = False,
        tampil_garis: bool = True,
        tampil_roi: bool = True,
        ukuran_label: int = 100,
        **kotak: int | None,
    ) -> dict[str, Any]:
        """Kirim setelan grading ke satu line. Melempar kalau line tidak menjawab.

        Pemanggil (`ConsoleService`) menangkapnya per line, jadi satu line yang
        mati tidak membatalkan pengiriman ke dua line lainnya — konsol sudah
        menyimpan nilainya dan akan mengirim ulang saat line itu kembali.
        """
        url = f"{self._settings.console_line_host}:{line.port}/internal/setelan"
        try:
            res = await self._http.ambil().post(
                url,
                json={
                    "conf_threshold": conf_threshold,
                    "minimum_size": minimum_size,
                    "garis_capture": garis_capture,
                    "sumbu_garis": sumbu_garis,
                    "mode_dev": mode_dev,
                    "tampil_garis": tampil_garis,
                    "tampil_roi": tampil_roi,
                    "ukuran_label": ukuran_label,
                    **kotak,  # roi_x1..roi_y2, None = the line keeps its `.env` box
                },
                headers={"x-internal-secret": self._settings.internal_secret},
                timeout=_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            logger.warning("Kirim setelan ke %s gagal: %s", line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc
        if res.status_code >= 400:
            raise LinePlcTolak(res.status_code, res.text[:200])
        return res.json()

    async def restart(self, line: LineEndpoint) -> None:
        """Suruh satu line mematikan diri supaya Docker menyalakannya ulang.

        Dipakai sesudah `media.env` ditulis: line membaca sumber kameranya dari
        environment saat boot, jadi setelan baru tidak berlaku sampai prosesnya
        benar-benar mati.

        Melempar kalau line tidak menjawab. Pemanggil TIDAK membatalkan
        penyimpanan karena itu: berkasnya sudah sah, tinggal line itu yang belum
        membacanya — dan ia akan membacanya sendiri saat hidup lagi.
        """
        await self._post(line, "/internal/restart", {})

    async def status(self, line: LineEndpoint) -> dict[str, Any]:
        """Called once a second by LineStatusWorker, so the timeout is short:
        the operator screen must not be made to wait on a dying line."""
        return await self._get_json(line, "/internal/status", timeout_s=1.5)

    async def setelan_aktif(self, line: LineEndpoint) -> dict[str, Any]:
        """The grading settings the line uses now, with its own `.env` box (`roi_env`).

        Read when support opens Settings, so the timeout is short: a dead line must not
        hold the screen (`services/roi_bawaan.py` asks the three side by side).
        """
        return await self._get_json(line, "/internal/setelan", timeout_s=_TIMEOUT_SETELAN_S)

    async def health_detail(self, line: LineEndpoint) -> dict[str, Any]:
        """Full `/health/detail` for the support diagnostics screen.

        Longer timeout than `status()`: this is a support-only read, not the
        once-a-second path, so it can afford to wait a little longer on a
        struggling line instead of flagging it unreachable too eagerly.
        """
        return await self._get_json(line, "/health/detail", timeout_s=5.0)

    async def camera_settings(self, line: LineEndpoint) -> dict[str, Any]:
        """`/internal/camera/settings` for the support camera settings screen.

        5 s like `health_detail`: the line itself waits up to 2 s for its capture thread. 409 (not a Hikrobot
        camera), 503 (camera not answering) and 404 (a line older than this route) arrive as `LineUnavailable`
        with their `status` through `_get_json`; the service words them.
        """
        return await self._get_json(line, "/internal/camera/settings", timeout_s=5.0)

    async def antrean_line(self, line: LineEndpoint) -> dict[str, Any]:
        """Antrean janjang line itu ke konsol (`/internal/outbox`, batch 2.4), untuk tab Status.

        Timeout sama dengan `health_detail`: layar support yang disegarkan tiap 5
        detik, bukan strip status tiap detik. Kunci yang ditolak sampai sebagai
        `LINE_MENOLAK` lewat `_get_json`.
        """
        return await self._get_json(line, "/internal/outbox", timeout_s=5.0)

    async def log_line(
        self, line: LineEndpoint, *, setelah: int, generasi: str, batas: int
    ) -> dict[str, Any]:
        """Satu halaman WARNING/ERROR line itu (`/internal/log`, batch 3.2) untuk tab Log.

        Timeout sama dengan `antrean_line`: tarikan latar tiap 10 detik, bukan strip
        status tiap detik. Line versi lama menjawab 404, dan itu sampai sebagai
        `LineUnavailable` dengan `status` 404 lewat `_get_json`: pemanggil
        (`TarikLogLineWorker`) diam dan mencoba lagi beberapa menit kemudian.
        """
        kueri = urlencode({"setelah": setelah, "generasi": generasi, "batas": batas})
        return await self._get_json(line, f"/internal/log?{kueri}", timeout_s=5.0)

    async def kirim_ulang_antrean_line(self, line: LineEndpoint) -> int:
        """Suruh line mengirim seluruh antreannya sekarang. Mengembalikan jumlahnya.

        Aturannya sama dengan `_get_json`: cuma 401/403 (penjaga kunci line) yang
        `LINE_MENOLAK`. Status galat lain datang dari line itu sendiri (disk penuh,
        `outbox.db` rusak) dan jadi `LINE_TIDAK_MENJAWAB` membawa statusnya: layar
        menyuruh menyamakan INTERNAL_SECRET untuk `LINE_MENOLAK`, dan untuk 500
        itu tindakan yang salah. Jawaban yang bukan `{"requeued": <int>}` juga
        `LINE_TIDAK_MENJAWAB`, bukan angka tebakan.
        """
        try:
            jawab = await self._post_json(line, "/internal/outbox/requeue", {})
        except LinePlcTolak as exc:
            ditolak = exc.status_code in (401, 403)
            raise LineUnavailable(
                LINE_MENOLAK if ditolak else LINE_TIDAK_MENJAWAB,
                f"{line.line_code} {'refused' if ditolak else 'answered'}: HTTP {exc.status_code} {exc.detail}",
                line=line.name,
                status=exc.status_code,
            ) from exc
        except ValueError as exc:  # badan 200 yang bukan JSON
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} answered non-JSON: {exc}", line=line.name
            ) from exc
        jumlah = jawab.get("requeued") if isinstance(jawab, dict) else None
        if not isinstance(jumlah, int) or isinstance(jumlah, bool):
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB,
                f"{line.line_code} answered an unexpected requeue body: {str(jawab)[:200]}",
                line=line.name,
            )
        return jumlah

    # ── rekam video developer ───────────────────────────────────────────────

    async def rekam_mulai(
        self, line: LineEndpoint, setelan: dict[str, Any]
    ) -> dict[str, Any]:
        """Suruh satu line mulai merekam dengan setelan ini.

        Setelan dikirim tiap kali mulai dan tidak disimpan line — itu yang
        membuat "restart container = rekaman mati" jadi sifat, bukan sesuatu
        yang harus dijaga kode tambahan.
        """
        return await self._post_json(line, "/internal/rekam/mulai", setelan)

    async def rekam_stop(self, line: LineEndpoint) -> dict[str, Any]:
        return await self._post_json(line, "/internal/rekam/stop", {})

    async def rekam_status(self, line: LineEndpoint) -> dict[str, Any]:
        """Dipanggil layar tiap beberapa detik selama tab rekam terbuka.

        Timeout `_TIMEOUT_S`, bukan 1,5 detik seperti `status()`: line yang
        sedang menjalankan inference kadang butuh lebih dari dua detik untuk
        menjawab, dan layar yang menyerah terlalu cepat menulis "Tak terbaca"
        untuk line yang sebenarnya sehat — terbaca persis seperti line mati.
        Ini layar support yang dibuka sesekali, bukan strip status yang
        dipolling tiap detik, jadi menunggu sedikit lebih lama tidak
        memperlambat apa pun yang dilihat operator.

        Kunci yang ditolak (401/403) sampai sebagai `LINE_MENOLAK`, bukan "tidak
        menjawab", lewat `_get_json` yang sama dengan pembacaan status lain.
        Gagalnya dicatat pemanggil (`rekam_status_semua`), sekali per line.
        """
        return await self._get_json(line, "/internal/rekam/status", timeout_s=_TIMEOUT_S)

    # ── Danger Zone (layar Setelan, support) ────────────────────────────────

    async def hapus_data(
        self, line: LineEndpoint, *, mode: str, diminta_oleh: str
    ) -> dict[str, Any]:
        """Suruh line menghapus datanya sendiri: menulis penanda lalu keluar,
        dihapus saat boot berikutnya. 409 (truk terpasang) sampai sebagai
        `LinePlcTolak` membawa kode statusnya, bukan "line mati"."""
        return await self._post_json(
            line, "/internal/hapus-data", {"mode": mode, "diminta_oleh": diminta_oleh}
        )

    async def rekam_hapus(self, line: LineEndpoint) -> dict[str, Any]:
        """Hapus rekaman milik line itu. 409 = sedang merekam."""
        return await self._post_json(line, "/internal/rekam/hapus", {})

    async def rekam_berkas(self, line: LineEndpoint) -> dict[str, Any]:
        """Jumlah + ukuran rekaman milik line itu, dan apakah sedang merekam."""
        return await self._get_json(line, "/internal/rekam/berkas", timeout_s=_TIMEOUT_S)

    async def hidup(self, line: LineEndpoint) -> bool:
        """Apakah proses line menjawab `/health` saat ini. Tidak pernah melempar.

        200 = hidup; 503 dari penjaga (AI mati ATAU frame berhenti) juga hidup: prosesnya
        jalan, cuma tidak menyortir. Dipakai berulang (tiap ¼ detik) saat konsol menunggu line keluar sesudah
        perintah hapus, jadi timeout-nya pendek: line yang sedang mati memang
        diharapkan tidak menjawab.
        """
        url = f"{self._settings.console_line_host}:{line.port}/health"
        try:
            res = await self._http.ambil().get(url, timeout=_TIMEOUT_HIDUP_S)
        except httpx.HTTPError:
            return False
        if res.status_code == 200:
            return True
        # `/health` menjawab 503 kalau AI line mati (batch 2.1) atau frame berhenti
        # (batch 3.6), tapi prosesnya masih hidup dan masih menjalankan urutan
        # tutupnya. Dibaca "mati" di sini, Danger Zone berhenti menunggu dan
        # mengosongkan konsol sebelum antrean simpan line itu habis dikirim.
        return res.status_code == 503 and _503_dari_penjaga(res)

    async def _get_json(
        self, line: LineEndpoint, path: str, *, timeout_s: float
    ) -> dict[str, Any]:
        """GET dipakai lima pembacaan status (`status`, `health_detail`,
        `plc_state`, `rekam_berkas`, `rekam_status`).

        401/403 diperiksa SEBELUM `raise_for_status()` dan dilempar sebagai
        `LINE_MENOLAK` (sama seperti `_post`), bukan `LINE_TIDAK_MENJAWAB`:
        keduanya dulu memakai `raise_for_status()` di dalam `except
        httpx.HTTPError`, jadi kunci INTERNAL_SECRET yang beda antara konsol
        dan line (compose host pabrik cuma meneruskannya ke sebagian
        container) terbaca sebagai "line tidak menjawab". Line yang sebenarnya
        masih menggrading dan masih mengirim event lewat WEBHOOK_SECRET
        tampil OFFLINE di layar operator, dan Danger Zone melaporkan "line
        mati" padahal cuma kuncinya yang beda.

        Penolakan dicatat DEBUG, bukan WARNING: `status()` dipanggil tiap detik,
        dan WARNING-nya milik `LineStatusWorker` (sekali per transisi). Pembaca
        lain menerima `LINE_MENOLAK` dan menampilkannya sendiri.
        """
        url = f"{self._settings.console_line_host}:{line.port}{path}"
        try:
            res = await self._http.ambil().get(
                url,
                headers={"x-internal-secret": self._settings.internal_secret},
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc
        if res.status_code in (401, 403):
            logger.debug(
                "%s ke %s menolak kunci: HTTP %s (INTERNAL_SECRET beda antara konsol dan line?)",
                path, line.line_code, res.status_code,
            )
            raise LineUnavailable(
                LINE_MENOLAK,
                f"{line.line_code} refused: HTTP {res.status_code} {res.text[:200]}",
                line=line.name,
                status=res.status_code,
            )
        try:
            res.raise_for_status()
        except httpx.HTTPError as exc:
            # `status` ikut: line versi lama yang belum punya rutenya menjawab 404,
            # dan layar bisa menulis "line menjawab HTTP 404", bukan sekadar mati.
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB,
                f"{line.line_code} did not answer: {exc}",
                line=line.name,
                status=res.status_code,
            ) from exc
        return res.json()

    async def _post_json(
        self, line: LineEndpoint, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Seperti `_post`, tapi memulangkan jawaban line.

        Dipakai rekam video: layar butuh nama berkas dan hitungan frame, dan
        kode status line (409 sudah merekam, 507 disk penuh) harus sampai ke
        layar sebagai pesan yang berbeda — bukan satu "gagal" untuk semuanya.
        """
        url = f"{self._settings.console_line_host}:{line.port}{path}"
        try:
            res = await self._http.ambil().post(
                url,
                json=body,
                headers={"x-internal-secret": self._settings.internal_secret},
                timeout=_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            logger.warning("Perintah %s ke %s gagal: %s", path, line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc
        if res.status_code >= 400:
            # Pesan line diteruskan apa adanya: "sudah merekam" dan "disk
            # penuh" butuh tindakan yang berbeda, dan meratakannya jadi satu
            # kalimat membuat support menebak.
            raise LinePlcTolak(res.status_code, res.text[:200])
        return res.json()

    async def _post(self, line: LineEndpoint, path: str, body: dict[str, Any]) -> None:
        url = f"{self._settings.console_line_host}:{line.port}{path}"
        try:
            res = await self._http.ambil().post(
                url,
                json=body,
                headers={"x-internal-secret": self._settings.internal_secret},
                timeout=_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            # The screen shows a translated sentence; the httpx cause lives in the log.
            logger.warning("Command %s to %s failed: %s", path, line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc
        if res.status_code >= 400:
            logger.warning(
                "Command %s refused by %s: HTTP %s %s",
                path, line.line_code, res.status_code, res.text[:200],
            )
            raise LineUnavailable(
                LINE_MENOLAK,
                f"{line.line_code} refused: HTTP {res.status_code} {res.text[:200]}",
                line=line.name,
                status=res.status_code,
            )
        logger.info("Command %s accepted by %s", path, line.line_code)
