import { Link } from "react-router-dom";

import { useT } from "../hooks/useT";

export default function NotFound() {
  const { t } = useT();
  return (
    <main style={{ padding: "var(--sp-5)", textAlign: "center" }}>
      <h1>{t("notFound.title")}</h1>
      <Link to="/dashboard">{t("notFound.back")}</Link>
    </main>
  );
}
