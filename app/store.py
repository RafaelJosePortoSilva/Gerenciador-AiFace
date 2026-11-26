"""Persistência simples em JSON para dispositivos, modelos e histórico."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.getenv("WPS_CONFIG_DIR", str(BASE_DIR / "config")))
DATA_DIR = Path(os.getenv("WPS_DATA_DIR", str(BASE_DIR / "data")))
DEVICES_FILE = CONFIG_DIR / "devices.json"
PROFILES_FILE = CONFIG_DIR / "profiles.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
FIRMWARE_FILE = DATA_DIR / "firmware.json"
FIRMWARE_DIR = DATA_DIR / "firmware"
_FIRMWARE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_lock = threading.RLock()
_status_cache: dict[str, dict[str, Any]] = {}


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        if not path.exists():
            return json.loads(json.dumps(fallback))
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(fallback))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)


def defaults() -> dict[str, Any]:
    return _read_json(DEVICES_FILE, {"defaults": {}, "devices": []}).get("defaults", {})


def list_devices() -> list[dict[str, Any]]:
    doc = _read_json(DEVICES_FILE, {"devices": []})
    base = doc.get("defaults", {})
    devices = []
    for item in doc.get("devices", []):
        merged = {**base, **item}
        merged["status"] = _status_cache.get(item.get("id"), {})
        devices.append(merged)
    return devices


def get_device(device_id: str) -> dict[str, Any] | None:
    for device in list_devices():
        if device.get("id") == device_id:
            return device
    return None


def save_device(device: dict[str, Any]) -> dict[str, Any]:
    doc = _read_json(DEVICES_FILE, {"defaults": {}, "devices": []})
    devices = doc.setdefault("devices", [])
    for index, existing in enumerate(devices):
        if existing.get("id") == device.get("id"):
            devices[index] = device
            break
    else:
        device.setdefault("id", f"relogio-{uuid.uuid4().hex[:8]}")
        devices.append(device)
    _write_json(DEVICES_FILE, doc)
    return device


def delete_device(device_id: str) -> bool:
    doc = _read_json(DEVICES_FILE, {"defaults": {}, "devices": []})
    devices = doc.get("devices", [])
    kept = [d for d in devices if d.get("id") != device_id]
    if len(kept) == len(devices):
        return False
    doc["devices"] = kept
    _write_json(DEVICES_FILE, doc)
    _status_cache.pop(device_id, None)
    return True


def cache_status(device_id: str, status: dict[str, Any]) -> None:
    with _lock:
        _status_cache[device_id] = status


def list_profiles() -> list[dict[str, Any]]:
    return _read_json(PROFILES_FILE, {"profiles": []}).get("profiles", [])


def get_profile(name: str) -> dict[str, Any] | None:
    return next((p for p in list_profiles() if p.get("name") == name), None)


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    doc = _read_json(PROFILES_FILE, {"profiles": []})
    profiles = doc.setdefault("profiles", [])
    for index, existing in enumerate(profiles):
        if existing.get("name") == profile.get("name"):
            profiles[index] = profile
            break
    else:
        profiles.append(profile)
    _write_json(PROFILES_FILE, doc)
    return profile


def delete_profile(name: str) -> bool:
    doc = _read_json(PROFILES_FILE, {"profiles": []})
    profiles = doc.get("profiles", [])
    kept = [p for p in profiles if p.get("name") != name]
    if len(kept) == len(profiles):
        return False
    doc["profiles"] = kept
    _write_json(PROFILES_FILE, doc)
    return True


def firmware_path(firmware_id: str) -> Path:
    """Resolve o arquivo de um ID gerado internamente, bloqueando path traversal."""
    if not _FIRMWARE_ID_RE.fullmatch(str(firmware_id)):
        raise ValueError("ID de firmware inválido")
    return FIRMWARE_DIR / f"{firmware_id}.bin"


def list_firmware() -> list[dict[str, Any]]:
    doc = _read_json(FIRMWARE_FILE, {"firmware": []})
    return [dict(item) for item in doc.get("firmware", []) if isinstance(item, dict)]


def get_firmware(firmware_id: str) -> dict[str, Any] | None:
    return next((f for f in list_firmware() if f.get("id") == firmware_id), None)


def save_firmware(record: dict[str, Any]) -> dict[str, Any]:
    doc = _read_json(FIRMWARE_FILE, {"firmware": []})
    items = doc.setdefault("firmware", [])
    for index, existing in enumerate(items):
        if existing.get("id") == record.get("id"):
            items[index] = dict(record)
            break
    else:
        items.append(dict(record))
    _write_json(FIRMWARE_FILE, doc)
    return dict(record)


def delete_firmware(firmware_id: str) -> bool:
    doc = _read_json(FIRMWARE_FILE, {"firmware": []})
    items = doc.get("firmware", [])
    kept = [f for f in items if f.get("id") != firmware_id]
    if len(kept) == len(items):
        return False
    doc["firmware"] = kept
    _write_json(FIRMWARE_FILE, doc)
    return True


def write_firmware_file(firmware_id: str, content: bytes) -> Path:
    path = firmware_path(firmware_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(content)
        temp.replace(path)
    return path


def read_firmware_file(firmware_id: str) -> bytes:
    return firmware_path(firmware_id).read_bytes()


def delete_firmware_file(firmware_id: str) -> bool:
    path = firmware_path(firmware_id)
    with _lock:
        if not path.exists():
            return False
        path.unlink()
        return True


def append_history(entry: dict[str, Any]) -> dict[str, Any]:
    record = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **entry,
    }
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with HISTORY_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_history(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        if not HISTORY_FILE.exists():
            return []
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    records = []
    for line in reversed(lines[-max(limit, 1) :]):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records[:limit]
