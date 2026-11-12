"use client";

import "./styles.css";
import { useContext, useEffect, useState } from "react";
import Link from "next/link";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEye, faEyeSlash } from "@fortawesome/free-solid-svg-icons";
import { useRouter } from "next/navigation";
import { useAppSelector, useAppDispatch } from "@/app/store/hooks";
import { setCurrentUser } from "@/app/store/slices/authSlice";
import { clearAgents } from "@/app/store/slices/agentsSlice";
import { apiSlice } from "@/app/store/apiSlice";
import { fetchApi, isEmailVerificationEnabled } from "@/app/utils/apiClient";
import toast from "react-hot-toast";

export default function LoginPage() {
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    email: "",
    password: "",
    rememberMe: false,
  });
  const [error, setError] = useState({
    email: "",
    password: "",
    errorMessage: "",
  });

  const router = useRouter();
  const dispatch = useAppDispatch();
  // Need to handle dispatch manually in this file

  // Block a brief flash of the sign-in form while we check for an existing
  // session below.
  const [checkingSession, setCheckingSession] = useState(true);

  // Don't force a still-logged-in user to sign in again. The access token
  // persists in localStorage across tab/browser restarts, so on mount we verify
  // it against /auth/me and, when it's still valid, send the user straight into
  // the app instead of showing this form. Only a missing/expired/revoked token
  // falls through to the login form.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (typeof window === "undefined" || !localStorage.getItem("access_token")) {
        setCheckingSession(false);
        return;
      }
      try {
        const me = await fetchApi("/api/auth/me", { method: "GET" });
        if (!cancelled && me && me.detail !== "Not authenticated") {
          dispatch(setCurrentUser(me));
          // Only hold an unverified user at the verification screen while the
          // admin toggle requires it; otherwise let them into the app.
          if (me.is_verified === false && (await isEmailVerificationEnabled())) {
            try { if (me.email) localStorage.setItem("pending_verification_email", me.email); } catch { /* non-fatal */ }
            router.replace("/auth/verify-email");
          } else {
            router.replace(me.has_org ? "/dashboard" : "/org/setup");
          }
          return;
        }
      } catch {
        // Stale/expired/revoked token — drop it and show the login form.
        localStorage.removeItem("access_token");
      }
      if (!cancelled) setCheckingSession(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [dispatch, router]);

  function isValidEmail(value: string) {
    return /^[a-zA-Z0-9_%+-]+(?:\.[a-zA-Z0-9_%+-]+)*@[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$/.test(
      value,
    );
  }

  async function handleSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    const { email, password } = formData;

    setError({ email: "", password: "", errorMessage: "" });

    let isError = false;

    if (!email) {
      setError((prev) => ({ ...prev, email: "Email is required" }));
      isError = true;
    }

    if (!password) {
      setError((prev) => ({ ...prev, password: "Password is required" }));
      isError = true;
    }

    if (!isValidEmail(email)) {
      setError((prev) => ({ ...prev, email: "Invalid email address" }));
      isError = true;
    }

    if (isError) {
      return;
    }

    const data = {
      email: formData.email.trim(),
      password: formData.password,
      remember_me: formData.rememberMe,
    };

    try {
      setLoading(true);
      const response = await fetch(
        `/api/auth/login`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
      );

      const result = await response.json();
      if (response.ok) {
        if (result.access_token) {
          localStorage.setItem("access_token", result.access_token);
        } else if (result.token) {
          localStorage.setItem("access_token", result.token);
        }

        toast.success(result.message || "Logged in successfully!");

        // Clear any cached API data from a previous/anonymous session so the
        // dashboard fetches this user's real state (AI keys, connections, …)
        // instead of a stale empty cache — otherwise an already-configured AI
        // provider reads as "not connected" until a manual refresh.
        dispatch(apiSlice.util.resetApiState());
        dispatch(clearAgents());

        try {
          const userRes = await fetchApi("/api/auth/me", { method: "GET" });
          if (userRes?.detail === "Not authenticated") {
            dispatch(setCurrentUser(undefined));
          } else {
            // Record the identity this browser now holds cached data for, so the
            // AuthWrapper bootstrap can detect a later account switch (see there).
            try {
              if (userRes?.id != null) localStorage.setItem("last_user_id", String(userRes.id));
            } catch { /* non-fatal */ }
            dispatch(setCurrentUser(userRes));
          }
        } catch (e) {
          console.error("Failed to fetch user after login", e);
          dispatch(setCurrentUser(result));
        }

        // Route an unverified account to the verification screen ONLY while the
        // admin toggle requires verification; otherwise send it into the app.
        const needsVerification =
          result.is_verified === false && (await isEmailVerificationEnabled());
        setTimeout(() => {
          if (needsVerification) {
            // Remember the email so Resend works without re-asking for it.
            try { localStorage.setItem("pending_verification_email", formData.email.trim()); } catch { /* non-fatal */ }
            router.push("/auth/verify-email");
          } else {
            router.push(result.has_org ? "/dashboard" : "/org/setup");
          }
        }, 100);
      } else {
        // An unverified account is blocked with 403 + a machine-readable code.
        // Route it to the verification (OTP) screen and trigger a resend there,
        // rather than showing a generic credentials error.
        const detail = result?.detail;
        const code = typeof detail === "object" ? detail?.code : undefined;
        if (response.status === 403 && code === "email_not_verified") {
          try { localStorage.setItem("pending_verification_email", formData.email.trim()); } catch { /* non-fatal */ }
          toast.error("Please verify your email before signing in.");
          router.push("/auth/verify-email?resend=1");
          return;
        }
        const message =
          typeof detail === "string"
            ? detail
            : (detail && typeof detail === "object" && detail.message) || "Invalid email or password";
        setError((prev) => ({ ...prev, errorMessage: message }));
      }
    } catch (error) {
      console.log(error);
      setError((prev) => ({
        ...prev,
        errorMessage: "An error occurred. Please try again.",
      }));
    } finally {
      setLoading(false);
    }
  }

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--bg)]">
        <span
          aria-label="Loading"
          style={{
            width: 28,
            height: 28,
            border: "3px solid var(--primary-soft)",
            borderTopColor: "var(--primary)",
            borderRadius: "50%",
            animation: "spin 0.6s linear infinite",
          }}
        />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col md:flex-row">
      <div className="hidden md:flex flex-1 promo-column relative overflow-hidden">
        <div className="promo-content">
          <div className="promo-brand">
            <div className="promo-icon">⚡</div>
            <h2>TASK FLEET <span>AI</span></h2>
          </div>
          <div className="promo-text">
            <h3>Ship Faster.<br/>Break Nothing.</h3>
            <p>Automate your code reviews with AI intelligence. Catch bugs before they reach production.</p>
          </div>
          <div className="promo-features">
            <div className="promo-feature">
              <div className="feature-icon">🔍</div>
              <div>
                <h4>Deep Context Analysis</h4>
                <p>Understands your entire repository architecture.</p>
              </div>
            </div>
            <div className="promo-feature">
              <div className="feature-icon">🛡️</div>
              <div>
                <h4>Security First</h4>
                <p>Identifies vulnerabilities instantly.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="flex-1 flex justify-center items-center p-6 bg-[var(--bg)]">
        <div className="login-card" style={{ margin: 0 }}>
        <div className="brand">
          <div className="brand-icon">⚡</div>
          <h1>
            TASK FLEET <span>AI</span>
          </h1>
          <p>Sign in to your dashboard</p>
        </div>

        {error.errorMessage && (
          <div className="msg error text-red-600">{error.errorMessage}</div>
        )}

        <form autoComplete="on" onSubmit={handleSubmit}>
          <div className="form-group">
            <label
              htmlFor="email"
              className={error.email ? "text-red-600 font-bold" : ""}
            >
              Email Address
            </label>
            <div className="input-wrap">
              <input
                value={formData.email}
                onChange={(e) => {
                  const value = e.target.value;
                  setFormData({ ...formData, email: value });
                  // Clear a standing email error as soon as the value becomes valid
                  // (or is emptied — an empty field isn't a "format" error).
                  if (error.email && (!value.trim() || isValidEmail(value.trim()))) {
                    setError((prev) => ({ ...prev, email: "" }));
                  }
                }}
                onBlur={(e) => {
                  // Flag an invalid email inline, the moment the field loses focus.
                  const value = e.target.value.trim();
                  setError((prev) => ({
                    ...prev,
                    email: value && !isValidEmail(value) ? "Invalid email address" : "",
                  }));
                }}
                type="email"
                id="email"
                name="email"
                placeholder="you@company.com"
                autoComplete="email"
                aria-invalid={!!error.email}
                className={
                  error.email
                    ? "border-2 border-red-400"
                    : ""
                }
              />
            </div>
            {error.email && <div className="field-error active">{error.email}</div>}
          </div>

          <div className="form-group">
            <label
              htmlFor="password"
              className={error.password ? "text-red-600 font-bold" : ""}
            >
              Password
            </label>
            <div className="input-wrap">
              <input
                value={formData.password}
                onChange={(e) => {
                  setFormData({ ...formData, password: e.target.value });
                  setError((prev) => ({ ...prev, password: "" }));
                }}
                type={showPassword ? "text" : "password"}
                id="password"
                name="password"
                placeholder="Enter your password"
                autoComplete="current-password"
                className={
                  error.password
                    ? "border-2 border-red-400"
                    : ""
                }
              />
              <button
                onClick={() => setShowPassword(!showPassword)}
                type="button"
                className="pw-toggle outline-none focus:outline-none focus:ring-0"
                aria-label="Toggle password visibility"
              >
                <FontAwesomeIcon icon={showPassword ? faEyeSlash : faEye} />
              </button>
            </div>
          </div>

          <div className="form-extras">
            <div className="remember-me">
              <input
                checked={formData.rememberMe}
                onChange={(e) =>
                  setFormData({ ...formData, rememberMe: e.target.checked })
                }
                type="checkbox"
                id="remember_me"
                name="remember_me"
              />
              <label htmlFor="remember_me">Remember me</label>
            </div>
            <Link href="/forgot-password" className="forgot-link">
              Forgot password?
            </Link>
          </div>

          <button
            className={`btn-submit ${loading ? "loading" : ""}`}
            id="submitBtn"
            disabled={loading}
          >
            {loading ? (
              <span className="spinner"></span>
            ) : (
              <span className="btn-text">Sign In</span>
            )}
          </button>
        </form>

        <div className="footer-links">
          Don't have an account? <Link href="/register">Create Account</Link>
        </div>
      </div>
      </div>
    </main>
  );
}
