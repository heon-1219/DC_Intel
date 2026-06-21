import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

import ListingRow from "./ListingRow";
import { api } from "../../api/client";
import { minCharsOk } from "../../lib/search";
import { useDebounced } from "../../hooks/useDebounced";
import { useT } from "../../hooks/useT";
import s from "./search.module.css";

interface Props {
  open: boolean;
  onClose: () => void;
}

/** Global search overlay (§6): debounce 250ms, min 2 chars (1 if Hangul), AbortController per
 *  keystroke (TanStack signal), 60s client cache, combobox/listbox a11y, ↑/↓ over listings,
 *  Enter selects, Esc/backdrop closes. */
export default function SearchOverlay({ open, onClose }: Props) {
  const { t, lang } = useT();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 250);
  const enabled = open && minCharsOk(debounced);

  const { data, isFetching, error } = useQuery({
    queryKey: ["search", debounced.trim().toLowerCase()],
    queryFn: ({ signal }) => api.search(debounced.trim(), signal),
    enabled,
    staleTime: 60_000,
  });

  const results = useMemo(() => (enabled ? (data?.data.results ?? []) : []), [enabled, data]);
  const flat = useMemo(() => results.flatMap((g) => g.listings), [results]);
  const [active, setActive] = useState(0);
  useEffect(() => setActive(0), [debounced]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
    else setQ("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const select = (instrument: string) => {
    onClose();
    navigate(`/stocks/${instrument}`);
  };

  const onInputKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && flat[active]) {
      e.preventDefault();
      select(flat[active].instrument);
    }
  };

  let idx = -1;
  return (
    <div className={s.backdrop} onClick={onClose}>
      <div className={s.panel} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className={s.input}
          type="search"
          role="combobox"
          aria-expanded={flat.length > 0}
          aria-controls="search-listbox"
          aria-activedescendant={flat[active] ? `opt-${active}` : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onInputKey}
        />
        {!minCharsOk(debounced) ? (
          <p className={s.msg}>{t("search.minChars")}</p>
        ) : error ? (
          <p className={s.msg}>{t("state.error")}</p>
        ) : isFetching && results.length === 0 ? (
          <p className={s.msg}>…</p>
        ) : results.length === 0 ? (
          <p className={s.msg}>{t("search.empty", { q: debounced })}</p>
        ) : (
          <ul id="search-listbox" role="listbox" className={s.list}>
            {results.map((g, gi) => (
              <Fragment key={gi}>
                <li role="presentation" className={s.group}>
                  {lang === "ko" ? g.company_name_ko : g.company_name_en}
                  <span className={s.groupSub}>
                    {lang === "ko" ? g.company_name_en : g.company_name_ko}
                  </span>
                </li>
                {g.listings.map((l) => {
                  idx += 1;
                  const myIdx = idx;
                  return (
                    <ListingRow
                      key={l.instrument}
                      listing={l}
                      lang={lang}
                      active={myIdx === active}
                      id={`opt-${myIdx}`}
                      onSelect={() => select(l.instrument)}
                    />
                  );
                })}
              </Fragment>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
