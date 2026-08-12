"""
FastAPI MCP Server for File Handler (legacy REST, SessionManager 연동)

보안 주의:
    - 이 서버에는 **호출자 인증이 없다**. 기본 바인드는 loopback(127.0.0.1) 전용이며,
      외부 노출은 `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 옵트인이 필요하다.
    - 도구가 여는 모든 파일/디렉터리는 `FileManager` 내부에서 `mcp_common.paths`
      허용 루트로 제한된다 (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

표준 MCP 클라이언트는 `server_stream.py` 의 `/mcp` 엔드포인트를 사용한다.
여기의 FileManager 호출은 원래부터 동기 호출이라 await 버그 대상이 아니다.
"""
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import sys
import os
import logging

# Add parent directories to path for module access
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)
file_handler_dir = os.path.join(grandparent_dir, "mcp_file_handler")

# Important: Add file_handler directory first for proper relative imports
sys.path.insert(0, file_handler_dir)
sys.path.insert(0, grandparent_dir)  # For session module
sys.path.insert(0, parent_dir)  # For direct module imports

try:
    from .tool_definitions import MCP_TOOLS
except ImportError:  # 스크립트 직접 실행
    from tool_definitions import MCP_TOOLS

# Configure logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import AuthDatabase for default user email lookup
try:
    from session.auth_database import AuthDatabase
    AUTH_DB_AVAILABLE = True
except ImportError:
    logger.warning("AuthDatabase not found, cannot get default user email")
    AUTH_DB_AVAILABLE = False


def get_default_user_email() -> Optional[str]:
    """
    Get default user email from auth.db when user_email is not provided.
    Returns the first user's email from azure_user_info table.
    """
    if not AUTH_DB_AVAILABLE:
        return None
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email')
        return None
    except Exception as e:
        logger.warning(f"Failed to get default user email: {e}")
        return None

# Try to import SessionManager - optional feature
try:
    from session.session_manager import SessionManager
    session_manager = SessionManager()
    from session.session_manager import Session
    USE_SESSION_MANAGER = True
    logger.info("SessionManager imported successfully")
except ImportError:
    logger.warning("SessionManager not found, using legacy mode without session management")
    session_manager = None
    Session = None
    USE_SESSION_MANAGER = False

# Import file handler components
from mcp_file_handler.file_manager import FileManager
from mcp_file_handler.metadata.manager import MetadataManager

app = FastAPI(title="File Handler MCP Server", version="1.0.0")

# Global instances for legacy mode (when SessionManager not available)
if not USE_SESSION_MANAGER:
    file_manager = FileManager()
    metadata_manager = file_manager.metadata_manager


@app.on_event("startup")
async def startup_event():
    """Start SessionManager on server startup (if available)"""
    if USE_SESSION_MANAGER:
        await session_manager.start()
        logger.info("SessionManager started")
    else:
        logger.info("Server started in legacy mode without SessionManager")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop SessionManager on server shutdown (if available)"""
    if USE_SESSION_MANAGER:
        await session_manager.stop()
        logger.info("SessionManager stopped")
    else:
        logger.info("Server shutdown in legacy mode")


async def ensure_file_manager_legacy():
    """
    Legacy method: Ensure FileManager is initialized before use
    Used when SessionManager is not available
    """
    global file_manager, metadata_manager
    if file_manager is None:
        file_manager = FileManager()
        metadata_manager = file_manager.metadata_manager


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "File Handler MCP Server",
        "version": "1.0.0",
        "session_manager_enabled": USE_SESSION_MANAGER
    }


@app.post("/mcp/v1/tools/list")
async def list_tools(request: Request):
    """List available MCP tools"""
    try:
        return JSONResponse({
            "tools": MCP_TOOLS
        })
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mcp/v1/tools/call")
async def call_tool(request: Request):
    """Call an MCP tool"""
    try:
        body = await request.json()
        tool_name = body.get("name")
        arguments = body.get("arguments", {})

        logger.info(f"Calling tool: {tool_name} with arguments: {arguments}")

        # Get session if available
        session = None
        user_email = arguments.get("user_email")

        # If user_email not provided, try to get default from auth.db
        if not user_email:
            user_email = get_default_user_email()
            if user_email:
                logger.info(f"Using default user_email from auth.db: {user_email}")

        if USE_SESSION_MANAGER and user_email:
            session = await session_manager.get_or_create_session(user_email)
            if not session.file_manager:
                session.file_manager = FileManager()
            file_mgr = session.file_manager
            meta_mgr = file_mgr.metadata_manager
        else:
            # Legacy mode
            await ensure_file_manager_legacy()
            file_mgr = file_manager
            meta_mgr = metadata_manager

        # Route to appropriate handler
        if tool_name == "process_file":
            result = file_mgr.process(
                input_path=arguments["input_path"],
                **{k: v for k, v in arguments.items() if k != "input_path"}
            )

        elif tool_name == "process_directory":
            result = file_mgr.process_directory(
                directory_path=arguments["directory_path"],
                **{k: v for k, v in arguments.items() if k != "directory_path"}
            )

        elif tool_name == "save_file_metadata":
            result = file_mgr.save_metadata(
                file_url=arguments["file_url"],
                keywords=arguments["keywords"],
                additional_metadata=arguments.get("additional_metadata")
            )

        elif tool_name == "search_file_metadata":
            result = file_mgr.search_metadata(**arguments)

        else:
            raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")

        return JSONResponse({
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, indent=2, ensure_ascii=False)
                }
            ]
        })

    except KeyError as e:
        logger.error(f"Missing required argument: {e}")
        raise HTTPException(status_code=400, detail=f"Missing required argument: {e}")
    except Exception as e:
        logger.error(f"Error calling tool: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    from mcp_common.net import resolve_bind_host

    bind_host = resolve_bind_host(server_name="file_handler")
    port = int(os.environ.get("MCP_LEGACY_PORT", 8092))
    logger.info(f"Starting File Handler MCP Server on {bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port)