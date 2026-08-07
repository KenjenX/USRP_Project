import os
from collections.abc import Callable, MutableMapping
from typing import Any

from sqlalchemy.orm import Session
from starlette.websockets import WebSocket

from backend.database import SessionLocal
from backend.models import User


SESSION_COOKIE_NAME = "usrp_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
SESSION_SECRET_MIN_LENGTH = 32
SESSION_SECRET_MIN_DISTINCT_CHARACTERS = 8
UNAUTHENTICATED_WEBSOCKET_CODE = 4401


def get_session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET", "")

    if len(secret) < SESSION_SECRET_MIN_LENGTH:
        raise RuntimeError(
            "SESSION_SECRET is required and must contain at least "
            f"{SESSION_SECRET_MIN_LENGTH} characters. Set it in the environment "
            "or the project root .env file before starting the backend."
        )

    if len(set(secret)) < SESSION_SECRET_MIN_DISTINCT_CHARACTERS:
        raise RuntimeError(
            "SESSION_SECRET is too weak. Use a random value with at least "
            f"{SESSION_SECRET_MIN_DISTINCT_CHARACTERS} distinct characters."
        )

    return secret


def get_session_user(
    session_data: MutableMapping[str, Any],
    db: Session,
) -> User | None:
    user_id = session_data.get("user_id")

    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return None

    return db.get(User, user_id)


async def authenticate_websocket(
    websocket: WebSocket,
    session_factory: Callable[[], Session] = SessionLocal,
) -> dict[str, int | str] | None:
    db = session_factory()
    try:
        user = get_session_user(websocket.session, db)
        if user is None:
            await websocket.close(code=UNAUTHENTICATED_WEBSOCKET_CODE)
            return None

        return {
            "id": user.id,
            "username": user.username,
        }
    finally:
        db.close()
