from pydantic import BaseModel, Field


class ApiMessage(BaseModel):
    message: str
    detail: str | None = None
    # Dipakai palmgrade-api lewat GET /system/versions. Sengaja menempel di
    # /health yang murah, bukan /health/detail yang menyentuh GPU + outbox.
    version: str = "unknown"


class HealthRinganSchema(ApiMessage):
    """`GET /health` line. `ai` = blok `services/penjaga_ai.ringkas()`; None
    sebelum lifespan memasang penjaganya."""

    ai: dict | None = None


class WorkerStatus(BaseModel):
    name: str
    alive: bool


class HealthDetailSchema(BaseModel):
    status: str
    environment: str
    version: str = "unknown"
    camera_type: str
    camera_connected: bool
    # None kalau PLC_ENABLED=false — itu keadaan normal di cloud dan PC dev,
    # bukan error. Isinya: inputs (motor fault 0-9 + E-stop 10), dropped_pulses,
    # dropped_submissions. Lihat plc.diagnostics().
    plc: dict | None = None
    gpu_available: bool
    gpu_device: str | None
    machine_id: str
    workers: list[WorkerStatus]
    # Model yang BENAR-BENAR dimuat line (bukan yang dipilih di `media.env`):
    # layar Model Deteksi menyandingkan keduanya. `None`/kosong = registry belum
    # dimuat, dan jalur health sengaja tidak memuatnya.
    model_file: str | None = None
    model_backend: str | None = None
    model_kelas: list[str] = Field(default_factory=list)
    # False = model yang jalan bukan tepat Ripe/Unripe/JK/TP: line ini tidak
    # menghitung janjang. None = tidak diketahui, BUKAN alarm.
    model_kelas_cocok: bool | None = None
    # Compute capability GPU line ("86"). Konsol mencocokkannya dengan nama
    # engine `<model>.sm<cc>.engine`. None = CPU / belum dimuat.
    gpu_sm: str | None = None
    # None = tidak diketahui: `outbox_lama_tertinggal` (sisa `artifacts/outbox.db`
    # yang gagal diserap, barisnya tidak terhitung di sini). Pembaca yang
    # menunggu angka (Danger Zone, `autograde reset-data`) menganggapnya belum
    # kosong.
    outbox_pending: int | None = 0
    outbox_failed: int = 0
    outbox_lama_tertinggal: bool = False
    # Antrean penulis bukti (`CaptureSaveWorker`). `capture_save_dropped` naik
    # berarti janjang yang SUDAH digrading dan sudah dapat pulse PLC tidak
    # tersimpan sama sekali — tidak ada gambar, tidak ada sidecar, jadi tidak ada
    # yang bisa ditemukan `BatchUploadWorker._scan()` belakangan. Diekspos di
    # sini karena satu baris log tidak akan pernah terbaca di PC yang cuma
    # dijenguk lewat AnyDesk, sementara angka ini sebaris dengan `outbox_*` yang
    # sudah rutin dilihat.
    capture_save_pending: int = 0
    capture_save_dropped: int = 0
    # TP yang muncul sesudah janjang terdekatnya difoto. Janjang difoto apa
    # adanya begitu menyentuh garis (keputusan operator 2026-09-18), jadi
    # tangkai yang telat memang tidak ikut. Diekspos supaya keputusan
    # menambah jendela tunggu nanti diambil dari angka, bukan dugaan.
    tp_telat: int = 0
    current_assignment_id: str | None = None
    last_successful_api_push: str | None = None
    # Batch 2.1: `PenjagaAi.ringkas_lengkap()` (keadaan AI + galat terakhir loop
    # deteksi). None = penjaga belum dipasang.
    ai: dict | None = None
    # Batch 3.6: laju TERUKUR (0 kalau gambar/grading terakhir lebih tua dari 5
    # detik) dan umur gambar terakhir. None = belum pernah ada gambar.
    fps_kamera: float = 0.0
    fps_deteksi: float = 0.0
    frame_umur_detik: float | None = None
    # Batch 3.7: `PemantauDisk.ringkas()` (tingkat, sisa GB, ambang, sejak).
    # None = pemantau belum dipasang (line versi lama tidak mengirimnya).
    disk: dict | None = None
    # Batch 3.6: lisensi line ini (`aktif`, `grading_diblokir`, `berlaku_sampai`).
    lisensi: dict | None = None
