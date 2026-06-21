import { useNavigate } from "react-router-dom";

import type { Lang, TrendingCard as Card } from "../../api/types";
import { pctArrow, pctSign, signedPct } from "../../lib/format";
import { useT } from "../../hooks/useT";
import Sparkline from "../common/Sparkline";
import d from "../../pages/dashboard.module.css";

export default function TrendingCard({ card, lang }: { card: Card; lang: Lang }) {
  const { t } = useT();
  const navigate = useNavigate();
  const name = lang === "ko" ? card.name_ko : card.name_en;
  const sign = pctSign(card.change_pct);
  const cls = sign === "bull" ? d.bull : sign === "bear" ? d.bear : d.neutral;

  // Win-rate badge band (§7.4.5): null → collecting; ≥55 bull / 45–55 neutral / <45 bear.
  const wr = card.win_rate_pct;
  const winCls =
    wr == null ? d.collecting : wr >= 55 ? d.winBull : wr >= 45 ? d.winNeutral : d.winBear;

  return (
    <button className={d.tCard} onClick={() => navigate(`/stocks/${card.instrument}`)}>
      <span className={d.tName}>{name}</span>
      <span className={d.tSym}>{card.instrument}</span>
      <span className={cls}>
        <span aria-hidden="true">{pctArrow(card.change_pct)}</span> {signedPct(card.change_pct)}
      </span>
      <Sparkline points={card.sparkline} positive={card.change_pct >= 0} />
      <span className={winCls}>
        {wr != null ? `🎯 ${t("trending.winRate", { pct: Math.round(wr) })}` : t("trending.collecting")}
      </span>
    </button>
  );
}
