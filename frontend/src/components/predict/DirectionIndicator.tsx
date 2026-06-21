import type { Direction, Timeframe } from "../../api/types";
import { DIR_ARROW, localDateTime } from "../../lib/format";
import { TF_LABEL } from "../../lib/timeframes";
import { useT } from "../../hooks/useT";
import p from "./predict.module.css";

const ARROW_CLS: Record<Direction, string> = { up: p.bull, down: p.bear, neutral: p.neutral };
const TEXT_CLS: Record<Direction, string> = { up: p.bullText, down: p.bearText, neutral: p.neutralText };

export default function DirectionIndicator({
  direction,
  timeframe,
  windowClosesAt,
}: {
  direction: Direction;
  timeframe: Timeframe;
  windowClosesAt: string;
}) {
  const { t, lang } = useT();
  return (
    <div
      className={p.direction}
      aria-label={`${t("predict.tab")}: ${t(`direction.${direction}`)}`}
    >
      <div className={`${p.arrow} ${ARROW_CLS[direction]}`} aria-hidden="true">
        {DIR_ARROW[direction]}
      </div>
      <div className={`${p.phrase} ${TEXT_CLS[direction]}`}>{t(`direction.${direction}`)}</div>
      <div className={p.caption}>
        {t("predict.window.until", {
          tf: TF_LABEL[lang][timeframe],
          time: localDateTime(windowClosesAt, lang),
        })}
      </div>
    </div>
  );
}
