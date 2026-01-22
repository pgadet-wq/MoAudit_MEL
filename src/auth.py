"""
MoAudit MEL - JWT Authentication
================================
JWT-based authentication middleware for API endpoints.
"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from pydantic import BaseModel

# JWT handling - using PyJWT
try:
    import jwt
    from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False


# Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# API Key for service-to-service communication
API_KEY = os.getenv("MOAUDIT_API_KEY", "")
API_KEY_HEADER = "X-API-Key"


# Models
class TokenPayload(BaseModel):
    """JWT token payload"""
    sub: str  # Subject (user ID)
    exp: datetime  # Expiration
    iat: datetime  # Issued at
    type: str = "access"  # Token type: access, refresh
    roles: List[str] = []  # User roles
    permissions: List[str] = []  # User permissions


class TokenResponse(BaseModel):
    """Token response model"""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int  # Seconds


class User(BaseModel):
    """User model"""
    id: str
    username: str
    email: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []
    is_active: bool = True
    metadata: Dict[str, Any] = {}


# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def create_access_token(
    subject: str,
    roles: List[str] = None,
    permissions: List[str] = None,
    expires_delta: Optional[timedelta] = None,
    additional_claims: Dict[str, Any] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: Token subject (usually user ID)
        roles: User roles
        permissions: User permissions
        expires_delta: Custom expiration time
        additional_claims: Additional JWT claims

    Returns:
        JWT token string
    """
    if not JWT_AVAILABLE:
        raise RuntimeError("PyJWT not installed. Install with: pip install PyJWT")

    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES))

    payload = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "type": "access",
        "roles": roles or [],
        "permissions": permissions or [],
    }

    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT refresh token.

    Args:
        subject: Token subject (usually user ID)
        expires_delta: Custom expiration time

    Returns:
        JWT refresh token string
    """
    if not JWT_AVAILABLE:
        raise RuntimeError("PyJWT not installed. Install with: pip install PyJWT")

    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS))

    payload = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "type": "refresh",
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_tokens(
    subject: str,
    roles: List[str] = None,
    permissions: List[str] = None,
) -> TokenResponse:
    """
    Create both access and refresh tokens.

    Args:
        subject: Token subject (usually user ID)
        roles: User roles
        permissions: User permissions

    Returns:
        TokenResponse with both tokens
    """
    access_token = create_access_token(subject, roles, permissions)
    refresh_token = create_refresh_token(subject)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def decode_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token string

    Returns:
        TokenPayload with decoded claims

    Raises:
        HTTPException: If token is invalid or expired
    """
    if not JWT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT authentication not available"
        )

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        return TokenPayload(
            sub=payload["sub"],
            exp=datetime.fromtimestamp(payload["exp"]),
            iat=datetime.fromtimestamp(payload["iat"]),
            type=payload.get("type", "access"),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
        )

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_api_key(api_key: str) -> bool:
    """
    Verify an API key.

    Args:
        api_key: API key to verify

    Returns:
        True if valid, False otherwise
    """
    if not API_KEY:
        return False
    return secrets.compare_digest(api_key, API_KEY)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    api_key: str = Depends(api_key_header),
) -> User:
    """
    Get the current authenticated user from JWT or API key.

    This is a FastAPI dependency that can be used to protect endpoints.

    Args:
        credentials: Bearer token credentials
        api_key: API key header

    Returns:
        User object

    Raises:
        HTTPException: If not authenticated
    """
    # Try API key first (for service-to-service communication)
    if api_key and verify_api_key(api_key):
        return User(
            id="service",
            username="service-account",
            roles=["service"],
            permissions=["*"],
        )

    # Try JWT token
    if credentials:
        token_data = decode_token(credentials.credentials)

        if token_data.type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return User(
            id=token_data.sub,
            username=token_data.sub,
            roles=token_data.roles,
            permissions=token_data.permissions,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    api_key: str = Depends(api_key_header),
) -> Optional[User]:
    """
    Get the current user if authenticated, otherwise None.

    Use this for endpoints that have optional authentication.
    """
    try:
        return await get_current_user(credentials, api_key)
    except HTTPException:
        return None


def require_roles(*required_roles: str):
    """
    Dependency factory for role-based access control.

    Usage:
        @app.get("/admin")
        async def admin_endpoint(user: User = Depends(require_roles("admin"))):
            return {"message": "Welcome, admin!"}
    """
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if "*" in user.permissions:
            return user

        if not any(role in user.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(required_roles)}",
            )
        return user

    return role_checker


def require_permissions(*required_permissions: str):
    """
    Dependency factory for permission-based access control.

    Usage:
        @app.post("/audit")
        async def run_audit(user: User = Depends(require_permissions("audit:create"))):
            return {"message": "Audit started"}
    """
    async def permission_checker(user: User = Depends(get_current_user)) -> User:
        if "*" in user.permissions:
            return user

        if not all(perm in user.permissions for perm in required_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires permissions: {', '.join(required_permissions)}",
            )
        return user

    return permission_checker


# Authentication middleware (for use with app.middleware)
class AuthMiddleware:
    """
    Authentication middleware for path-based protection.

    Usage:
        app.add_middleware(AuthMiddleware, protected_paths=["/api/"])
    """

    def __init__(
        self,
        app,
        protected_paths: List[str] = None,
        excluded_paths: List[str] = None,
    ):
        self.app = app
        self.protected_paths = protected_paths or []
        self.excluded_paths = excluded_paths or ["/health", "/docs", "/openapi.json"]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Check if path is excluded
        for excluded in self.excluded_paths:
            if path.startswith(excluded):
                await self.app(scope, receive, send)
                return

        # Check if path needs protection
        needs_auth = False
        for protected in self.protected_paths:
            if path.startswith(protected):
                needs_auth = True
                break

        if not needs_auth:
            await self.app(scope, receive, send)
            return

        # Extract and verify token
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        api_key = headers.get(API_KEY_HEADER.lower().encode(), b"").decode()

        # Check API key
        if api_key and verify_api_key(api_key):
            await self.app(scope, receive, send)
            return

        # Check JWT
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                decode_token(token)
                await self.app(scope, receive, send)
                return
            except HTTPException:
                pass

        # Not authenticated - return 401
        response = {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        }
        await send(response)

        body = b'{"detail": "Not authenticated"}'
        await send({
            "type": "http.response.body",
            "body": body,
        })


# Utility functions for testing
def create_test_token(
    user_id: str = "test-user",
    roles: List[str] = None,
    permissions: List[str] = None,
) -> str:
    """Create a test token (for use in tests only)"""
    return create_access_token(
        subject=user_id,
        roles=roles or ["user"],
        permissions=permissions or ["read"],
    )


# Token refresh endpoint handler
async def refresh_access_token(refresh_token: str) -> TokenResponse:
    """
    Refresh an access token using a refresh token.

    Args:
        refresh_token: Valid refresh token

    Returns:
        New TokenResponse with fresh access token
    """
    token_data = decode_token(refresh_token)

    if token_data.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for refresh",
        )

    # Create new access token (keep existing refresh token)
    access_token = create_access_token(token_data.sub)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
