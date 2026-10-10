from copy import deepcopy

from app.models.test_case import TestCase


def generate_valid_payload(schema: dict):
    """
    Generate a representative request body, including nested objects and arrays.
    """
    return _generate_object_payload(schema)


def _generate_object_payload(schema: dict) -> dict:
    schema = _effective_schema(schema)
    payload = {}
    for field, details in schema.get("properties", {}).items():
        payload[field] = _generate_schema_value(details)
    return payload


def _generate_schema_value(schema: dict):
    schema = _effective_schema(schema)
    if "default" in schema:
        return schema["default"]

    if "enum" in schema:
        enum_values = schema["enum"]
        return enum_values[0] if enum_values else None

    field_type = schema.get("type")
    if isinstance(field_type, list):
        non_null_types = [item for item in field_type if item != "null"]
        if not non_null_types and "null" in field_type:
            return None
        field_type = non_null_types[0] if non_null_types else None
        schema["type"] = field_type
    elif schema.get("nullable") is True and field_type not in {"object", "array"}:
        return None

    if field_type == "string":
        value = _valid_string_example(schema.get("format"))
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
        elif isinstance(schema.get("exclusiveMinimum"), (int, float)) and not isinstance(schema.get("exclusiveMinimum"), bool):
            value = int(schema["exclusiveMinimum"]) + 1
        else:
            value = 0
        if schema.get("exclusiveMinimum") is True and "minimum" in schema:
            value = max(value, int(schema["minimum"]) + 1)
        if isinstance(schema.get("maximum"), (int, float)):
            value = min(value, int(schema["maximum"]))
        if schema.get("exclusiveMaximum") is True and "maximum" in schema:
            value = min(value, int(schema["maximum"]) - 1)
        if isinstance(schema.get("exclusiveMaximum"), (int, float)) and not isinstance(schema.get("exclusiveMaximum"), bool):
            value = min(value, int(schema["exclusiveMaximum"]) - 1)
        return value

    if field_type == "number":
        value = schema.get("minimum", 0.0)
        if isinstance(schema.get("exclusiveMinimum"), (int, float)) and not isinstance(schema.get("exclusiveMinimum"), bool):
            value = max(value, schema["exclusiveMinimum"] + 0.1)
        elif schema.get("exclusiveMinimum") is True and isinstance(schema.get("minimum"), (int, float)):
            value = max(value, schema["minimum"] + 0.1)
        if isinstance(schema.get("maximum"), (int, float)):
            value = min(value, schema["maximum"])
        if isinstance(schema.get("exclusiveMaximum"), (int, float)) and not isinstance(schema.get("exclusiveMaximum"), bool):
            value = min(value, schema["exclusiveMaximum"] - 0.1)
        elif schema.get("exclusiveMaximum") is True and isinstance(schema.get("maximum"), (int, float)):
            value = min(value, schema["maximum"] - 0.1)
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
    schema = _effective_schema(schema)
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
    schema = _effective_schema(schema)
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
        if schema.get("exclusiveMinimum") is True and isinstance(schema.get("minimum"), (int, float)):
            add_case("At exclusive minimum", schema["minimum"])
        if schema.get("exclusiveMaximum") is True and isinstance(schema.get("maximum"), (int, float)):
            add_case("At exclusive maximum", schema["maximum"])

    if field_type == "string":
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and min_length > 0:
            add_case("Below minimum length", "x" * (min_length - 1))
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and max_length >= 0:
            add_case("Above maximum length", "x" * (max_length + 1))
        format_name = schema.get("format")
        if format_name in _INVALID_FORMAT_EXAMPLES:
            add_case(f"Invalid {format_name} format", _INVALID_FORMAT_EXAMPLES[format_name])

    enum_values = schema.get("enum")
    if isinstance(enum_values, list):
        invalid_enum = "__invalid_enum_value__"
        while invalid_enum in enum_values:
            invalid_enum += "_"
        add_case("Invalid enum value", invalid_enum)

    schema_types = schema.get("type")
    allows_null = schema.get("nullable") is True or (
        isinstance(schema_types, list) and "null" in schema_types
    ) or (isinstance(enum_values, list) and None in enum_values)
    if schema_types is not None and not allows_null:
        add_case("Null value for non-nullable field", None)

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


_STRING_EXAMPLES = {
    "email": "john@example.com",
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "date": "2030-01-02",
    "date-time": "2030-01-02T03:04:05Z",
    "uri": "https://example.com/resource",
    "ipv4": "192.0.2.1",
}

_INVALID_FORMAT_EXAMPLES = {
    "email": "invalid-email",
    "uuid": "not-a-uuid",
    "date": "not-a-date",
    "date-time": "not-a-date-time",
    "uri": "not a uri",
    "ipv4": "999.999.999.999",
}


def _valid_string_example(format_name: str | None) -> str:
    return _STRING_EXAMPLES.get(format_name, "sample")


def _effective_schema(schema: dict) -> dict:
    """Flatten common schema compositions deterministically for test samples."""
    if not isinstance(schema, dict):
        return {}
    effective = {key: value for key, value in schema.items() if key not in {"allOf", "oneOf", "anyOf"}}

    for branch in schema.get("allOf", []):
        if not isinstance(branch, dict):
            continue
        branch = _effective_schema(branch)
        for key, value in branch.items():
            if key == "properties" and isinstance(value, dict):
                properties = dict(effective.get("properties", {}))
                for name, property_schema in value.items():
                    existing = properties.get(name, {})
                    properties[name] = _merge_schema_pair(existing, property_schema) if isinstance(existing, dict) and isinstance(property_schema, dict) else property_schema
                effective["properties"] = properties
            elif key == "required" and isinstance(value, list):
                effective[key] = list(dict.fromkeys([*effective.get(key, []), *value]))
            elif key in {"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"} and isinstance(value, (int, float)):
                effective[key] = max(effective.get(key, value), value)
            elif key in {"maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"} and isinstance(value, (int, float)):
                effective[key] = min(effective.get(key, value), value)
            elif key == "enum" and isinstance(value, list) and isinstance(effective.get(key), list):
                effective[key] = [item for item in effective[key] if item in value]
            else:
                effective.setdefault(key, value)

    alternatives = schema.get("oneOf") or schema.get("anyOf")
    if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], dict):
        branch = _effective_schema(alternatives[0])
        effective = {**effective, **branch}
        if isinstance(schema.get("properties"), dict) and isinstance(branch.get("properties"), dict):
            effective["properties"] = {**schema["properties"], **branch["properties"]}
        if isinstance(schema.get("required"), list) and isinstance(branch.get("required"), list):
            effective["required"] = list(dict.fromkeys([*schema["required"], *branch["required"]]))

    return effective


def _merge_schema_pair(left: dict, right: dict) -> dict:
    merged = {**left, **right}
    for key in {"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"}:
        if key in left and key in right:
            merged[key] = max(left[key], right[key])
    for key in {"maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"}:
        if key in left and key in right:
            merged[key] = min(left[key], right[key])
    if isinstance(left.get("required"), list) and isinstance(right.get("required"), list):
        merged["required"] = list(dict.fromkeys([*left["required"], *right["required"]]))
    if isinstance(left.get("enum"), list) and isinstance(right.get("enum"), list):
        merged["enum"] = [value for value in left["enum"] if value in right["enum"]]
    return merged

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
        schema = _effective_schema(parameter.get("schema", {}))
        value = _generate_schema_value(schema)
        if "default" not in schema and "minimum" not in schema and "exclusiveMinimum" not in schema:
            if schema.get("type") in {"integer", "number"}:
                value = 1
        if schema.get("type") == "string" and not any(key in schema for key in ("default", "enum", "format")):
            value = "test-value"
            if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
                value += "x" * (schema["minLength"] - len(value))
            if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
                value = value[:schema["maxLength"]]

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


def generate_parameter_negative_tests(parameters: list) -> list[dict]:
    """Generate isolated missing/invalid cases for query and header parameters."""
    values = generate_parameter_values(parameters)
    tests = []
    for parameter in parameters:
        name = parameter.get("name")
        location = parameter.get("location")
        if not name or location not in {"query", "header"}:
            continue
        target = "headers" if location == "header" else "query"
        value = values[target].get(name)
        schema = _effective_schema(parameter.get("schema", {}))

        if parameter.get("required") is True and not (location == "header" and name.lower() == "authorization"):
            tests.append({
                "name": f"Missing required parameter: {name}",
                "location": location,
                "parameter": name,
                "value": None,
                "missing": True,
                "exclude_request_default": True,
            })

        if schema.get("type") == "array" and isinstance(value, list):
            minimum = schema.get("minItems")
            maximum = schema.get("maxItems")
            if isinstance(minimum, int) and minimum > 0:
                tests.append({
                    "name": f"Below minimum array size: {name}",
                    "location": location,
                    "parameter": name,
                    "value": [],
                    "exclude_request_default": True,
                })
            if isinstance(maximum, int) and maximum >= 0:
                item = value[0] if value else _generate_schema_value(schema.get("items", {}))
                tests.append({
                    "name": f"Above maximum array size: {name}",
                    "location": location,
                    "parameter": name,
                    "value": [*value[:maximum], item],
                    "exclude_request_default": True,
                })
            continue

        for case in _scalar_constraint_cases(schema, value, (name,), {name: value}):
            tests.append({
                "name": case["name"],
                "location": location,
                "parameter": name,
                "value": case["payload"][name],
                "exclude_request_default": True,
            })
    return tests


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
    _add_security_placeholders(endpoint, parameter_values)
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

    for parameter_test in generate_parameter_negative_tests(endpoint.get("parameters", [])):
        path_params = dict(parameter_values["path"])
        query_params = dict(parameter_values["query"])
        headers = dict(parameter_values["headers"])
        target = headers if parameter_test["location"] == "header" else query_params
        if parameter_test.get("missing"):
            target.pop(parameter_test["parameter"], None)
        else:
            target[parameter_test["parameter"]] = parameter_test["value"]
        test_cases.append(TestCase(
            name=parameter_test["name"],
            method=endpoint["method"],
            path=endpoint["path"],
            type="negative",
            path_params=path_params,
            query_params=query_params,
            headers=headers,
            body=valid_payload if has_request_body_schema else None,
            expected_status=_documented_validation_error_statuses(endpoint),
            request_header_exclusions={parameter_test["parameter"]} if parameter_test["location"] == "header" else set(),
            request_query_exclusions={parameter_test["parameter"]} if parameter_test["location"] == "query" else set(),
        ))

    authentication_case = _missing_authentication_case(
        endpoint,
        parameter_values,
        body=valid_payload if has_request_body_schema else None,
    )
    if authentication_case is not None:
        test_cases.append(authentication_case)

    return test_cases


def _add_security_placeholders(endpoint: dict, values: dict) -> None:
    requirements = endpoint.get("security_requirements", [])
    if not requirements or any(not requirement for requirement in requirements):
        return
    schemes = endpoint.get("security_schemes", {})
    for requirement in requirements:
        for scheme_name in requirement:
            scheme = schemes.get(scheme_name, {})
            scheme_type = scheme.get("type")
            if scheme_type == "apiKey":
                location = scheme.get("in")
                name = scheme.get("name")
                if not name:
                    continue
                if location == "header":
                    values["headers"].setdefault(name, "test-api-key")
                elif location == "query":
                    values["query"].setdefault(name, "test-api-key")
                elif location == "cookie":
                    existing = values["headers"].get("Cookie", "")
                    values["headers"]["Cookie"] = "; ".join(part for part in (existing, f"{name}=test-api-key") if part)
            elif scheme_type == "http":
                scheme_name = str(scheme.get("scheme", "")).lower()
                if scheme_name == "basic":
                    values["headers"].setdefault("Authorization", "Basic dGVzdDp0ZXN0")
                elif scheme_name == "bearer":
                    values["headers"].setdefault("Authorization", "Bearer test-token")
            elif scheme_type in {"oauth2", "openIdConnect"}:
                values["headers"].setdefault("Authorization", "Bearer test-token")


def _missing_authentication_case(endpoint: dict, values: dict, body) -> TestCase | None:
    requirements = endpoint.get("security_requirements", [])
    if not requirements or any(not requirement for requirement in requirements):
        return None

    schemes = endpoint.get("security_schemes", {})
    headers_to_remove = set()
    query_to_remove = set()
    supported = False
    for requirement in requirements:
        for scheme_name in requirement:
            scheme = schemes.get(scheme_name, {})
            scheme_type = scheme.get("type")
            if scheme_type in {"http", "oauth2", "openIdConnect"}:
                headers_to_remove.add("authorization")
                supported = True
            elif scheme_type == "apiKey":
                location = scheme.get("in")
                name = scheme.get("name")
                if location == "header" and name:
                    headers_to_remove.add(name.lower())
                    supported = True
                elif location == "query" and name:
                    query_to_remove.add(name)
                    supported = True
                elif location == "cookie" and name:
                    headers_to_remove.add("cookie")
                    supported = True
    if not supported:
        return None

    headers = {
        name: value for name, value in values["headers"].items()
        if name.lower() not in headers_to_remove
    }
    query_params = {
        name: value for name, value in values["query"].items()
        if name not in query_to_remove
    }
    expected = _documented_auth_error_statuses(endpoint)
    return TestCase(
        name=f"Missing authentication: {endpoint['method']} {endpoint['path']}",
        method=endpoint["method"],
        path=endpoint["path"],
        type="negative",
        path_params=values["path"],
        query_params=query_params,
        headers=headers,
        body=body,
        expected_status=expected,
        request_header_exclusions=headers_to_remove,
        request_query_exclusions=query_to_remove,
    )


def _documented_success_statuses(endpoint: dict) -> list[int] | None:
    """Return documented numeric 2xx response codes for a positive case."""
    statuses = [status for status in _documented_status_codes(endpoint) if 200 <= status < 300]
    return statuses or None


def _documented_validation_error_statuses(endpoint: dict) -> list[int] | None:
    """Return documented 400/422 statuses for schema-validation failures."""
    documented_statuses = _documented_status_codes(endpoint)
    expected_statuses = [status for status in (400, 422) if status in documented_statuses]
    return expected_statuses or None


def _documented_auth_error_statuses(endpoint: dict) -> list[int] | None:
    statuses = _documented_status_codes(endpoint)
    expected_statuses = [status for status in (401, 403) if status in statuses]
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
