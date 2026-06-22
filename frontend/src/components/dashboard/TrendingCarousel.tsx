import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import TrendingCard from "./TrendingCard";
import { api } from "../../api/client";
import type { Lang } from "../../api/types";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import { FreshCaption, StaleChip } from "../common/Chips";
import ErrorCard from "../common/ErrorCard";
import cm from "../common/common.module.css";
import d from "../../pages/dashboard.module.css";

type Region = "kr" | "us";
const REGION_KEY = "dc_intel_region";

function initialRegion(lang: Lang): Region {
  try {
    const stored = localStorage.getItem(REGION_KEY);
    if (stored === "kr" || stored === "us") return stored;
  } catch {
    /* ignore */
  }
  return lang === "ko" ? "kr" : "us";
}

export default function TrendingCarousel() {
  const { t, lang } = useT();
  const [region, setRegion] = useState<Region>(() => initialRegion(lang));

  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["trending", region],
    queryFn: ({ signal }) => api.trending(region, signal),
    ...pollOptions(60_000),
  });

  // Merge gainers + losers → top 10 movers by |%change| (§7.2.1).
  const cards = useMemo(() => {
    const r = data?.data.regions.find((x) => x.region === region) ?? data?.data.regions[0];
    if (!r) return [];
    return [...r.gainers, ...r.losers]
      .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
      .slice(0, 10);
  }, [data, region]);

  const pick = (rg: Region) => {
    setRegion(rg);
    try {
      localStorage.setItem(REGION_KEY, rg);
    } catch {
      /* ignore */
    }
  };

  return (
    <section className={d.widget}>
      <div className={d.widgetHead}>
        <h2 className={d.widgetTitle}>{t("trending.title")}</h2>
        <div className={d.regionToggle} role="group" aria-label={t("a11y.region")}>
          <button
            className={region === "kr" ? d.regionBtnActive : d.regionBtn}
            aria-pressed={region === "kr"}
            onClick={() => pick("kr")}
          >
            {t("trending.region.kr")}
          </button>
          <button
            className={region === "us" ? d.regionBtnActive : d.regionBtn}
            aria-pressed={region === "us"}
            onClick={() => pick("us")}
          >
            {t("trending.region.us")}
          </button>
        </div>
      </div>
      {data &&
        (data.meta.is_stale ? (
          <StaleChip asOf={data.meta.data_as_of} />
        ) : (
          <FreshCaption asOf={data.meta.data_as_of} />
        ))}
      {isLoading ? (
        <div className={d.carousel}>
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className={`${d.tCard} ${cm.skeleton}`} style={{ height: 148 }} />
          ))}
        </div>
      ) : error && !data ? (
        <ErrorCard onRetry={() => refetch()} />
      ) : cards.length === 0 ? (
        <p className={d.empty}>{t("trending.empty")}</p>
      ) : (
        <div className={d.carousel}>
          {cards.map((c) => (
            <TrendingCard key={c.instrument} card={c} lang={lang} />
          ))}
        </div>
      )}
    </section>
  );
}
