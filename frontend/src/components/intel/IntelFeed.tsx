import { useQuery } from "@tanstack/react-query";

import AnomalyBanner from "./AnomalyBanner";
import IntelCard from "./IntelCard";
import { api } from "../../api/client";
import ErrorCard from "../common/ErrorCard";
import Skeleton from "../common/Skeleton";
import { FreshCaption, StaleChip } from "../common/Chips";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import d from "../../pages/dashboard.module.css";

/** Global feed (dashboard) or per-stock variant (prediction view) when `stock` is given. */
export default function IntelFeed({ stock }: { stock?: string }) {
  const { t, lang } = useT();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["intel", lang, stock ?? "all"],
    queryFn: ({ signal }) => api.marketIntel(lang, { stock, limit: stock ? 5 : 20 }, signal),
    ...pollOptions(60_000),
  });

  return (
    <section className={d.widget}>
      <div className={d.widgetHead}>
        <h2 className={d.widgetTitle}>{t("intel.title")}</h2>
        {data &&
          (data.meta.is_stale ? (
            <StaleChip asOf={data.meta.data_as_of} />
          ) : (
            <FreshCaption asOf={data.meta.data_as_of} />
          ))}
      </div>
      {isLoading ? (
        <Skeleton count={4} height={120} />
      ) : error && !data ? (
        <ErrorCard onRetry={() => refetch()} />
      ) : !data || data.data.clusters.length === 0 ? (
        <p className={d.empty}>{t("state.empty.intel")}</p>
      ) : (
        <>
          <AnomalyBanner anomalies={data.data.anomalies} />
          {data.data.clusters.map((c) => (
            <IntelCard key={c.cluster_id} cluster={c} />
          ))}
        </>
      )}
    </section>
  );
}
