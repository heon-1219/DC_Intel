import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { formatMoney, pctArrow, pctSign, signedPct } from "../../lib/format";
import { isOpenish, useMarketHours } from "../../hooks/useMarketHours";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import { MarketClosedChip, StaleChip } from "../common/Chips";
import p from "./predict.module.css";

export default function PriceHeader({ listing }: { listing: string }) {
  const { lang } = useT();
  const [symbol, exchange] = listing.split(":");
  const clientState = useMarketHours(exchange); // §3.1: client sessions drive the poll cadence
  const base = isOpenish(clientState) ? 30_000 : 300_000;

  const { data } = useQuery({
    queryKey: ["price", listing],
    queryFn: ({ signal }) => api.price(listing, signal),
    ...pollOptions(base),
  });
  const d = data?.data;
  const marketState = d?.market_state ?? clientState; // server state wins for the displayed chip
  const sign = d?.change_pct != null ? pctSign(d.change_pct) : "neutral";
  const cls = sign === "bull" ? p.bullText : sign === "bear" ? p.bearText : p.neutralText;

  return (
    <header className={p.header}>
      <span className={p.name}>{d ? (lang === "ko" ? d.name_ko : d.name_en) : symbol}</span>
      <span className={p.sym}>{listing}</span>
      {/* price + change always render (— placeholder) so they never pop in / shift (P9). */}
      <span className={p.headPrice}>{d ? formatMoney(d.price, d.currency, lang) : "—"}</span>
      <span className={`${p.headChange} ${cls}`}>
        {d && d.change_pct != null ? (
          <>
            <span aria-hidden="true">{pctArrow(d.change_pct)}</span> {signedPct(d.change_pct)}
          </>
        ) : (
          "—"
        )}
      </span>
      {marketState === "closed" ? (
        <MarketClosedChip />
      ) : data?.meta.is_stale ? (
        <StaleChip asOf={data.meta.data_as_of} />
      ) : null}
    </header>
  );
}
