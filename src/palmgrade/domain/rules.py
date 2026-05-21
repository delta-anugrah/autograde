def derive_ripeness_status(label: str, area: int = 0, minimum_size: int = 0) -> str:
    if area > 0 and minimum_size > 0 and area < minimum_size:
        return "rej"
    return "rej" if "rej" in label.lower() else "acc"
