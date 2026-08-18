from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.auth_session import get_session_user
from backend.database import get_db
from backend.models import User
from backend.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    UserIdentityResponse,
)


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


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
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

    if payload.current_password != user.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters",
        )

    if len(payload.new_password) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must not exceed 128 characters",
        )

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be different from the current password",
        )

    user.password = payload.new_password

    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to change password",
        ) from error

    return {"message": "Password changed successfully"}


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
