import { Navigate, Outlet } from "react-router-dom";

import AppHeader from "./AppHeader";
import { useAuth } from "../hooks/useAuth";

/** Gate + chrome for authenticated routes. */
export default function ProtectedLayout() {
  const { isAuthed } = useAuth();
  if (!isAuthed) {
    const here = window.location.pathname + window.location.search;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(here)}`} replace />;
  }
  return (
    <>
      <AppHeader />
      <Outlet />
    </>
  );
}
