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

import httpx

from ...core.config import LineEndpoint, Settings
from ...domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB, OperatorError

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0


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


class LineClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport  # tests swap the network, like ErpClient

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

    async def plc_state(self, line: LineEndpoint) -> dict[str, Any]:
        """DI snapshot + testable coils for the commissioning test screen.

        Read-only lane; same short timeout as `status()` — this backs a
        polling screen, not a once-a-shift diagnostic read.
        """
        url = f"{self._settings.console_line_host}:{line.port}/internal/plc"
        try:
            async with httpx.AsyncClient(timeout=2.0, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc

    async def plc_coil(self, line: LineEndpoint, *, coil: int, requested_by: str) -> dict[str, Any]:
        """Fire one PLC coil on `line` for a wiring test. Raises on 4xx/5xx —
        the caller (DevService) must see the reason, not a silent no-op."""
        url = f"{self._settings.console_line_host}:{line.port}/internal/plc/coil"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(
                    url,
                    json={"machine_id": line.machine_id, "coil": coil, "requested_by": requested_by},
                    headers={"x-internal-secret": self._settings.internal_secret},
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
    ) -> dict[str, Any]:
        """Kirim setelan grading ke satu line. Melempar kalau line tidak menjawab.

        Pemanggil (`ConsoleService`) menangkapnya per line, jadi satu line yang
        mati tidak membatalkan pengiriman ke dua line lainnya — konsol sudah
        menyimpan nilainya dan akan mengirim ulang saat line itu kembali.
        """
        url = f"{self._settings.console_line_host}:{line.port}/internal/setelan"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(
                    url,
                    json={
                        "conf_threshold": conf_threshold,
                        "minimum_size": minimum_size,
                        "garis_capture": garis_capture,
                        "sumbu_garis": sumbu_garis,
                        "mode_dev": mode_dev,
                    },
                    headers={"x-internal-secret": self._settings.internal_secret},
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
        url = f"{self._settings.console_line_host}:{line.port}/internal/status"
        try:
            async with httpx.AsyncClient(timeout=1.5, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc

    async def health_detail(self, line: LineEndpoint) -> dict[str, Any]:
        """Full `/health/detail` for the support diagnostics screen.

        Longer timeout than `status()`: this is a support-only read, not the
        once-a-second path, so it can afford to wait a little longer on a
        struggling line instead of flagging it unreachable too eagerly.
        """
        url = f"{self._settings.console_line_host}:{line.port}/health/detail"
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc

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
        """
        url = f"{self._settings.console_line_host}:{line.port}/internal/rekam/status"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            logger.warning("Status rekam dari %s gagal: %s", line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc

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
        url = f"{self._settings.console_line_host}:{line.port}/internal/rekam/berkas"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} did not answer: {exc}", line=line.name
            ) from exc

    async def hidup(self, line: LineEndpoint) -> bool:
        """Apakah proses line menjawab `/health` saat ini. Tidak pernah melempar.

        Dipakai berulang (tiap ¼ detik) saat konsol menunggu line keluar sesudah
        perintah hapus, jadi timeout-nya pendek: line yang sedang mati memang
        diharapkan tidak menjawab.
        """
        url = f"{self._settings.console_line_host}:{line.port}/health"
        try:
            async with httpx.AsyncClient(timeout=0.5, transport=self._transport) as client:
                res = await client.get(url)
            return res.status_code == 200
        except httpx.HTTPError:
            return False

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
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(
                    url,
                    json=body,
                    headers={"x-internal-secret": self._settings.internal_secret},
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
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(
                    url,
                    json=body,
                    headers={"x-internal-secret": self._settings.internal_secret},
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
