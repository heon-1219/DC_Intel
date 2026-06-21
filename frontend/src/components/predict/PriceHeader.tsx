import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { formatMoney, pctArrow, pctSign, signedPct } from "../../lib/format";
import { isOpenish, useMarketHours } from "../../hooks/useMarketHours";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import p from "./predict.module.css";

export default function PriceHeader({ listing }: { listing: string }) {
  const { lang } = useT();
  const [symbol, exchange] = listing.split(":");
  const state = useMarketHours(exchange);
  const base = isOpenish(state) ? 30_000 : 300_000; // §3.1 price cadence

  const { data } = useQuery({
    queryKey: ["price", listing],
    queryFn: ({ signal }) => api.price(listing, signal),
    ...pollOptions(base),
  });
  const d = data?.data;
  const sign = d?.change_pct != null ? pctSign(d.change_pct) : "neutral";
  const cls = sign === "bull" ? p.bullText : sign === "bear" ? p.bearText : p.neutralText;

  return (
    <header className={p.header}>
      <span className={p.name}>{d ? (lang === "ko" ? d.name_ko : d.name_en) : symbol}</span>
      <span className={p.sym}>{listing}</span>
      {d && <span className={p.headPrice}>{formatMoney(d.price, d.currency, lang)}</span>}
      {d && d.change_pct != null && (
        <span className={`${p.headChange} ${cls}`}>
          <span aria-hidden="true">{pctArrow(d.change_pct)}</span> {signedPct(d.change_pct)}
        </span>
      )}
    </header>
  );
}
