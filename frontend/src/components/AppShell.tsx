import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeftRight, LogOut, Menu, Mic, X } from "lucide-react";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import LineSidebar from "./LineSidebar";
import { Initials, ThemeToggle } from "./ui";

interface NavItem {
  to: string;
  label: string;
  title: string;
  subtitle: string;
}

export default function AppShell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  const { user, loginRequired, mode } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const isAdmin = user?.role === "admin";

  useEffect(() => setOpen(false), [location.pathname]);

  // Observabilidade vale no modo solo (a API a libera sem login) e para o administrador no colaborativo.
  const nav: NavItem[] = [
    { to: "/estudio", label: "Estúdio Ao Vivo", title: "Estúdio Ao Vivo", subtitle: "Credenciamento do bot, andamento da reunião, transcrição ao vivo e chat com o agente" },
    { to: "/gravacoes", label: "Gravações", title: "Gravações", subtitle: "Biblioteca de sessões, transcrições indexadas, decisões e chat do agente" },
    ...(!loginRequired || isAdmin
      ? [{ to: "/observabilidade", label: "Observabilidade", title: "Observabilidade", subtitle: "Métricas e logs de todos os serviços, guardados no Redis" }]
      : []),
  ];
  // Minha conta não fica no menu: abre pelo bloco do usuário, na barra lateral.
  const activeIndex = nav.findIndex((n) => location.pathname.startsWith(n.to));
  const meta = location.pathname.startsWith("/conta")
    ? { title: "Minha conta", subtitle: "Memória do agente, sessões abertas, senha e administração" }
    : nav[Math.max(0, activeIndex)];
  const workspace = mode === "collab" ? "Modo colaborativo" : "Modo solo";

  const navigation = (
    <LineSidebar
      items={nav.map((n) => n.label)}
      activeIndex={activeIndex}
      onItemClick={(i) => navigate(nav[i].to)}
      accentColor="var(--color-emerald-300)"
      textColor="var(--color-zinc-400)"
      markerColor="var(--color-zinc-700)"
      showIndex
      showMarker
      proximityRadius={100}
      maxShift={22}
      falloff="smooth"
      markerLength={36}
      markerGap={0}
      tickScale={0.5}
      scaleTick
      itemGap={14}
      fontSize={0.875}
      smoothing={160}
    />
  );

  const userBlock = (
    <div className="space-y-3 border-t border-white/8 pt-4">
      {user ? (
        <div className="flex items-center gap-3 px-2">
          <Initials name={user.name} size="h-9 w-9" />
          <button type="button" onClick={() => navigate("/conta")} className="min-w-0 text-left" title="Minha conta">
            <p className="truncate text-xs font-semibold text-white">{user.name}</p>
            <p className="truncate text-[11px] text-zinc-400">{user.email}</p>
            <p className="text-[11px] text-emerald-300 underline-offset-2 hover:underline">Minha conta</p>
          </button>
        </div>
      ) : (
        <p className="px-2 text-[11px] text-zinc-500">Modo solo: sem login.</p>
      )}
      {loginRequired && (
        <button
          type="button"
          onClick={onLogout}
          className="flex w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/10"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Encerrar sessão</span>
        </button>
      )}
    </div>
  );

  const brand = (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/icon-64.png" alt="" className="h-8 w-8 shrink-0" />
      <div className="min-w-0">
        <span className="block text-base font-semibold tracking-tight text-white">Sona</span>
        <span className="block truncate text-[11px] text-zinc-400">{workspace}</span>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-dvh bg-bg text-zinc-100">
      <aside className="fixed inset-y-0 hidden w-60 flex-col border-r border-white/8 bg-surface px-4 py-5 lg:flex xl:w-64">
        <div className="mb-8 space-y-3">
          {brand}
          <ModeSwitch />
        </div>
        <nav aria-label="Navegação principal" className="flex-1 px-1">{navigation}</nav>
        {userBlock}
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button type="button" aria-label="Fechar menu" className="fixed inset-0 bg-black/65 backdrop-blur-xs" onClick={() => setOpen(false)} />
          <aside className="relative z-10 flex w-72 max-w-[85vw] flex-col border-r border-white/10 bg-surface p-5">
            <div className="mb-3 flex items-center justify-between">
              {brand}
              <button type="button" onClick={() => setOpen(false)} aria-label="Fechar menu" className="rounded-lg p-1.5 text-zinc-400 hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mb-6">
              <ModeSwitch />
            </div>
            <nav aria-label="Navegação principal" className="flex-1 px-1">{navigation}</nav>
            {userBlock}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:pl-60 xl:pl-64">
        <header className="sticky top-0 z-30 border-b border-white/8 bg-bg/90 px-4 py-4 backdrop-blur-md sm:px-8">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 sm:gap-6">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => setOpen(true)}
                aria-label="Abrir navegação"
                className="shrink-0 rounded-xl border border-white/10 p-2 text-zinc-300 hover:text-white lg:hidden"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div className="min-w-0">
                <h1 className="truncate text-lg font-semibold tracking-tight text-white sm:text-xl">{meta.title}</h1>
                <p className="hidden truncate text-xs text-zinc-400 sm:block">{meta.subtitle}</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <ThemeToggle />
              {!location.pathname.startsWith("/estudio") && (
                <button
                  type="button"
                  onClick={() => navigate("/estudio")}
                  className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-xl bg-emerald-400 px-3.5 py-2 text-xs font-semibold text-zinc-950 transition-colors hover:bg-emerald-300"
                >
                  <Mic className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Ir para Estúdio</span>
                </button>
              )}
              {loginRequired && (
                <button
                  type="button"
                  onClick={onLogout}
                  className="hidden shrink-0 items-center gap-1.5 whitespace-nowrap rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/10 sm:inline-flex"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  <span>Trocar conta</span>
                </button>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 px-3 py-5 sm:px-8 sm:py-6">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}

function ModeSwitch() {
  const { user, mode, signOut, reloadConfig } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (user?.role !== "admin") return null;

  const target = mode === "solo" ? "collab" : "solo";
  const targetLabel = target === "collab" ? "colaborativo" : "solo";

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      await api.switchMode(target);
      await signOut();
      await reloadConfig();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível trocar de modo");
      setBusy(false);
    }
  };

  return (
    <div className="px-2">
      {confirming ? (
        <div className="space-y-2 rounded-xl border border-white/10 bg-black/30 p-3">
          <p className="text-[11px] leading-relaxed text-zinc-300">
            Mudar para o modo {targetLabel}? Todos saem da conta e entram com uma conta do modo {targetLabel}.
          </p>
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={run} className="rounded-lg bg-emerald-400 px-2.5 py-1.5 text-[11px] font-semibold text-zinc-950 hover:bg-emerald-300">
              {busy ? "Trocando…" : "Confirmar"}
            </button>
            <button type="button" disabled={busy} onClick={() => { setConfirming(false); setError(""); }} className="rounded-lg px-2.5 py-1.5 text-[11px] text-zinc-400 hover:text-zinc-100">
              Cancelar
            </button>
          </div>
          {error && <p className="text-[11px] text-rose-400">{error}</p>}
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/10"
        >
          <ArrowLeftRight className="h-3.5 w-3.5" />
          <span>Mudar para {targetLabel}</span>
        </button>
      )}
    </div>
  );
}

