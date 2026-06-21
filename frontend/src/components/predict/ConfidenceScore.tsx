import type { Direction } from "../../api/types";
import { DIR_BG } from "../../lib/format";
import { useT } from "../../hooks/useT";
import p from "./predict.module.css";

export default function ConfidenceScore({
  confidence,
  direction,
}: {
  confidence: number;
  direction: Direction;
}) {
  const { t } = useT();
  return (
    <div className={p.conf}>
      <div className={p.confNum}>{confidence}%</div>
      <div className={p.confLabel} title={t("confidence.tooltip")}>
        {t("confidence.label", { pct: confidence })} ⓘ
      </div>
      <div className={p.confTrack}>
        <div
          className={p.confFill}
          style={{ width: `${Math.max(0, Math.min(100, confidence))}%`, background: DIR_BG[direction] }}
        />
        <div className={p.confMid} title={t("confidence.coinflip")} />
      </div>
    </div>
  );
}
