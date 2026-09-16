import logging
import os


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    if os.getenv("DEBUG_MODEL_OUTPUT", "").lower() in ("1", "true"):
        # Nama logger diturunkan dari paket ini sendiri, bukan ditulis tangan.
        # Dulu barisnya `"src.palmgrade.workers..."`, padahal paketnya dimuat
        # sebagai `palmgrade...` (`src` itu root path, bukan bagian nama modul),
        # jadi level DEBUG mendarat di logger yang tidak pernah dipakai siapa pun
        # dan `DEBUG_MODEL_OUTPUT=true` tidak menghasilkan satu baris pun.
        # Diam-diam, karena menyetel level logger yang tidak ada bukan error.
        paket = __name__.rsplit(".", 2)[0]  # palmgrade.core.logging -> palmgrade
        logging.getLogger(f"{paket}.workers.frame_processing_worker").setLevel(logging.DEBUG)

