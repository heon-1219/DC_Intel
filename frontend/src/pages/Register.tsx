import { useT } from "../hooks/useT";

// Placeholder — real form in M9d.
export default function Register() {
  const { t } = useT();
  return <main style={{ padding: "var(--sp-5)" }}><h1>{t("auth.register.title")}</h1></main>;
}
