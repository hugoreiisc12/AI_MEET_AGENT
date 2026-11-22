import { useState, type FormEvent, type ReactNode } from "react";
import { ArrowRight, Lock, Mail, User as UserIcon } from "lucide-react";
import { RobotHero } from "../components/ref/robot-hero";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/endpoints";
import { getLastUser, setLastUser } from "../lib/prefs";
import { Initials, ThemeToggle } from "../components/ui";
import type { User } from "../api/types";

type View = "login" | "signup" | "forgot";
type DoneFn = (user: User, token: string) => void;

const MIN_PASSWORD = 8;

export default function AuthScreens() {
  const [view, setView] = useState<View>("login");

  return (
    <div className="flex min-h-dvh w-full flex-col bg-surface text-zinc-100 lg:flex-row">
      <div className="relative min-w-0 flex-1">
        <RobotHero
          backgroundText="AI MEET"
          showNavbar={false}
          className="h-[320px] sm:h-[440px] lg:h-dvh lg:min-h-[640px]"
          pantallaColor="#00ffc6"
          pantallaBrillo={1.25}
        />
      </div>

      <aside className="flex w-full shrink-0 flex-col justify-between border-t border-white/15 bg-surface p-5 sm:p-8 lg:w-[460px] lg:border-l lg:border-t-0 lg:p-10 xl:w-[500px]">
        <div className="space-y-7 sm:space-y-8">
          <div className="flex items-center justify-between gap-4 border-b border-white/10 pb-5">
            <div className="flex items-center gap-2.5">
              <img src="/icon-64.png" alt="" className="h-7 w-7 shrink-0" />
              <span className="text-sm font-semibold tracking-wide text-white">AI MEET</span>
            </div>
            <ThemeToggle />
          </div>

          <div className="space-y-2.5">
            <p className="text-xs font-medium uppercase tracking-wider text-neon">Acesso · Agente de transcrição ativa</p>
            <h2 className="text-3xl font-semibold leading-[1.05] tracking-tight text-white sm:text-4xl">
              Sua escuta
              <span className="block font-serif font-medium italic text-neon">pronta para agir.</span>
            </h2>
          </div>

          <AuthCard view={view} onView={setView} />
        </div>

        <p className="mt-6 border-t border-white/8 pt-6 text-xs text-zinc-500">
          Captura acústica protegida · Sessão pronta para transcrição e resumo.
        </p>
      </aside>
    </div>
  );
}

function AuthCard({ view, onView }: { view: View; onView: (v: View) => void }) {
  const { config, signIn } = useAuth();
  const last = getLastUser();

  const done: DoneFn = (user, token) => {
    setLastUser({ name: user.name, email: user.email });
    signIn(user, token);
  };

  return (
    <div className="w-full space-y-4 rounded-2xl border border-white/12 bg-white/[0.03] p-5 shadow-2xl">
      {last && view === "login" && (
        <div className="flex items-center gap-3 border-b border-white/10 pb-3.5">
          <Initials name={last.name} />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">{last.name}</p>
            <p className="truncate text-xs text-zinc-400">{last.email}</p>
          </div>
        </div>
      )}

      {view === "login" && <LoginView initialEmail={last?.email ?? ""} onDone={done} />}
      {view === "signup" && <SignupView onDone={done} />}
      {view === "forgot" && <ForgotView enabled={!!config?.email_enabled} onDone={() => onView("login")} />}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1 text-xs text-zinc-400">
        {view !== "login" && <LinkButton onClick={() => onView("login")}>Voltar ao login</LinkButton>}
        {view === "login" && config?.registration_open && <LinkButton onClick={() => onView("signup")}>Criar conta</LinkButton>}
        {view === "login" && <LinkButton onClick={() => onView("forgot")}>Esqueci a senha</LinkButton>}
      </div>
    </div>
  );
}

function LoginView({ initialEmail, onDone }: { initialEmail: string; onDone: DoneFn }) {
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Informe seu e-mail e senha para entrar.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await api.login(email.trim(), password);
      onDone(res.user, res.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível entrar");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <AuthInput label="E-mail" icon={<Mail className="h-4 w-4" />} type="email" autoComplete="email" value={email} onChange={setEmail} />
      <AuthInput label="Senha" icon={<Lock className="h-4 w-4" />} type="password" autoComplete="current-password" value={password} onChange={setPassword} />
      {error && <p className="text-xs text-rose-400" role="alert">{error}</p>}
      <SubmitButton busy={busy}>Entrar</SubmitButton>
    </form>
  );
}

function SignupView({ onDone }: { onDone: DoneFn }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError("As senhas não conferem.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await api.register(name.trim(), email.trim(), password);
      onDone(res.user, res.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível criar a conta");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <AuthInput label="Nome" icon={<UserIcon className="h-4 w-4" />} value={name} onChange={setName} />
      <AuthInput label="E-mail" icon={<Mail className="h-4 w-4" />} type="email" autoComplete="email" value={email} onChange={setEmail} />
      <AuthInput label={`Senha (mínimo de ${MIN_PASSWORD} caracteres)`} icon={<Lock className="h-4 w-4" />} type="password" autoComplete="new-password" value={password} onChange={setPassword} minLength={MIN_PASSWORD} />
      <AuthInput label="Repita a senha" icon={<Lock className="h-4 w-4" />} type="password" autoComplete="new-password" value={confirm} onChange={setConfirm} />
      {error && <p className="text-xs text-rose-400" role="alert">{error}</p>}
      <SubmitButton busy={busy}>Criar conta</SubmitButton>
    </form>
  );
}

function ForgotView({ enabled, onDone }: { enabled: boolean; onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (!enabled) return <p className="text-xs text-zinc-300">Recuperação por e-mail indisponível: peça a quem administra o sistema.</p>;

  const run = async (fn: () => Promise<unknown>, ok: string, after?: () => void) => {
    setBusy(true);
    try {
      await fn();
      setNotice({ ok: true, text: ok });
      after?.();
    } catch (err) {
      setNotice({ ok: false, text: err instanceof Error ? err.message : "Falha na operação" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => api.forgotPassword(email.trim()), "Se o e-mail tiver conta, o código foi enviado (vale 15 minutos).");
        }}
      >
        <AuthInput label="E-mail" icon={<Mail className="h-4 w-4" />} type="email" value={email} onChange={setEmail} />
        <SubmitButton busy={busy}>Enviar código</SubmitButton>
      </form>
      <form
        className="space-y-3 border-t border-white/10 pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => api.resetPassword(email.trim(), code.trim(), password), "Senha alterada. Entre com a nova senha.", onDone);
        }}
      >
        <AuthInput label="Código recebido" icon={<Lock className="h-4 w-4" />} value={code} onChange={setCode} />
        <AuthInput label={`Nova senha (mínimo de ${MIN_PASSWORD} caracteres)`} icon={<Lock className="h-4 w-4" />} type="password" value={password} onChange={setPassword} minLength={MIN_PASSWORD} />
        <SubmitButton busy={busy}>Criar nova senha</SubmitButton>
      </form>
      {notice && <p className={`text-xs ${notice.ok ? "text-emerald-300" : "text-rose-400"}`}>{notice.text}</p>}
    </div>
  );
}

function AuthInput({
  label,
  icon,
  value,
  onChange,
  type = "text",
  autoComplete,
  minLength,
}: {
  label: string;
  icon: ReactNode;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  autoComplete?: string;
  minLength?: number;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-zinc-400">{label}</span>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400">{icon}</span>
        <input
          type={type}
          autoComplete={autoComplete}
          minLength={minLength}
          required
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-xl border border-white/12 bg-white/5 py-2.5 pl-9 pr-3 text-sm text-white placeholder:text-zinc-500 focus:border-neon focus:outline-none"
        />
      </div>
    </label>
  );
}

function SubmitButton({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="flex w-full items-center justify-center gap-2 rounded-xl bg-neon px-4 py-3 text-sm font-semibold text-zinc-950 transition-colors hover:bg-neon-strong"
    >
      <span>{busy ? "Aguarde..." : children}</span>
      <ArrowRight className="h-4 w-4" />
    </button>
  );
}

function LinkButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="underline underline-offset-4 transition-colors hover:text-neon">
      {children}
    </button>
  );
}
