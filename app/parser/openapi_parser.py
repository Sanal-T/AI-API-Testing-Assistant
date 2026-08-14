import json
import yaml
from pathlib import Path


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
    Resolve an OpenAPI $ref into its actual schema.
    """

    ref = schema.get("$ref")

    if not ref:
        return schema

    parts = ref.split("/")

    current = spec

    for part in parts[1:]:
        current = current.get(part, {})

    return current

def extract_endpoints(spec: dict):
    """
    Extract endpoint metadata from an OpenAPI specification.
    """

    endpoints = []

    paths = spec.get("paths", {})

    for path, methods in paths.items():

        for method, details in methods.items():

            endpoint = {
                "method": method.upper(),
                "path": path,
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "parameters": extract_parameters(details),
                "request_body": details.get("requestBody", {}),
                "responses": details.get("responses", {}),
            }
            request_body = endpoint["request_body"]

            content = request_body.get("content", {})

            json_content = content.get("application/json", {})

            schema = json_content.get("schema", {})

            endpoint["resolved_schema"] = resolve_schema_ref(spec, schema)

            endpoints.append(endpoint)

    return endpoints

def extract_parameters(details: dict):
    """
    Extract and normalize endpoint parameters.
    """

    parameters = []

    for parameter in details.get("parameters", []):

        parameters.append({
            "name": parameter.get("name"),
            "location": parameter.get("in"),
            "required": parameter.get("required", False),
            "schema": parameter.get("schema", {})
        })

    return parameters