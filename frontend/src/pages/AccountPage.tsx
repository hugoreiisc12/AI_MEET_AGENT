import { useEffect, useState, type FormEvent } from "react";
import { Trash2 } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/endpoints";
import type { MemoryNote, Session, User } from "../api/types";
import { Alert, Button, Card, Empty, Field, Initials, Input, Select, Spinner } from "../components/ui";
import { formatDate } from "../lib/format";

const MIN_PASSWORD = 8;
type Notice = { tone: "success" | "error"; text: string } | null;

export default function AccountPage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="space-y-6">
      <section className="flex items-center gap-4 rounded-2xl border border-white/10 bg-panel p-4 sm:p-6">
        <Initials name={user.name} size="h-14 w-14" />
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-white">{user.name}</h2>
          <p className="truncate text-xs text-zinc-400">
            {user.email} · conta criada em {formatDate(user.created_at)}
            {user.role === "admin" ? " · administrador" : ""}
          </p>
        </div>
      </section>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <MemoryCard />
          <SessionsCard />
        </div>
        <div className="space-y-6 lg:col-span-5">
          <PasswordCard />
          {user.role === "admin" && <AdminPurgeCard />}
        </div>
      </div>
    </div>
  );
}

function MemoryCard() {
  const [notes, setNotes] = useState<MemoryNote[] | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const load = () => api.memory().then(setNotes).catch((e) => setNotice({ tone: "error", text: e instanceof Error ? e.message : "Erro" }));
  useEffect(() => {
    void load();
  }, []);

  return (
    <Card title="Memória do agente" subtitle='O que você pediu para o agente lembrar no chat; vale em todas as suas reuniões. Ex.: "lembre que prefiro atas em tópicos".'>
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {!notes && !notice && <Spinner />}
      {notes && notes.length === 0 && <Empty title="Nenhuma nota ainda." />}
      {notes && notes.length > 0 && (
        <ul className="divide-y divide-white/8">
          {notes.map((n) => (
            <li key={n.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="text-sm text-zinc-100">{n.text}</p>
                <p className="text-xs text-zinc-500">{formatDate(n.created_at)}</p>
              </div>
              <Button
                variant="ghost"
                aria-label="Apagar nota"
                onClick={() =>
                  api.deleteMemory(n.id).then(load).catch((e) => setNotice({ tone: "error", text: e instanceof Error ? e.message : "Erro" }))
                }
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SessionsCard() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const fail = (e: unknown) => setNotice({ tone: "error", text: e instanceof Error ? e.message : "Erro" });
  const load = () => api.sessions().then(setSessions).catch(fail);
  useEffect(() => {
    void load();
  }, []);

  const others = (sessions ?? []).filter((s) => !s.current);

  return (
    <Card title="Sessões abertas" subtitle="Cada navegador ou aparelho em que você entrou. Encerrar uma sessão pede login de novo nela.">
      {!sessions && !notice && <Spinner />}
      {sessions && (
        <ul className="divide-y divide-white/8">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="truncate text-sm text-zinc-100">
                  {s.current ? "Esta sessão" : "Outra sessão"}
                  {s.ip ? ` · ${s.ip}` : ""}
                </p>
                <p className="truncate text-xs text-zinc-500">
                  Entrou em {formatDate(s.created_at)} · expira em {formatDate(s.expires_at)}
                </p>
              </div>
              {!s.current && <Button onClick={() => api.endSession(s.id).then(load).catch(fail)}>Encerrar</Button>}
            </li>
          ))}
        </ul>
      )}
      {others.length > 0 && (
        <div className="mt-5 space-y-3 border-t border-white/8 pt-4">
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input type="checkbox" className="accent-emerald-400" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            Confirmo: encerrar as outras {others.length} sessões
          </label>
          <Button
            variant="danger"
            disabled={!confirm}
            onClick={() =>
              api
                .endOtherSessions()
                .then((r) => {
                  setNotice({ tone: "success", text: `${r.count} sessões encerradas. Esta continua aberta.` });
                  setConfirm(false);
                  return load();
                })
                .catch(fail)
            }
          >
            Encerrar todas as outras sessões
          </Button>
        </div>
      )}
      {notice && <div className="mt-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
    </Card>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== again) {
      setNotice({ tone: "error", text: "As senhas não conferem." });
      return;
    }
    setBusy(true);
    try {
      const r = await api.changePassword(current, next);
      setNotice({ tone: "success", text: `Senha trocada. ${r.count} outras sessões foram encerradas.` });
      setCurrent("");
      setNext("");
      setAgain("");
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Não foi possível trocar a senha" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Trocar senha">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Senha atual">
          <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </Field>
        <Field label={`Nova senha (mínimo de ${MIN_PASSWORD} caracteres)`}>
          <Input type="password" autoComplete="new-password" minLength={MIN_PASSWORD} value={next} onChange={(e) => setNext(e.target.value)} required />
        </Field>
        <Field label="Repita a nova senha">
          <Input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        </Field>
        {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
        <Button type="submit" variant="primary" busy={busy}>Trocar senha</Button>
      </form>
    </Card>
  );
}

function AdminPurgeCard() {
  const [scope, setScope] = useState<"expired" | "user" | "all_but_mine">("expired");
  const [users, setUsers] = useState<User[]>([]);
  const [userId, setUserId] = useState("");
  const [typed, setTyped] = useState("");
  const [notice, setNotice] = useState<Notice>(null);

  useEffect(() => {
    api
      .users()
      .then((list) => {
        setUsers(list);
        setUserId(list[0]?.id ?? "");
      })
      .catch(() => setUsers([]));
  }, []);

  const run = async () => {
    try {
      const r = await api.purgeSessions(scope, userId);
      setNotice({ tone: "success", text: `${r.count} sessões apagadas.` });
      setTyped("");
    } catch (e) {
      setNotice({ tone: "error", text: e instanceof Error ? e.message : "Erro" });
    }
  };

  return (
    <Card title="Administração: limpar sessões" subtitle={`Apaga só sessões: nenhum usuário nem reunião é afetado, e a sua continua. ${users.length} conta(s) cadastradas.`}>
      <div className="space-y-4">
        <Field label="O que limpar">
          <Select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="expired">Sessões vencidas</option>
            <option value="user">Todas as sessões de um usuário</option>
            <option value="all_but_mine">Todas, exceto a minha</option>
          </Select>
        </Field>
        {scope === "user" && (
          <Field label="Usuário">
            <Select value={userId} onChange={(e) => setUserId(e.target.value)}>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.email})
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Digite LIMPAR para confirmar">
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} />
        </Field>
        <Button variant="danger" disabled={typed !== "LIMPAR"} onClick={run}>
          Limpar sessões
        </Button>
        {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      </div>
    </Card>
  );
}
