import { BrowserRouter } from "react-router-dom";

import ErrorBoundary from "./components/common/ErrorBoundary";
import { AuthProvider } from "./hooks/useAuth";
import AppRoutes from "./routes";

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
