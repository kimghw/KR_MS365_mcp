"""
Server-specific initialization module for Outlook MCP Server
This module contains custom initialization logic that varies by server type
"""

import logging
from typing import Dict, Any
import os

logger = logging.getLogger(__name__)


async def initialize_services(context: Dict[str, Any]) -> None:
    """
    Initialize server-specific services and configurations
    Called during server startup

    Args:
        context: Dictionary containing server configuration
            - server_name: Name of the server
            - use_session_manager: Whether SessionManager is enabled
            - services: Dict of service instances (for legacy mode)
    """
    server_name = context.get("server_name", "unknown")
    use_session_manager = context.get("use_session_manager", False)

    logger.info(f"Initializing {server_name} server services...")

    if server_name == "outlook":
        # Outlook-specific initialization
        if not use_session_manager:
            # Legacy mode - initialize global services
            services = context.get("services", {})

            # Initialize GraphMailQuery if present
            if "graph_mail_query" in services:
                query_service = services["graph_mail_query"]
                if hasattr(query_service, "initialize"):
                    await query_service.initialize()
                    logger.info("GraphMailQuery initialized")

            # Initialize GraphMailClient if present
            if "graph_mail_client" in services:
                client_service = services["graph_mail_client"]
                if hasattr(client_service, "initialize"):
                    await client_service.initialize()
                    logger.info("GraphMailClient initialized")

        # Load Azure configuration
        try:
            from session.azure_config import AzureConfig

            azure_config = AzureConfig()
            context["azure_config"] = azure_config
            logger.info("Azure configuration loaded")
        except ImportError:
            logger.warning("Azure configuration not available")

        # Initialize auth database
        try:
            from session.auth_database import AuthDatabase

            auth_db = AuthDatabase()
            # auth_db.init_db()  # Skip for test
            context["auth_db"] = auth_db
            logger.info("Auth database initialized")
        except ImportError:
            logger.warning("Auth database not available")


async def initialize_session(session: Any, user_email: str) -> None:
    """
    Initialize a user session with server-specific setup
    Called when creating a new session for a user

    Args:
        session: Session object to initialize
        user_email: User's email address
    """
    # Outlook-specific session initialization
    if hasattr(session, "graph_mail_query"):
        await session.graph_mail_query.initialize()

    if hasattr(session, "graph_mail_client"):
        await session.graph_mail_client.initialize()


async def cleanup_services(context: Dict[str, Any]) -> None:
    """
    Cleanup server-specific resources during shutdown

    Args:
        context: Server context dictionary
    """
    server_name = context.get("server_name", "unknown")
    logger.info(f"Cleaning up {server_name} server resources...")

    # Close database connections if needed
    if "auth_db" in context:
        try:
            context["auth_db"].close()
            logger.info("Auth database closed")
        except Exception as e:
            logger.error(f"Error closing auth database: {e}")

    # Cleanup other resources
    services = context.get("services", {})
    for service_name, service in services.items():
        if hasattr(service, "cleanup"):
            try:
                await service.cleanup()
                logger.info(f"Service {service_name} cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up {service_name}: {e}")


def get_service_config() -> Dict[str, Any]:
    """
    Get server-specific configuration

    Returns:
        Configuration dictionary with server-specific settings
    """
    return {
        "session_timeout_minutes": int(os.environ.get("SESSION_TIMEOUT", "30")),
        "cleanup_interval_minutes": int(os.environ.get("CLEANUP_INTERVAL", "5")),
        "max_sessions": int(os.environ.get("MAX_SESSIONS", "100")),
        "require_auth": os.environ.get("REQUIRE_AUTH", "true").lower() == "true",
        "default_top": int(os.environ.get("DEFAULT_TOP", "10")),
        "max_results": int(os.environ.get("MAX_RESULTS", "100")),
    }


def validate_environment() -> bool:
    """
    Validate that required environment variables and dependencies are present

    Returns:
        True if environment is valid, False otherwise
    """
    required_vars = []
    missing_vars = []

    # Check Outlook-specific requirements
    if os.environ.get("MCP_SERVER_TYPE") == "outlook":
        required_vars = ["AZURE_CLIENT_ID", "AZURE_TENANT_ID"]
        missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return False

    return True
