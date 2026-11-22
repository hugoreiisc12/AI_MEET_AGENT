import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import AppShell from "./components/AppShell";
import { Spinner } from "./components/ui";

// Cada tela vira um pedaço separado: o three.js (robô e escultura) só baixa quando a tela que o usa abre.
const AuthScreens = lazy(() => import("./pages/AuthScreens"));
const StudioPage = lazy(() => import("./pages/StudioPage"));
const RecordingsPage = lazy(() => import("./pages/RecordingsPage"));
const ObservabilityPage = lazy(() => import("./pages/ObservabilityPage"));
const AccountPage = lazy(() => import("./pages/AccountPage"));

const fallback = (
  <div className="flex h-dvh items-center justify-center bg-bg">
    <Spinner />
  </div>
);

function LegacyMeetingRedirect() {
  const { id } = useParams();
  return <Navigate to={`/gravacoes/${id ?? ""}`} replace />;
}

export default function App() {
  const { configError, user, loading, loginRequired, signOut } = useAuth();
  const navigate = useNavigate();

  if (loading) return fallback;

  if (configError) {
    return (
      <div className="flex h-dvh items-center justify-center bg-bg p-6 text-center">
        <div>
          <p className="text-sm text-rose-300">Não foi possível falar com a API.</p>
          <p className="mt-1 text-xs text-zinc-500">{configError}</p>
        </div>
      </div>
    );
  }

  if (loginRequired && !user) {
    return (
      <Suspense fallback={fallback}>
        <AuthScreens />
      </Suspense>
    );
  }

  // Sair sempre volta ao login principal (AI MEET com o robô).
  const logout = async () => {
    await signOut();
    navigate("/estudio", { replace: true });
  };

  const canObserve = !loginRequired || user?.role === "admin";

  return (
    <AppShell onLogout={() => void logout()}>
      <Suspense fallback={<div className="flex justify-center py-20"><Spinner /></div>}>
      <Routes>
        <Route path="/" element={<Navigate to="/estudio" replace />} />
        <Route path="/estudio" element={<StudioPage />} />
        <Route path="/gravacoes" element={<RecordingsPage />} />
        <Route path="/gravacoes/:id" element={<RecordingsPage />} />
        <Route path="/observabilidade" element={canObserve ? <ObservabilityPage /> : <Navigate to="/estudio" replace />} />
        <Route path="/reunioes/:id" element={<LegacyMeetingRedirect />} />
        <Route path="/reunioes" element={<Navigate to="/gravacoes" replace />} />
        <Route path="/chat" element={<Navigate to="/gravacoes" replace />} />
        <Route path="/conta" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/estudio" replace />} />
      </Routes>
      </Suspense>
    </AppShell>
  );
}
