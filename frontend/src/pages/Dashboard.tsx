import { useT } from "../hooks/useT";

// Placeholder — widgets in M9e.
export default function Dashboard() {
  const { t } = useT();
  return <main style={{ padding: "var(--sp-5)" }}><h1>{t("nav.dashboard")}</h1></main>;
}
