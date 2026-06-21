import { useEffect, useState } from "react";

import { localTime, relativeTime } from "../../lib/format";
import { useT } from "../../hooks/useT";
import s from "./common.module.css";

/** Amber "data delayed" chip (§3.2). Live region so AT announces the state change. */
export function StaleChip({ asOf }: { asOf?: string | null }) {
  const { t, lang } = useT();
  const time = asOf ? localTime(asOf, lang) : "";
  return (
    <span className={s.stale} role="status" aria-live="polite">
      ⏱ {t("state.stale", { time })}
    </span>
  );
}

export function MarketClosedChip() {
  const { t } = useT();
  return <span className={s.closed}>{t("state.marketClosed")}</span>;
}

/** Quiet "Updated x ago" caption; re-renders every 30s so the age stays current (§3.2 fresh). */
export function FreshCaption({ asOf }: { asOf: string }) {
  const { t } = useT();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  return <span className={s.fresh}>{t("state.fresh", { time: relativeTime(asOf, t, now) })}</span>;
}

/** Open/closed status dot + word (never color alone, §9). */
export function StatusDot({ open }: { open: boolean }) {
  const { t } = useT();
  return (
    <span>
      <span className={open ? s.dotOpen : s.dotClosed} aria-hidden="true" />
      {open ? t("state.open") : t("state.closed")}
    </span>
  );
}
