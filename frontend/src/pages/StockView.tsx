import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { TIMEFRAMES, type Timeframe } from "../api/types";
import AccuracyBadge from "../components/predict/AccuracyBadge";
import ConfidenceScore from "../components/predict/ConfidenceScore";
import CrossMarketTable from "../components/predict/CrossMarketTable";
import DirectionIndicator from "../components/predict/DirectionIndicator";
import EvidenceList from "../components/predict/EvidenceList";
import PriceHeader from "../components/predict/PriceHeader";
import TimeframeSelector from "../components/predict/TimeframeSelector";
import Disclaimer from "../components/common/Disclaimer";
import ErrorCard from "../components/common/ErrorCard";
import Skeleton from "../components/common/Skeleton";
import HistoryTab from "../components/history/HistoryTab";
import IntelFeed from "../components/intel/IntelFeed";
import { useT } from "../hooks/useT";
import p from "../components/predict/predict.module.css";

const TF_KEY = "dc_intel_tf";
function readTf(): Timeframe {
  try {
    const v = sessionStorage.getItem(TF_KEY);
    if (v && (TIMEFRAMES as string[]).includes(v)) return v as Timeframe;
  } catch {
    /* ignore */
  }
  return "24h";
}

function PredictionTab({ listing }: { listing: string }) {
  const { t, lang } = useT();
  const [tf, setTf] = useState<Timeframe>(() => readTf());
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["predict", listing, tf],
    queryFn: ({ signal }) => api.predict(listing, tf, signal),
    staleTime: 60_000,
    retry: false,
  });
  const setTimeframe = (v: Timeframe) => {
    setTf(v);
    try {
      sessionStorage.setItem(TF_KEY, v);
    } catch {
      /* ignore */
    }
  };
  const code = error instanceof ApiError ? error.code : undefined;

  return (
    <div className={p.body}>
      <div className={p.predGrid}>
        <div>
          {isLoading ? (
            <Skeleton count={1} height={180} />
          ) : code === "MODEL_UNAVAILABLE" ? (
            <p className={p.note}>{t("predict.modelUnavailable")}</p>
          ) : code === "SOURCE_DEGRADED" ? (
            <p className={p.note}>{t("predict.degraded")}</p>
          ) : error || !data ? (
            <ErrorCard onRetry={() => refetch()} />
          ) : (
            <>
              <DirectionIndicator
                direction={data.data.direction}
                timeframe={tf}
                windowClosesAt={data.data.window_closes_at}
              />
              <ConfidenceScore confidence={data.data.confidence} direction={data.data.direction} />
            </>
          )}
          <TimeframeSelector value={tf} onChange={setTimeframe} />
          <AccuracyBadge listing={listing} />
        </div>
        <div>
          <section className={p.section}>
            <h3 className={p.sectionTitle}>{t("predict.why")}</h3>
            {data ? (
              <EvidenceList items={data.data.evidence} lang={lang} />
            ) : (
              <Skeleton count={3} height={28} />
            )}
          </section>
          <CrossMarketTable listing={listing} />
          <IntelFeed stock={listing} />
        </div>
      </div>
    </div>
  );
}

export default function StockView() {
  const { t } = useT();
  const { listing } = useParams();
  const location = useLocation();
  if (!listing) return null;
  const isHistory = location.pathname.endsWith("/history");

  return (
    <main>
      <PriceHeader listing={listing} />
      <div className={p.tabs} role="tablist">
        <Link
          to={`/stocks/${listing}`}
          role="tab"
          aria-selected={!isHistory}
          className={!isHistory ? p.tabActive : p.tab}
        >
          {t("predict.tab")}
        </Link>
        <Link
          to={`/stocks/${listing}/history`}
          role="tab"
          aria-selected={isHistory}
          className={isHistory ? p.tabActive : p.tab}
        >
          {t("history.tab")}
        </Link>
      </div>
      {isHistory ? <HistoryTab listing={listing} /> : <PredictionTab listing={listing} />}
      <Disclaimer />
    </main>
  );
}
