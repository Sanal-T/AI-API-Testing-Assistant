from copy import deepcopy

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
            value = "john@example.com"
        else:
            value = "sample"
        minimum = schema.get("minLength", 0)
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            value = value + ("x" * (minimum - len(value)))
        if isinstance(maximum, int) and maximum >= 0 and len(value) > maximum:
            value = value[:maximum]
        return value

    if field_type == "integer":
        if "minimum" in schema:
            value = schema["minimum"]
        elif isinstance(schema.get("exclusiveMinimum"), (int, float)):
            value = int(schema["exclusiveMinimum"]) + 1
        else:
            value = 0
        if isinstance(schema.get("maximum"), (int, float)):
            value = min(value, int(schema["maximum"]))
        if isinstance(schema.get("exclusiveMaximum"), (int, float)):
            value = min(value, int(schema["exclusiveMaximum"]) - 1)
        return value

    if field_type == "number":
        value = schema.get("minimum", 0.0)
        if isinstance(schema.get("exclusiveMinimum"), (int, float)):
            value = max(value, schema["exclusiveMinimum"] + 0.1)
        if isinstance(schema.get("maximum"), (int, float)):
            value = min(value, schema["maximum"])
        if isinstance(schema.get("exclusiveMaximum"), (int, float)):
            value = min(value, schema["exclusiveMaximum"] - 0.1)
        return value

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
    """Generate deterministic invalid cases for supported schema constraints."""
    tests = _negative_cases_for_object(schema, generate_valid_payload(schema))

    # 3. Empty body, only when the endpoint declares a request body schema.
    if include_empty_body_test:
        tests.append({
            "name": "Empty request body",
            "type": "negative",
            "payload": {},
        })

    return tests


def _negative_cases_for_object(
    schema: dict,
    valid_value: dict,
    path: tuple[str, ...] = (),
    root_value: dict | None = None,
) -> list[dict]:
    if root_value is None:
        root_value = valid_value
    tests = []
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    for field in required_fields:
        invalid_payload = deepcopy(root_value)
        parent = _value_at_path(invalid_payload, path) if path else invalid_payload
        parent.pop(field, None)
        tests.append(_negative_case(f"Missing required field: {'.'.join((*path, field))}", invalid_payload))

    for field, details in properties.items():
        field_path = (*path, field)
        field_name = ".".join(field_path)
        current_value = valid_value.get(field)

        if details.get("type") == "object" or "properties" in details:
            tests.extend(_negative_cases_for_object(details, current_value or {}, field_path, root_value))
            continue

        if details.get("type") == "array":
            tests.extend(_array_constraint_cases(details, current_value or [], field_path, root_value))
            item_schema = details.get("items", {})
            if current_value:
                item_cases = _scalar_constraint_cases(item_schema, current_value[0], field_path, root_value)
                for item_case in item_cases:
                    item_payload = item_case["payload"]
                    invalid_item = _value_at_path(item_payload, field_path)
                    item_payload = deepcopy(root_value)
                    _value_at_path(item_payload, field_path)[0] = invalid_item
                    item_case["payload"] = item_payload
                    item_case["name"] = f"{item_case['name']}.item"
                    tests.append(item_case)
            continue

        tests.extend(_scalar_constraint_cases(details, current_value, field_path, root_value))

    return tests


def _scalar_constraint_cases(schema: dict, value, path: tuple[str, ...], valid_root: dict) -> list[dict]:
    field_name = ".".join(path)
    tests = []

    def add_case(label: str, invalid_value):
        payload = deepcopy(valid_root)
        _set_at_path(payload, path, invalid_value)
        if label in {"below minimum", "above maximum"}:
            name = f"{field_name} {label}"
        else:
            name = f"{label}: {field_name}"
        tests.append(_negative_case(name, payload))

    field_type = schema.get("type")
    if field_type in {"integer", "number"}:
        for keyword, direction, offset in (
            ("minimum", "below minimum", -1),
            ("maximum", "above maximum", 1),
            ("exclusiveMinimum", "at or below exclusive minimum", 0),
            ("exclusiveMaximum", "at or above exclusive maximum", 0),
        ):
            bound = schema.get(keyword)
            if isinstance(bound, (int, float)) and not isinstance(bound, bool):
                invalid_value = bound + offset
                if keyword == "exclusiveMinimum":
                    invalid_value = bound
                elif keyword == "exclusiveMaximum":
                    invalid_value = bound
                add_case(direction, invalid_value)

    if field_type == "string":
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and min_length > 0:
            add_case("Below minimum length", "x" * (min_length - 1))
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and max_length >= 0:
            add_case("Above maximum length", "x" * (max_length + 1))
        if schema.get("format") == "email":
            add_case("Invalid email format", "invalid-email")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list):
        invalid_enum = "__invalid_enum_value__"
        while invalid_enum in enum_values:
            invalid_enum += "_"
        add_case("Invalid enum value", invalid_enum)

    return tests


def _array_constraint_cases(schema: dict, value: list, path: tuple[str, ...], valid_root: dict) -> list[dict]:
    tests = []
    field_name = ".".join(path)
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")

    if isinstance(minimum, int) and minimum > 0:
        payload = deepcopy(valid_root)
        _set_at_path(payload, path, value[: minimum - 1])
        tests.append(_negative_case(f"Below minimum array size: {field_name}", payload))
    if isinstance(maximum, int) and maximum >= 0:
        payload = deepcopy(valid_root)
        item = value[0] if value else _generate_schema_value(schema.get("items", {}))
        expanded = list(value)
        expanded.extend([item] * max(0, maximum - len(expanded)))
        _set_at_path(payload, path, [*expanded[:maximum], item])
        tests.append(_negative_case(f"Above maximum array size: {field_name}", payload))
    return tests


def _negative_case(name: str, payload: dict) -> dict:
    return {"name": name, "type": "negative", "payload": payload}


def _set_at_path(value: dict, path: tuple[str, ...], replacement) -> None:
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = replacement


def _value_at_path(value: dict, path: tuple[str, ...]):
    for part in path:
        value = value[part]
    return value

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
