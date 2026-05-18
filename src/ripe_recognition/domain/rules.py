from .value_objects import InspectionStatus


def derive_status(prediction: str) -> InspectionStatus:
    return "FAIL" if "rej" in prediction.lower() else "PASS"

