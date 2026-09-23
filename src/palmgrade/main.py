from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.dependencies import (
    get_capture_repository,
    get_outbox_store,
    get_realtime_inspection_pipeline,
    get_runtime_state,
    get_settings,
    get_webhook_client,
    set_camera,
)
from .integrations.outbox.outbox_store import OutboxStore
from .routes.internal import router as internal_router
from .workers.outbox_retry_worker import OutboxRetryWorker
from .core.logging import configure_logging
from .integrations.camera.base import CameraSource
from .integrations.camera.hikrobot_camera import HikrobotCamera
from .integrations.camera.opencv_camera import OpenCVCamera
from .integrations.camera.photo_camera import PhotoCamera
from .license.gate import grading_blocked
from .license.guard import LicenseGuardMiddleware
from .license.local_repo import LicenseLocalRepo
from .license.manager import LicenseManager
from .domain.setelan_grading import bersihkan_setelan
from .domain.sumber_kamera_resolver import rencana_kamera
from .integrations.scheduler.upload_scheduler import UploadScheduler
from .integrations.upload.r2_uploader import R2Uploader
from .integrations.upload.upload_manifest import UploadManifest
from .workers.batch_upload_worker import BatchUploadWorker
from .workers.capture_save_worker import CaptureSaveWorker
from .routes.health import router as health_router
from .routes.inspection import router as inspection_router
from .routes.streaming import router as streaming_router
from .workers.display_worker import DisplayWorker
from .workers.event_broadcast_worker import EventBroadcastWorker
from .workers.frame_capture_worker import FrameCaptureWorker
from .workers.frame_processing_worker import FrameProcessingWorker
from .plc import shutdown_plc_worker, start_plc_worker

load_dotenv(override=False)

logger = logging.getLogger(__name__)


async def _tarik_setelan_grading(settings, state) -> None:
    """Tanya konsol berapa setelan grading yang berlaku, sekali saat start.

    Override di `RuntimeState` hilang bersama prosesnya, jadi container line yang
    dibuat ulang akan kembali memakai `.env` — padahal konsol masih memegang
    angka yang sudah disetujui. Tanpa tarikan ini, satu `docker compose up` di
    tengah shift diam-diam mengembalikan ambang lama dan tidak ada yang tahu
    sampai tonase harian terlihat aneh.

    Gagal = diam dan pakai `.env`. Konsol yang belum hidup saat line start itu
    kejadian normal (urutan start container tidak dijamin), dan line yang menolak
    start gara-gara itu jauh lebih buruk daripada line yang jalan dengan nilai
    `.env` sampai setelan berikutnya disimpan.
    """
    url = f"{settings.backend_url}{settings.backend_api_ver}/internal/setelan"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                url, headers={"x-webhook-secret": settings.webhook_secret}
            )
        if res.status_code != 200:
            logger.info("Setelan grading tidak diambil (HTTP %s) — pakai .env", res.status_code)
            return
        data = res.json()
        if data.get("sumber") != "konsol":
            # Konsol belum pernah diubah dari layar: nilainya memang .env, dan
            # menimpanya dengan angka yang sama cuma bikin log membingungkan.
            return
        # `garis_capture` ikut kalau konsolnya sudah tahu field itu; konsol lama
        # tidak mengirimnya, dan `bersihkan_setelan` mengisinya 0 (garis mati).
        bersih = bersihkan_setelan(
            {
                k: data[k]
                for k in ("conf_threshold", "minimum_size", "garis_capture", "sumbu_garis", "mode_dev")
                if k in data
            }
        )
        state.conf_threshold_override = bersih["conf_threshold"]
        state.minimum_size_override = bersih["minimum_size"]
        state.garis_capture_override = bersih["garis_capture"]
        state.sumbu_garis_override = bersih["sumbu_garis"]
        state.mode_dev_override = bersih["mode_dev"]
        logger.info(
            "Setelan grading diambil dari konsol: conf=%s minimum_size=%s garis=%s sumbu=%s",
            bersih["conf_threshold"], bersih["minimum_size"],
            bersih["garis_capture"], bersih["sumbu_garis"],
        )
    except Exception as exc:
        logger.info("Setelan grading tidak bisa diambil (%s) — pakai .env", exc)


async def _tarik_penugasan(settings, state) -> None:
    """Tanya konsol truk mana yang sedang dibongkar di line ini, sekali saat start.

    Pasangan `_tarik_setelan_grading`, untuk hal yang sama-sama hidup di
    `RuntimeState`: penugasan truk hilang bersama proses, dan konsol cuma
    mendorongnya saat operator menekan Tugaskan/Lepas. Tanpa tarikan ini,
    `autograde restart` di tengah shift membuat line lupa truknya sementara layar
    konsol tetap menampilkan platnya — janjang berikutnya tersimpan dengan
    `assignment_id` kosong dan tidak pernah masuk rekap yang dibayar. Terbukti di
    PC Lampung 2026-09-23, tanpa satu pun error.

    Gagal = diam dan jalan tanpa truk, seperti sebelum ada fitur ini. Konsol yang
    belum hidup saat line start itu kejadian normal (urutan start container tidak
    dijamin), dan operator tetap bisa menugaskan dari layar.
    """
    url = f"{settings.backend_url}{settings.backend_api_ver}/internal/penugasan"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                url,
                params={"machine_id": settings.machine_id},
                headers={"x-webhook-secret": settings.webhook_secret},
            )
        if res.status_code != 200:
            logger.info("Penugasan tidak diambil (HTTP %s) — line start tanpa truk", res.status_code)
            return
        data = res.json()
        assignment_id = str(data.get("assignment_id") or "").strip()
        truck_id = str(data.get("truck_id") or "").strip()
        # Keduanya wajib. Memasang satu tanpa yang lain memberi line truk hantu:
        # `truck_folder` menamai folder capture dengan potongan kosong, dan
        # janjang satu truk menumpuk di folder yang bukan miliknya.
        if not (assignment_id and truck_id):
            return
        state.current_assignment_id = assignment_id
        state.current_truck_id = truck_id
        state.current_ffb_source = data.get("ffb_source")
        state.current_plate = data.get("plate")
        state.current_assigned_at = data.get("assigned_at")
        logger.info(
            "Penugasan dipulihkan dari konsol: truck=%s assignment=%s plate=%s ffb_source=%s",
            truck_id, assignment_id, data.get("plate"), data.get("ffb_source"),
        )
    except Exception as exc:
        logger.info("Penugasan tidak bisa diambil (%s) — line start tanpa truk", exc)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    _lic_manager: LicenseManager | None = None
    if settings.lic_enabled:
        _lic_repo = LicenseLocalRepo(settings.artifacts_dir / "license.db")
        _lic_manager = LicenseManager(settings.lic_pubkey_pem, _lic_repo, settings.lic_token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if _lic_manager:
            await _lic_manager.init()
            asyncio.create_task(_lic_manager.run_clock_ratchet())

        # Only `results/`. Nothing writes to the others: REJ images are found
        # through `ripeness_status` metadata, and logs go to stdout for Docker.
        settings.results_dir.mkdir(parents=True, exist_ok=True)

        # Fail-fast kalau secret masih default di production (dev tetap boleh,
        # cuma warning). Lihat Settings.validate_for_runtime().
        settings.validate_for_runtime()

        # Sumber kamera — `CAMERA_TYPE` + `MEDIA_FILE`, disusun layar Support
        # dan diteruskan Compose lewat `media.env`. Pemetaannya hidup di
        # `domain/sumber_kamera_resolver` supaya bisa diuji tanpa menyalakan
        # aplikasi; di sini tinggal membangun apa yang direncanakan.
        # `settings.media_dir` diteruskan, BUKAN dibiarkan memakai konstanta
        # `/media` bawaan resolver: yang terakhir itu path di dalam container,
        # dan jalur native (`make line`) menunjuk `media/` di repo. Tanpa ini
        # line native mati saat start dengan "File tidak ditemukan: /media/..."
        # walau berkasnya ada dan layar sudah memilihnya.
        rencana = rencana_kamera(
            settings.sumber_kamera(),
            settings.media_file,
            settings.camera_video_loop,
            media_dir=settings.media_dir,
        )
        # `.env` lama menulis PATH penuh di CAMERA_VIDEO_PATH/CAMERA_PHOTO_PATH,
        # bukan nama berkas. Selama berkas itu masih dipakai (PC yang belum
        # pindah ke media.env), path aslinya menang atas hasil join ke /media.
        if not settings.media_file:
            if settings.camera_video_path:
                rencana = replace(rencana, video_path=settings.camera_video_path)
            if settings.camera_photo_path:
                rencana = replace(rencana, photo_path=settings.camera_photo_path)
        camera_type = rencana.camera_type
        if camera_type == "opencv":
            # `video_path` kosong = webcam lewat device index.
            opencv_source: int | str = rencana.video_path or settings.camera_device_index
            camera: CameraSource = OpenCVCamera(
                source=opencv_source,
                width=settings.camera_width,
                height=settings.camera_height,
                fps=settings.camera_fps,
                is_video_file=bool(rencana.video_path),
                loop=rencana.loop,
            )
        elif camera_type == "photo":
            camera = PhotoCamera(path=rencana.photo_path)
        else:
            camera = HikrobotCamera()

        try:
            camera.connect(index=settings.camera_device_index, serial=settings.camera_serial, feature_file=settings.camera_feature_file)
        except RuntimeError as exc:
            if camera_type == "hikrobot":
                logger.warning("Camera not found at startup: %s — FrameCaptureWorker will keep retrying", exc)
            else:
                raise
        set_camera(camera)

        state = get_runtime_state()
        state.main_loop = asyncio.get_running_loop()

        # Sesudah `state` ada, sebelum worker deteksi menyala: setelan yang
        # dipegang konsol harus sudah terpasang saat janjang pertama lewat.
        await _tarik_setelan_grading(settings, state)
        await _tarik_penugasan(settings, state)

        # Gerbang lisensi untuk thread grading. Fail CLOSED: token yang tidak
        # bisa diverifikasi meninggalkan license_exp = 0, dan 0 berarti kamera
        # diam. Middleware HTTP saja tidak cukup — grading jalan di thread
        # background yang tidak pernah lewat login.
        if _lic_manager:
            effective = await _lic_manager.get_effective_license()
            state.license_exp = effective.grace_ends_at
            if effective.is_expired:
                logger.error(
                    "Lisensi tidak berlaku (%s) — deteksi TIDAK dijalankan", effective.reason
                )
            elif effective.warning:
                logger.warning("%s: %s", effective.warning.code, effective.warning.message)

        pipeline = get_realtime_inspection_pipeline()
        storage_instance = get_capture_repository().storage
        webhook = get_webhook_client()

        broadcast_worker = EventBroadcastWorker(state=state)
        asyncio.create_task(broadcast_worker.run_loop())

        def _start_worker(name: str, target_fn) -> threading.Thread:
            t = threading.Thread(target=target_fn, daemon=True, name=name)
            t.start()
            return t

        capture_worker = FrameCaptureWorker(camera=camera, state=state, target_fps=settings.camera_fps, device_index=settings.camera_device_index, serial=settings.camera_serial, feature_file=settings.camera_feature_file)
        display_worker = DisplayWorker(
            state=state,
            pipeline=pipeline,
            settings=settings,
            target_fps=settings.stream_fps or 12,
        )
        # Penulis bukti, thread sendiri. Encode WebP frame sensor penuh memakan
        # ~285 ms per gambar (diukur di PC Lampung 2026-09-17), dan selama itu
        # dulu deteksi BERHENTI — frame dibuang diam-diam, ByteTrack kehilangan
        # jejak, layar membeku. Dipisah supaya biaya itu dipikul core lain.
        capture_saver = CaptureSaveWorker(
            settings=settings,
            storage=storage_instance,
            outbox_store=get_outbox_store(),
        )
        processing_worker = FrameProcessingWorker(
            pipeline=pipeline,
            state=state,
            storage=storage_instance,
            webhook=webhook,
            settings=settings,
            outbox_store=get_outbox_store(),
            capture_saver=capture_saver,
        )

        state.worker_threads = [
            ("capture", _start_worker("capture", capture_worker.run_loop), capture_worker),
            ("display", _start_worker("display", display_worker.run_loop), display_worker),
            ("processing", _start_worker("processing", processing_worker.run_loop), processing_worker),
            # Didaftarkan seperti worker lain supaya ikut diawasi watchdog 10
            # detik: penulis yang mati tanpa pengganti berarti grading jalan,
            # PLC menyortir, layar menghitung — dan nol bukti tersimpan.
            ("capture_save", _start_worker("capture_save", capture_saver.run_loop), capture_saver),
        ]

        # OutboxRetryWorker — kirim event ke API di BACKEND_URL, poll 1 detik.
        # Ini jalur realtime untuk operator (Grading History + gambar). Batch
        # upload R2 ke cloud (UPLOAD_API_URL) jalan terpisah dan tidak diganggu:
        # event_id-nya sama, jadi kalaupun keduanya menunjuk API yang sama, yang
        # kedua dibalas already_processed.
        #
        # PENTING: BACKEND_URL harus API LOKAL (http://<ip-pc>:2500), bukan
        # api.smagri.id. Menunjuk cloud dari sini yang membanjiri produksi
        # dengan ~1098 event tes pada 2026-08-09.
        outbox_worker = OutboxRetryWorker(
            outbox=get_outbox_store(),
            settings=settings,
            state=state,
        )
        outbox_thread = _start_worker("outbox_retry", outbox_worker.run_loop)
        state.worker_threads.append(("outbox_retry", outbox_thread, outbox_worker))

        # PLC — sinyal grading ke PLC lewat coupler ODOT (Modbus-TCP).
        # Mengembalikan None kalau PLC_ENABLED=false, jadi di cloud dan di PC
        # dev tidak ada thread tambahan sama sekali. Didaftarkan ke
        # worker_threads supaya ikut di-restart watchdog 10 detik kalau mati.
        # `camera` di lambda ini variabel lokal `lifespan`, di-assign sekali di
        # atas (baris ~84-95) dan TIDAK PERNAH di-rebind sesudahnya. Jadi lambda
        # ini selamanya menunjuk objek kamera yang sama — dan justru itu yang
        # bikin benar: reconnect tidak membuat objek baru, `FrameCaptureWorker`
        # cuma mengubah `.connected` di tempat pada objek yang sama
        # (`integrations/camera/base.py:9`). health_check karena itu selalu
        # membaca status terkini, bukan snapshot saat startup.
        # Dibungkus try/except karena PLC itu fitur OPSIONAL yang default-nya mati:
        # env rusak (mis. PLC_PULSE_MS=0 yang lolos int() lalu ditolak
        # PulseScheduler.__post_init__) tidak boleh menjatuhkan lifespan dan ikut
        # mematikan grading. Gagal di sini = jalan terus tanpa PLC.
        try:
            plc_worker = start_plc_worker(
                settings,
                health_check=lambda: camera.connected,
                license_ok=lambda: not grading_blocked(settings.lic_enabled, state.license_exp),
            )
        except Exception:
            logger.exception("Start PLC gagal — grading tetap jalan, PLC dinonaktifkan")
            plc_worker = None
        if plc_worker is not None:
            state.worker_threads.append(("plc", _start_worker("plc", plc_worker.run_loop), plc_worker))

        async def _watchdog() -> None:
            while True:
                await asyncio.sleep(10)
                for i, (name, thread, worker) in enumerate(state.worker_threads):
                    if not thread.is_alive():
                        logger.error("Worker thread '%s' died — restarting", name)
                        new_thread = _start_worker(name, worker.run_loop)
                        state.worker_threads[i] = (name, new_thread, worker)

        asyncio.create_task(_watchdog())

        # Batch upload cloud: gambar → R2, teks → API cloud, tiap jam.
        upload_manifest = UploadManifest(db_path=settings.state_dir / "upload_manifest.db")
        r2_uploader = R2Uploader(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
        batch_worker = BatchUploadWorker(
            settings=settings, manifest=upload_manifest, uploader=r2_uploader
        )
        upload_scheduler = UploadScheduler(settings=settings, run_batch=batch_worker.run_batch_once)
        upload_scheduler.start()

        yield

        from .core.dependencies import get_camera

        # PLC didahulukan: saat SIGTERM tiba, coil OK/NG punya peluang kira-kira
        # 1 dari 2 sedang ON di tengah pulse (200ms ON dalam siklus 400 ms, 2
        # tick). Kontrak coil itu "satu pulse = satu buah" — dibiarkan ON sampai
        # watchdog ODOT menyerah (masih 30 detik) berarti PLC menyortir banyak
        # buah dengan keputusan basi. Digarap best-effort: gagal di sini tidak
        # boleh menghalangi sisa shutdown.
        try:
            plc_thread = next((t for name, t, _ in state.worker_threads if name == "plc"), None)
            shutdown_plc_worker(plc_thread)
        except Exception:
            logger.exception("Shutdown PLC gagal — shutdown lain tetap dilanjutkan")

        # Janjang yang sudah digrading (dan sudah dapat pulse PLC) tapi belum
        # sempat ditulis akan hilang bersama proses ini. Beri penulis kesempatan
        # menghabiskan antreannya dulu — beberapa ratus milidetik per janjang,
        # dan antreannya cuma tiga dalam. Best-effort: gagal di sini tidak boleh
        # menahan sisa shutdown.
        try:
            if not capture_saver.tunggu_kosong(timeout=5.0):
                logger.warning(
                    "Shutdown: %d janjang masih di antrean simpan dan tidak sempat ditulis",
                    capture_saver.antrean,
                )
            capture_saver.stop(timeout=2.0)
        except Exception:
            logger.exception("Menguras antrean simpan gagal — shutdown dilanjutkan")

        try:
            camera = get_camera()
            camera.disconnect()
        except RuntimeError:
            pass
        upload_scheduler.stop()

    app = FastAPI(title="Ripe Recognition API", lifespan=lifespan)

    # License Guard — added first so CORS (added second) becomes outermost.
    # Response path: Router → License → CORS, so 403 from License gets CORS headers.
    if _lic_manager:
        app.add_middleware(LicenseGuardMiddleware, manager=_lic_manager)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files — path /captures/... → artifacts/ directory
    # image_url format: "captures/results/{date}/{timestamp}.webp"
    artifacts_dir = settings.artifacts_dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/captures", StaticFiles(directory=str(artifacts_dir)), name="captures")

    app.include_router(health_router)
    app.include_router(inspection_router)
    app.include_router(streaming_router)
    app.include_router(internal_router)

    @app.websocket("/ws/results")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        state = get_runtime_state()
        state.websocket_clients.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            state.websocket_clients.remove(websocket)

    return app


app = create_app()
