import { useNavigate } from "react-router-dom";

import ConfirmBadge from "./ConfirmBadge";
import CredibilityMeter from "./CredibilityMeter";
import type { IntelCluster, Sentiment } from "../../api/types";
import { relativeTime } from "../../lib/format";
import { useT } from "../../hooks/useT";
import s from "./intel.module.css";

const SENT: Record<Sentiment, { cls: string; arrow: string }> = {
  bullish: { cls: s.bull, arrow: "▲" },
  bearish: { cls: s.bear, arrow: "▼" },
  neutral: { cls: s.neutral, arrow: "▬" },
};

/** Hard pipeline rule (§7.2.4): a cluster with no badge is NOT rendered. */
export default function IntelCard({ cluster }: { cluster: IntelCluster }) {
  const { t } = useT();
  const navigate = useNavigate();
  if (!cluster.badge) return null;

  const top = cluster.items[0];
  const sent = SENT[cluster.sentiment] ?? SENT.neutral;
  const clickable = !!cluster.stock;
  const go = () => {
    if (cluster.stock) navigate(`/stocks/${cluster.stock.symbol}:${cluster.stock.exchange}`);
  };

  return (
    <article
      className={clickable ? s.clickable : s.card}
      onClick={clickable ? go : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                go();
              }
            }
          : undefined
      }
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <div className={s.badgeRow}>
        <ConfirmBadge badge={cluster.badge} confirmUrl={cluster.confirm_url} />
      </div>
      <CredibilityMeter score={cluster.max_credibility} band={cluster.credibility_band} />
      <div className={`${s.sentChip} ${sent.cls}`}>
        <span aria-hidden="true">{sent.arrow}</span> {t(`sentiment.${cluster.sentiment}`)}
        <span className={s.sub}>
          {t("intel.sentimentSure", { pct: Math.round(cluster.sentiment_confidence * 100) })}
        </span>
      </div>
      {top && (
        <p className={s.snippet} lang={top.lang}>
          {top.content_snippet}
        </p>
      )}
      {top && (
        <div className={s.meta}>
          {top.source}
          {top.author_handle ? ` · ${top.author_handle}` : ""} · {relativeTime(top.posted_at, t)} ·{" "}
          {t("intel.sources", { n: cluster.item_count })}
        </div>
      )}
      {cluster.coordinated_warning && <div className={s.coord}>⚠ {t("intel.coordinated")}</div>}
    </article>
  );
}
