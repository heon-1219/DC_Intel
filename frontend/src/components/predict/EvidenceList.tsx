import type { EvidenceItem, Lang } from "../../api/types";
import { useT } from "../../hooks/useT";
import p from "./predict.module.css";

const ICON: Record<string, string> = { technical: "📈", sentiment: "💬", calendar: "📅" };

/** Up to 3 evidence bullets (icon + pre-localized phrase + contribution bar). All bullets push toward
 *  the predicted direction (prediction-model §6.2); contributions sum to 100. */
export default function EvidenceList({ items, lang }: { items: EvidenceItem[]; lang: Lang }) {
  const { t } = useT();
  if (!items.length) return <p className={p.note}>{t("predict.evidence.empty")}</p>;
  return (
    <div>
      {items.slice(0, 3).map((e, i) => (
        <div key={i}>
          <div className={p.evRow}>
            <span aria-hidden="true">{ICON[e.kind] ?? "📈"}</span>
            <span className={p.evText}>{lang === "ko" ? e.text_ko : e.text_en}</span>
            <span className={p.evPct}>{e.contribution_pct}%</span>
          </div>
          <div className={p.evBarWrap}>
            <div
              className={p.evBar}
              style={{ width: `${e.contribution_pct}%`, background: "var(--text-2)" }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
