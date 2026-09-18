import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.models import ExternalSource
from app.sources import NormalizedFeature, register_adapter

DEFAULT_TIMEOUT_SECONDS = 20
MAX_TIMEOUT_SECONDS = 120


class GeoJSONAdapter:
    def fetch(self, source: ExternalSource) -> list[dict[str, Any]]:
        endpoint = _endpoint(source)
        payload = _request_json(endpoint, _config(source)["timeout_seconds"])
        if (
            not isinstance(payload, dict)
            or payload.get("type") != "FeatureCollection"
            or not isinstance(payload.get("features"), list)
            or not all(isinstance(feature, dict) for feature in payload["features"])
        ):
            raise ValueError("GeoJSON source must return a FeatureCollection")
        return payload["features"]

    def normalize(
        self, record: dict[str, Any], source: ExternalSource
    ) -> NormalizedFeature:
        config = _config(source)
        if record.get("type") != "Feature" or not isinstance(
            record.get("geometry"), dict
        ):
            raise ValueError("GeoJSON source contains an invalid Feature")
        properties = record.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("GeoJSON Feature properties must be an object")
        external_id = (
            record.get("id")
            if config["id_property"] is None
            else properties.get(config["id_property"])
        )
        if isinstance(external_id, bool) or external_id in (None, ""):
            raise ValueError("GeoJSON Feature has no configured ID")
        return NormalizedFeature(
            external_id=str(external_id),
            source_record_id=str(external_id),
            geometry=record["geometry"],
            properties={
                target: properties.get(field)
                for target, field in config["properties"].items()
            },
            source_url=_endpoint(source),
            metadata={"adapter": "geojson"},
        )


def _endpoint(source: ExternalSource) -> str:
    if not source.endpoint:
        raise ValueError("GeoJSON source endpoint is required")
    parts = urlsplit(source.endpoint)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("GeoJSON source endpoint must be HTTPS")
    return source.endpoint


def _config(source: ExternalSource) -> dict[str, Any]:
    config = source.adapter_config
    if not isinstance(config, dict):
        raise ValueError("GeoJSON source configuration must be an object")
    id_property = config.get("id_property")
    if id_property is not None and not isinstance(id_property, str):
        raise ValueError("GeoJSON id_property must be a string")
    properties = config.get("properties")
    if not isinstance(properties, dict) or not all(
        isinstance(target, str) and isinstance(field, str)
        for target, field in properties.items()
    ):
        raise ValueError("GeoJSON properties must map output names to source fields")
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(
            f"GeoJSON timeout_seconds must be an integer between 1 and "
            f"{MAX_TIMEOUT_SECONDS}"
        )
    return {
        "id_property": id_property,
        "properties": properties,
        "timeout_seconds": timeout,
    }


def _request_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    request = Request(url, headers={"Accept": "application/geo+json, application/json"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(
            response.read().decode(response.headers.get_content_charset() or "utf-8")
        )


register_adapter("geojson", GeoJSONAdapter())
