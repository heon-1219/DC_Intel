import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { useT } from "../hooks/useT";
import s from "../pages/auth.module.css";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { t, lang } = useT();
  const { login, register, isAuthed } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const returnTo = params.get("returnTo") || "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [pending, setPending] = useState(false);
  const [touched, setTouched] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  if (isAuthed) return <Navigate to={returnTo} replace />;

  const emailValid = EMAIL_RE.test(email);
  const pwValid = password.length >= 8;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!emailValid || !pwValid) return;
    setPending(true);
    setFormErr(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, lang);
      navigate(returnTo, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "INVALID_CREDENTIALS") setFormErr(t("auth.err.invalid"));
        else if (err.code === "EMAIL_TAKEN") setFormErr(t("auth.err.taken"));
        else setFormErr(err.localized(lang) || t("auth.err.generic"));
      } else {
        setFormErr(t("auth.err.generic"));
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <div className={s.wrap}>
      <form className={s.card} onSubmit={onSubmit} noValidate>
        <h1 className={s.logo}>{t("app.name")}</h1>
        <h2 className={s.title}>{t(mode === "login" ? "auth.login.title" : "auth.register.title")}</h2>

        {formErr && (
          <div className={s.formError} role="alert">
            {formErr}
          </div>
        )}

        <div className={s.field}>
          <label className={s.label} htmlFor="email">
            {t("auth.email")}
          </label>
          <input
            id="email"
            className={s.input}
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={touched && !emailValid}
          />
          {touched && !emailValid && <div className={s.fieldError}>{t("auth.err.emailFormat")}</div>}
        </div>

        <div className={s.field}>
          <label className={s.label} htmlFor="password">
            {t("auth.password")}
          </label>
          <div className={s.inputRow}>
            <input
              id="password"
              className={s.input}
              type={showPw ? "text" : "password"}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={touched && !pwValid}
            />
            <button
              type="button"
              className={s.toggle}
              aria-pressed={showPw}
              onClick={() => setShowPw((v) => !v)}
            >
              {t(showPw ? "auth.password.hide" : "auth.password.show")}
            </button>
          </div>
          {touched && !pwValid && <div className={s.fieldError}>{t("auth.err.passwordLen")}</div>}
        </div>

        <button className={s.submit} type="submit" disabled={pending}>
          {t(mode === "login" ? "auth.login.cta" : "auth.register.cta")}
        </button>

        <Link className={s.alt} to={mode === "login" ? "/register" : "/login"}>
          {t(mode === "login" ? "auth.toRegister" : "auth.toLogin")}
        </Link>
        {mode === "login" && <span className={s.forgot}>{t("auth.forgot")}</span>}
      </form>
    </div>
  );
}
