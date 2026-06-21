import { useT } from "./hooks/useT";

// Placeholder shell for M9a; replaced by the router in M9b.
export default function App() {
  const { t } = useT();
  return (
    <main style={{ padding: "var(--sp-5)" }}>
      <h1>{t("app.name")}</h1>
    </main>
  );
}
