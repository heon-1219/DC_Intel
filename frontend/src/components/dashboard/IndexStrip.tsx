import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { IndexTile, Lang } from "../../api/types";
import { intNumber, pctArrow, pctSign, signedPct } from "../../lib/format";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import { FreshCaption, StaleChip, StatusDot } from "../common/Chips";
import ErrorCard from "../common/ErrorCard";
import Sparkline from "../common/Sparkline";
import cm from "../common/common.module.css";
import d from "../../pages/dashboard.module.css";

function Tile({ ix, lang }: { ix: IndexTile; lang: Lang }) {
  const { t } = useT();
  const sign = pctSign(ix.change_pct);
  const cls = sign === "bull" ? d.bull : sign === "bear" ? d.bear : d.neutral;
  return (
    <div className={d.indexTile}>
      <div className={d.indexName}>
        <span>{t(`indexes.code.${ix.code}`)}</span>
        <StatusDot open={ix.market_state === "open"} />
      </div>
      <div className={d.indexLevel}>{ix.level != null ? intNumber(ix.level, lang) : "—"}</div>
      <div className={`${d.changeRow} ${cls}`}>
        <span aria-hidden="true">{pctArrow(ix.change_pct)}</span>
        {ix.change_pct != null ? signedPct(ix.change_pct) : "—"}
      </div>
      <Sparkline points={ix.sparkline} positive={(ix.change_pct ?? 0) >= 0} width={140} height={28} />
    </div>
  );
}

export default function IndexStrip() {
  const { t, lang } = useT();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["indexes"],
    queryFn: ({ signal }) => api.indexes(signal),
    ...pollOptions(60_000),
  });
  return (
    <section className={d.widget}>
      <div className={d.widgetHead}>
        <h2 className={d.widgetTitle}>{t("indexes.title")}</h2>
        {data &&
          (data.meta.is_stale ? (
            <StaleChip asOf={data.meta.data_as_of} />
          ) : (
            <FreshCaption asOf={data.meta.data_as_of} />
          ))}
      </div>
      {isLoading ? (
        <div className={d.strip}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className={`${d.indexTile} ${cm.skeleton}`} style={{ height: 110 }} />
          ))}
        </div>
      ) : error && !data ? (
        <ErrorCard onRetry={() => refetch()} />
      ) : (
        <div className={d.strip}>
          {data!.data.indexes.map((ix) => (
            <Tile key={ix.code} ix={ix} lang={lang} />
          ))}
        </div>
      )}
    </section>
  );
}
