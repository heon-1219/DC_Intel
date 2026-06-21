import { useState } from "react";

import type { HistoryItem, OutcomeStatus } from "../../api/types";
import { DIR_ARROW, localDateTime, pctSign, signedPct } from "../../lib/format";
import { TF_LABEL } from "../../lib/timeframes";
import { useT } from "../../hooks/useT";
import s from "./history.module.css";

const OUTCOME: Record<OutcomeStatus, { icon: string; key: string }> = {
  correct: { icon: "✅", key: "outcome.win" },
  incorrect: { icon: "❌", key: "outcome.loss" },
  pending: { icon: "⏳", key: "outcome.pending" },
};

function Row({ item }: { item: HistoryItem }) {
  const { t, lang } = useT();
  const [open, setOpen] = useState(false);
  const dirCls = item.direction === "up" ? s.bull : item.direction === "down" ? s.bear : s.neutral;
  const move = item.outcome?.move_pct ?? null;
  const moveSign = pctSign(move);
  const moveCls = moveSign === "bull" ? s.bull : moveSign === "bear" ? s.bear : s.neutral;
  const o = OUTCOME[item.status];

  return (
    <div className={s.row}>
      <button className={s.rowMain} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className={s.when}>{localDateTime(item.predicted_at, lang)}</span>
        <span>{TF_LABEL[lang][item.timeframe]}</span>
        <span className={dirCls}>
          <span aria-hidden="true">{DIR_ARROW[item.direction]}</span> {t(`predict.short.${item.direction}`)} ·{" "}
          {item.confidence}%
        </span>
        <span className={moveCls}>{move != null ? signedPct(move) : "—"}</span>
        <span>
          <span aria-hidden="true">{o.icon}</span> {t(o.key)}
        </span>
      </button>
      {open && (
        <div className={s.detail}>
          {lang === "ko" ? item.evidence_summary_ko : item.evidence_summary_en}
          <div className={s.mv}>{item.model_version}</div>
        </div>
      )}
    </div>
  );
}

export default function HistoryLog({ items }: { items: HistoryItem[] }) {
  const { t } = useT();
  const [modal, setModal] = useState(false);
  return (
    <div>
      <div className={s.log}>
        {items.map((i) => (
          <Row key={i.prediction_id} item={i} />
        ))}
      </div>
      <button className={s.scoreLink} onClick={() => setModal(true)}>
        {t("history.scoreInfo")} ⓘ
      </button>
      {modal && (
        <div className={s.modalBackdrop} onClick={() => setModal(false)}>
          <div className={s.modal} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>{t("history.scoreInfo")}</h3>
            <p>{t("history.scoreInfo.body")}</p>
            <button onClick={() => setModal(false)}>{t("history.close")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
