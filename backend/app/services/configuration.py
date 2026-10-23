"""Validate API training configuration through the existing ML contract."""

from ml.models.config import Phase3Config


def phase3_config(value=None):
    if value is None:
        return Phase3Config()
    if not isinstance(value, dict):
        raise ValueError("Training configuration must be an object")
    try:
        return Phase3Config(**value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid chronological training configuration") from exc
