import { useState } from "react";
import "./auth.css";

function PasswordVisibilityIcon({ isVisible }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {isVisible ? (
        <>
          <path d="m3 3 18 18" />
          <path d="M10.6 6.2A10.7 10.7 0 0 1 12 6c6 0 9.5 6 9.5 6a16.7 16.7 0 0 1-3 3.7M6.2 6.2C3.8 7.8 2.5 12 2.5 12s3.5 6 9.5 6a9.9 9.9 0 0 0 3.1-.5" />
          <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
        </>
      ) : (
        <>
          <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
          <circle cx="12" cy="12" r="3" />
        </>
      )}
    </svg>
  );
}

export default function LoginPage({ errorMessage, isSubmitting, onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();

    const succeeded = await onLogin({ username, password });
    if (!succeeded) {
      setPassword("");
      setIsPasswordVisible(false);
    }
  }

  return (
    <main className="auth-screen">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand">
          <span>USRP B210 SPECTRUM</span>
          <h1 id="login-title">TOOLS SCANNER</h1>
          <p>Sign in to continue to the scanner workspace.</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label htmlFor="login-username">Username</label>
          <input
            id="login-username"
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck="false"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={isSubmitting}
            required
            autoFocus
          />

          <label htmlFor="login-password">Password</label>
          <div className="login-password-field">
            <input
              id="login-password"
              name="password"
              type={isPasswordVisible ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={isSubmitting}
              required
            />
            <button
              type="button"
              className="login-password-toggle"
              onClick={() => setIsPasswordVisible((visible) => !visible)}
              disabled={isSubmitting}
              aria-label={isPasswordVisible ? "Hide password" : "Show password"}
              title={isPasswordVisible ? "Hide password" : "Show password"}
            >
              <PasswordVisibilityIcon isVisible={isPasswordVisible} />
            </button>
          </div>

          <div className="login-error" role="alert" aria-live="polite">
            {errorMessage}
          </div>

          <button className="login-button" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "SIGNING IN..." : "LOGIN"}
          </button>
        </form>
      </section>
    </main>
  );
}
