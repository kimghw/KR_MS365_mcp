"""
MCP Service Decorator with parameter capture
"""

import inspect
from typing import Any, Callable, Dict, List, Optional, get_type_hints
from functools import wraps

# Global registry for MCP services
MCP_SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {}


def mcp_service(
    tool_name: Optional[str] = None,
    description: Optional[str] = None,
    server_name: Optional[str] = None,
    service_name: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    priority: Optional[int] = None,
    related_objects: Optional[List[str]] = None,
    service_signature: Optional[List[Dict[str, Any]]] = None,
    include_in_registry: bool = True,
):
    """
    Decorator for MCP service functions that captures function signature

    Args:
        tool_name: Optional tool name (defaults to function name)
        description: Optional description of the service
        server_name: Server/module name (e.g., 'outlook', 'attachment')
        service_name: Service function name (e.g., 'query_search')
        category: Category classification
        tags: List of tags for the service
        priority: Priority level (integer)
        related_objects: List of related object paths
        service_signature: Optional manual service signature definition (list of param dicts)
        include_in_registry: Whether to include in global registry
    """

    def decorator(func: Callable) -> Callable:
        # Get function signature
        sig = inspect.signature(func)
        params = sig.parameters

        # Get type hints
        try:
            type_hints = get_type_hints(func)
        except Exception:
            type_hints = {}

        # Extract parameter information
        param_info = []
        required_params = []

        for param_name, param in params.items():
            # Skip 'self' and 'cls' parameters
            if param_name in ("self", "cls"):
                continue

            param_data = {"name": param_name, "type": None, "default": None, "required": True}

            # Get type annotation
            if param_name in type_hints:
                type_annotation = type_hints[param_name]
                param_data["type"] = str(type_annotation).replace("typing.", "")

                # Check if Optional
                if (
                    "Optional" in str(type_annotation)
                    or "Union" in str(type_annotation)
                    and type(None) in type_annotation.__args__
                ):
                    param_data["required"] = False

            # Get default value
            if param.default != inspect.Parameter.empty:
                param_data["default"] = param.default
                param_data["required"] = False

            param_info.append(param_data)

            if param_data["required"]:
                required_params.append(param_name)

        # Create service metadata
        final_service_name = tool_name or func.__name__

        # Use service_signature if provided, otherwise use auto-detected param_info
        final_parameters = service_signature if service_signature else param_info

        service_metadata = {
            "name": final_service_name,
            "function": func.__name__,
            "module": func.__module__,
            "description": description or func.__doc__ or f"{final_service_name} MCP service",
            "server_name": server_name,
            "service_name": service_name or func.__name__,
            "category": category,
            "tags": tags or [],
            "priority": priority,
            "related_objects": related_objects or [],
            "is_async": inspect.iscoroutinefunction(func),
            "parameters": final_parameters,
            "required_parameters": required_params,
            "return_type": str(type_hints.get("return", "Any")).replace("typing.", ""),
            "signature": str(sig),
        }

        # Add to registry if requested
        if include_in_registry:
            MCP_SERVICE_REGISTRY[final_service_name] = service_metadata

        # Attach metadata to function
        func._mcp_service_metadata = service_metadata

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Return appropriate wrapper
        if inspect.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # Attach metadata to wrapper
        wrapper._mcp_service_metadata = service_metadata

        return wrapper

    return decorator


def get_mcp_service_info(func_or_name: Any) -> Optional[Dict[str, Any]]:
    """
    Get MCP service metadata from a function or by name

    Args:
        func_or_name: Function object or service name string

    Returns:
        Service metadata dictionary or None
    """
    if isinstance(func_or_name, str):
        return MCP_SERVICE_REGISTRY.get(func_or_name)
    elif hasattr(func_or_name, "_mcp_service_metadata"):
        return func_or_name._mcp_service_metadata
    return None


def list_mcp_services() -> List[Dict[str, Any]]:
    """
    List all registered MCP services

    Returns:
        List of service metadata dictionaries
    """
    return list(MCP_SERVICE_REGISTRY.values())


def generate_inputschema_from_service(service_name: str) -> Dict[str, Any]:
    """
    Generate JSON Schema inputSchema from MCP service metadata

    Args:
        service_name: Name of the MCP service

    Returns:
        JSON Schema compatible inputSchema
    """
    service_info = MCP_SERVICE_REGISTRY.get(service_name)
    if not service_info:
        return {"type": "object", "properties": {}, "required": []}

    properties = {}

    # Type mapping
    type_mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "dict": "object",
        "Dict": "object",
        "list": "array",
        "List": "array",
        "Any": "string",
    }

    for param in service_info["parameters"]:
        param_name = param["name"]
        param_type = param.get("type", "Any")

        # Basic type conversion
        json_type = "string"  # default

        for py_type, js_type in type_mapping.items():
            if py_type in param_type:
                json_type = js_type
                break

        # Handle Optional types
        if "Optional" in param_type or not param["required"]:
            properties[param_name] = {"type": [json_type, "null"], "description": f"{param_name} parameter"}
        else:
            properties[param_name] = {"type": json_type, "description": f"{param_name} parameter"}

        # Add default value if present
        if param["default"] is not None:
            properties[param_name]["default"] = param["default"]

    return {"type": "object", "properties": properties, "required": service_info["required_parameters"]}


# Example usage
if __name__ == "__main__":
    # Example removed - use actual service functions instead
    pass
