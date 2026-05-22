#!/bin/bash

# MCP Tool Editor Web Interface Launcher

echo "======================================"
echo "MCP Tool Definitions Editor"
echo "======================================"
echo ""

# Navigate to the script directory
cd "$(dirname "$0")"

# Use the mcp_server's venv
MCP_SERVER_VENV="../mcp_outlook/mcp_server/venv"

# Check if virtual environment exists
if [ ! -d "$MCP_SERVER_VENV" ]; then
    echo "Error: MCP server virtual environment not found at $MCP_SERVER_VENV"
    echo "Please create it first in the mcp_server directory"
    exit 1
else
    source $MCP_SERVER_VENV/bin/activate
fi

# Create backups directory if it doesn't exist
mkdir -p backups

# Generate editor_config.json and server mappings from @mcp_service decorators
echo "Generating editor_config.json from @mcp_service decorators..."
python ../jinja/generate_editor_config.py
echo ""

echo "Generating server mappings from @mcp_service decorators..."
python ../jinja/generate_server_mappings.py
echo ""

echo "Starting web server..."
echo "Access the editor at: http://localhost:8080"
echo "Press Ctrl+C to stop the server"
echo ""

# Run the Flask app
python tool_editor_web.py