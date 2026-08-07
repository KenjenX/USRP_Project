import { useState } from "react";
import "./auth.css";

export default function LoginPage({ errorMessage, isSubmitting, onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();

    const succeeded = await onLogin({ username, password });
    if (!succeeded) setPassword("");
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
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isSubmitting}
            required
          />

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
