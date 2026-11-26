"""Teste de ponta a ponta com um equipamento AiFace simulado.

Uso: .venv\\Scripts\\python.exe tests\\smoke_test.py
Não altera nenhum equipamento real nem os arquivos de configuração do projeto.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

MOCK_PORT = 18080
APP_PORT = 8100
BASE = f"http://127.0.0.1:{APP_PORT}"


def ip_int(value: str) -> int:
    result = 0
    for part in value.split("."):
        result = (result << 8) + int(part)
    return result


STATE = {
    "config": {
        "modelname": "AiFace", "deviceid": 1, "firmware": "mock-1.0",
        "curip": "127.0.0.1", "mac": "00-00-00-00-00-01", "time": "2026-01-01 00:00:00",
        "useduser": 0, "usersize": 5000, "usedlog": 0, "logsize": 1000,
        "language": 19, "serverip": ip_int("8.8.8.8"), "door_opentime": 5,
        "door_password": 0, "wlan_pwd": "segredo", "webserver_pwd": "123",
        "netipaddress": ip_int("192.168.1.50"), "netmask": ip_int("255.255.255.0"),
        "filllight_period": 0, "dst_start": 342, "reboottime1": 750,
    },
    "company": {"companyname": "Empresa Antiga", "companyaddr": "", "companycpny": ""},
    "last_setdevinfo": None,
    "firmware": None,
}


class MockDevice(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/home.html":
            body = b"<html><title>AI Biometric Device Management System</title></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        if parsed.path == "/api/firmware/upload":
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            chunk = self.rfile.read(length)
            fw = STATE["firmware"] or {"parts": [], "requests": 0}
            fw["offset"] = int(query.get("offset", 0))
            fw["total"] = int(query.get("total", 0))
            fw["name"] = query.get("name")
            fw["password"] = query.get("password")
            fw["parts"].append(chunk)
            fw["requests"] += 1
            if not chunk:
                fw["final_md5"] = query.get("md5")
                fw["received"] = b"".join(fw["parts"])
            STATE["firmware"] = fw
            self._json({"result": True, "offset": fw["offset"]})
            return
        if parsed.path != "/api":
            self._json({"error": "not found"}, 404)
            return
        payload = json.loads(self.rfile.read(length) or b"{}")
        cmd = payload.get("cmd")
        if cmd == "getlang":
            self._json({"ret": "getlang", "sn": "MOCK-001", "lang": "Brazilian", "result": True})
        elif cmd == "reg":
            self._json({"ret": "reg", "sn": "MOCK-001", "devinfo": STATE["config"], "result": True})
        elif cmd == "getdevinfo":
            self._json({"ret": "getdevinfo", "sn": "MOCK-001", **STATE["config"], "result": True})
        elif cmd == "getcompanyfile":
            self._json({"ret": "getcompanyfile", "sn": "MOCK-001", **STATE["company"], "result": True})
        elif cmd == "setdevinfo":
            STATE["last_setdevinfo"] = payload
            for key, value in payload.items():
                if key not in ("password", "cmd", "nowtime"):
                    STATE["config"][key] = value
            self._json({"ret": "setdevinfo", "sn": "MOCK-001", "result": True})
        elif cmd == "setcompanyfile":
            for key in ("companyname", "companyaddr", "companycpny"):
                if key in payload:
                    STATE["company"][key] = payload[key]
            self._json({"ret": "setcompanyfile", "sn": "MOCK-001", "result": True})
        else:
            self._json({"ret": cmd, "result": True})


def wait_for(url: str, timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=1)
            return
        except requests.RequestException:
            time.sleep(0.2)
    raise RuntimeError(f"Servidor não iniciou: {url}")


def check(label: str, condition: bool, detail: str = "") -> None:
    print(("PASS  " if condition else "FAIL  ") + label + (f" :: {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


def main() -> None:
    mock = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockDevice)
    threading.Thread(target=mock.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "WPS_CONFIG_DIR": tmp, "WPS_DATA_DIR": tmp}
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(APP_PORT)],
            cwd=PROJECT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            wait_for(BASE + "/api/health")
            created = requests.post(BASE + "/api/devices", json={
                "id": "mock-01", "host": "127.0.0.1", "port": MOCK_PORT,
                "label": "Relógio simulado", "password": "123",
            }, timeout=10)
            check("cadastrar equipamento", created.ok, str(created.status_code))

            refreshed = requests.post(BASE + "/api/devices/refresh", timeout=10).json()
            status = refreshed[0]["status"]
            check("detecção da assinatura", status["signature"] and status["sn"] == "MOCK-001")

            config = requests.get(BASE + "/api/devices/mock-01/config", timeout=10).json()
            check("IP decodificado", config["serverip"] == "8.8.8.8", config["serverip"])
            check("horário decodificado", config["reboottime1"] == "12:30", config["reboottime1"])
            check("segredos fora do payload configurável", "wlan_pwd" not in config and "webserver_pwd" not in config)
            check("senha zero não mascarada", config["door_password"] == "", str(config["door_password"]))

            desired = {"language": 0, "serverip": "192.168.1.10", "door_opentime": 7}
            preview = requests.post(BASE + "/api/devices/mock-01/preview", json={"fields": desired}, timeout=10).json()
            changed = {c["field"] for c in preview["changes"]}
            check("prévia sem gravar", changed == set(desired) and STATE["last_setdevinfo"] is None, str(changed))

            applied = requests.post(BASE + "/api/devices/mock-01/apply", json={
                "fields": desired, "confirm": True, "operator": "teste"
            }, timeout=10).json()
            check("aplicação confirmada", applied.get("applied") is True)
            check("IP codificado na API", STATE["config"]["serverip"] == ip_int("192.168.1.10"))
            check("demais campos preservados", STATE["config"]["dst_start"] == 342)
            check("payload setdevinfo completo", STATE["last_setdevinfo"]["cmd"] == "setdevinfo"
                  and "nowtime" in STATE["last_setdevinfo"] and STATE["last_setdevinfo"]["password"] == "123")

            company = requests.post(BASE + "/api/devices/mock-01/company", json={
                "fields": {"companyname": "Empresa Nova"}, "confirm": True
            }, timeout=10)
            check("empresa aplicada", company.ok and STATE["company"]["companyname"] == "Empresa Nova")

            requests.post(BASE + "/api/profiles", json={
                "name": "smoke", "description": "",
                "fields": {"language": 19, "door_opentime": 9},
                "company": {"companyname": "Empresa Modelo"},
            }, timeout=10)
            bulk = requests.post(BASE + "/api/bulk/apply", json={
                "profile": "smoke", "device_ids": ["mock-01"], "confirm": True,
                "include_company": True,
            }, timeout=10).json()
            check("aplicação em lote", bulk["results"][0]["applied"] is True)
            check("modelo aplicado", STATE["config"]["door_opentime"] == 9
                  and STATE["company"]["companyname"] == "Empresa Modelo")

            meta = requests.get(BASE + "/api/meta", timeout=10).json()
            categories = meta["setting_categories"]
            check("categorias do dispositivo", len(categories) == 13
                  and categories[0]["label"] == "elevator control"
                  and categories[-1]["label"] == "Comm set=>APP Notify", str(len(categories)))
            check("campos novos no whitelist", all(k in meta["setting_fields"] for k in (
                "fpmatch_level", "fps_peruser", "palm_vein_level", "palm_det_level",
                "app_token", "wear_mask",
            )))

            advanced = requests.post(BASE + "/api/devices/mock-01/apply", json={
                "fields": {
                    "fpmatch_level": 5, "palm_vein_level": 60, "app_token": "token-teste"
                },
                "confirm": True,
            }, timeout=10).json()
            check("configurações avançadas aplicadas", advanced.get("applied") is True
                  and STATE["config"]["fpmatch_level"] == 5
                  and STATE["config"]["palm_vein_level"] == 60
                  and STATE["config"]["app_token"] == "token-teste")

            all_fields = requests.get(BASE + "/api/devices/mock-01/config", timeout=10).json()
            all_preview = requests.post(
                BASE + "/api/devices/mock-01/preview",
                json={"fields": all_fields}, timeout=10,
            ).json()
            check("prévia de todas as abas", all_preview.get("dry_run") is True
                  and not all_preview.get("unknown_fields")
                  and isinstance(all_preview.get("changes"), list))
            all_apply = requests.post(
                BASE + "/api/devices/mock-01/apply",
                json={"fields": all_fields, "confirm": True}, timeout=10,
            ).json()
            check("envio de todas as abas", all_apply.get("applied") is True
                  and STATE["last_setdevinfo"]["cmd"] == "setdevinfo")

            save_payload = {
                "name": "copiado-mock", "description": "Salvo do equipamento",
                "include_company": True, "operator": "teste",
            }
            save_preview = requests.post(
                BASE + "/api/devices/mock-01/save-profile",
                json={**save_payload, "confirm": False}, timeout=10,
            ).json()
            check("prévia do modelo salvo", save_preview.get("applied") is False
                  and save_preview.get("fields_count", 0) > 10
                  and "wlan_pwd" not in save_preview.get("fields", {})
                  and "app_token" not in save_preview.get("fields", {}))
            saved_profile = requests.post(
                BASE + "/api/devices/mock-01/save-profile",
                json={**save_payload, "confirm": True}, timeout=10,
            ).json()
            profile = next((p for p in requests.get(BASE + "/api/profiles", timeout=10).json()
                            if p.get("name") == "copiado-mock"), None)
            check("modelo salvo do equipamento", saved_profile.get("applied") is True
                  and profile is not None
                  and profile["fields"].get("language") == 19
                  and profile["fields"].get("door_opentime") == 9
                  and "app_token" not in profile["fields"]
                  and profile["company"].get("companyname") == "Empresa Modelo")
            check("histórico do modelo salvo", any(
                h.get("action") == "save_profile_from_device"
                for h in requests.get(BASE + "/api/history", timeout=10).json()
            ))

            firmware_data = b"X" * (1024 * 1024 + 32)
            firmware_md5 = hashlib.md5(firmware_data).hexdigest()
            invalid = requests.post(
                BASE + "/api/devices/mock-01/firmware",
                files={"file": ("firmware.pkg", firmware_data)},
                data={"confirm": "false"}, timeout=15,
            )
            check("validação de nome .pkg", invalid.status_code == 400, str(invalid.status_code))

            preview_fw = requests.post(
                BASE + "/api/devices/mock-01/firmware",
                files={"file": ("firmware-update-1.0.pkg", firmware_data)},
                data={"confirm": "false"}, timeout=15,
            ).json()
            check("prévia do firmware", preview_fw.get("applied") is False
                  and preview_fw.get("md5") == firmware_md5 and STATE["firmware"] is None)

            started = requests.post(
                BASE + "/api/devices/mock-01/firmware",
                files={"file": ("firmware-update-1.0.pkg", firmware_data)},
                data={"confirm": "true", "operator": "teste"}, timeout=15,
            ).json()
            check("upload de firmware iniciado", started.get("applied") is True and bool(started.get("job_id")))
            job_id = started["job_id"]
            status = None
            deadline = time.time() + 20
            while time.time() < deadline:
                status = requests.get(
                    BASE + f"/api/devices/mock-01/firmware/jobs/{job_id}", timeout=10
                ).json()
                if status["status"] in ("done", "error"):
                    break
                time.sleep(0.2)
            fw = STATE["firmware"] or {}
            check("upload de firmware concluído", status and status["status"] == "done", str(status))
            check("chunks e MD5 do firmware", fw.get("final_md5") == firmware_md5
                  and fw.get("received") == firmware_data and fw.get("requests") == 3,
                  str(fw.get("requests")))
            check("senha do equipamento no upload", fw.get("password") == "123")

            lib_preview = requests.post(
                BASE + "/api/firmware",
                files={"file": ("firmware-update-2.0.pkg", firmware_data)},
                data={"description": "Versao 2.0", "confirm": "false"}, timeout=15,
            ).json()
            check("prévia da biblioteca", lib_preview.get("saved") is False
                  and lib_preview.get("md5") == firmware_md5
                  and not requests.get(BASE + "/api/firmware", timeout=10).json())

            lib_saved = requests.post(
                BASE + "/api/firmware",
                files={"file": ("firmware-update-2.0.pkg", firmware_data)},
                data={"description": "Versao 2.0", "confirm": "true"}, timeout=15,
            ).json()
            library = requests.get(BASE + "/api/firmware", timeout=10).json()
            firmware_id = lib_saved.get("id", "")
            stored_path = Path(tmp) / "firmware" / f"{firmware_id}.bin"
            check("arquivo salvo na biblioteca", lib_saved.get("saved") is True
                  and len(library) == 1 and library[0].get("md5") == firmware_md5
                  and library[0].get("description") == "Versao 2.0")
            check("conteúdo persistido", stored_path.exists()
                  and stored_path.read_bytes() == firmware_data)

            STATE["firmware"] = None
            lib_started = requests.post(
                BASE + "/api/devices/mock-01/firmware",
                data={"firmware_id": firmware_id, "confirm": "true", "operator": "teste"},
                timeout=15,
            ).json()
            check("envio do arquivo salvo iniciado", lib_started.get("applied") is True
                  and lib_started.get("firmware_id") == firmware_id)
            status = None
            deadline = time.time() + 20
            while time.time() < deadline:
                status = requests.get(
                    BASE + f"/api/devices/mock-01/firmware/jobs/{lib_started['job_id']}",
                    timeout=10,
                ).json()
                if status["status"] in ("done", "error"):
                    break
                time.sleep(0.2)
            fw = STATE["firmware"] or {}
            check("envio do arquivo salvo concluído", status and status["status"] == "done"
                  and fw.get("final_md5") == firmware_md5 and fw.get("received") == firmware_data)
            missing_source = requests.post(
                BASE + "/api/devices/mock-01/firmware", data={"confirm": "false"}, timeout=10
            )
            check("origem obrigatória no envio", missing_source.status_code == 400,
                  str(missing_source.status_code))

            del_preview = requests.delete(
                BASE + f"/api/firmware/{firmware_id}", timeout=10
            ).json()
            check("prévia da exclusão da biblioteca", del_preview.get("deleted") is False
                  and len(requests.get(BASE + "/api/firmware", timeout=10).json()) == 1)
            deleted = requests.delete(
                BASE + f"/api/firmware/{firmware_id}?confirm=true", timeout=10
            ).json()
            check("arquivo excluído da biblioteca", deleted.get("deleted") is True
                  and not requests.get(BASE + "/api/firmware", timeout=10).json()
                  and not stored_path.exists())
            check("histórico da biblioteca", {
                h.get("action") for h in requests.get(BASE + "/api/history", timeout=10).json()
            } >= {"firmware_saved", "firmware_deleted"})

            history = requests.get(BASE + "/api/history", timeout=10).json()
            check("histórico registrado", len(history) >= 10, str(len(history)))
        finally:
            server.terminate()
            server.wait(timeout=10)
            mock.shutdown()
    print("\nTodos os testes passaram.")


if __name__ == "__main__":
    main()
