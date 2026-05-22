from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..core.config import Settings
from ..integrations.storage.local_file_storage import LocalFileStorage


@dataclass
class ResultRepository:
    settings: Settings
    storage: LocalFileStorage

    def list_today_results(self) -> list[dict[str, Any]]:
        today = datetime.now().strftime("%Y-%m-%d")
        result_dir = self.settings.results_dir / today
        grouped: dict[str, dict[str, Any]] = {}

        for path in self.storage.list_json_files(result_dir):
            meta = self.storage.read_json(path)

            # Derive base key dari filename (strip _ripeness / _tp suffix)
            base_name = path.stem.replace("_ripeness", "").replace("_tp", "")

            if base_name not in grouped:
                grouped[base_name] = {
                    "id": base_name,
                    "timestamp": meta.get("timestamp", ""),
                    "image_url": None,
                    "capture_type": meta.get("capture_type", "auto"),
                    "truck_id": meta.get("truck_id"),
                    "ripeness_status": None,
                    "ripeness_confidence": 0,
                    "tp_status": None,
                    "tp_confidence": 0,
                    "bounding_box": meta.get("bounding_box"),
                }

            filename = path.name
            if "_ripeness" in filename:
                grouped[base_name]["ripeness_status"] = meta.get("ripeness_status")
                grouped[base_name]["ripeness_confidence"] = meta.get("ripeness_confidence", 0)
                grouped[base_name]["image_url"] = meta.get("image_path") or meta.get("image_url")
            elif "_tp" in filename:
                grouped[base_name]["tp_status"] = meta.get("tp_status")
                grouped[base_name]["tp_confidence"] = meta.get("tp_confidence", 0)
            else:
                # manual capture atau format lama
                grouped[base_name]["ripeness_status"] = meta.get("ripeness_status") or meta.get("status")
                grouped[base_name]["ripeness_confidence"] = meta.get("ripeness_confidence") or meta.get("confidence", 0)
                grouped[base_name]["image_url"] = meta.get("image_url") or meta.get("image_path")

        events = [ev for ev in grouped.values() if ev["ripeness_status"]]

        for ev in events:
            conf = round(ev.get("ripeness_confidence") or 0, 2)
            ev["title"] = f"{ev['ripeness_status']} Detected"
            ev["description"] = f"{ev['ripeness_status']} (conf={conf})"

        return events
