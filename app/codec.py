"""Conversão entre os valores brutos da API do equipamento e valores legíveis.

O firmware envia IPs como inteiro big-endian, datas DST como mês*32+dia,
horários como minutos desde 00:00 e intervalos de luz como 4 bytes empacotados.
"""

from __future__ import annotations

import re
from typing import Any

IP_FIELDS = {
    "serverip",
    "netipaddress",
    "netmask",
    "netgateway",
    "dns_server_ip",
    "wlan_ip_address",
    "wlan_net_mask",
    "wlan_gateway",
}

MONTH_DAY_FIELDS = {"dst_start", "dst_end"}
HOUR_MINUTE_FIELDS = {"reboottime1", "reboottime2", "reboottime3"}
TIME_RANGE_FIELDS = {"filllight_period"}

# Campos que nunca devem ser exibidos em claro na interface ou no histórico.
SECRET_FIELDS = {
    "password",
    "wlan_pwd",
    "webserver_pwd",
    "excel_password",
    "door_password",
    "app_token",
    "cpucard_key",
    "qrcode_pwd",
    "keypad_pwd",
    "commpassword",
}
MASK = "••••••••"


def ip_to_int(value: Any) -> int:
    if isinstance(value, int):
        return value & 0xFFFFFFFF
    parts = str(value).strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"IP inválido: {value!r}")
    result = 0
    for part in parts:
        octet = int(part)
        if not 0 <= octet <= 255:
            raise ValueError(f"IP inválido: {value!r}")
        result = (result << 8) + octet
    return result


def int_to_ip(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return ".".join(str((number >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def month_day_to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", str(value))
    if not match:
        raise ValueError(f"Data DST inválida (use MM/DD): {value!r}")
    month, day = (int(x) for x in match.groups())
    return month * 32 + day


def int_to_month_day(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number // 32:02d}/{number % 32:02d}"


def hour_minute_to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    match = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", str(value))
    if not match:
        raise ValueError(f"Horário inválido (use HH:MM): {value!r}")
    hour, minute = (int(x) for x in match.groups())
    return hour * 60 + minute


def int_to_hour_minute(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number // 60:02d}:{number % 60:02d}"


def time_range_to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    match = re.fullmatch(
        r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*~\s*(\d{1,2})\s*:\s*(\d{1,2})\s*",
        str(value),
    )
    if not match:
        raise ValueError(f"Intervalo inválido (use HH:MM~HH:MM): {value!r}")
    sh, sm, eh, em = (int(x) for x in match.groups())
    return (sh << 24) | (sm << 16) | (eh << 8) | em


def int_to_time_range(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return (
        f"{(number >> 24 & 0xFF):02d}:{(number >> 16 & 0xFF):02d}"
        f"~{(number >> 8 & 0xFF):02d}:{(number & 0xFF):02d}"
    )


def decode(raw: dict[str, Any], *, reveal_secrets: bool = False) -> dict[str, Any]:
    """Decodifica os valores brutos para exibição/edição."""
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if key in IP_FIELDS:
            result[key] = int_to_ip(value)
        elif key in MONTH_DAY_FIELDS:
            result[key] = int_to_month_day(value)
        elif key in HOUR_MINUTE_FIELDS:
            result[key] = int_to_hour_minute(value)
        elif key in TIME_RANGE_FIELDS:
            result[key] = int_to_time_range(value)
        elif key in SECRET_FIELDS and not reveal_secrets:
            result[key] = MASK if value not in (None, "", 0) else ""
        else:
            result[key] = value
    return result


def encode(values: dict[str, Any]) -> dict[str, Any]:
    """Codifica valores editáveis de volta para o formato da API.

    Valores mascarados são descartados: o chamador deve sempre mesclar os
    campos desejados sobre a configuração lida diretamente do equipamento.
    """
    result: dict[str, Any] = {}
    for key, value in values.items():
        if value == MASK:
            continue
        if key in IP_FIELDS:
            result[key] = ip_to_int(value)
        elif key in MONTH_DAY_FIELDS:
            result[key] = month_day_to_int(value)
        elif key in HOUR_MINUTE_FIELDS:
            result[key] = hour_minute_to_int(value)
        elif key in TIME_RANGE_FIELDS:
            result[key] = time_range_to_int(value)
        else:
            result[key] = value
    return result


def mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (MASK if k in SECRET_FIELDS and v not in (None, "", 0) else mask(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask(item) for item in value]
    return value
