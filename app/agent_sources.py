import hashlib
import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.geometry import validate_geometry, validate_properties

MAX_BYTES = 64 * 1024 * 1024
MAX_FEATURES = 10_000
MAX_MAPPINGS = 32
MAX_URL_LENGTH = 2_000
MAX_NAME_LENGTH = 100
MAX_PAGE_SIZE = 1_000
MAX_PAGES = 100
MAX_PARAMETER_NAME_LENGTH = 50


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects are not allowed")


@dataclass(frozen=True)
class PreflightResult:
    proposal: dict[str, Any]
    dataset: dict[str, Any]
    fingerprint: str
    summary: dict[str, Any]
    warnings: list[str]


def canonical_proposal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Source proposal must be an object")
    allowed = {
        "endpoint",
        "slug",
        "name",
        "description",
        "category",
        "geometry_types",
        "dataset_id",
        "id_property",
        "properties",
        "timeout_seconds",
        "attribution",
        "license",
        "pagination",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("Source proposal contains unsupported fields")
    result = dict(value)
    endpoint = result.get("endpoint")
    _validate_url(endpoint)
    if not isinstance(result.get("slug"), str) or not result["slug"].islower():
        raise ValueError("Source slug must be lowercase")
    for field in ("name", "category", "dataset_id"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise ValueError(f"Source {field} is required")
    if len(result["name"]) > MAX_NAME_LENGTH:
        raise ValueError("Source name must be at most 100 characters")
    types = result.get("geometry_types")
    if (
        not isinstance(types, list)
        or not types
        or not all(isinstance(item, str) for item in types)
    ):
        raise ValueError("geometry_types must be a non-empty list")
    mappings = result.get("properties", {})
    if not isinstance(mappings, dict) or len(mappings) > MAX_MAPPINGS:
        raise ValueError("At most 32 property mappings are allowed")
    if not all(
        isinstance(k, str) and isinstance(v, str) and k and v
        for k, v in mappings.items()
    ):
        raise ValueError("Property mappings must contain non-empty strings")
    if any(
        len(k) > MAX_NAME_LENGTH or len(v) > MAX_NAME_LENGTH
        for k, v in mappings.items()
    ):
        raise ValueError("Property mapping names must be at most 100 characters")
    timeout = result.get("timeout_seconds", 20)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= 60
    ):
        raise ValueError("timeout_seconds must be an integer between 1 and 60")
    result["timeout_seconds"] = timeout
    result["properties"] = dict(sorted(mappings.items()))
    result["geometry_types"] = list(dict.fromkeys(types))
    result["pagination"] = canonical_pagination(result.get("pagination"))
    return result


def canonical_pagination(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("pagination must be an object")
    allowed = {"type", "limit_param", "offset_param", "page_size", "max_pages"}
    if set(value) - allowed:
        raise ValueError("pagination contains unsupported fields")
    if value.get("type") != "offset":
        raise ValueError("pagination.type must be 'offset'")
    limit_param = value.get("limit_param")
    offset_param = value.get("offset_param")
    for name, parameter in (
        ("limit_param", limit_param),
        ("offset_param", offset_param),
    ):
        if (
            not isinstance(parameter, str)
            or not 1 <= len(parameter) <= MAX_PARAMETER_NAME_LENGTH
            or not parameter.replace("_", "").isalnum()
            or not parameter[0].isalpha()
        ):
            raise ValueError(f"pagination.{name} is invalid")
    if limit_param == offset_param:
        raise ValueError("pagination parameters must be different")
    page_size = value.get("page_size")
    max_pages = value.get("max_pages")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_PAGE_SIZE
    ):
        raise ValueError(
            f"pagination.page_size must be an integer between 1 and {MAX_PAGE_SIZE}"
        )
    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or not 1 <= max_pages <= MAX_PAGES
    ):
        raise ValueError(
            f"pagination.max_pages must be an integer between 1 and {MAX_PAGES}"
        )
    return {
        "type": "offset",
        "limit_param": limit_param,
        "offset_param": offset_param,
        "page_size": page_size,
        "max_pages": max_pages,
    }


def _validate_url(url: Any) -> tuple[str, list[str]]:
    if not isinstance(url, str) or len(url) > MAX_URL_LENGTH:
        raise ValueError("Endpoint must be a URL of at most 2000 characters")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.port not in (None, 443) or not parts.hostname:
        raise ValueError("Endpoint must use HTTPS on port 443")
    if parts.username or parts.password or parts.fragment:
        raise ValueError("Endpoint cannot contain credentials or a fragment")
    hostname = parts.hostname.rstrip(".").lower()
    if (
        hostname == "localhost"
        or "." not in hostname
        or hostname.endswith((".local", ".internal"))
    ):
        raise ValueError("Endpoint hostname is not public")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as error:
        raise ValueError("Endpoint hostname could not be resolved") from error
    if not addresses:
        raise ValueError("Endpoint hostname has no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise ValueError("Endpoint resolves to a forbidden address")
        if address in {"169.254.169.254", "169.254.170.2", "100.100.100.200"}:
            raise ValueError("Endpoint resolves to a metadata address")
    return hostname, sorted(addresses)


def fetch_dataset(endpoint: str, timeout: int) -> tuple[dict[str, Any], dict[str, Any]]:
    hostname, addresses = _validate_url(endpoint)
    request = Request(
        endpoint, headers={"Accept": "application/geo+json, application/json"}
    )
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError(f"GeoJSON endpoint returned HTTP {response.status}")
        data = bytearray()
        while True:
            chunk = response.read(min(1024 * 1024, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError("GeoJSON response exceeds 64 MiB")
        payload = json.loads(
            bytes(data).decode(response.headers.get_content_charset() or "utf-8")
        )
    return payload, {"hostname": hostname, "addresses": addresses, "bytes": len(data)}


def paginate_json(
    endpoint: str,
    timeout: int,
    pagination: dict[str, Any] | None,
    request: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Collect a bounded offset-paginated FeatureCollection before publishing it."""
    if pagination is None:
        payload, identity = request(endpoint, timeout)
        _require_feature_collection(payload)
        return payload, [identity], 1

    page_size = pagination["page_size"]
    features: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    for page_number in range(pagination["max_pages"]):
        offset = page_number * page_size
        page_url = _pagination_url(
            endpoint,
            pagination["limit_param"],
            pagination["offset_param"],
            page_size,
            offset,
        )
        payload, identity = request(page_url, timeout)
        _require_feature_collection(payload)
        page_features = payload["features"]
        features.extend(page_features)
        identities.append({"url": page_url, **identity})
        if len(features) > MAX_FEATURES:
            raise ValueError("GeoJSON source contains more than 10000 features")
        if len(page_features) < page_size:
            return (
                {"type": "FeatureCollection", "features": features},
                identities,
                page_number + 1,
            )
    raise ValueError("GeoJSON pagination limit reached while pages remain full")


def _require_feature_collection(payload: Any) -> None:
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "FeatureCollection"
        or not isinstance(payload.get("features"), list)
        or not all(isinstance(feature, dict) for feature in payload["features"])
    ):
        raise ValueError("GeoJSON source must return a FeatureCollection")


def _pagination_url(
    endpoint: str, limit_param: str, offset_param: str, page_size: int, offset: int
) -> str:
    parts = urlsplit(endpoint)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query = [
        (key, value) for key, value in query if key not in {limit_param, offset_param}
    ]
    query.extend(((limit_param, str(page_size)), (offset_param, str(offset))))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def validate_dataset(
    proposal: dict[str, Any], payload: Any, seen_ids: set[str] | None = None
) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "FeatureCollection"
        or not isinstance(payload.get("features"), list)
    ):
        raise ValueError("GeoJSON source must return a FeatureCollection")
    features = payload["features"]
    if len(features) > MAX_FEATURES:
        raise ValueError("GeoJSON source contains more than 10000 features")
    ids = seen_ids if seen_ids is not None else set()
    geometry_types: set[str] = set()
    mappings = proposal["properties"]
    for feature in features:
        if (
            not isinstance(feature, dict)
            or feature.get("type") != "Feature"
            or not isinstance(feature.get("geometry"), dict)
            or feature["geometry"] is None
        ):
            raise ValueError("GeoJSON source contains an invalid Feature")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("GeoJSON Feature properties must be an object")
        external_id = (
            properties.get(proposal["id_property"])
            if proposal.get("id_property")
            else feature.get("id")
        )
        if (
            isinstance(external_id, bool)
            or external_id is None
            or str(external_id) == ""
        ):
            raise ValueError("GeoJSON Feature has no configured ID")
        normalized_id = str(external_id)
        if normalized_id in ids:
            raise ValueError("GeoJSON source contains duplicate record IDs")
        ids.add(normalized_id)
        for field in mappings.values():
            if field not in properties:
                raise ValueError(f"Mapped property is missing: {field}")
        validate_geometry(feature["geometry"], proposal["geometry_types"])
        validate_properties(properties)
        geometry_types.add(feature["geometry"]["type"])
    if not geometry_types.issubset(set(proposal["geometry_types"])):
        raise ValueError("Declared geometry types do not match the dataset")
    return {
        "feature_count": len(features),
        "geometry_types": sorted(geometry_types),
        "id_count": len(ids),
    }


def preflight(proposal: dict[str, Any]) -> PreflightResult:
    normalized = canonical_proposal(proposal)
    payload, identities, pages = paginate_json(
        normalized["endpoint"],
        normalized["timeout_seconds"],
        normalized["pagination"],
        fetch_dataset,
    )
    seen_ids: set[str] = set()
    summary = validate_dataset(normalized, payload, seen_ids)
    canonical = json.dumps(
        {"proposal": normalized, "identity": identities, "dataset": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return PreflightResult(
        normalized,
        payload,
        fingerprint,
        summary | {"pages_fetched": pages, "identities": identities},
        ["DNS addresses are prechecked but not pinned during TLS connection."],
    )
