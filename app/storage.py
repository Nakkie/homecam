import json
import os
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CAMERAS_FILE = DATA_DIR / "cameras.json"
CAMERAS_TMP = DATA_DIR / "cameras.json.tmp"


class CamerasCorruptError(Exception):
    """cameras.json exists but cannot be parsed."""


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_cameras() -> list[dict[str, Any]]:
    _ensure_data_dir()
    if not CAMERAS_FILE.exists():
        return []
    try:
        with CAMERAS_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise CamerasCorruptError(str(exc)) from exc
    if not isinstance(data, list):
        raise CamerasCorruptError("cameras.json must contain a JSON array")
    return data


def save_cameras(cameras: list[dict[str, Any]]) -> None:
    _ensure_data_dir()
    with CAMERAS_TMP.open("w", encoding="utf-8") as f:
        json.dump(cameras, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(CAMERAS_TMP, CAMERAS_FILE)
