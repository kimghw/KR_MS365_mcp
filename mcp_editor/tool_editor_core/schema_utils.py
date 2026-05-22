"""
Schema Processing Utilities

JSON 스키마 처리 함수들:
- 스키마 필드 정렬
- 기본값 제거
- 개행 문자 정리
- targetParam 추가
- 파라미터 변환 (dict <-> list)
"""


def order_schema_fields(schema):
    """Recursively order schema fields according to JSON Schema standard"""
    if not isinstance(schema, dict):
        return schema

    ordered = {}

    # Add type first
    if "type" in schema:
        ordered["type"] = schema["type"]

    # Add description second
    if "description" in schema:
        ordered["description"] = schema["description"]

    # Add enum if present
    if "enum" in schema:
        ordered["enum"] = schema["enum"]

    # Add format if present
    if "format" in schema:
        ordered["format"] = schema["format"]

    # Process properties recursively
    if "properties" in schema:
        ordered_props = {}
        for prop_name, prop_value in schema["properties"].items():
            ordered_props[prop_name] = order_schema_fields(prop_value)
        ordered["properties"] = ordered_props

    # Add items for arrays
    if "items" in schema:
        ordered["items"] = order_schema_fields(schema["items"])

    # Add required
    if "required" in schema:
        ordered["required"] = schema["required"]

    # Add any other fields
    for k, v in schema.items():
        if k not in ["type", "description", "enum", "format", "properties", "items", "required"]:
            ordered[k] = v

    return ordered


def remove_defaults(schema):
    """Recursively remove 'default' keys from schema"""
    if isinstance(schema, dict):
        schema = {k: remove_defaults(v) for k, v in schema.items() if k != "default"}
        # Handle properties
        if "properties" in schema and isinstance(schema["properties"], dict):
            schema["properties"] = {k: remove_defaults(v) for k, v in schema["properties"].items()}
        # Handle items
        if "items" in schema:
            schema["items"] = remove_defaults(schema["items"])
    elif isinstance(schema, list):
        schema = [remove_defaults(item) for item in schema]
    return schema


def clean_newlines_from_schema(schema):
    """Recursively remove newline characters from all description fields in schema,
    and also remove internal _source metadata fields"""
    if isinstance(schema, dict):
        cleaned = {}
        for key, value in schema.items():
            # Skip internal metadata fields
            if key == "_source":
                continue
            if key == "description" and isinstance(value, str):
                # Remove newline and carriage return characters
                cleaned_value = value.replace("\n", " ").replace("\r", " ")
                # Remove multiple spaces that might result from the replacement
                cleaned[key] = " ".join(cleaned_value.split())
            else:
                cleaned[key] = clean_newlines_from_schema(value)
        return cleaned
    elif isinstance(schema, list):
        return [clean_newlines_from_schema(item) for item in schema]
    else:
        return schema


def ensure_target_params(schema):
    """Ensure all properties have targetParam field.

    Every inputSchema property should have a targetParam that specifies which
    mcp_service parameter it maps to. If not specified, defaults to property name.

    Example:
        'user_email': {'type': 'string', 'description': '...'}
        -> 'user_email': {'type': 'string', 'description': '...', 'targetParam': 'user_email'}
    """
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            # Process properties
            processed_props = {}
            for prop_name, prop_def in value.items():
                if isinstance(prop_def, dict):
                    # Add targetParam if not present (defaults to property name)
                    if "targetParam" not in prop_def:
                        prop_def = dict(prop_def)
                        prop_def["targetParam"] = prop_name
                    # Recursively process nested properties
                    processed_props[prop_name] = ensure_target_params(prop_def)
                else:
                    processed_props[prop_name] = prop_def
            result[key] = processed_props
        elif isinstance(value, dict):
            result[key] = ensure_target_params(value)
        elif isinstance(value, list):
            result[key] = [ensure_target_params(item) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value

    return result


def convert_params_dict_to_list(params_dict: dict) -> list:
    """Convert parameters from dict format to unified list format.

    Input (dict format - used in mcp_service_factors):
        {'subject': {'default': True, 'description': '메시지 제목', 'type': 'boolean'}}

    Output (list format - unified structure):
        [{'name': 'subject', 'type': 'boolean', 'is_optional': False, 'default': True, 'description': '메시지 제목'}]
    """
    if not params_dict:
        return []

    params_list = []
    for param_name, param_info in params_dict.items():
        param_type = param_info.get("type", "string")
        has_default = "default" in param_info
        default_val = param_info.get("default")

        # is_optional: True if has default value or type is explicitly optional
        is_optional = has_default or param_type.lower() in ("optional", "null")

        param_entry = {
            "name": param_name,
            "type": param_type,
            "is_optional": is_optional,
            "default": default_val,
            "has_default": has_default,
            "description": param_info.get("description", ""),
        }
        # Preserve class_name if available (for custom class types)
        if param_info.get("class_name"):
            param_entry["class_name"] = param_info["class_name"]
        params_list.append(param_entry)

    return params_list


def convert_params_list_to_dict(params_list: list) -> dict:
    """Convert parameters from list format to dict format (reverse conversion).

    Input (list format):
        [{'name': 'subject', 'type': 'boolean', 'is_optional': False, 'default': True, 'description': '메시지 제목'}]

    Output (dict format):
        {'subject': {'default': True, 'description': '메시지 제목', 'type': 'boolean'}}
    """
    if not params_list:
        return {}

    params_dict = {}
    for param in params_list:
        name = param.get("name")
        if not name:
            continue

        param_dict = {"type": param.get("type", "string")}
        # Preserve class_name if available (for custom class types)
        if param.get("class_name"):
            param_dict["class_name"] = param["class_name"]
        # Only add default if has_default is True
        if param.get("has_default", False):
            param_dict["default"] = param.get("default")
        if param.get("description"):
            param_dict["description"] = param["description"]

        params_dict[name] = param_dict

    return params_dict


def is_all_none_defaults(factor_data):
    """Check if all parameter defaults are None (making the factor useless).

    When all defaults in mcp_service_factors are None, the factor has no effect
    on parameter merging and should be removed.

    Exception: 'internal' source factors are always useful because they indicate
    the parameter should be hidden from LLM, regardless of default values.

    Handles both list format (new) and dict format (legacy) for parameters.
    """
    if not isinstance(factor_data, dict):
        return False

    # Internal source factors are always useful - they indicate the parameter
    # should be hidden from LLM, even without specific default values
    if factor_data.get("source") == "internal":
        return False

    parameters = factor_data.get("parameters", [])
    if not parameters:
        return True  # No parameters = effectively all None

    # Handle list format (new unified structure)
    if isinstance(parameters, list):
        for param in parameters:
            if isinstance(param, dict):
                default_value = param.get("default")
                # If any default is not None, the factor is useful
                if default_value is not None:
                    return False
    # Handle dict format (legacy structure)
    elif isinstance(parameters, dict):
        for param_name, param_def in parameters.items():
            if isinstance(param_def, dict):
                default_value = param_def.get("default")
                # If any default is not None, the factor is useful
                if default_value is not None:
                    return False

    return True  # All defaults are None


def prune_internal_properties(tools_data: list, internal_args: dict):
    """Remove inputSchema properties that are marked as internal args.

    This keeps tool_definition_templates/tool_definitions in sync even if
    internal_args were added/edited outside the UI toggle flow.
    """
    if not internal_args:
        return tools_data

    for tool in tools_data:
        name = tool.get("name")
        internal_props = internal_args.get(name)
        if not internal_props:
            continue

        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            continue

        props = schema.get("properties")
        if not isinstance(props, dict):
            continue

        for prop_name in list(internal_props.keys()):
            if prop_name in props:
                del props[prop_name]
            if isinstance(schema.get("required"), list):
                schema["required"] = [r for r in schema["required"] if r != prop_name]

    return tools_data
