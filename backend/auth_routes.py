from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.auth_session import get_session_user
from backend.database import get_db
from backend.models import User
from backend.schemas import LoginRequest, UserIdentityResponse


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


def invalid_credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


@router.post(
    "/login",
    response_model=UserIdentityResponse,
)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    username = payload.username.strip()

    if not username or not payload.password:
        raise invalid_credentials_error()

    user = db.query(User).filter(User.username == username).first()

    if user is None or payload.password != user.password:
        raise invalid_credentials_error()

    request.session.clear()
    request.session["user_id"] = user.id

    return user


@router.get(
    "/me",
    response_model=UserIdentityResponse,
)
def current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_session_user(request.session, db)

    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
