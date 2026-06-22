import { Component, type ReactNode } from "react";

import { useT } from "../../hooks/useT";
import s from "./common.module.css";

function Fallback() {
  const { t } = useT();
  return (
    <main className={s.boundary} role="alert">
      <h1>{t("error.boundary.title")}</h1>
      <button type="button" className={s.boundaryBtn} onClick={() => window.location.reload()}>
        {t("error.boundary.reload")}
      </button>
    </main>
  );
}

/** Top-level boundary: a render throw (e.g. malformed API data) degrades to a localized fallback +
 *  reload instead of white-screening the whole app. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <Fallback /> : this.props.children;
  }
}
