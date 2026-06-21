import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy } from "react";

import HistoryLog from "./HistoryLog";
import { api } from "../../api/client";
import { useT } from "../../hooks/useT";
import ErrorCard from "../common/ErrorCard";
import Skeleton from "../common/Skeleton";
import hs from "./history.module.css";
import p from "../predict/predict.module.css";

// Code-split Recharts: only the History tab pulls it, keeping the main bundle light.
const AccuracyTrendChart = lazy(() => import("./AccuracyTrendChart"));

/** "Your predictions on this stock" (§7.4.7) — auth-required, newest first, on-navigation only. */
export default function HistoryTab({ listing }: { listing: string }) {
  const { t } = useT();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["history", listing],
    queryFn: ({ signal }) => api.history(listing, 30, signal),
  });

  return (
    <div className={p.body}>
      {isLoading ? (
        <Skeleton count={10} height={44} />
      ) : error && !data ? (
        <ErrorCard onRetry={() => refetch()} />
      ) : !data || data.data.items.length === 0 ? (
        <p className={p.note}>{t("history.empty")}</p>
      ) : (
        <>
          <section className={hs.trend}>
            <h3 className={hs.trendTitle}>{t("history.trend.title")}</h3>
            <Suspense fallback={<Skeleton count={1} height={120} />}>
              <AccuracyTrendChart items={data.data.items} />
            </Suspense>
          </section>
          <HistoryLog items={data.data.items} />
        </>
      )}
    </div>
  );
}
