import json
import yaml
from pathlib import Path
from urllib.parse import unquote

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}


def load_spec(file_path: str):
    """
    Load an OpenAPI specification from a YAML or JSON file.
    """

    path = Path(file_path)

    if path.suffix.lower() in [".yaml", ".yml"]:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    elif path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    raise ValueError("Unsupported file format.")

def resolve_schema_ref(spec: dict, schema: dict):
    """
    Resolve local schema references recursively in objects and arrays.
    """
    return _resolve_refs(spec, schema, reference_stack=())


def _resolve_refs(spec: dict, value, reference_stack: tuple[str, ...]):
    if isinstance(value, list):
        return [_resolve_refs(spec, item, reference_stack) for item in value]
    if not isinstance(value, dict):
        return value

    if "$ref" in value:
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ValueError(f"Only local JSON Pointer references are supported: {ref!r}")
        if ref in reference_stack:
            raise ValueError(f"Circular schema reference detected: {ref}")

        target = _lookup_local_reference(spec, ref)
        if not isinstance(target, dict):
            raise ValueError(f"Schema reference {ref!r} does not point to an object.")
        # Preserve schema siblings while allowing local fields to override the target.
        resolved = {**target, **{key: item for key, item in value.items() if key != "$ref"}}
        return _resolve_refs(spec, resolved, reference_stack + (ref,))

    resolved = dict(value)
    properties = value.get("properties")
    if isinstance(properties, dict):
        resolved["properties"] = {
            name: _resolve_refs(spec, property_schema, reference_stack)
            for name, property_schema in properties.items()
        }

    for keyword in ("items", "additionalProperties", "not"):
        nested_schema = value.get(keyword)
        if isinstance(nested_schema, (dict, list)):
            resolved[keyword] = _resolve_refs(spec, nested_schema, reference_stack)

    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        nested_schemas = value.get(keyword)
        if isinstance(nested_schemas, list):
            resolved[keyword] = _resolve_refs(spec, nested_schemas, reference_stack)

    return resolved


def _lookup_local_reference(spec: dict, ref: str):
    current = spec
    pointer = unquote(ref[2:])
    for encoded_token in pointer.split("/"):
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"Unresolved schema reference {ref!r} at token {token!r}.")
    return current

def extract_endpoints(spec: dict):
    """
    Extract endpoint metadata from an OpenAPI specification.
    """

    endpoints = []

    paths = spec.get("paths", {})

    for path, methods in paths.items():

        for method, details in methods.items():
            if method.lower() not in _HTTP_METHODS:
                continue

            endpoint = {
                "method": method.upper(),
                "path": path,
                "server_urls": extract_server_urls(spec, methods, details),
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "parameters": extract_parameters(spec, details, path_item=methods),
                "request_body": details.get("requestBody", {}),
                "request_body_required": details.get("requestBody", {}).get("required", False) is True,
                "responses": details.get("responses", {}),
            }
            endpoint["request_body_schemas"] = extract_request_body_schemas(
                spec,
                endpoint["request_body"],
            )
            endpoint["response_schemas"] = extract_response_schemas(
                spec,
                endpoint["responses"],
            )
            endpoint["resolved_schema"] = endpoint["request_body_schemas"].get(
                "application/json",
                {},
            )

            endpoints.append(endpoint)

    return endpoints


def extract_server_urls(spec: dict, path_item: dict, operation: dict) -> list[str]:
    """Return the effective OpenAPI server URLs for an operation.

    Operation-level servers override path-level servers, which override
    document-level servers. OpenAPI defaults to the relative URL "/" when
    no servers are declared. Templated URLs are retained as written.
    """
    if "servers" in operation:
        servers = operation["servers"]
    elif "servers" in path_item:
        servers = path_item["servers"]
    else:
        servers = spec.get("servers", [{"url": "/"}])

    if not isinstance(servers, list):
        return []
    return [
        server["url"]
        for server in servers
        if isinstance(server, dict) and isinstance(server.get("url"), str)
    ]


def extract_request_body_schemas(spec: dict, request_body: dict) -> dict[str, dict]:
    """Return resolved schemas for each declared request media type."""
    content = request_body.get("content", {})
    if not isinstance(content, dict):
        return {}

    schemas_by_media_type = {}
    for media_type, media_details in content.items():
        if not isinstance(media_details, dict) or "schema" not in media_details:
            continue
        schemas_by_media_type[media_type] = resolve_schema_ref(
            spec,
            media_details["schema"],
        )
    return schemas_by_media_type


def extract_response_schemas(spec: dict, responses: dict) -> dict[str, dict]:
    """Return response schemas grouped by status code and media type."""
    response_schemas = {}
    for status_code, response in responses.items():
        if not isinstance(response, dict):
            continue
        content = response.get("content", {})
        if not isinstance(content, dict):
            continue

        schemas_by_media_type = {}
        for media_type, media_details in content.items():
            if not isinstance(media_details, dict) or "schema" not in media_details:
                continue
            schemas_by_media_type[media_type] = resolve_schema_ref(
                spec,
                media_details["schema"],
            )

        if schemas_by_media_type:
            response_schemas[str(status_code)] = schemas_by_media_type

    return response_schemas


def extract_parameters(spec: dict, details: dict, path_item: dict | None = None):
    """
    Extract path-level and operation-level parameters.

    Operation-level parameters override path-level parameters with the same
    (name, location) pair, as specified by OpenAPI.
    """
    parameters_by_key = {}
    inherited_parameters = (path_item or {}).get("parameters", [])
    operation_parameters = details.get("parameters", [])

    for parameter in [*inherited_parameters, *operation_parameters]:
        normalized = {
            "name": parameter.get("name"),
            "location": parameter.get("in"),
            "required": parameter.get("required", False),
            "schema": resolve_schema_ref(spec, parameter.get("schema", {})),
        }
        key = (normalized["name"], normalized["location"])
        parameters_by_key[key] = normalized

    return list(parameters_by_key.values())
