import type { WhisperData, WhisperStatus } from "../../api/types";
import { ApiError } from "../../api/client";
import { localDate, pctSign } from "../../lib/format";
import { useWhisper } from "../../hooks/useWhisper";
import { useT } from "../../hooks/useT";
import ErrorCard from "../common/ErrorCard";
import Skeleton from "../common/Skeleton";
import s from "./whisper.module.css";

const BADGE: Record<WhisperStatus, { cls: string; icon: string }> = {
  // blue/confirmed, amber/speculation, gray/neutral — NEVER green/red (reserved for price up/down).
  corroborated: { cls: s.badgeCorroborated, icon: "✔" },
  tentative: { cls: s.badgeTentative, icon: "⚠" },
  no_reliable_whisper: { cls: s.badgeNeutral, icon: "—" },
};

const SURPRISE_CLS = { bull: s.bull, bear: s.bear, neutral: s.neutral } as const;
const SURPRISE_ARROW = { bull: "▲", bear: "▼", neutral: "▬" } as const;

function fmtEps(v: number): string {
  // EPS is a small dollar figure; 2 decimals keeps a stable, tabular footprint.
  return v.toFixed(2);
}

function StatusBadge({ status }: { status: WhisperStatus }) {
  const { t } = useT();
  const b = BADGE[status];
  return (
    <span className={b.cls} title={t(`whisper.status.${status}.tooltip`)}>
      <span aria-hidden="true">{b.icon}</span> {t(`whisper.status.${status}`)}
    </span>
  );
}

/** AIWCE whisper EPS vs official consensus + a corroboration badge — or an honest empty/abstain
 *  state (never a fake number). Mounted under the prediction column on StockView. */
export default function WhisperCard({ listing }: { listing: string }) {
  const { t, lang } = useT();
  const { data, error, isLoading, refetch } = useWhisper(listing);

  if (isLoading) {
    // Skeleton sized to the populated card (header + 2 lines) → zero layout shift.
    return (
      <section className={s.card} aria-busy="true">
        <Skeleton count={1} height={24} />
        <Skeleton count={2} height={28} />
      </section>
    );
  }

  // Unknown symbol / malformed instrument / network → honest retry card (the symbol is generally
  // valid here since the page loaded, but keep the same error contract as siblings).
  if (error && !(error instanceof ApiError && error.status === 404) && !data) {
    return (
      <section className={s.card}>
        <h3 className={s.title}>{t("whisper.title")}</h3>
        <ErrorCard onRetry={() => refetch()} />
      </section>
    );
  }

  const w: WhisperData | undefined = data?.data;

  // No row computed yet OR no upcoming earnings → quiet empty state (not an error).
  if (!w || w.status === null || w.earnings_date === null || error) {
    return (
      <section className={s.card}>
        <h3 className={s.title}>{t("whisper.title")}</h3>
        <p className={s.quiet}>{t("whisper.empty")}</p>
      </section>
    );
  }

  // Honest abstention — sources disagree too much. Never invent a number.
  if (w.status === "no_reliable_whisper" || w.whisper_value === null) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h3 className={s.title}>{t("whisper.title")}</h3>
          <StatusBadge status="no_reliable_whisper" />
        </div>
        <p className={s.quiet}>
          {w.abstain_reason
            ? t("whisper.abstain.reason", { reason: w.abstain_reason })
            : t("whisper.abstain")}
        </p>
        {w.earnings_date && (
          <div className={s.meta}>
            <span>{t("whisper.earningsOn", { date: localDate(w.earnings_date, lang) })}</span>
          </div>
        )}
      </section>
    );
  }

  // corroborated | tentative — show the value vs consensus + a directional surprise.
  const surprise = w.surprise_vs_anchor;
  const sign = pctSign(surprise == null ? null : surprise / Math.max(0.1, Math.abs(w.anchor ?? 1)) * 100);

  return (
    <section className={s.card}>
      <div className={s.head}>
        <h3 className={s.title}>{t("whisper.title")}</h3>
        <StatusBadge status={w.status} />
        {w.confidence != null && (
          <span className={s.familiesLabel}>{t("whisper.confidence", { pct: w.confidence })}</span>
        )}
      </div>
      <p className={s.explain}>{t("whisper.explain")}</p>

      <div className={s.values}>
        <div className={s.valueBlock}>
          <span className={s.valueLabel}>{t("whisper.whisperLabel")}</span>
          <span className={s.valueNum}>{fmtEps(w.whisper_value)}</span>
        </div>
        {w.anchor != null && (
          <div className={s.valueBlock}>
            <span className={s.valueLabel}>{t("whisper.anchorLabel")}</span>
            <span className={s.anchorNum}>{fmtEps(w.anchor)}</span>
          </div>
        )}
        {surprise != null && (
          <div className={s.valueBlock}>
            <span className={s.valueLabel}>{t("whisper.surpriseLabel")}</span>
            <span className={`${s.surprise} ${SURPRISE_CLS[sign]}`}>
              <span aria-hidden="true">{SURPRISE_ARROW[sign]}</span>
              {surprise >= 0 ? "+" : ""}
              {fmtEps(surprise)}
            </span>
          </div>
        )}
      </div>

      <div className={s.meta}>
        <span className={s.metaNum}>{t("whisper.inliers", { n: w.n_inliers })}</span>
        {w.earnings_date && (
          <span>{t("whisper.earningsOn", { date: localDate(w.earnings_date, lang) })}</span>
        )}
      </div>

      {w.contributing_families.length > 0 && (
        <div className={s.families}>
          <span className={s.familiesLabel}>{t("whisper.sourcesLabel")}</span>
          {w.contributing_families.map((f) => (
            <span key={f} className={s.chip}>
              {f}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
