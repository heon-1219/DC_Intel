import s from "./common.module.css";

/** Pulsing placeholder blocks sized to the final content (zero layout shift, §8/P9). */
export default function Skeleton({ count = 1, height = 48 }: { count?: number; height?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={s.skeleton} style={{ height }} />
      ))}
    </>
  );
}
