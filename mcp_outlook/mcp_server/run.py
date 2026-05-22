#!/usr/bin/env python
"""
MCP Server Launcher
Starts the FastAPI MCP server for Outlook Graph Mail
Initializes SessionManager if available
"""
import uvicorn
import sys
import os
import logging

# Add paths for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

sys.path.insert(0, current_dir)  # For server module
sys.path.insert(0, parent_dir)  # For mcp_outlook modules
sys.path.insert(0, grandparent_dir)  # For root modules (session_manager)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def setup_session_manager():
    """
    Try to set up SessionManager if available
    Returns True if SessionManager is available and initialized
    """
    try:
        # Try to import SessionManager from project root
        from session.session_manager import SessionManager

        session_manager = SessionManager()

        # Create the SessionManager instance if not already created
        if session_manager:
            logger.info("SessionManager found and will be initialized on server startup")
            print("[OK] SessionManager enabled - multi-user support active")
            return True
    except ImportError:
        logger.info("SessionManager not found - server will run in legacy mode")
        print("[INFO] SessionManager not found - running in single-instance mode")
        return False


def main():
    """Launch the MCP server"""
    print("=" * 60)
    print("Starting Outlook MCP Server")
    print("=" * 60)

    # Check and setup SessionManager
    has_session_manager = setup_session_manager()

    print("Server Configuration:")
    print(f"  - Mode: {'Multi-user (SessionManager)' if has_session_manager else 'Legacy (Single-instance)'}")
    print("  - URL: http://localhost:3000")
    print("  - MCP Protocol Endpoints:")
    print("    • POST / (initialize, tools/list, tools/call)")
    if has_session_manager:
        print("    • GET /sessions (session management info)")
    print("=" * 60)

    # Run the server
    uvicorn.run("server:app", host="0.0.0.0", port=3000, reload=True, log_level="info")


if __name__ == "__main__":
    main()
