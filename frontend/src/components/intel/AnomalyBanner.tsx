import type { IntelAnomaly, Lang } from "../../api/types";
import { signedPct } from "../../lib/format";
import s from "./intel.module.css";

/** Anomaly banners above the feed (§7.2.4). Uses the backend's canonical localized headline when
 *  present, else a best-effort name + signed move. Empty list → nothing. */
export default function AnomalyBanner({
  anomalies,
  lang,
}: {
  anomalies: IntelAnomaly[];
  lang: Lang;
}) {
  if (!anomalies?.length) return null;
  return (
    <>
      {anomalies.map((a, i) => {
        const headline = lang === "ko" ? a.headline_ko : a.headline_en;
        const fallback =
          a.name != null
            ? `${a.name}${a.signed_pct != null ? ` ${signedPct(a.signed_pct)}` : ""}`
            : "";
        const text = headline ?? fallback;
        if (!text) return null;
        return (
          <div key={i} className={s.anomaly} role="status">
            ⚡ {text}
          </div>
        );
      })}
    </>
  );
}
