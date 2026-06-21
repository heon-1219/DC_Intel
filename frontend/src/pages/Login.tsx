import { useT } from "../hooks/useT";

// Placeholder — real form in M9d.
export default function Login() {
  const { t } = useT();
  return <main style={{ padding: "var(--sp-5)" }}><h1>{t("auth.login.title")}</h1></main>;
}
