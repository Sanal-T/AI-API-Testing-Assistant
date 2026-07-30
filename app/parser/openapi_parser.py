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
                "parameters": details.get("parameters", []),
                "request_body": details.get("requestBody", {}),
                "responses": details.get("responses", {}),
            }

            endpoints.append(endpoint)

    return endpoints