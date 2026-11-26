"""Cliente da API HTTP dos relógios AiFace (AI Biometric Device Management System)."""

from __future__ import annotations

import calendar
import hashlib
import os
from datetime import datetime
from typing import Any

import requests

from .codec import MASK, SECRET_FIELDS, decode, encode, mask

SIGNATURE_MARKERS = (
    "AI Biometric Device Management System",
    "resources/css/admin.css",
    "UISTR_AI_BIO_ID_SYSTEM",
)

FIRMWARE_CHUNK_SIZE = 1024 * 1024
FIRMWARE_EXTENSIONS = ("zip", "pkg")


def _field(
    name: str,
    label: str,
    kind: str = "text",
    options: list[tuple[Any, str]] | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {"name": name, "label": label, "type": kind}
    if options is not None:
        field["options"] = [[value, text] for value, text in options]
    return field


def _category(key: str, label: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"key": key, "label": label, "fields": fields}


# Categorias na mesma ordem e com os mesmos nomes da tela "Device setup" do equipamento.
SETTING_CATEGORIES = (
    _category("elevator", "elevator control", [
        _field("elevator_control", "elevator control", "boolean"),
        _field("floors", "floors", "number"),
        _field("have_g_floor", "G Floor", "boolean"),
        _field("base_floor", "Start Floor", "enum", [(0, "1/G"), (1, "-1"), (2, "-2"), (3, "-3"), (4, "-4"), (5, "-5")]),
    ]),
    _category("enroll", "Enroll Option", [
        _field("rfid_free_reg", "RFID Free Registration", "boolean"),
        _field("rfid_auto_reg", "Swipe to register face", "boolean"),
        _field("face_double_check", "Face Duplication Check", "boolean"),
        _field("reg_card_1", "Register RFID 1"),
        _field("reg_card_2", "Register RFID 2"),
        _field("reg_card_3", "Register RFID 3"),
    ]),
    _category("shift", "Shift", [
        _field("reverifytime", "Re verify", "number"),
        _field("glog_warning", "Log Warning", "number"),
        _field("use_logphoto", "Save Photo", "enum", [(0, "no"), (1, "yes"), (2, "Random Snap")]),
        _field("stranger_photo", "Stranger Photo", "boolean"),
        _field("verifyfail_hint", "Verify fail Hint", "boolean"),
        _field("selfchecklog", "Self-service check log", "boolean"),
        _field("default_shift", "Default Shift", "number"),
        _field("shift_weekend", "Weekend", "enum", [
            (0, "Sat.&Sun. off"), (1, "Sun. off"), (2, "Sat.half,Sun.full"),
            (3, "Fri.off"), (4, "Fri.&Sat.off"), (5, "No"),
        ]),
        _field("shift_weekend_ot", "Weekend Overtime", "boolean"),
        _field("auto_sign", "Auto sign", "enum", [
            (0, "No"), (1, "Inout day"), (2, "In a day"), (3, "Out a day"),
            (4, "Only in"), (5, "Only out"),
        ]),
        _field("excel_password", "Excel Pwd"),
        _field("allow_latetime", "Late time", "number"),
        _field("allow_earlytime", "Early time", "number"),
        _field("reverify_nolock", "Reverify not Open door", "boolean"),
    ]),
    _category("time", "Time", [
        _field("time_format", "Time fmt", "enum", [(0, "24H"), (1, "12H")]),
        _field("date_format", "Date fmt", "enum", [(0, "Y/M/D"), (1, "M/D/Y"), (2, "D/M/Y")]),
        _field("use_dst", "DST", "boolean"),
        _field("dst_start", "DST Start", "month_day"),
        _field("dst_end", "DST End", "month_day"),
        _field("use_ntp", "NTP", "boolean"),
        _field("ntp_timezone", "timezone", "enum", [
            (0, "UTC+0"), (1, "UTC+1"), (2, "UTC+2"), (3, "UTC+3"), (4, "UTC+4"),
            (5, "UTC+5"), (6, "UTC+6"), (7, "UTC+7"), (8, "UTC+8"), (9, "UTC+9"),
            (10, "UTC+10"), (11, "UTC+11"), (12, "UTC+12"),
            (13, "UTC-1"), (14, "UTC-2"), (15, "UTC-3"), (16, "UTC-4"),
            (17, "UTC-5"), (18, "UTC-6"), (19, "UTC-7"), (20, "UTC-8"),
            (21, "UTC-9"), (22, "UTC-10"), (23, "UTC-11"), (24, "UTC-12"),
            (25, "UTC+3:30"), (26, "UTC+4:30"), (27, "UTC+5:30"),
            (28, "UTC+5:45"), (29, "UTC+6:30"), (30, "UTC+9:30"),
            (31, "UTC-3:30"), (32, "UTC-4:30"),
        ]),
        _field("reboottime1", "Reboot Time1", "hour_minute"),
        _field("reboottime2", "Reboot Time2", "hour_minute"),
        _field("reboottime3", "Reboot Time3", "hour_minute"),
    ]),
    _category("bell", "Bell", [
        _field("bellcount", "Bell Times", "number"),
        _field("ring_style", "Bell Style", "enum", [(0, "________"), (1, "__ __ __")]),
        _field("belloutput", "Bell Output", "enum", [(0, "no"), (1, "bell")]),
    ]),
    _category("device_setup", "System=>Device setup", [
        _field("language", "Language", "enum", [(0, "English"), (7, "Español"), (19, "Português-BR")]),
        _field("volume", "Voice", "number"),
        _field("tts_voice", "Play name voice", "boolean"),
        _field("multifaces", "multi faces", "boolean"),
        _field("showresulttime", "result time", "number"),
        _field("screensavertime", "advert time", "number"),
        _field("sleeptime", "sleep time", "number"),
        _field("screensaver_wakeup", "screen saver wakeup", "enum", [(0, "face"), (1, "touch")]),
        _field("label_style", "label style", "enum", [(0, "default"), (1, "gym style"), (2, "message bar")]),
        _field("identify_distance", "identify distance", "enum", [(0, "short"), (1, "middle"), (2, "long")]),
        _field("live_detect", "live check", "boolean"),
        _field("show_avatar", "show avatar", "boolean"),
    ]),
    _category("advanced_setup", "System=>Advanced setup", [
        _field("managers", "max managers", "number"),
        _field("verifymode", "device verify mode", "number"),
        _field("use_qrcode", "qrcode", "enum", [
            (0, "no"), (1, "vistor qrcode"), (2, "card->qrcode"), (3, "server qrcode"),
        ]),
        _field("hide_privacy", "hide privacy", "boolean"),
        _field("fcmatch_level", "1:N threshold", "number"),
        _field("live_treshold", "live threshold", "number"),
        _field("fpmatch_level", "fp threshold", "number"),
        _field("fps_peruser", "user fp count", "number"),
        _field("wear_mask", "wear mask", "boolean"),
        _field("mask_treshold", "mask threshold", "number"),
        _field("filllight", "fill light", "enum", [(0, "AUTO"), (1, "NC"), (2, "NO")]),
        _field("filllight_period", "filllight_period", "time_range"),
        _field("exposure_value", "exposure_value", "number"),
        _field("palm_vein_level", "palm_vein_level", "number"),
        _field("palm_det_level", "palm_det_level", "number"),
        _field("disable_face", "disable_face", "boolean"),
        _field("online_debug", "online debug", "boolean"),
    ]),
    _category("lock", "lock setting", [
        _field("door_opentime", "door_opentime", "number"),
        _field("door_sensor_type", "door_sensor_type", "enum", [(0, "ng"), (1, "nc"), (2, "no")]),
        _field("door_alarm_time", "door_alarm_time", "number"),
        _field("stranger_lock", "stranger_lock", "boolean"),
        _field("door_password", "door_password", "number"),
        _field("door_mutiopen", "multiusers", "number"),
        _field("door_antipass", "door_antipass", "enum", [
            (0, "no"), (1, "in"), (2, "out"), (3, "two way"),
        ]),
        _field("wiegand_output_mode", "wiegand_output_mode", "enum", [
            (0, "id"), (1, "card"), (2, "m+id"), (3, "group id"), (4, "group+id"),
        ]),
        _field("wiegand_output_bit", "wiegand_output_bit", "enum", [
            (0, "26bit"), (1, "34bit"), (2, "42bit"), (3, "50bit"), (4, "58bit"), (5, "64bit"),
        ]),
        _field("access_times", "Access times", "number"),
        _field("wiegand_port", "wiegand port", "enum", [(0, "Output"), (1, "Input"), (2, "Doorsensor")]),
        _field("card_disp_format", "card_disp_format", "enum", [(0, "digital"), (1, "wiegand"), (2, "hex")]),
        _field("card_reversal", "card_reversal", "boolean"),
        _field("wg_reversal", "wg reversal", "boolean"),
        _field("outwg_shot", "outwg_shot", "boolean"),
        _field("door_interlock", "door_interlock", "boolean"),
        _field("door_firealarmin", "door_firealarmin", "boolean"),
        _field("door_trycount", "door_trycount", "number"),
        _field("timezone_punchs", "timezone_punchs", "number"),
        _field("access_denied_nolog", "access_denied_nolog", "boolean"),
        _field("outof_notimzone_denied", "outof_notimzone_denied", "boolean"),
    ]),
    _category("comm_serial", "Comm set=>serial", [
        _field("deviceid", "deviceid", "number"),
        _field("netportnum", "netportnum", "number"),
        _field("combaurate", "combaurate", "enum", [
            (0, "9600"), (1, "19200"), (2, "38400"), (3, "57600"), (4, "115200"),
        ]),
        _field("rs485_fun", "rs485_fun", "enum", [(0, "No"), (1, "Printer"), (2, "Send json")]),
    ]),
    _category("comm_server", "Comm set=>server", [
        _field("use_bs", "use_bs", "boolean"),
        _field("use_domain_name", "use_domain_name", "boolean"),
        _field("bs_domain_name", "bs_domain_name"),
        _field("serverip", "serverip", "ip"),
        _field("serverport", "serverport", "number"),
        _field("server_response_time", "server_response_time", "number"),
        _field("server_verify", "server_verify", "enum", [
            (0, "no"), (1, "yes"), (2, "Offline Waiver"),
        ]),
    ]),
    _category("comm_ethernet", "Comm set=>Ethernet", [
        _field("use_eth_dhcp", "use_eth_dhcp", "boolean"),
        _field("netipaddress", "netipaddress", "ip"),
        _field("netmask", "netmask", "ip"),
        _field("netgateway", "netgateway", "ip"),
        _field("dns_server_ip", "dns_server_ip", "ip"),
    ]),
    _category("comm_wifi", "Comm set=>WIFI", [
        _field("use_wlan_dhcp", "use_wlan_dhcp", "boolean"),
        _field("wlan_ip_address", "wlan_ip_address", "ip"),
        _field("wlan_net_mask", "wlan_net_mask", "ip"),
        _field("wlan_gateway", "wlan_gateway", "ip"),
    ]),
    _category("comm_app", "Comm set=>APP Notify", [
        _field("line_notify", "line_notify", "boolean"),
        _field("app_token", "APP_TOKEN"),
        _field("line_push_type", "line_push_type", "enum", [
            (0, "all push"), (1, "each punch"), (2, "summary push"), (3, "no"),
        ]),
    ]),
)

# Campos visíveis em todos os modelos de firmware, na ordem das categorias acima.
SETTING_FIELDS = tuple(dict.fromkeys(
    field["name"]
    for category in SETTING_CATEGORIES
    for field in category["fields"]
))

# Campos não exibidos no formulário, mas preservados no payload enviado ao equipamento.
EXTRA_SETTING_FIELDS = ("slog_warning", "live_level", "wlan_ssid")
SETTING_FIELDS = tuple(dict.fromkeys((*SETTING_FIELDS, *EXTRA_SETTING_FIELDS)))

COMPANY_FIELDS = ("companyname", "companyaddr", "companycpny")

READONLY_COMMANDS = {
    "reg", "getdevinfo", "getlang", "getlangoption", "getuserlist",
    "getunuserdid", "getrtlog", "getshift", "getholiday", "getbelltime",
    "getdevlock", "getquestionnaire", "getcompanyfile", "getdir",
    "getuserids", "getreport",
}


class DeviceError(RuntimeError):
    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.detail = detail


class DeviceClient:
    def __init__(
        self,
        host: str,
        *,
        port: int = 80,
        scheme: str = "http",
        password: str = "123",
        username: str = "admin",
        timeout: float = 3.0,
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.scheme = scheme if scheme in ("http", "https") else "http"
        self.password = password
        self.username = username
        self.timeout = float(timeout)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def _get(self, path: str, timeout: float | None = None) -> requests.Response:
        try:
            return requests.get(
                f"{self.base_url}{path}", timeout=timeout or self.timeout
            )
        except requests.RequestException as exc:
            raise DeviceError(f"Não foi possível conectar em {self.base_url}: {exc}") from exc

    def api(
        self,
        cmd: str,
        *,
        use_password: bool = True,
        timeout: float | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"cmd": cmd}
        if use_password:
            payload["password"] = self.password
        payload.update(extra)
        try:
            response = requests.post(
                f"{self.base_url}/api",
                json=payload,
                timeout=timeout or self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise DeviceError(f"Falha ao chamar '{cmd}' em {self.host}: {exc}") from exc
        except ValueError as exc:
            raise DeviceError(f"Resposta inválida de '{cmd}' em {self.host}") from exc
        if not isinstance(data, dict):
            raise DeviceError(f"Resposta inesperada de '{cmd}' em {self.host}")
        if data.get("result") is False and cmd not in ("getquestionnaire",):
            raise DeviceError(f"Equipamento recusou '{cmd}': {data.get('msg') or 'sem detalhes'}")
        return data

    def probe(self) -> dict[str, Any]:
        """Identifica o equipamento pela assinatura HTTP e pelo comando getlang."""
        result: dict[str, Any] = {
            "host": self.host,
            "base_url": self.base_url,
            "reachable": False,
            "signature": False,
            "matched_by": [],
            "sn": None,
            "lang": None,
            "error": None,
        }
        try:
            page = self._get("/home.html")
            result["reachable"] = True
            if any(marker in page.text for marker in SIGNATURE_MARKERS):
                result["matched_by"].append("pagina home.html")
        except DeviceError as exc:
            result["error"] = str(exc)
            return result

        try:
            lang = self.api("getlang", use_password=False, timeout=self.timeout)
            if lang.get("ret") == "getlang" and lang.get("sn"):
                result["signature"] = True
                result["matched_by"].append("api getlang")
                result["sn"] = lang.get("sn")
                result["lang"] = lang.get("lang")
        except DeviceError as exc:
            result["error"] = f"{result['error'] or ''} {exc}".strip()
        return result

    def read_snapshot(self) -> dict[str, Any]:
        """Lê identificação, configuração e empresa em uma única chamada lógica."""
        probe = self.probe()
        if not probe["signature"]:
            return {"probe": probe, "reg": None, "config": None, "company": None}
        reg = self.api("reg")
        raw = self.api("getdevinfo")
        settings = {k: raw[k] for k in SETTING_FIELDS if k in raw}
        # "floors" vem de reg em alguns firmwares, não de getdevinfo.
        for key in ("floors",):
            if key not in settings and key in reg.get("devinfo", {}):
                settings[key] = reg["devinfo"][key]
        try:
            company = self.api("getcompanyfile")
        except DeviceError:
            company = {}
        return {
            "probe": probe,
            "reg": reg,
            "config": decode(settings),
            "company": {k: v for k, v in company.items() if k in COMPANY_FIELDS},
            "counts": {
                "users": reg.get("devinfo", {}).get("useduser"),
                "logs": reg.get("devinfo", {}).get("usedlog"),
                "faces": reg.get("devinfo", {}).get("usedface"),
            },
        }

    def current_settings(self) -> dict[str, Any]:
        """Configuração bruta, mantendo os valores IP/horário no formato da API."""
        raw = self.api("getdevinfo")
        return {k: raw[k] for k in SETTING_FIELDS if k in raw}

    @staticmethod
    def _nowtime() -> int:
        # Espelha getUTCTimeInSecondsWithOffset() da interface do equipamento.
        return calendar.timegm(datetime.now().timetuple()) - 8 * 3600

    @staticmethod
    def diff(current: dict[str, Any], desired: dict[str, Any]) -> list[dict[str, Any]]:
        changes = []
        for key, value in sorted(desired.items()):
            before = current.get(key, "<campo ausente>")
            if key in SECRET_FIELDS:
                before = MASK if before not in (None, "", 0) else ""
                after = MASK if value not in (None, "", 0, MASK) else ""
            else:
                after = value
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        return changes

    def preview(self, desired: dict[str, Any]) -> dict[str, Any]:
        """Calcula o que mudaria sem escrever no equipamento."""
        current_raw = self.current_settings()
        desired_encoded = encode(desired)
        unknown = sorted(set(desired_encoded) - set(SETTING_FIELDS))
        merged_raw = {**current_raw, **{k: v for k, v in desired_encoded.items() if k in SETTING_FIELDS}}
        changes = self.diff(decode(current_raw), decode(merged_raw))
        return {
            "host": self.host,
            "dry_run": True,
            "unknown_fields": unknown,
            "changes": changes,
            "would_send": mask(merged_raw),
        }

    def apply_settings(self, desired: dict[str, Any]) -> dict[str, Any]:
        """Aplica alterações mesclando sobre a configuração atual do equipamento."""
        current_raw = self.current_settings()
        desired_encoded = encode(desired)
        unknown = sorted(set(desired_encoded) - set(SETTING_FIELDS))
        if unknown:
            raise DeviceError(f"Campos não suportados: {', '.join(unknown)}")
        merged_raw = {**current_raw, **desired_encoded}
        changes = self.diff(decode(current_raw), decode(merged_raw))
        payload = {
            **merged_raw,
            "password": self.password,
            "cmd": "setdevinfo",
            "nowtime": self._nowtime(),
        }
        try:
            response = requests.post(
                f"{self.base_url}/api", json=payload, timeout=max(self.timeout, 8)
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise DeviceError(f"Falha ao enviar configuração para {self.host}: {exc}") from exc
        except ValueError as exc:
            raise DeviceError(f"Resposta inválida ao configurar {self.host}") from exc
        return {
            "host": self.host,
            "cmd": "setdevinfo",
            "result": data.get("result", True),
            "response": mask(data),
            "changes": changes,
        }

    def apply_company(self, desired: dict[str, Any]) -> dict[str, Any]:
        current = self.api("getcompanyfile")
        current = {k: v for k, v in current.items() if k in COMPANY_FIELDS}
        unknown = sorted(set(desired) - set(COMPANY_FIELDS))
        if unknown:
            raise DeviceError(f"Campos de empresa não suportados: {', '.join(unknown)}")
        merged = {**current, **desired}
        changes = self.diff(current, merged)
        data = self.api("setcompanyfile", **merged)
        return {
            "host": self.host,
            "cmd": "setcompanyfile",
            "result": data.get("result", True),
            "response": mask(data),
            "changes": changes,
        }

    @staticmethod
    def validate_firmware(filename: str, content: bytes) -> str:
        """Aplica as mesmas regras da tela 'Atualizar FW' do equipamento."""
        name = os.path.basename(filename or "").strip()
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension not in FIRMWARE_EXTENSIONS:
            raise DeviceError("Selecione um arquivo .zip ou .pkg")
        if extension == "pkg" and "-update-" not in name:
            raise DeviceError("Para arquivos .pkg, o nome deve conter '-update-'")
        if not content:
            raise DeviceError("Arquivo de firmware vazio")
        return name

    def upload_firmware(
        self,
        filename: str,
        content: bytes,
        *,
        progress: Any = None,
    ) -> dict[str, Any]:
        """Envia o firmware em chunks, exatamente como a página do equipamento.

        A última requisição tem offset == total, corpo vazio e o MD5 final.
        """
        name = self.validate_firmware(filename, content)
        total = len(content)
        digest = hashlib.md5()
        offset = 0
        last_response = ""
        while True:
            chunk = content[offset : offset + FIRMWARE_CHUNK_SIZE]
            digest.update(chunk)
            md5_hex = digest.hexdigest() if offset >= total else ""
            params = {
                "offset": offset,
                "total": total,
                "name": name,
                "md5": md5_hex,
                "password": self.password,
            }
            try:
                response = requests.post(
                    f"{self.base_url}/api/firmware/upload",
                    params=params,
                    data=chunk,
                    timeout=max(self.timeout, 30),
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                raise DeviceError(
                    f"Falha no upload de firmware para {self.host} (offset {offset}): {exc}"
                ) from exc
            last_response = response.text[:500]
            if progress:
                progress(min(offset + len(chunk), total), total)
            if not chunk:
                break
            offset += len(chunk)
        return {
            "host": self.host,
            "filename": name,
            "size": total,
            "md5": digest.hexdigest(),
            "chunks": (total + FIRMWARE_CHUNK_SIZE - 1) // FIRMWARE_CHUNK_SIZE + 1,
            "response": last_response,
        }

    def readonly_command(self, cmd: str, **extra: Any) -> dict[str, Any]:
        if cmd not in READONLY_COMMANDS:
            raise DeviceError(f"Comando '{cmd}' não está na lista de leitura segura")
        return mask(self.api(cmd, **extra))
