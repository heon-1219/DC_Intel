import { useEffect, useState } from "react";

import { useT } from "../../hooks/useT";
import s from "./common.module.css";

/** Client-side countdown to a UTC instant (ui-ux §7.2.3): ticks each minute, switches to per-second
 *  under 1h, shows "Happening now" at T-0, and renders nothing once >30 min past. `aria-live="off"`
 *  (a ticking live region is screen-reader noise; the absolute time is shown alongside). */
export default function CountdownLabel({ targetUtc }: { targetUtc: string }) {
  const { t } = useT();
  const target = new Date(targetUtc).getTime();
  const [now, setNow] = useState(() => Date.now());
  const remaining = Math.floor((target - now) / 1000);
  const under1h = remaining > 0 && remaining < 3600;

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), under1h ? 1000 : 60_000);
    return () => clearInterval(id);
  }, [under1h]);

  if (remaining <= 0) {
    if (remaining > -1800) return <span aria-live="off">{t("calendar.happeningNow")}</span>;
    return null;
  }
  const d = Math.floor(remaining / 86400);
  const h = Math.floor((remaining % 86400) / 3600);
  const m = Math.floor((remaining % 3600) / 60);
  const sec = remaining % 60;
  const text =
    d > 0
      ? t("calendar.countdown", { d, h })
      : h > 0
        ? t("calendar.countdown.soon", { h, m })
        : t("calendar.countdown.min", { m, s: sec });
  return (
    <span className={s.countdown} aria-live="off">
      {text}
    </span>
  );
}
