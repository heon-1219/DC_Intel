import { useT } from "../../hooks/useT";
import s from "./common.module.css";

/** Mandatory fixed disclaimer (ui-ux §1) — footer of the dashboard and prediction view. */
export default function Disclaimer() {
  const { t } = useT();
  return <p className={s.disclaimer}>{t("disclaimer")}</p>;
}
