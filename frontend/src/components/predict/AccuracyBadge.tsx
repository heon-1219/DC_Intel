import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { useT } from "../../hooks/useT";
import p from "./predict.module.css";

const MIN_SAMPLE = 20;

/** Public win-rate badge (§7.4.5). Uses directional.win_rate_pct over graded_total; collecting-data
 *  state below MIN_SAMPLE=20. Non-critical → hidden while loading/on error. */
export default function AccuracyBadge({ listing }: { listing: string }) {
  const { t } = useT();
  const { data } = useQuery({
    queryKey: ["accuracy", listing],
    queryFn: ({ signal }) => api.accuracy(listing, signal),
    staleTime: 300_000,
  });
  if (!data) return null;
  const a = data.data;

  if (a.low_sample) {
    const pct = Math.min(100, Math.round((a.graded_total / MIN_SAMPLE) * 100));
    return (
      <div className={p.accCollecting}>
        <span>{t("accuracy.collecting", { done: a.graded_total, min: MIN_SAMPLE })}</span>
        <div className={p.accProgress}>
          <div className={p.accProgressFill} style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  const wr = a.directional.win_rate_pct ?? 0;
  const cls = wr >= 55 ? p.accBull : wr >= 45 ? p.accNeutral : p.accBear;
  const tip = a.by_timeframe
    .map((b) => `${b.timeframe}: ${b.directional.win_rate_pct ?? t("accuracy.na")}`)
    .join(" · ");
  return (
    <div className={cls} title={tip}>
      🎯 {t("accuracy.badge", { pct: Math.round(wr), n: a.graded_total })}
    </div>
  );
}
