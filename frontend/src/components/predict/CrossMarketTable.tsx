import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { formatMoney, intNumber, localTime, pctSign, signedPct } from "../../lib/format";
import { pollOptions } from "../../hooks/usePolling";
import { useT } from "../../hooks/useT";
import { FreshCaption, StaleChip, StatusDot } from "../common/Chips";
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
          {data &&
            (data.meta.is_stale ? (
              <StaleChip asOf={data.meta.data_as_of} />
            ) : (
              <FreshCaption asOf={data.meta.data_as_of} />
            ))}
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
                const diffText =
                  l.diff_pct_vs_base == null
                    ? "—"
                    : sign === "neutral"
                      ? t("diff.zero")
                      : signedPct(l.diff_pct_vs_base);
                const fxRate = data?.data.fx_rates.USDKRW;
                const go = () => {
                  if (!current) navigate(`/stocks/${l.instrument}`);
                };
                return (
                  <tr
                    key={l.instrument}
                    className={current ? p.xmktRowActive : p.xmktRow}
                    role={current ? undefined : "button"}
                    tabIndex={current ? undefined : 0}
                    onClick={go}
                    onKeyDown={(e) => {
                      if (!current && (e.key === "Enter" || e.key === " ")) {
                        e.preventDefault();
                        go();
                      }
                    }}
                  >
                    <td data-label={t("xmkt.col.market")}>{l.instrument}</td>
                    <td data-label={t("xmkt.col.price")}>
                      {l.price != null ? formatMoney(l.price, l.currency, lang) : "—"}
                    </td>
                    <td
                      data-label={t("xmkt.col.vsPrimary")}
                      className={cls}
                      title={
                        fxRate != null && l.data_as_of
                          ? t("diff.tooltip.fx", { rate: intNumber(fxRate, lang), time: localTime(l.data_as_of, lang) })
                          : undefined
                      }
                    >
                      {diffText}
                    </td>
                    <td data-label={t("xmkt.col.updated")}>
                      {l.data_as_of ? localTime(l.data_as_of, lang) : "—"}
                    </td>
                    <td data-label={t("xmkt.col.status")}>
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
