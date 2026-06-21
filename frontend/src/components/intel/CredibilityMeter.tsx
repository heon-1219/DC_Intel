import { useT } from "../../hooks/useT";
import s from "./intel.module.css";

/** 0–100 credibility meter + score + band label (§6.4 bands), band text pre-localized by backend. */
export default function CredibilityMeter({ score, band }: { score: number; band: string }) {
  const { t } = useT();
  return (
    <div className={s.cred}>
      <span className={s.credMeter} aria-hidden="true">
        <span className={s.credFill} style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </span>
      <span className={s.credText}>{t("intel.cred.band", { score, band })}</span>
    </div>
  );
}
