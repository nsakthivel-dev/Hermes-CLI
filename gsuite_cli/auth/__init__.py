"""
Authentication module for Google Workspace services
"""

from .oauth import OAuthManager, AuthenticationError

__all__ = ['OAuthManager', 'AuthenticationError']
