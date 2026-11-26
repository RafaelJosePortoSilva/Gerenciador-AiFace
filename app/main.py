"""Webservice para consultar e configurar relógios de ponto AiFace na rede."""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .codec import MASK, SECRET_FIELDS, decode, mask
from .device_client import (
    COMPANY_FIELDS,
    FIRMWARE_CHUNK_SIZE,
    READONLY_COMMANDS,
    SETTING_CATEGORIES,
    SETTING_FIELDS,
    DeviceClient,
    DeviceError,
)

app = FastAPI(
    title="Gestor de Relógios AiFace",
    description="Inventário, leitura e aplicação padronizada de configurações em relógios de ponto.",
    version="1.0.0",
)

API_TOKEN = os.getenv("WPS_API_TOKEN", "").strip()

_FIRMWARE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="firmware")
_firmware_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()

_JOB_PUBLIC_KEYS = (
    "job_id", "device_id", "host", "filename", "firmware_id", "size", "md5",
    "status", "uploaded", "total", "percent", "message", "result",
)


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job[key] for key in _JOB_PUBLIC_KEYS if key in job}


def _set_job(job_id: str, **changes: Any) -> None:
    with _jobs_lock:
        job = _firmware_jobs.get(job_id)
        if job is not None:
            job.update(changes)


@app.middleware("http")
async def token_guard(request, call_next):
    if API_TOKEN and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        if request.headers.get("x-api-token") != API_TOKEN:
            return JSONResponse(status_code=401, content={"detail": "Token de API inválido"})
    return await call_next(request)


class DeviceInput(BaseModel):
    id: str | None = None
    host: str
    port: int = 80
    scheme: str = "http"
    label: str = ""
    location: str = ""
    username: str = "admin"
    password: str = "123"
    timeout: float = 3.0
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    notes: str = ""
    archived: bool = False


class FieldsInput(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
    operator: str = ""


class ProfileInput(BaseModel):
    name: str
    description: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    company: dict[str, Any] = Field(default_factory=dict)


class CommandInput(BaseModel):
    cmd: str
    extra: dict[str, Any] = Field(default_factory=dict)


class BulkInput(BaseModel):
    profile: str
    device_ids: list[str] | None = None
    confirm: bool = False
    include_company: bool = True
    operator: str = ""


class SaveProfileInput(BaseModel):
    name: str
    description: str = ""
    include_company: bool = True
    confirm: bool = False
    operator: str = ""
    fields: dict[str, Any] | None = None
    company: dict[str, Any] | None = None


def client_for(device: dict[str, Any]) -> DeviceClient:
    return DeviceClient(
        str(device["host"]),
        port=int(device.get("port", 80)),
        scheme=str(device.get("scheme", "http")),
        password=str(device.get("password", "123")),
        username=str(device.get("username", "admin")),
        timeout=float(device.get("timeout", 3.0)),
    )


def describe_firmware(filename: str, content: bytes) -> dict[str, Any]:
    """Valida o nome e devolve os metadados usados no painel e no histórico."""
    name = DeviceClient.validate_firmware(filename, content)
    return {
        "filename": name,
        "size": len(content),
        "md5": hashlib.md5(content).hexdigest(),
        "chunks": (len(content) + FIRMWARE_CHUNK_SIZE - 1) // FIRMWARE_CHUNK_SIZE + 1,
    }


def require_device(device_id: str) -> dict[str, Any]:
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Equipamento '{device_id}' não cadastrado")
    return device


def handle_error(exc: DeviceError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "gestor-relogios-aiface", "devices": len(store.list_devices())}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {
        "setting_fields": list(SETTING_FIELDS),
        "setting_categories": list(SETTING_CATEGORIES),
        "firmware_chunk_size": FIRMWARE_CHUNK_SIZE,
        "company_fields": list(COMPANY_FIELDS),
        "secret_fields": sorted(SECRET_FIELDS),
        "readonly_commands": sorted(READONLY_COMMANDS),
        "auth_required": bool(API_TOKEN),
    }


@app.get("/api/devices")
def devices() -> list[dict[str, Any]]:
    return mask(store.list_devices())


@app.post("/api/devices")
def create_device(payload: DeviceInput) -> dict[str, Any]:
    device = payload.model_dump(exclude_none=True)
    if not device.get("id"):
        device["id"] = f"relogio-{device['host'].replace('.', '-')}"
    saved = store.save_device(device)
    return mask(saved)


@app.post("/api/devices/refresh")
def refresh_devices() -> list[dict[str, Any]]:
    def probe(device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        try:
            status = client_for(device).probe()
            status["checked_at"] = status.get("checked_at")
        except DeviceError as exc:
            status = {
                "host": device.get("host"),
                "reachable": False,
                "signature": False,
                "error": str(exc),
            }
        return str(device["id"]), status

    targets = [
        d for d in store.list_devices()
        if d.get("enabled", True) and not d.get("archived", False)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(probe, d) for d in targets]
        for future in as_completed(futures):
            device_id, status = future.result()
            status["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            store.cache_status(device_id, status)
    return mask(store.list_devices())


@app.get("/api/devices/{device_id}")
def device_detail(device_id: str) -> dict[str, Any]:
    device = require_device(device_id)
    try:
        snapshot = client_for(device).read_snapshot()
    except DeviceError as exc:
        raise handle_error(exc) from exc
    return {"device": mask(device), **mask(snapshot)}


@app.get("/api/devices/{device_id}/config")
def device_config(device_id: str) -> dict[str, Any]:
    device = require_device(device_id)
    try:
        return mask(decode(client_for(device).current_settings()))
    except DeviceError as exc:
        raise handle_error(exc) from exc


@app.post("/api/devices/{device_id}/preview")
def preview_config(device_id: str, payload: FieldsInput) -> dict[str, Any]:
    device = require_device(device_id)
    if not payload.fields:
        raise HTTPException(status_code=400, detail="Informe ao menos um campo em 'fields'")
    try:
        return client_for(device).preview(payload.fields)
    except (DeviceError, ValueError) as exc:
        raise handle_error(DeviceError(str(exc))) from exc


@app.post("/api/devices/{device_id}/apply")
def apply_config(device_id: str, payload: FieldsInput) -> dict[str, Any]:
    device = require_device(device_id)
    if not payload.fields:
        raise HTTPException(status_code=400, detail="Informe ao menos um campo em 'fields'")
    client = client_for(device)
    try:
        if not payload.confirm:
            return {
                "applied": False,
                "message": "Prévia: envie confirm=true para aplicar as alterações.",
                **client.preview(payload.fields),
            }
        result = client.apply_settings(payload.fields)
    except (DeviceError, ValueError) as exc:
        raise handle_error(DeviceError(str(exc))) from exc
    store.append_history({
        "action": "apply_fields",
        "device_id": device_id,
        "host": device.get("host"),
        "operator": payload.operator,
        "changes": result.get("changes", []),
        "result": result.get("result"),
    })
    return {"applied": True, **result}


@app.post("/api/devices/{device_id}/company")
def apply_company(device_id: str, payload: FieldsInput) -> dict[str, Any]:
    device = require_device(device_id)
    client = client_for(device)
    try:
        current = client.api("getcompanyfile")
        current = {k: v for k, v in current.items() if k in COMPANY_FIELDS}
        changes = client.diff(current, payload.fields)
        if not payload.confirm:
            return {"applied": False, "changes": changes, "dry_run": True}
        result = client.apply_company(payload.fields)
    except DeviceError as exc:
        raise handle_error(exc) from exc
    store.append_history({
        "action": "apply_company",
        "device_id": device_id,
        "host": device.get("host"),
        "operator": payload.operator,
        "changes": changes,
        "result": result.get("result"),
    })
    return {"applied": True, **result}


@app.post("/api/devices/{device_id}/save-profile")
def save_profile_from_device(device_id: str, payload: SaveProfileInput) -> dict[str, Any]:
    """Salva a configuração lida do equipamento como um modelo reutilizável."""
    device = require_device(device_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome do modelo é obrigatório")
    try:
        snapshot = client_for(device).read_snapshot()
    except DeviceError as exc:
        raise handle_error(exc) from exc

    current = snapshot.get("config") or {}
    if not current:
        raise HTTPException(
            status_code=502, detail="Não foi possível ler a configuração do equipamento"
        )

    fields = {
        key: value
        for key, value in current.items()
        if key in SETTING_FIELDS and key not in SECRET_FIELDS
    }
    if payload.fields is not None:
        fields.update({
            key: value
            for key, value in payload.fields.items()
            if key in SETTING_FIELDS and key not in SECRET_FIELDS
        })

    company = {
        key: value
        for key, value in (snapshot.get("company") or {}).items()
        if key in COMPANY_FIELDS
    }
    if payload.company is not None:
        company.update({
            key: value
            for key, value in payload.company.items()
            if key in COMPANY_FIELDS
        })
    if not payload.include_company:
        company = {}

    document: dict[str, Any] = {
        "name": name,
        "description": payload.description,
        "fields": fields,
        "company": company,
        "source_device_id": device_id,
        "source_host": device.get("host"),
        "source_serial": (snapshot.get("probe") or {}).get("sn"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    counts = {"fields_count": len(fields), "company_count": len(company)}
    if not payload.confirm:
        return {
            "applied": False,
            "message": "Prévia: envie confirm=true para salvar o modelo.",
            **document,
            **counts,
        }

    saved = store.save_profile(document)
    store.append_history({
        "action": "save_profile_from_device",
        "profile": name,
        "device_id": device_id,
        "host": device.get("host"),
        "operator": payload.operator,
        **counts,
        "result": True,
    })
    return {"applied": True, "profile": saved, **counts}


@app.post("/api/devices/{device_id}/command")
def read_command(device_id: str, payload: CommandInput) -> dict[str, Any]:
    device = require_device(device_id)
    try:
        return client_for(device).readonly_command(payload.cmd, **payload.extra)
    except DeviceError as exc:
        raise handle_error(exc) from exc


@app.post("/api/devices/{device_id}/firmware")
async def upload_firmware(
    device_id: str,
    file: UploadFile | None = File(None),
    firmware_id: str | None = Form(None),
    confirm: bool = Form(False),
    operator: str = Form(""),
) -> dict[str, Any]:
    """Envia um arquivo local ou um arquivo salvo na biblioteca ao equipamento."""
    device = require_device(device_id)
    if (file is None) == (firmware_id is None):
        raise HTTPException(
            status_code=400, detail="Informe 'file' ou 'firmware_id' (apenas um)"
        )

    source = "library" if file is None else "upload"
    if file is not None:
        content = await file.read()
        filename = file.filename or ""
    else:
        record = store.get_firmware(firmware_id or "")
        if record is None:
            raise HTTPException(status_code=404, detail="Arquivo de firmware salvo não encontrado")
        try:
            content = store.read_firmware_file(record["id"])
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=f"Arquivo salvo indisponível: {exc}") from exc
        filename = str(record.get("filename", ""))

    try:
        info = describe_firmware(filename, content)
    except DeviceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = info["filename"]
    info["source"] = source
    if source == "library":
        info["firmware_id"] = firmware_id
    if not confirm:
        return {
            "applied": False,
            "message": "Prévia: envie confirm=true para enviar o firmware ao equipamento.",
            **info,
        }

    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "job_id": job_id,
        "device_id": device_id,
        "host": device.get("host"),
        "filename": name,
        "firmware_id": firmware_id if source == "library" else None,
        "size": len(content),
        "md5": info["md5"],
        "status": "queued",
        "uploaded": 0,
        "total": len(content),
        "percent": 0.0,
        "message": "Na fila",
        "result": None,
    }
    with _jobs_lock:
        _firmware_jobs[job_id] = job

    def work() -> None:
        def report(sent: int, total: int) -> None:
            _set_job(
                job_id,
                uploaded=sent,
                total=total,
                percent=round(sent * 100 / total, 2) if total else 100.0,
            )

        _set_job(job_id, status="running", message="Enviando firmware...")
        try:
            result = client_for(device).upload_firmware(name, content, progress=report)
            _set_job(
                job_id,
                status="done",
                uploaded=len(content),
                total=len(content),
                percent=100.0,
                message="Firmware enviado com sucesso",
                result=result,
            )
            store.append_history({
                "action": "firmware_upload",
                "device_id": device_id,
                "host": device.get("host"),
                "operator": operator,
                "filename": name,
                "firmware_id": firmware_id if source == "library" else None,
                "size": len(content),
                "md5": info["md5"],
                "result": True,
            })
        except DeviceError as exc:
            _set_job(job_id, status="error", message=str(exc), result=None)
            store.append_history({
                "action": "firmware_upload",
                "device_id": device_id,
                "host": device.get("host"),
                "operator": operator,
                "filename": name,
                "firmware_id": firmware_id if source == "library" else None,
                "size": len(content),
                "md5": info["md5"],
                "result": False,
                "error": str(exc),
            })

    _FIRMWARE_POOL.submit(work)
    return {"applied": True, **_job_public(job)}


@app.get("/api/devices/{device_id}/firmware/jobs/{job_id}")
def firmware_job_status(device_id: str, job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _firmware_jobs.get(job_id)
    if job is None or job.get("device_id") != device_id:
        raise HTTPException(status_code=404, detail="Job de firmware não encontrado")
    return _job_public(job)


@app.get("/api/firmware")
def firmware_library() -> list[dict[str, Any]]:
    return store.list_firmware()


@app.post("/api/firmware")
async def save_firmware_file(
    file: UploadFile = File(...),
    description: str = Form(""),
    confirm: bool = Form(False),
) -> dict[str, Any]:
    """Guarda um arquivo de atualização para reutilizar em qualquer equipamento."""
    content = await file.read()
    try:
        info = describe_firmware(file.filename or "", content)
    except DeviceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    info["description"] = description
    if not confirm:
        return {
            "saved": False,
            "message": "Prévia: envie confirm=true para salvar o arquivo na biblioteca.",
            **info,
        }

    firmware_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "id": firmware_id,
        **info,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        store.write_firmware_file(firmware_id, content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gravar arquivo: {exc}") from exc
    store.save_firmware(record)
    store.append_history({
        "action": "firmware_saved",
        "filename": record["filename"],
        "size": record["size"],
        "md5": record["md5"],
        "result": True,
    })
    return {"saved": True, **record}


@app.delete("/api/firmware/{firmware_id}")
def delete_firmware_file(firmware_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {
            "deleted": False,
            "message": "Prévia: envie confirm=true para excluir o arquivo salvo.",
        }
    try:
        record = store.get_firmware(firmware_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Arquivo de firmware salvo não encontrado")
        store.delete_firmware(firmware_id)
        store.delete_firmware_file(firmware_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.append_history({
        "action": "firmware_deleted",
        "filename": record.get("filename"),
        "md5": record.get("md5"),
        "result": True,
    })
    return {"deleted": True, "id": firmware_id, "filename": record.get("filename")}


@app.put("/api/devices/{device_id}")
def update_device(device_id: str, payload: DeviceInput) -> dict[str, Any]:
    existing = require_device(device_id)
    data = payload.model_dump(exclude_none=True)
    current = {key: value for key, value in existing.items() if key != "status"}
    if data.get("password") == MASK:
        data["password"] = current.get("password")
    current.update(data)
    current["id"] = device_id
    return mask(store.save_device(current))


@app.delete("/api/devices/{device_id}")
def remove_device(device_id: str) -> dict[str, Any]:
    require_device(device_id)
    return {"deleted": store.delete_device(device_id)}


@app.get("/api/profiles")
def profiles() -> list[dict[str, Any]]:
    return store.list_profiles()


@app.post("/api/profiles")
def upsert_profile(payload: ProfileInput) -> dict[str, Any]:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nome do modelo é obrigatório")
    return store.save_profile(payload.model_dump())


@app.delete("/api/profiles/{name}")
def remove_profile(name: str) -> dict[str, Any]:
    return {"deleted": store.delete_profile(name)}


@app.get("/api/devices/{device_id}/diff")
def diff_profile(device_id: str, profile: str) -> dict[str, Any]:
    device = require_device(device_id)
    model = store.get_profile(profile)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Modelo '{profile}' não encontrado")
    try:
        current = client_for(device).current_settings()
        return {
            "device_id": device_id,
            "profile": profile,
            "changes": client_for(device).diff(decode(current), model.get("fields", {})),
        }
    except DeviceError as exc:
        raise handle_error(exc) from exc


@app.post("/api/bulk/apply")
def bulk_apply(payload: BulkInput) -> dict[str, Any]:
    model = store.get_profile(payload.profile)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Modelo '{payload.profile}' não encontrado")
    devices = store.list_devices()
    if payload.device_ids:
        devices = [d for d in devices if d.get("id") in payload.device_ids]
    devices = [
        d for d in devices
        if d.get("enabled", True) and not d.get("archived", False)
    ]
    if not devices:
        raise HTTPException(status_code=400, detail="Nenhum equipamento selecionado")

    results = []
    for device in devices:
        client = client_for(device)
        entry: dict[str, Any] = {"device_id": device.get("id"), "host": device.get("host")}
        try:
            if not payload.confirm:
                preview = client.preview(model.get("fields", {}))
                entry.update({"applied": False, "changes": preview["changes"]})
            else:
                applied = client.apply_settings(model.get("fields", {}))
                changes = list(applied["changes"])
                if payload.include_company and model.get("company"):
                    company = client.apply_company(model["company"])
                    changes.extend(
                        {
                            "field": f"company.{c['field']}",
                            "before": c["before"],
                            "after": c["after"],
                        }
                        for c in company["changes"]
                    )
                entry.update({"applied": True, "result": applied.get("result"), "changes": changes})
                store.append_history({
                    "action": "apply_profile",
                    "profile": payload.profile,
                    "device_id": device.get("id"),
                    "host": device.get("host"),
                    "operator": payload.operator,
                    "changes": changes,
                    "result": applied.get("result"),
                })
        except DeviceError as exc:
            entry.update({"applied": False, "error": str(exc)})
        results.append(entry)
    return {"profile": payload.profile, "confirm": payload.confirm, "results": results}


@app.get("/api/history")
def history(limit: int = 100) -> list[dict[str, Any]]:
    return store.read_history(limit)


import os as _os  # noqa: E402

app.mount("/", StaticFiles(directory=_os.path.join(_os.path.dirname(__file__), "static"), html=True), name="ui")
