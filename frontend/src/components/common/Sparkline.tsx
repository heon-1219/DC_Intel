export function sparklinePath(points: number[], width: number, height: number, pad = 2): string {
  if (points.length < 2) return "";
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const stepX = (width - pad * 2) / (points.length - 1);
  const h = height - pad * 2;
  return points
    .map((p, i) => {
      const x = pad + i * stepX;
      const y = pad + (h - ((p - min) / range) * h);
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

interface Props {
  points: number[];
  /** true → green, false → red, undefined → neutral gray. */
  positive?: boolean;
  width?: number;
  height?: number;
}

/** Pure SVG sparkline, `aria-hidden` (the adjacent % text carries the value, §9). Flat gray line
 *  when there are too few points (the documented empty state). */
export default function Sparkline({ points, positive, width = 120, height = 32 }: Props) {
  const color =
    positive === undefined ? "var(--neutral)" : positive ? "var(--bull)" : "var(--bear)";
  if (!points || points.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden="true" style={{ display: "block" }}>
        <line
          x1={2}
          y1={height / 2}
          x2={width - 2}
          y2={height / 2}
          stroke="var(--neutral)"
          strokeWidth={1.5}
          opacity={0.35}
        />
      </svg>
    );
  }
  return (
    <svg width={width} height={height} aria-hidden="true" style={{ display: "block" }}>
      <path
        d={sparklinePath(points, width, height)}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
