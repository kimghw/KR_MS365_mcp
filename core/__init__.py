"""
Core Module - TokenProviderProtocol 정의

mcp_outlook이 session.AuthManager를 직접 의존하지 않도록 추상화.
"""

from .protocols import TokenProviderProtocol

__all__ = ['TokenProviderProtocol']
