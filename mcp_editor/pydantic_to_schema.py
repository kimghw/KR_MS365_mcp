"""
Utility to convert Pydantic BaseModel classes to JSON Schema for MCP Tool Definitions
"""

import json
import sys
import os
from typing import Dict, Any, Type, List
from pydantic import BaseModel
import importlib.util

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pydantic_to_mcp_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """
    Convert a Pydantic BaseModel to MCP tool definition schema format.

    Args:
        model_class: Pydantic BaseModel class

    Returns:
        Dictionary containing the JSON schema for MCP tool definition
    """
    # Get JSON schema from Pydantic
    schema = model_class.model_json_schema(mode="validation")

    # Convert to MCP format
    mcp_schema = {"type": "object", "properties": {}, "required": []}

    # Process properties
    if "properties" in schema:
        for prop_name, prop_def in schema["properties"].items():
            mcp_prop = {}

            # Handle type
            if "type" in prop_def:
                mcp_prop["type"] = prop_def["type"]
            elif "anyOf" in prop_def:
                # Handle Optional types
                types = [t.get("type") for t in prop_def["anyOf"] if t.get("type") != "null"]
                if types:
                    mcp_prop["type"] = types[0] if len(types) == 1 else "string"

            # Handle description
            if "description" in prop_def:
                mcp_prop["description"] = prop_def["description"]
            elif "title" in prop_def:
                mcp_prop["description"] = prop_def["title"]

            # Handle enum values
            if "enum" in prop_def:
                mcp_prop["enum"] = prop_def["enum"]

            # Handle array items
            if mcp_prop.get("type") == "array" and "items" in prop_def:
                if isinstance(prop_def["items"], dict):
                    mcp_prop["items"] = {"type": prop_def["items"].get("type", "string")}

            # Handle nested objects
            if mcp_prop.get("type") == "object" and "properties" in prop_def:
                nested_props = {}
                nested_required = []

                for nested_name, nested_def in prop_def["properties"].items():
                    nested_prop = {}
                    if "type" in nested_def:
                        nested_prop["type"] = nested_def["type"]
                    if "description" in nested_def:
                        nested_prop["description"] = nested_def["description"]
                    nested_props[nested_name] = nested_prop

                    if nested_def.get("required", False):
                        nested_required.append(nested_name)

                mcp_prop["properties"] = nested_props
                if nested_required:
                    mcp_prop["required"] = nested_required

            mcp_schema["properties"][prop_name] = mcp_prop

    # Process required fields
    if "required" in schema:
        mcp_schema["required"] = schema["required"]

    return mcp_schema


def _resolve_path(path: str) -> str:
    """Resolve a path relative to the editor directory"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def _get_config_path() -> str:
    """
    Determine config path with override support.
    Priority:
    1) MCP_EDITOR_CONFIG env (absolute or relative)
    2) editor_config.<module>.json if MCP_EDITOR_MODULE is set and exists
    3) editor_config.json (default)
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.environ.get("MCP_EDITOR_CONFIG")
    if env_path:
        return _resolve_path(env_path)

    module_name = os.environ.get("MCP_EDITOR_MODULE")
    if module_name:
        candidate = os.path.join(base_dir, f"editor_config.{module_name}.json")
        if os.path.exists(candidate):
            return candidate

    return os.path.join(base_dir, "editor_config.json")


def _load_graph_type_modules(graph_type_paths: List[str] | None = None) -> List[Any]:
    """Load outlook_types modules from configured paths"""
    if graph_type_paths is None:
        config_path = _get_config_path()

        # Default path if config missing
        graph_type_paths = ["../mcp_outlook/outlook_types.py"]
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # Multi-profile
                        if isinstance(data.get("_default"), dict) or any(isinstance(v, dict) for v in data.values()):
                            profile = data.get("_default", {})
                            # Support both new types_files and legacy graph_types_files
                            if isinstance(profile, dict):
                                if isinstance(profile.get("types_files"), list):
                                    graph_type_paths = profile["types_files"]
                                elif isinstance(profile.get("graph_types_files"), list):
                                    graph_type_paths = profile["graph_types_files"]
                        # Legacy single profile
                        elif isinstance(data.get("types_files"), list):
                            graph_type_paths = data["types_files"]
                        elif isinstance(data.get("graph_types_files"), list):
                            graph_type_paths = data["graph_types_files"]
        except Exception as e:
            print(f"Warning: could not load graph type config: {e}")

    modules = []
    for path in graph_type_paths:
        resolved = _resolve_path(path)
        if not os.path.exists(resolved):
            print(f"Warning: outlook_types file not found: {resolved}")
            continue
        spec = importlib.util.spec_from_file_location("outlook_types", resolved)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def load_graph_types_models(graph_type_paths: List[str] | None = None):
    """Load and merge BaseModel classes from configured outlook_types files"""
    models = {}
    modules = _load_graph_type_modules(graph_type_paths)
    for module in modules:
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj != BaseModel:
                models[name] = obj
    return models


def generate_mcp_schemas_from_graph_types(graph_type_paths: List[str] | None = None):
    """Generate MCP schemas for all BaseModel classes in outlook_types.py"""
    models = load_graph_types_models(graph_type_paths)
    schemas = {}

    for name, model in models.items():
        schemas[name] = pydantic_to_mcp_schema(model)

    return schemas


def update_tool_with_basemodel_schema(
    tool_def: Dict[str, Any], model_name: str, prop_name: str, graph_type_paths: List[str] | None = None
):
    """
    Update a specific property in a tool definition with a BaseModel schema.

    Args:
        tool_def: The tool definition dictionary
        model_name: Name of the BaseModel class (e.g., 'FilterParams')
        prop_name: Name of the property to update (e.g., 'filter')

    Returns:
        Updated tool definition
    """
    models = load_graph_types_models(graph_type_paths)

    if model_name in models:
        schema = pydantic_to_mcp_schema(models[model_name])

        # Update the specific property with the schema
        if "inputSchema" in tool_def and "properties" in tool_def["inputSchema"]:
            if prop_name in tool_def["inputSchema"]["properties"]:
                # Preserve existing description if any
                existing_desc = tool_def["inputSchema"]["properties"][prop_name].get("description")

                # Update with BaseModel schema
                tool_def["inputSchema"]["properties"][prop_name] = {
                    "type": "object",
                    "description": existing_desc or f"{model_name} parameters",
                    "properties": schema["properties"],
                    "required": schema.get("required", []),
                }

    return tool_def


# Example usage for updating query_emails tool
def update_query_emails_tool():
    """Update query_emails tool with BaseModel schemas"""
    from tool_definitions import MCP_TOOLS

    # Find query_emails tool
    for tool in MCP_TOOLS:
        if tool["name"] == "query_emails":
            # Update filter property with FilterParams schema
            tool = update_tool_with_basemodel_schema(tool, "FilterParams", "filter")
            # Update exclude property with ExcludeParams schema
            tool = update_tool_with_basemodel_schema(tool, "ExcludeParams", "exclude")
            # Update select property with SelectParams schema
            tool = update_tool_with_basemodel_schema(tool, "SelectParams", "select")

            return tool

    return None


if __name__ == "__main__":
    # Generate all schemas
    schemas = generate_mcp_schemas_from_graph_types()

    print("Available BaseModel schemas from outlook_types.py:")
    print("=" * 50)

    for name, schema in schemas.items():
        print(f"\n{name}:")
        print(json.dumps(schema, indent=2))

    print("\n" + "=" * 50)
    print("\nExample: Updating query_emails tool with BaseModel schemas...")

    updated_tool = update_query_emails_tool()
    if updated_tool:
        print("\nUpdated query_emails tool definition:")
        print(json.dumps(updated_tool, indent=2))
