import { useEffect, useRef } from "react";

import { useT } from "../../hooks/useT";
import s from "./search.module.css";

interface Props {
  open: boolean;
  onClose: () => void;
}

/** M9d: dialog shell (focus on open, Esc/backdrop close). M9f adds the debounced search + results
 *  + combobox a11y. */
export default function SearchOverlay({ open, onClose }: Props) {
  const { t } = useT();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className={s.backdrop} onClick={onClose}>
      <div className={s.panel} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className={s.input}
          type="search"
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
        />
      </div>
    </div>
  );
}
