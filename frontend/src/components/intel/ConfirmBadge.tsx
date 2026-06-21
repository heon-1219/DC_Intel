import type { IntelBadge } from "../../api/types";
import s from "./intel.module.css";

/** CONFIRMED/UNCONFIRMED badge per market-intel-pipeline §8.2 — blue/amber, never green/red. The
 *  label + disclaimer come pre-localized from the backend. */
export default function ConfirmBadge({
  badge,
  confirmUrl,
}: {
  badge: IntelBadge;
  confirmUrl: string | null;
}) {
  const confirmed = badge.style === "confirmed";
  return (
    <span className={confirmed ? s.confirmed : s.unconfirmed} title={badge.disclaimer}>
      <span aria-hidden="true">{confirmed ? "✔" : "⚠"}</span> {badge.label}
      {confirmed && confirmUrl && (
        <a className={s.confirmLink} href={confirmUrl} target="_blank" rel="noreferrer" aria-label="source">
          ↗
        </a>
      )}
    </span>
  );
}
