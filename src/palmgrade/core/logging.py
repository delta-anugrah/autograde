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
        logging.getLogger("src.palmgrade.workers.frame_processing_worker").setLevel(logging.DEBUG)

