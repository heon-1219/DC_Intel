import { useT } from "../../hooks/useT";
import s from "./common.module.css";

/** Per-widget error with tap-to-retry (≥44px, §8). Never a full-screen error (except auth → login). */
export default function ErrorCard({ onRetry }: { onRetry?: () => void }) {
  const { t } = useT();
  return (
    <button type="button" className={s.error} onClick={onRetry}>
      {t("state.error")}
    </button>
  );
}
