import type { Lang, SearchListing } from "../../api/types";
import { formatMoney, pctSign, signedPct } from "../../lib/format";
import { useT } from "../../hooks/useT";
import s from "./search.module.css";

interface Props {
  listing: SearchListing;
  lang: Lang;
  active: boolean;
  id: string;
  onSelect: () => void;
}

export default function ListingRow({ listing, lang, active, id, onSelect }: Props) {
  const { t } = useT();
  const price = listing.last_price != null ? formatMoney(listing.last_price, listing.currency, lang) : "—";
  const diff = listing.diff_vs_primary_pct;
  const sign = pctSign(diff);
  const diffCls = sign === "bull" ? s.bull : sign === "bear" ? s.bear : s.neutral;
  const board = listing.kind === "adr" ? "ADR/OTC" : listing.board ?? listing.exchange;

  return (
    <li
      id={id}
      role="option"
      aria-selected={active}
      className={active ? s.rowActive : s.row}
      onMouseDown={(e) => {
        e.preventDefault();
        onSelect();
      }}
    >
      <span aria-hidden="true">●</span>
      <span className={s.rowMeta}>
        <span>{listing.symbol}</span>
        <span className={s.rowSym}>{board}</span>
      </span>
      <span className={s.rowPrice}>{price}</span>
      {listing.is_primary ? (
        <span className={s.primaryTag}>{t("search.primary")}</span>
      ) : diff != null ? (
        <span className={`${s.diff} ${diffCls}`}>{sign === "neutral" ? t("diff.zero") : signedPct(diff)}</span>
      ) : (
        <span className={`${s.diff} ${s.neutral}`}>—</span>
      )}
    </li>
  );
}
