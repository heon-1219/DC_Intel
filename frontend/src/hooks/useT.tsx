import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import en from "../locales/en.json";
import ko from "../locales/ko.json";

export type Lang = "en" | "ko";
type Dict = Record<string, string>;
const DICTS: Record<Lang, Dict> = { en: en as Dict, ko: ko as Dict };
const STORAGE_KEY = "dc_intel_lang";

export function detectLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "en" || stored === "ko") return stored;
  } catch {
    /* localStorage unavailable */
  }
  const nav = typeof navigator !== "undefined" ? navigator.language : "en";
  return nav.toLowerCase().startsWith("ko") ? "ko" : "en";
}

export function interpolate(tpl: string, params?: Record<string, string | number>): string {
  if (!params) return tpl;
  return tpl.replace(/\{(\w+)\}/g, (_, k: string) => (k in params ? String(params[k]) : `{${k}}`));
}

type TFn = (key: string, params?: Record<string, string | number>) => string;
interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: TFn;
}
const Ctx = createContext<LangCtx | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang; // §9: <html lang> tracks the toggle
  }, [lang]);

  const t = useCallback<TFn>(
    (key, params) => interpolate(DICTS[lang][key] ?? DICTS.en[key] ?? key, params),
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useT(): LangCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useT must be used within LangProvider");
  return ctx;
}
