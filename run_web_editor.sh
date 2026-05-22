#!/bin/bash

# MCP Web Editor Launcher Script
# Usage: ./run_web_editor.sh [profile_name]

echo "========================================="
echo "  MCP Tool Editor Web Interface"
echo "========================================="
echo ""

# Set profile if provided as argument
if [ ! -z "$1" ]; then
    export MCP_EDITOR_MODULE="$1"
    echo "Using profile: $1"
else
    echo "Using default profile"
fi

# Navigate to project root (script directory)
cd "$(dirname "$0")"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Please install Python 3."
    exit 1
fi

# Check if tool_editor_web.py exists
if [ ! -f "mcp_editor/tool_editor_web.py" ]; then
    echo "Error: mcp_editor/tool_editor_web.py not found."
    exit 1
fi

echo ""
echo "Starting web editor..."
echo "Press Ctrl+C to stop"
echo ""

# Run the web editor
python3 mcp_editor/tool_editor_web.py
