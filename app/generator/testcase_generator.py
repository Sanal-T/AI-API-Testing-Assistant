from app.models.test_case import TestCase


def generate_valid_payload(schema: dict):
    """
    Generate a valid request body from a schema.
    """

    payload = {}

    properties = schema.get("properties", {})

    for field, details in properties.items():

        field_type = details.get("type")

        if field_type == "string":

            if details.get("format") == "email":
                payload[field] = "john@example.com"

            elif "enum" in details:
                payload[field] = details["enum"][0]

            else:
                payload[field] = "sample"

        elif field_type == "integer":

            minimum = details.get("minimum", 0)

            payload[field] = minimum

        elif field_type == "boolean":

            payload[field] = True

    return payload


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
            "expected": "4xx"
        })

    # 2. Boundary tests and format validation
    for field, details in properties.items():

        field_type = details.get("type")

        if field_type == "integer":

            minimum = details.get("minimum")
            maximum = details.get("maximum")

            if minimum is not None:
                payload = valid_payload.copy()
                payload[field] = minimum - 1

                tests.append({
                    "name": f"{field} below minimum",
                    "type": "negative",
                    "payload": payload,
                    "expected": "4xx"
                })

            if maximum is not None:
                payload = valid_payload.copy()
                payload[field] = maximum + 1

                tests.append({
                    "name": f"{field} above maximum",
                    "type": "negative",
                    "payload": payload,
                    "expected": "4xx"
                })

        elif field_type == "string":

            if details.get("format") == "email":
                payload = valid_payload.copy()
                payload[field] = "invalid-email"

                tests.append({
                    "name": f"Invalid email format: {field}",
                    "type": "negative",
                    "payload": payload,
                    "expected": "4xx"
                })

            if "enum" in details:
                payload = valid_payload.copy()
                payload[field] = "invalid-value"

                tests.append({
                    "name": f"Invalid enum value: {field}",
                    "type": "negative",
                    "payload": payload,
                    "expected": "4xx"
                })

    # 3. Empty body, only when the endpoint declares a request body schema.
    if include_empty_body_test:
        tests.append({
            "name": "Empty request body",
            "type": "negative",
            "payload": {},
            "expected": "4xx"
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

    for negative_test in generate_negative_tests(
        schema,
        include_empty_body_test=has_request_body_schema,
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
                # The current generator's generic "4xx" expectation does not
                # identify a specific status code, so leave it explicitly unknown.
                expected_status=[],
            )
        )

    return test_cases


def _documented_success_statuses(endpoint: dict) -> list[int]:
    """Return documented numeric 2xx response codes for a positive case."""
    statuses = []
    for response_code in endpoint.get("responses", {}):
        try:
            status = int(response_code)
        except (TypeError, ValueError):
            continue
        if 200 <= status < 300:
            statuses.append(status)
    return sorted(set(statuses))
