import json
from typing import Any

from fastapi import HTTPException

MAX_PROPERTIES_BYTES = 64_000


def validate_geometry(geometry: dict[str, Any], allowed_types: list[str]) -> None:
    geometry_type = geometry.get("type")
    if geometry_type not in allowed_types:
        raise HTTPException(
            status_code=422, detail="Geometry type is not allowed by layer"
        )
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        raise HTTPException(status_code=422, detail="Geometry coordinates are required")
    _validate_coordinates(coordinates)


def validate_properties(properties: dict[str, Any]) -> None:
    if len(json.dumps(properties).encode()) > MAX_PROPERTIES_BYTES:
        raise HTTPException(status_code=422, detail="Feature properties exceed 64 KB")


def _validate_coordinates(value: Any) -> None:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(
            isinstance(number, (int, float)) and not isinstance(number, bool)
            for number in value
        )
    ):
        longitude, latitude = value
        if -180 <= longitude <= 180 and -90 <= latitude <= 90:
            return
        raise HTTPException(
            status_code=422, detail="Coordinates are outside WGS84 bounds"
        )
    if isinstance(value, (list, tuple)) and value:
        for item in value:
            _validate_coordinates(item)
        return
    raise HTTPException(status_code=422, detail="Invalid GeoJSON coordinates")
