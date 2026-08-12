from collections.abc import Callable

from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse

from backend.auth_session import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    get_session_secret,
    get_session_user,
)
from backend.database import SessionLocal


PUBLIC_AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
}


class EnvironmentSessionMiddleware:
    """Build SessionMiddleware only after validating the environment secret."""

    def __init__(self, app):
        self.middleware = SessionMiddleware(
            app,
            secret_key=get_session_secret(),
            session_cookie=SESSION_COOKIE_NAME,
            max_age=SESSION_MAX_AGE_SECONDS,
            same_site="lax",
            https_only=False,
        )

    async def __call__(self, scope, receive, send):
        await self.middleware(scope, receive, send)


class AuthenticationRequiredMiddleware:
    """Reject unauthenticated application API requests before routing."""

    def __init__(
        self,
        app,
        session_factory: Callable[[], Session] = SessionLocal,
    ):
        self.app = app
        self.session_factory = session_factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        requires_authentication = (
            path.startswith("/api/")
            and path not in PUBLIC_AUTH_PATHS
            and method != "OPTIONS"
        )

        if not requires_authentication:
            await self.app(scope, receive, send)
            return

        session_data = scope.get("session", {})
        db = self.session_factory()
        try:
            user = get_session_user(session_data, db)
            if user is not None:
                scope.setdefault("state", {})["authenticated_user"] = {
                    "id": user.id,
                    "username": user.username,
                }
        finally:
            db.close()

        if user is None:
            session_data.clear()
            response = JSONResponse(
                {"detail": "Not authenticated"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
