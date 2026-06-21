import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { formatMoney, localTime, pctSign, signedPct } from "../../lib/format";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import { StaleChip, StatusDot } from "../common/Chips";
import ErrorCard from "../common/ErrorCard";
import Skeleton from "../common/Skeleton";
import p from "./predict.module.css";

export default function CrossMarketTable({ listing }: { listing: string }) {
  const { t, lang } = useT();
  const navigate = useNavigate();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["xmkt", listing],
    queryFn: ({ signal }) => api.pricesAcrossMarkets(listing, signal),
    ...pollOptions(60_000),
  });

  const listings = data?.data.listings ?? [];

  return (
    <section className={p.section}>
      <h3 className={p.sectionTitle}>{t("xmkt.title")}</h3>
      {isLoading ? (
        <Skeleton count={3} height={40} />
      ) : error && !data ? (
        <ErrorCard onRetry={() => refetch()} />
      ) : listings.length <= 1 ? (
        <p className={p.note}>
          {t("xmkt.single", { exchange: listings[0]?.exchange ?? listing.split(":")[1] })}
        </p>
      ) : (
        <>
          {data?.meta.is_stale && <StaleChip asOf={data.meta.data_as_of} />}
          <table className={p.xmktTable}>
            <thead>
              <tr>
                <th>{t("xmkt.col.market")}</th>
                <th>{t("xmkt.col.price")}</th>
                <th>{t("xmkt.col.vsPrimary")}</th>
                <th>{t("xmkt.col.updated")}</th>
                <th>{t("xmkt.col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {listings.map((l) => {
                const sign = pctSign(l.diff_pct_vs_base);
                const cls = sign === "bull" ? p.bullText : sign === "bear" ? p.bearText : p.neutralText;
                const current = l.instrument === listing;
                return (
                  <tr
                    key={l.instrument}
                    className={current ? p.xmktRowActive : p.xmktRow}
                    onClick={() => !current && navigate(`/stocks/${l.instrument}`)}
                  >
                    <td>{l.instrument}</td>
                    <td>{l.price != null ? formatMoney(l.price, l.currency, lang) : "—"}</td>
                    <td className={cls}>
                      {l.diff_pct_vs_base != null ? signedPct(l.diff_pct_vs_base) : "—"}
                    </td>
                    <td>{l.data_as_of ? localTime(l.data_as_of, lang) : "—"}</td>
                    <td>
                      <StatusDot open={l.market_state === "open"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
