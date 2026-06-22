import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import SearchOverlay from "./search/SearchOverlay";
import { useAuth } from "../hooks/useAuth";
import { useT } from "../hooks/useT";
import s from "./header.module.css";

export default function AppHeader() {
  const { t, lang, setLang } = useT();
  const { logout } = useAuth();
  const [searchOpen, setSearchOpen] = useState(false);

  // "/" focuses search on desktop (§6.1), unless typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className={s.header}>
      <Link to="/dashboard" className={s.logo}>
        {t("app.name")}
      </Link>

      <button
        type="button"
        className={s.searchTrigger}
        onClick={() => setSearchOpen(true)}
        aria-haspopup="dialog"
      >
        🔍 {t("search.placeholder")}
      </button>

      <div className={s.langToggle} role="group" aria-label={t("a11y.language")}>
        <button
          type="button"
          className={lang === "ko" ? s.langBtnActive : s.langBtn}
          aria-pressed={lang === "ko"}
          onClick={() => setLang("ko")}
        >
          {t("lang.toggle.ko")}
        </button>
        <button
          type="button"
          className={lang === "en" ? s.langBtnActive : s.langBtn}
          aria-pressed={lang === "en"}
          onClick={() => setLang("en")}
        >
          {t("lang.toggle.en")}
        </button>
      </div>

      <button type="button" className={s.logout} onClick={logout}>
        {t("nav.logout")}
      </button>

      <SearchOverlay open={searchOpen} onClose={() => setSearchOpen(false)} />
    </header>
  );
}
