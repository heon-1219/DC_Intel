import type { IntelAnomaly } from "../../api/types";
import { signedPct } from "../../lib/format";
import { useT } from "../../hooks/useT";
import s from "./intel.module.css";

/** Anomaly banners above the feed (§7.2.4). Builds the canonical localized headline from the
 *  backend anomaly payload (change_pct + stock + window). Empty list → nothing. */
export default function AnomalyBanner({ anomalies }: { anomalies: IntelAnomaly[] }) {
  const { t } = useT();
  if (!anomalies?.length) return null;
  return (
    <>
      {anomalies.map((a, i) => {
        if (a.change_pct == null || !a.stock) return null;
        return (
          <div key={i} className={s.anomaly} role="status">
            ⚡{" "}
            {t("intel.anomaly.headline", {
              sym: a.stock.symbol,
              pct: signedPct(a.change_pct),
              min: a.window_minutes ?? 30,
            })}
          </div>
        );
      })}
    </>
  );
}
