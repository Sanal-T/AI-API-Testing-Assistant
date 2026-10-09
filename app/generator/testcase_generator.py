from app.models.test_case import TestCase


def generate_valid_payload(schema: dict):
    """
    Generate a representative request body, including nested objects and arrays.
    """
    return _generate_object_payload(schema)


def _generate_object_payload(schema: dict) -> dict:
    payload = {}
    for field, details in schema.get("properties", {}).items():
        payload[field] = _generate_schema_value(details)
    return payload


def _generate_schema_value(schema: dict):
    if "default" in schema:
        return schema["default"]

    if "enum" in schema:
        enum_values = schema["enum"]
        return enum_values[0] if enum_values else None

    field_type = schema.get("type")

    if field_type == "string":
        if schema.get("format") == "email":
            return "john@example.com"
        return "sample"

    if field_type == "integer":
        return schema.get("minimum", 0)

    if field_type == "number":
        return schema.get("minimum", 0.0)

    if field_type == "boolean":
        return True

    if field_type == "object" or "properties" in schema:
        return _generate_object_payload(schema)

    if field_type == "array":
        item_schema = schema.get("items", {})
        minimum_items = max(0, schema.get("minItems", 0))
        count = max(1, minimum_items)
        maximum_items = schema.get("maxItems")
        if maximum_items is not None:
            count = min(count, maximum_items)
        return [_generate_schema_value(item_schema) for _ in range(count)]

    # An unconstrained schema accepts any JSON value; a string is a simple sample.
    return "sample"


def generate_negative_tests(schema: dict, include_empty_body_test: bool = False):
    """
    Generate negative test cases based on OpenAPI schema constraints.
    """

    tests = []

    valid_payload = generate_valid_payload(schema)

    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    # 1. Missing required fields
    for field in required_fields:
        payload = valid_payload.copy()
        payload.pop(field, None)

        tests.append({
            "name": f"Missing required field: {field}",
            "type": "negative",
            "payload": payload,
        })

    # 2. Boundary tests and format validation
    for field, details in properties.items():

        field_type = details.get("type")

        if field_type in {"integer", "number"}:

            minimum = details.get("minimum")
            maximum = details.get("maximum")

            if minimum is not None:
                payload = valid_payload.copy()
                payload[field] = minimum - 1

                tests.append({
                    "name": f"{field} below minimum",
                    "type": "negative",
                    "payload": payload,
                })

            if maximum is not None:
                payload = valid_payload.copy()
                payload[field] = maximum + 1

                tests.append({
                    "name": f"{field} above maximum",
                    "type": "negative",
                    "payload": payload,
                })

        elif field_type == "string":

            if details.get("format") == "email":
                payload = valid_payload.copy()
                payload[field] = "invalid-email"

                tests.append({
                    "name": f"Invalid email format: {field}",
                    "type": "negative",
                    "payload": payload,
                })

            if "enum" in details:
                payload = valid_payload.copy()
                payload[field] = "invalid-value"

                tests.append({
                    "name": f"Invalid enum value: {field}",
                    "type": "negative",
                    "payload": payload,
                })

    # 3. Empty body, only when the endpoint declares a request body schema.
    if include_empty_body_test:
        tests.append({
            "name": "Empty request body",
            "type": "negative",
            "payload": {},
        })

    return tests

def generate_parameter_values(parameters: list):
    """
    Generate default test values for path, query, and header parameters.
    """

    values = {
        "path": {},
        "query": {},
        "headers": {}
    }

    for parameter in parameters:
        name = parameter.get("name")
        location = parameter.get("location")
        schema = parameter.get("schema", {})

        parameter_type = schema.get("type")

        # Use OpenAPI default value when available
        if "default" in schema:
            value = schema["default"]

        elif parameter_type == "integer":
            value = schema.get("minimum", 1)

        elif parameter_type == "number":
            value = schema.get("minimum", 1)

        elif parameter_type == "boolean":
            value = True

        elif parameter_type == "string":
            value = "test-value"

        else:
            value = "test-value"

        if location == "path":
            values["path"][name] = value

        elif location == "query":
            values["query"][name] = value

        elif location == "header":
            if name.lower() == "authorization":
                values["headers"][name] = "Bearer test-token"
            else:
                values["headers"][name] = value

    return values


def generate_test_cases(endpoint: dict) -> list[TestCase]:
    """Build validated test cases from one extracted endpoint."""
    schema = endpoint.get("resolved_schema", {})
    request_body = endpoint.get("request_body", {})
    content = request_body.get("content", {})
    has_request_body_schema = any(
        isinstance(media_type, dict) and "schema" in media_type
        for media_type in content.values()
    )
    request_body_required = endpoint.get(
        "request_body_required",
        request_body.get("required", False),
    ) is True

    parameter_values = generate_parameter_values(endpoint.get("parameters", []))
    valid_payload = generate_valid_payload(schema)
    expected_success_statuses = _documented_success_statuses(endpoint)

    test_cases = [
        TestCase(
            name=f"Valid request: {endpoint['method']} {endpoint['path']}",
            method=endpoint["method"],
            path=endpoint["path"],
            type="positive",
            path_params=parameter_values["path"],
            query_params=parameter_values["query"],
            headers=parameter_values["headers"],
            body=valid_payload if has_request_body_schema else None,
            expected_status=expected_success_statuses,
        )
    ]

    if has_request_body_schema and not request_body_required:
        test_cases.append(
            TestCase(
                name=f"Omit optional request body: {endpoint['method']} {endpoint['path']}",
                method=endpoint["method"],
                path=endpoint["path"],
                type="positive",
                path_params=parameter_values["path"],
                query_params=parameter_values["query"],
                headers=parameter_values["headers"],
                body=None,
                expected_status=expected_success_statuses,
            )
        )

    for negative_test in generate_negative_tests(
        schema,
        include_empty_body_test=has_request_body_schema and request_body_required,
    ):
        test_cases.append(
            TestCase(
                name=negative_test["name"],
                method=endpoint["method"],
                path=endpoint["path"],
                type=negative_test["type"],
                path_params=parameter_values["path"],
                query_params=parameter_values["query"],
                headers=parameter_values["headers"],
                body=negative_test["payload"],
                expected_status=_documented_validation_error_statuses(endpoint),
            )
        )

    return test_cases


def _documented_success_statuses(endpoint: dict) -> list[int] | None:
    """Return documented numeric 2xx response codes for a positive case."""
    statuses = [status for status in _documented_status_codes(endpoint) if 200 <= status < 300]
    return statuses or None


def _documented_validation_error_statuses(endpoint: dict) -> list[int] | None:
    """Return documented 400/422 statuses for schema-validation failures."""
    documented_statuses = _documented_status_codes(endpoint)
    expected_statuses = [status for status in (400, 422) if status in documented_statuses]
    return expected_statuses or None


def _documented_status_codes(endpoint: dict) -> set[int]:
    statuses = set()
    for response_code in endpoint.get("responses", {}):
        try:
            status = int(response_code)
        except (TypeError, ValueError):
            continue
        if 100 <= status <= 599:
            statuses.add(status)
    return statuses
