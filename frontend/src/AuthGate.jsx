import { useCallback, useEffect, useState } from "react";
import App from "./App.jsx";
import LoginPage from "./LoginPage.jsx";

const AUTH_ME_URL = "/api/auth/me";
const AUTH_LOGIN_URL = "/api/auth/login";
const AUTH_LOGOUT_URL = "/api/auth/logout";

export default function AuthGate() {
  const [authState, setAuthState] = useState("checking");
  const [loginError, setLoginError] = useState("");
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function checkSession() {
      try {
        const response = await fetch(AUTH_ME_URL, {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });

        if (response.ok) {
          setAuthState("authenticated");
          return;
        }

        if (response.status === 401) {
          setAuthState("unauthenticated");
          return;
        }

        throw new Error("Session check failed.");
      } catch (error) {
        if (error.name === "AbortError") return;
        setLoginError("Unable to connect to the authentication service.");
        setAuthState("unauthenticated");
      }
    }

    checkSession();
    return () => controller.abort();
  }, []);

  const handleLogin = useCallback(async ({ username, password }) => {
    setIsLoggingIn(true);
    setLoginError("");

    try {
      const response = await fetch(AUTH_LOGIN_URL, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        setLoginError("Invalid username or password");
        return false;
      }

      setAuthState("authenticated");
      return true;
    } catch {
      setLoginError("Unable to connect to the authentication service.");
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  const handleLogout = useCallback(async () => {
    setIsLoggingOut(true);

    try {
      const response = await fetch(AUTH_LOGOUT_URL, {
        method: "POST",
        credentials: "same-origin",
      });

      if (!response.ok) return;

      setLoginError("");
      setAuthState("unauthenticated");
    } catch {
      return;
    } finally {
      setIsLoggingOut(false);
    }
  }, []);

  if (authState === "checking") {
    return (
      <main className="auth-screen auth-checking" aria-busy="true">
        <div className="auth-loading-indicator" aria-hidden="true" />
        <p>Checking session...</p>
      </main>
    );
  }

  if (authState !== "authenticated") {
    return (
      <LoginPage
        errorMessage={loginError}
        isSubmitting={isLoggingIn}
        onLogin={handleLogin}
      />
    );
  }

  return <App isLoggingOut={isLoggingOut} onLogout={handleLogout} />;
}
