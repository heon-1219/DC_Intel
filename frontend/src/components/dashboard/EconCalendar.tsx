import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import type { CalendarEvent } from "../../api/types";
import { localTime } from "../../lib/format";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import { FreshCaption, StaleChip } from "../common/Chips";
import CountdownLabel from "../common/CountdownLabel";
import ErrorCard from "../common/ErrorCard";
import Skeleton from "../common/Skeleton";
import d from "../../pages/dashboard.module.css";

const ORDER = { high: 0, medium: 1, low: 2 } as const;
const DOTS = { high: "●●●", medium: "●●○", low: "●○○" } as const;
const IMPACT_CLASS = { high: d.impactHigh, medium: d.impactMed, low: d.impactLow } as const;
const IMPACT_KEY = { high: "calendar.impact.high", medium: "calendar.impact.med", low: "calendar.impact.low" } as const;

function Row({ ev }: { ev: CalendarEvent }) {
  const { t, lang } = useT();
  const title = lang === "ko" ? ev.title_ko : ev.title_en;
  return (
    <div className={d.calRow}>
      <span className={`${d.impactDots} ${IMPACT_CLASS[ev.impact_level]}`} aria-hidden="true">
        {DOTS[ev.impact_level]}
      </span>
      <div className={d.calBody}>
        <div className={d.calName}>{title}</div>
        <div className={d.calMeta}>
          <span className={IMPACT_CLASS[ev.impact_level]}>{t(IMPACT_KEY[ev.impact_level])}</span> ·{" "}
          {ev.country} · {localTime(ev.scheduled_at_utc, lang)} ·{" "}
          <CountdownLabel targetUtc={ev.scheduled_at_utc} />
        </div>
      </div>
    </div>
  );
}

export default function EconCalendar() {
  const { t, lang } = useT();
  const [expanded, setExpanded] = useState(false);
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["calendar", lang],
    queryFn: ({ signal }) => api.calendar(lang, 7, signal),
    ...pollOptions(600_000),
  });

  const events = (data?.data.events ?? [])
    .slice()
    .sort(
      (a, b) =>
        ORDER[a.impact_level] - ORDER[b.impact_level] ||
        a.scheduled_at_utc.localeCompare(b.scheduled_at_utc),
    );
  const shown = expanded ? events : events.slice(0, 8);

  return (
    <section className={d.widget}>
      <div className={d.widgetHead}>
        <h2 className={d.widgetTitle}>{t("calendar.title")}</h2>
        {data &&
          (data.data.data_stale ? (
            <StaleChip asOf={data.meta.data_as_of} />
          ) : (
            <FreshCaption asOf={data.meta.data_as_of} />
          ))}
      </div>
      {isLoading ? (
        <Skeleton count={5} height={44} />
      ) : error && !data ? (
        <ErrorCard onRetry={() => refetch()} />
      ) : events.length === 0 ? (
        <p className={d.empty}>{t("calendar.empty")}</p>
      ) : (
        <>
          {shown.map((ev) => (
            <Row key={ev.id} ev={ev} />
          ))}
          {!expanded && events.length > 8 && (
            <button className={d.showAll} onClick={() => setExpanded(true)}>
              {t("calendar.showAll", { n: events.length })}
            </button>
          )}
        </>
      )}
    </section>
  );
}
