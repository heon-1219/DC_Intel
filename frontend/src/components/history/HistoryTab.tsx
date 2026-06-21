import { useT } from "../../hooks/useT";
import p from "../predict/predict.module.css";

// Placeholder — HistoryLog + AccuracyTrendChart land in M9h.
export default function HistoryTab({ listing }: { listing: string }) {
  const { t } = useT();
  return (
    <div className={p.body}>
      <p className={p.note}>
        {listing} · {t("history.tab")}
      </p>
    </div>
  );
}
