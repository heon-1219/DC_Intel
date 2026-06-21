import { type KeyboardEvent } from "react";

import { TIMEFRAMES, type Timeframe } from "../../api/types";
import { TF_LABEL } from "../../lib/timeframes";
import { useT } from "../../hooks/useT";
import p from "./predict.module.css";

export default function TimeframeSelector({
  value,
  onChange,
}: {
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}) {
  const { t, lang } = useT();

  const onKey = (e: KeyboardEvent) => {
    const i = TIMEFRAMES.indexOf(value);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      onChange(TIMEFRAMES[Math.min(i + 1, TIMEFRAMES.length - 1)]);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      onChange(TIMEFRAMES[Math.max(i - 1, 0)]);
    }
  };

  return (
    <div className={p.tfRow} role="radiogroup" aria-label={t("timeframe.label")}>
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          type="button"
          role="radio"
          aria-checked={tf === value}
          tabIndex={tf === value ? 0 : -1}
          className={tf === value ? p.tfBtnActive : p.tfBtn}
          onClick={() => onChange(tf)}
          onKeyDown={onKey}
        >
          {TF_LABEL[lang][tf]}
        </button>
      ))}
    </div>
  );
}
