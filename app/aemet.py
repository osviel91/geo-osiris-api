import json
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.models import ExternalSource
from app.sources import NormalizedFeature, register_adapter

DEFAULT_ENDPOINT = (
    "https://opendata.aemet.es/opendata/api/valores/climatologicos/"
    "inventarioestaciones/todasestaciones/"
)


class AemetStationsAdapter:
    def fetch(self, source: ExternalSource) -> list[dict[str, Any]]:
        api_key = os.getenv("AEMET_API_KEY")
        if not api_key:
            raise ValueError("AEMET_API_KEY is not configured")
        response = _request_json(
            _with_api_key(source.endpoint or DEFAULT_ENDPOINT, api_key)
        )
        if not isinstance(response, dict) or not isinstance(response.get("datos"), str):
            raise ValueError("AEMET station inventory response has no data URL")
        records = _request_json(response["datos"])
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise ValueError("AEMET station inventory is not a record list")
        return records

    def normalize(
        self, record: dict[str, Any], source: ExternalSource
    ) -> NormalizedFeature:
        record_id = _required(record, "indicativo")
        latitude = _coordinate(_required(record, "latitud"), "latitude")
        longitude = _coordinate(_required(record, "longitud"), "longitude")
        timestamps = {
            key: str(record[key])
            for key in ("fecha", "fint", "fnac")
            if record.get(key) not in (None, "")
        }
        return NormalizedFeature(
            external_id=record_id,
            source_record_id=record_id,
            geometry={"type": "Point", "coordinates": [longitude, latitude]},
            properties={
                "name": record.get("nombre", record_id),
                "station_type": "weather_observation_station",
                "provider": "AEMET",
                "province": record.get("provincia"),
                "altitude_m": _number(record.get("altitud")),
            },
            source_url=source.endpoint or DEFAULT_ENDPOINT,
            observed_at=_timestamp(timestamps),
            metadata={"source_timestamps": timestamps},
        )


def _with_api_key(url: str, api_key: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["api_key"] = api_key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _request_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            return json.loads(payload.decode(charset))
        except UnicodeDecodeError:
            return json.loads(payload.decode("latin-1"))


def _required(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if value is None or not str(value).strip():
        raise ValueError(f"AEMET station is missing {field}")
    return str(value).strip()


def _coordinate(value: str, axis: str) -> float:
    try:
        coordinate = float(value)
    except ValueError:
        match = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)([NSEW])", value)
        if match is None:
            raise ValueError(f"Invalid AEMET {axis}") from None
        degrees, minutes, seconds, direction = match.groups()
        coordinate = int(degrees) + int(minutes) / 60 + float(seconds) / 3600
        if direction in {"S", "W"}:
            coordinate *= -1
    if axis == "latitude" and not -90 <= coordinate <= 90:
        raise ValueError("Invalid AEMET latitude")
    if axis == "longitude" and not -180 <= coordinate <= 180:
        raise ValueError("Invalid AEMET longitude")
    return coordinate


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(values: dict[str, str]) -> datetime | None:
    for value in values.values():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    return None


register_adapter("aemet_stations", AemetStationsAdapter())
