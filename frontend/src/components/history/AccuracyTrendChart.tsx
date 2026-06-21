import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import type { HistoryItem } from "../../api/types";
import { gradedCount, rollingWinRate } from "../../lib/history";
import { useT } from "../../hooks/useT";
import s from "./history.module.css";

const MIN_SAMPLE = 20;

/** The user's personal rolling win rate (§7.4.7). Hidden (collecting note) below 20 graded. */
export default function AccuracyTrendChart({ items }: { items: HistoryItem[] }) {
  const { t } = useT();
  const graded = gradedCount(items);
  if (graded < MIN_SAMPLE) {
    return <p className={s.collecting}>{t("history.collecting", { n: graded })}</p>;
  }
  const data = rollingWinRate(items);
  return (
    <div style={{ width: "100%", height: 120 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="x" tick={{ fontSize: 11 }} stroke="var(--text-3)" />
          <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} stroke="var(--text-3)" />
          <ReferenceLine y={50} stroke="var(--text-3)" strokeDasharray="4 4" />
          <Line
            type="monotone"
            dataKey="rate"
            stroke="var(--confirmed)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
