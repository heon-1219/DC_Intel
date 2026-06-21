import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

/** Gate for authenticated routes; AppHeader is added in M9d. */
export default function ProtectedLayout() {
  const { isAuthed } = useAuth();
  if (!isAuthed) {
    const here = window.location.pathname + window.location.search;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(here)}`} replace />;
  }
  return <Outlet />;
}
