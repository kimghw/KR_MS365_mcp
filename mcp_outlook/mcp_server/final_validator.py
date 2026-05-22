#!/usr/bin/env python3
"""
Final validation script to ensure tool definitions are consistent
"""

import json
import sys
import re


def validate_tools():
    """Validate that server.py properly uses tool_definitions.py"""

    print("=" * 60)
    print("MCP TOOL VALIDATION REPORT")
    print("=" * 60)

    # 1. Check that server.py imports from tool_definitions
    print("\n1. Checking imports in server.py...")
    with open("server.py", "r") as f:
        server_content = f.read()

    if "from tool_definitions import MCP_TOOLS" in server_content:
        print("   [OK] server.py correctly imports MCP_TOOLS from tool_definitions.py")
    else:
        print("   [FAIL] server.py does NOT import MCP_TOOLS from tool_definitions.py")
        return False

    # 2. Check that server.py doesn't have its own MCP_TOOLS definition
    print("\n2. Checking for duplicate MCP_TOOLS definitions...")
    if re.search(r"^MCP_TOOLS\s*=\s*\[", server_content, re.MULTILINE):
        print("   [FAIL] server.py has its own MCP_TOOLS definition (should use import only)")
        return False
    else:
        print("   [OK] server.py does not have duplicate MCP_TOOLS definition")

    # 3. Load tools from tool_definitions.py
    print("\n3. Loading tools from tool_definitions.py...")
    from tool_definitions import MCP_TOOLS

    print(f"   [OK] Loaded {len(MCP_TOOLS)} tools")

    tool_names = [tool["name"] for tool in MCP_TOOLS]
    print(f"   Tools: {tool_names}")

    # 4. Check that all tools have handlers in server.py
    print("\n4. Checking tool handlers in server.py...")

    # Find all handler patterns
    handler_patterns = [r'if\s+tool_name\s*==\s*["\']([^"\']+)["\']:', r'elif\s+tool_name\s*==\s*["\']([^"\']+)["\']:']

    handlers_found = set()
    for pattern in handler_patterns:
        matches = re.findall(pattern, server_content)
        handlers_found.update(matches)

    print(f"   Found {len(handlers_found)} handlers: {sorted(handlers_found)}")

    # Compare tools and handlers
    tools_set = set(tool_names)
    missing_handlers = tools_set - handlers_found
    extra_handlers = handlers_found - tools_set

    if missing_handlers:
        print(f"   [FAIL] Missing handlers for: {sorted(missing_handlers)}")
    else:
        print("   [OK] All tools have handlers")

    if extra_handlers:
        print(f"   [WARN]  Extra handlers without tools: {sorted(extra_handlers)}")

    # 5. Check that handle_list_tools uses MCP_TOOLS
    print("\n5. Checking handle_list_tools function...")
    if '"tools": MCP_TOOLS' in server_content:
        print("   [OK] handle_list_tools correctly returns MCP_TOOLS")
    else:
        print("   [FAIL] handle_list_tools does not use MCP_TOOLS")
        return False

    # 6. Validate each tool structure
    print("\n6. Validating tool structures...")
    all_valid = True
    for tool in MCP_TOOLS:
        errors = []

        # Check required fields
        if "name" not in tool:
            errors.append("missing 'name' field")
        if "description" not in tool:
            errors.append("missing 'description' field")
        if "inputSchema" not in tool:
            errors.append("missing 'inputSchema' field")

        # Check inputSchema structure
        if "inputSchema" in tool:
            schema = tool["inputSchema"]
            if "type" not in schema or schema["type"] != "object":
                errors.append("inputSchema must have type: 'object'")
            if "properties" not in schema:
                errors.append("inputSchema missing 'properties'")
            if "required" not in schema:
                errors.append("inputSchema missing 'required' array")

        if errors:
            print(f"   [FAIL] {tool.get('name', 'Unknown')}: {', '.join(errors)}")
            all_valid = False

    if all_valid:
        print("   [OK] All tools have valid structure")

    # Final summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    # Check for problematic strings that might be rejected by AI providers
    print("\n7. Checking for potentially problematic content...")
    problematic_keywords = [
        "hack",
        "exploit",
        "injection",
        "malware",
        "virus",
        "trojan",
        "phishing",
        "spam",
        "steal",
        "breach",
        "crack",
        "bypass",
    ]

    issues_found = False
    for tool in MCP_TOOLS:
        tool_str = json.dumps(tool).lower()
        for keyword in problematic_keywords:
            if keyword in tool_str:
                print(f"   [WARN]  Tool '{tool['name']}' contains keyword: '{keyword}'")
                issues_found = True

    if not issues_found:
        print("   [OK] No problematic keywords found")

    # Final result
    print("\n" + "=" * 60)
    if all_valid and not missing_handlers and not issues_found:
        print("[OK] VALIDATION PASSED: All checks successful!")
        print("   - Tools properly imported from tool_definitions.py")
        print("   - No duplicate definitions")
        print("   - All tools have handlers")
        print("   - All tools have valid structure")
        print("   - No problematic content detected")
        return True
    else:
        print("[FAIL] VALIDATION FAILED: Issues detected")
        return False


if __name__ == "__main__":
    try:
        result = validate_tools()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n[FAIL] Error during validation: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
