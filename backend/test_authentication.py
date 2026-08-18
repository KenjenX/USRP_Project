import os
import unittest

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from backend.auth_middleware import (
    AuthenticationRequiredMiddleware,
    EnvironmentSessionMiddleware,
)
from backend.auth_routes import router as auth_router
from backend.auth_session import (
    UNAUTHENTICATED_WEBSOCKET_CODE,
    authenticate_websocket,
)
from backend.database import Base, get_db
from backend.models import User


TEST_SESSION_SECRET = "test-only-session-secret-7cf89a2d41be"
TEST_ADMIN_PASSWORD = "test-admin-password"


class AuthenticationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_session_secret = os.environ.get("SESSION_SECRET")
        os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.testing_session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )
        User.__table__.create(bind=cls.engine)

        db = cls.testing_session_local()
        try:
            db.add(
                User(
                    username="admin",
                    password=TEST_ADMIN_PASSWORD,
                )
            )
            db.commit()
        finally:
            db.close()

        app = FastAPI()

        def override_get_db():
            db = cls.testing_session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.include_router(auth_router)

        @app.get("/api/status")
        def protected_status():
            return {"status": "ok"}

        @app.websocket("/api/spectrum/stream")
        async def protected_spectrum_stream(websocket: WebSocket):
            user = await authenticate_websocket(
                websocket,
                session_factory=cls.testing_session_local,
            )
            if user is None:
                return
            await websocket.accept()
            await websocket.send_json({"authenticated": True})

        app.add_middleware(
            AuthenticationRequiredMiddleware,
            session_factory=cls.testing_session_local,
        )
        app.add_middleware(EnvironmentSessionMiddleware)
        cls.app = app

    def setUp(self):
        db = self.testing_session_local()
        try:
            user = db.query(User).filter(User.username == "admin").one()
            user.password = TEST_ADMIN_PASSWORD
            db.commit()
        finally:
            db.close()

    def login(self, client, password=TEST_ADMIN_PASSWORD):
        return client.post(
            "/api/auth/login",
            json={"username": "admin", "password": password},
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        if cls.original_session_secret is None:
            os.environ.pop("SESSION_SECRET", None)
        else:
            os.environ["SESSION_SECRET"] = cls.original_session_secret

    def test_login_succeeds(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "test-admin-password",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "admin")
        self.assertIn("usrp_session", response.cookies)

    def test_login_rejects_unknown_username_with_generic_error(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "username": "unknown",
                    "password": "test-admin-password",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid username or password")

    def test_login_rejects_wrong_password_with_generic_error(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "wrong-password",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid username or password")

    def test_me_without_session_returns_401(self):
        with TestClient(self.app) as client:
            response = client.get("/api/auth/me")

        self.assertEqual(response.status_code, 401)

    def test_me_after_login_returns_identity(self):
        with TestClient(self.app) as client:
            login_response = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "test-admin-password",
                },
            )
            response = client.get("/api/auth/me")

        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "admin")

    def test_change_password_requires_authenticated_session(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": TEST_ADMIN_PASSWORD,
                    "new_password": "replacement-password",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Not authenticated")

    def test_change_password_rejects_wrong_current_password_without_update(self):
        with TestClient(self.app) as client:
            self.login(client)
            response = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "incorrect-current-password",
                    "new_password": "replacement-password",
                },
            )

        db = self.testing_session_local()
        try:
            stored_password = (
                db.query(User).filter(User.username == "admin").one().password
            )
        finally:
            db.close()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Current password is incorrect")
        self.assertEqual(stored_password, TEST_ADMIN_PASSWORD)

    def test_change_password_stores_plaintext_updates_login_and_preserves_session(self):
        new_password = "replacement-password"

        with TestClient(self.app) as client:
            self.assertEqual(self.login(client).status_code, 200)
            response = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": TEST_ADMIN_PASSWORD,
                    "new_password": new_password,
                },
            )
            me_response = client.get("/api/auth/me")

        db = self.testing_session_local()
        try:
            stored_password = (
                db.query(User).filter(User.username == "admin").one().password
            )
        finally:
            db.close()

        with TestClient(self.app) as client:
            old_login_response = self.login(client)
            new_login_response = self.login(client, new_password)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Password changed successfully"})
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["username"], "admin")
        self.assertEqual(stored_password, new_password)
        self.assertEqual(old_login_response.status_code, 401)
        self.assertEqual(new_login_response.status_code, 200)
        self.assertNotIn(TEST_ADMIN_PASSWORD, response.text)
        self.assertNotIn(new_password, response.text)

    def test_change_password_rejects_too_short_new_password(self):
        with TestClient(self.app) as client:
            self.login(client)
            response = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": TEST_ADMIN_PASSWORD,
                    "new_password": "short",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "New password must be at least 8 characters",
        )

    def test_change_password_rejects_too_long_new_password(self):
        with TestClient(self.app) as client:
            self.login(client)
            response = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": TEST_ADMIN_PASSWORD,
                    "new_password": "n" * 129,
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "New password must not exceed 128 characters",
        )

    def test_change_password_rejects_current_password_reuse(self):
        with TestClient(self.app) as client:
            self.login(client)
            response = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": TEST_ADMIN_PASSWORD,
                    "new_password": TEST_ADMIN_PASSWORD,
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "New password must be different from the current password",
        )

    def test_logout_clears_session(self):
        with TestClient(self.app) as client:
            client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "test-admin-password",
                },
            )
            logout_response = client.post("/api/auth/logout")
            me_response = client.get("/api/auth/me")

        self.assertEqual(logout_response.status_code, 204)
        self.assertEqual(logout_response.content, b"")
        self.assertEqual(me_response.status_code, 401)

    def test_application_endpoint_requires_session(self):
        with TestClient(self.app) as client:
            response = client.get("/api/status")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Not authenticated")

    def test_websocket_without_session_is_closed_with_4401(self):
        with TestClient(self.app) as client:
            with self.assertRaises(WebSocketDisconnect) as raised:
                with client.websocket_connect("/api/spectrum/stream"):
                    pass

        self.assertEqual(
            raised.exception.code,
            UNAUTHENTICATED_WEBSOCKET_CODE,
        )


if __name__ == "__main__":
    unittest.main()
