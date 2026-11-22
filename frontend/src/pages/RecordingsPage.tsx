import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Clock, Download, MessageSquare, Play, RotateCcw, Search, Sparkles, Trash2 } from "lucide-react";
import { api } from "../api/endpoints";
import type { MeetingDetail, MeetingStatusInfo, MeetingTimeline } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { toClock, toLogTime } from "../api/adapters";
import { IN_PROGRESS, STATUS_LABEL, formatDate, formatDuration, progressLabel, sectionMeta } from "../lib/format";
import { ChatPanel } from "../components/chat";
import { downloadText } from "../lib/download";

const FILTERS = [
  { id: "all", label: "Todas" },
  { id: "done", label: "Concluídas" },
  { id: "progress", label: "Em andamento" },
  { id: "error", label: "Com erro" },
] as const;
type Filter = (typeof FILTERS)[number]["id"];

export default function RecordingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [items, setItems] = useState<MeetingStatusInfo[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const loadList = useCallback(() => {
    api
      .meetings()
      .then((list) => {
        setItems(list);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar gravações"));
  }, []);

  useEffect(() => {
    loadList();
    const t = window.setInterval(loadList, 5000);
    return () => window.clearInterval(t);
  }, [loadList]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter((m) => {
      const byFilter =
        filter === "all" ||
        (filter === "done" && m.status === "done") ||
        (filter === "error" && m.status === "error") ||
        (filter === "progress" && IN_PROGRESS.includes(m.status));
      const byQuery = !q || m.title.toLowerCase().includes(q) || (m.summary?.overview ?? "").toLowerCase().includes(q);
      return byFilter && byQuery;
    });
  }, [items, filter, query]);

  const activeId = id ?? filtered[0]?.meeting_id;

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
        <div className="relative w-full md:max-w-sm">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar gravações ou resumos…"
            className="w-full rounded-xl border border-white/10 bg-panel py-2.5 pl-10 pr-4 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-emerald-400 focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1 rounded-xl border border-white/10 bg-panel p-1">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === f.id ? "bg-emerald-400 text-zinc-950" : "text-zinc-400 hover:text-zinc-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-xs text-rose-400">{error}</p>}

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12">
        <div className="divide-y divide-white/6 overflow-hidden rounded-2xl border border-white/10 bg-panel lg:col-span-5">
          {items === null ? (
            <p className="p-8 text-center text-sm text-zinc-400">Carregando…</p>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-sm font-medium text-zinc-300">Nenhuma gravação encontrada</p>
              <p className="mt-1 text-xs text-zinc-500">Ajuste o filtro ou inicie uma nova captura no Estúdio.</p>
            </div>
          ) : (
            filtered.map((m) => {
              const selected = activeId === m.meeting_id;
              return (
                <button
                  key={m.meeting_id}
                  type="button"
                  onClick={() => navigate(`/gravacoes/${m.meeting_id}`)}
                  className={`w-full p-4 text-left transition-colors ${selected ? "bg-white/6" : "hover:bg-white/3"}`}
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2 text-xs text-zinc-400">
                    <span className="truncate">
                      {STATUS_LABEL[m.status]} · {formatDate(m.started_at)}
                    </span>
                    <span className="font-mono-tabular shrink-0 text-zinc-300">{toClock((m.duration_minutes ?? 0) * 60)}</span>
                  </div>
                  <h3 className="mb-1 line-clamp-1 text-sm font-semibold text-white">{m.title}</h3>
                  <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
                    {m.summary?.overview || (IN_PROGRESS.includes(m.status) ? progressLabel(m.status, m.queue_position) : m.error || (m.status === "done" ? "Concluída. Abra para ver o resumo e conversar com o agente." : "Sem resumo."))}
                  </p>
                </button>
              );
            })
          )}
        </div>

        <div className="min-w-0 lg:col-span-7">
          {activeId ? (
            <Inspector key={activeId} meetingId={activeId} onDeleted={() => { loadList(); navigate("/gravacoes"); }} onChanged={loadList} />
          ) : (
            <div className="rounded-2xl border border-white/10 bg-panel px-6 py-16 text-center text-sm text-zinc-400">
              Selecione uma gravação ao lado para ver a transcrição, os itens de ação e conversar com o agente.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Campos do resumo v2 (S15-4): contribuições, tópico → decisão e questões em aberto. */
function SummaryV2({ summary }: { summary: NonNullable<MeetingDetail["summary"]> }) {
  const sections = [
    { title: "Contribuições por participante", items: (summary.contributions ?? []).map((c) => `${c.speaker}: ${c.points.join("; ")}`) },
    { title: "Tópicos e decisões", items: (summary.topic_decisions ?? []).map((t) => `${t.topic} → ${t.decision}${t.effect ? ` (${t.effect})` : ""}`) },
    { title: "Questões em aberto", items: summary.open_questions ?? [] },
  ].filter((s) => s.items.length > 0);
  if (sections.length === 0) return null;
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      {sections.map((s) => (
        <div key={s.title}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">{s.title}</h3>
          <ul className="space-y-1.5 text-xs leading-relaxed text-zinc-300">
            {s.items.map((item, i) => <li key={i}>• {item}</li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Transcrição com cada fala endereçável: ?t=hh:mm (vindo de uma citação) rola até ela e a destaca. */
function Transcript({ text, at }: { text: string; at: string | null }) {
  const lines = useMemo(() => text.split("\n"), [text]);
  const target = at ? lines.findIndex((l) => l.startsWith(`[${at}]`) || l.startsWith(`[${at}:`)) : -1;
  useEffect(() => {
    if (target >= 0) document.getElementById(`fala-${target}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [target]);
  return (
    <div className="max-h-64 overflow-y-auto pr-1 text-sm leading-relaxed text-zinc-300">
      {lines.map((l, i) => (
        <p key={i} id={`fala-${i}`} className={`whitespace-pre-wrap rounded px-1 ${i === target ? "bg-emerald-400/15 text-zinc-100" : ""}`}>
          {l}
        </p>
      ))}
    </div>
  );
}

function Inspector({ meetingId, onDeleted, onChanged }: { meetingId: string; onDeleted: () => void; onChanged: () => void }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("aba") === "chat" ? "chat" : "resumo";
  const [m, setM] = useState<MeetingDetail | null>(null);
  const [status, setStatus] = useState<MeetingStatusInfo | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setM(await api.meeting(meetingId));
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Erro ao carregar a gravação" });
    }
  }, [meetingId]);

  useEffect(() => {
    void load();
  }, [load]);

  const inProgress = !!m && IN_PROGRESS.includes(m.status);
  useEffect(() => {
    if (!inProgress) return;
    let last = m?.status;
    const tick = async () => {
      try {
        const s = await api.meetingStatus(meetingId);
        setStatus(s);
        if (s.status !== last) {
          last = s.status;
          await load();
          onChanged();
        }
      } catch {
        // tenta de novo no próximo ciclo
      }
    };
    void tick();
    const t = window.setInterval(tick, 5000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId, inProgress]);

  if (!m) {
    return <div className="rounded-2xl border border-white/10 bg-panel px-6 py-16 text-center text-sm text-zinc-400">{notice?.text ?? "Carregando…"}</div>;
  }

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      setNotice({ ok: true, text: ok });
      await load();
      onChanged();
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Falha na operação" });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteMeeting(meetingId);
      onDeleted();
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Não foi possível apagar" });
      setBusy(false);
    }
  };

  const current = status ?? m;
  const summary = m.summary;
  const setTab = (t: "resumo" | "chat") => setParams(t === "chat" ? { aba: "chat" } : {});
  // O chat com o agente fica no Estúdio Ao Vivo: abre lá, já com esta reunião selecionada.
  const openInStudio = () => navigate(`/estudio?reuniao=${meetingId}`);

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-white/10 bg-panel p-4 sm:p-6">
        <div className="flex flex-col justify-between gap-4 border-b border-white/8 pb-5 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-zinc-400">
              <span>{STATUS_LABEL[m.status]}</span>
              <span aria-hidden="true">·</span>
              <span>{formatDate(m.started_at)}</span>
              <span aria-hidden="true">·</span>
              <span className="font-mono-tabular inline-flex items-center gap-1 text-zinc-300">
                <Clock className="h-3 w-3" />
                {toClock((m.duration_minutes ?? 0) * 60)}
              </span>
            </div>
            <h2 className="text-lg font-semibold text-white sm:text-xl">{m.title}</h2>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {m.status === "error" && m.has_audio && (
              <button type="button" disabled={busy} onClick={() => run(() => api.reprocess(meetingId), "Reprocessamento iniciado.")} className="flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-white/15 bg-white/5 px-3.5 py-2 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10">
                <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
                <span>Reprocessar áudio</span>
              </button>
            )}
            {m.status === "done" && (
              <button type="button" onClick={() => (tab === "chat" ? setTab("resumo") : openInStudio())} className="flex items-center gap-1.5 whitespace-nowrap rounded-xl bg-emerald-400 px-3.5 py-2 text-xs font-semibold text-zinc-950 transition-colors hover:bg-emerald-300">
                <MessageSquare className="h-3.5 w-3.5" />
                <span>{tab === "chat" ? "Ver resumo" : "Abrir no Chat do Agente"}</span>
              </button>
            )}
            {confirmDelete ? (
              <>
                <button type="button" onClick={remove} className="whitespace-nowrap rounded-xl bg-rose-500 px-3 py-2 text-xs font-semibold text-on-color hover:bg-rose-600">
                  Apagar definitivamente
                </button>
                <button type="button" onClick={() => setConfirmDelete(false)} className="rounded-xl px-2 py-2 text-xs text-zinc-400 hover:text-zinc-100">
                  Cancelar
                </button>
              </>
            ) : (
              <button
                type="button"
                aria-label="Excluir gravação"
                disabled={inProgress}
                title={inProgress ? "Espere o processamento terminar para apagar" : undefined}
                onClick={() => setConfirmDelete(true)}
                className="rounded-xl border border-white/10 p-2 text-zinc-400 transition-colors hover:border-rose-400/40 hover:text-rose-400"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {confirmDelete && <p className="pt-3 text-xs text-zinc-400">Apaga a gravação, o resumo, a transcrição, a conversa e os arquivos gerados.</p>}
        {notice && <p className={`pt-3 text-xs ${notice.ok ? "text-emerald-400" : "text-rose-400"}`}>{notice.text}</p>}

        {inProgress && (
          <div className="mt-5 rounded-xl border border-white/8 bg-black/25 px-4 py-3">
            {current.stalled ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-amber-300">⚠️ {progressLabel(current.status)} parou: nenhum worker está processando. Um serviço pode ter reiniciado.</p>
                <button type="button" disabled={busy} onClick={() => run(() => api.resume(meetingId), "Processamento retomado.")} className="flex items-center gap-1.5 rounded-xl bg-emerald-400 px-3 py-1.5 text-xs font-semibold text-zinc-950">
                  <RotateCcw className="h-3.5 w-3.5" /> Retomar
                </button>
              </div>
            ) : (
              <p className="text-xs text-zinc-300">
                {progressLabel(current.status, current.queue_position)}…
                {current.stage_elapsed_s != null ? ` · há ${formatDuration(current.stage_elapsed_s)}` : ""}
                {current.stage_typical_s != null ? ` · costuma levar ${formatDuration(current.stage_typical_s)}` : ""}
              </p>
            )}
          </div>
        )}

        {m.status === "error" && <p className="mt-5 text-xs text-rose-400">Falha: {m.error}</p>}
        <Diagnostics meetingId={meetingId} />

        {tab === "resumo" && m.status === "done" && (
          <div className="mt-6 space-y-6">
            <div className="flex items-center justify-between gap-4 rounded-xl border border-white/8 bg-black/25 px-4 py-3">
              <div className="flex items-center gap-3">
                <button type="button" onClick={openInStudio} aria-label="Conversar sobre a gravação no Estúdio" className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300 transition-colors hover:bg-emerald-400/25">
                  <Play className="h-3.5 w-3.5 fill-current" />
                </button>
                <div>
                  <p className="text-xs font-medium text-zinc-200">Transcrição indexada e pronta para consulta</p>
                  <p className="text-xs text-zinc-400">{m.participants?.length || 0} participante(s) identificados</p>
                </div>
              </div>
              <span className="font-mono-tabular text-xs text-zinc-400">{toClock((m.duration_minutes ?? 0) * 60)}</span>
            </div>

            {summary ? (
              <>
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">Resumo executivo</h3>
                  <p className="text-sm leading-relaxed text-zinc-200">{summary.overview}</p>
                </div>

                {summary.topics.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">Tópicos</h3>
                    <ul className="space-y-1 text-xs text-zinc-300">
                      {summary.topics.map((t, i) => <li key={i}>• {t}</li>)}
                    </ul>
                  </div>
                )}

                <div className="grid grid-cols-1 gap-6 pt-2 md:grid-cols-2">
                  <div>
                    <h3 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Decisões registradas</h3>
                    {summary.decisions.length === 0 ? (
                      <p className="text-xs text-zinc-500">Nenhuma decisão.</p>
                    ) : (
                      <ul className="space-y-2 text-xs text-zinc-300">
                        {summary.decisions.map((d, i) => (
                          <li key={i} className="leading-relaxed">
                            <details>
                              <summary className="cursor-pointer">
                                • {d.description}
                                {d.status ? <span className="ml-1 text-zinc-500">({d.status})</span> : null}
                              </summary>
                              <p className="mt-1 pl-3 text-zinc-500">{d.context || "Sem contexto adicional."}</p>
                            </details>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <ActionItems meetingId={meetingId} m={m} onChanged={load} />
                </div>

                <SummaryV2 summary={summary} />

                {summary.extra_sections &&
                  Object.entries(summary.extra_sections).map(([key, value]) => {
                    const meta = sectionMeta(key);
                    return (
                      <div key={key}>
                        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                          {meta.emoji} {meta.label}
                        </h3>
                        {Array.isArray(value) ? (
                          <ul className="space-y-1 text-xs text-zinc-300">
                            {value.map((item, i) => (
                              <li key={i}>• {typeof item === "object" && item !== null ? Object.values(item as Record<string, unknown>).join(" — ") : String(item)}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-xs leading-relaxed text-zinc-300">{typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
                        )}
                      </div>
                    );
                  })}
              </>
            ) : (
              <p className="text-sm text-zinc-400">Esta gravação não tem resumo.</p>
            )}

            {m.transcript && (
              <div className="border-t border-white/8 pt-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Transcrição completa</h3>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => api.downloadMarkdown(meetingId, m.title).catch(() => setNotice({ ok: false, text: "Não foi possível baixar o resumo" }))} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-white/5">
                      <Download className="h-3.5 w-3.5" /> Resumo (.md)
                    </button>
                    <button type="button" onClick={() => downloadText(m.transcript ?? "", `${m.title}_transcricao.txt`)} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-white/5">
                      <Download className="h-3.5 w-3.5" /> Transcrição (.txt)
                    </button>
                  </div>
                </div>
                <Transcript text={m.transcript} at={params.get("t")} />
              </div>
            )}
          </div>
        )}
      </div>

      {tab === "chat" && m.status === "done" && <ChatPanel meetingId={meetingId} />}
    </div>
  );
}

function ActionItems({ meetingId, m, onChanged }: { meetingId: string; m: MeetingDetail; onChanged: () => Promise<void> }) {
  const tasks = m.summary?.tasks ?? [];
  const [pending, setPending] = useState<Record<number, boolean>>({});
  const [to, setTo] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [sending, setSending] = useState(false);

  const toggle = async (index: number, done: boolean) => {
    setPending((p) => ({ ...p, [index]: done }));
    try {
      await api.setTaskDone(meetingId, index, done);
      await onChanged();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Não foi possível salvar" });
    } finally {
      setPending((p) => {
        const { [index]: _drop, ...rest } = p;
        return rest;
      });
    }
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!to.trim()) return;
    setSending(true);
    try {
      const r = await api.emailTasks(meetingId, to.trim());
      setMsg({ ok: true, text: `Tarefas enviadas para ${r.to}.` });
      setTo("");
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Não foi possível enviar" });
    } finally {
      setSending(false);
    }
  };

  return (
    <div>
      <h3 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Itens de ação</h3>
      {tasks.length === 0 ? (
        <p className="text-xs text-zinc-500">Nenhuma tarefa.</p>
      ) : (
        <div className="space-y-2">
          {tasks.map((t, i) => {
            const done = pending[i] ?? !!t.done;
            return (
              <label key={i} className="flex cursor-pointer items-start gap-2.5 border-b border-white/6 pb-2 text-xs last:border-0">
                <input type="checkbox" className="mt-0.5 accent-emerald-400" checked={done} onChange={(e) => void toggle(i, e.target.checked)} />
                <span>
                  <span className={`block font-medium ${done ? "text-zinc-500 line-through" : "text-zinc-200"}`}>{t.description}</span>
                  <span className="mt-0.5 block text-zinc-400">
                    {t.responsible || "Sem responsável"}
                    {t.deadline ? ` · prazo ${t.deadline}` : ""}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}
      {tasks.length > 0 && (
        <form onSubmit={send} className="mt-3 flex gap-2">
          <input
            type="email"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="Enviar tarefas para pessoa@empresa.com"
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-emerald-400 focus:outline-none"
          />
          <button type="submit" disabled={sending || !to.trim()} className="shrink-0 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs text-zinc-100 hover:bg-white/15">
            {sending ? "Enviando…" : "Enviar"}
          </button>
        </form>
      )}
      {msg && <p className={`mt-2 text-xs ${msg.ok ? "text-emerald-400" : "text-rose-400"}`}>{msg.text}</p>}
    </div>
  );
}

function Diagnostics({ meetingId }: { meetingId: string }) {
  const { user } = useAuth();
  const [data, setData] = useState<MeetingTimeline | null>(null);
  const [error, setError] = useState("");
  if (user?.role !== "admin") return null;

  const load = () => {
    if (data) return;
    api
      .meetingTimeline(meetingId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar o diagnóstico"));
  };

  return (
    <details className="mt-5 rounded-xl border border-white/8 bg-black/20 px-4 py-3" onToggle={(e) => (e.currentTarget.open ? load() : undefined)}>
      <summary className="cursor-pointer text-xs font-medium text-zinc-300">Diagnóstico (administrador)</summary>
      {error && <p className="mt-3 text-xs text-rose-400">{error}</p>}
      {!data && !error && <p className="mt-3 text-xs text-zinc-500">Carregando…</p>}
      {data && (
        <div className="mt-3 space-y-3 text-xs">
          {data.metrics && Object.keys(data.metrics).length > 0 && (
            <p className="font-mono-tabular text-zinc-300">
              {Object.entries(data.metrics)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ")}
            </p>
          )}
          {data.logs.length === 0 ? (
            <p className="text-zinc-500">Nenhum log desta reunião (os logs ficam no Redis, só no modo colaborativo).</p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-y-auto pr-1 font-mono-tabular">
              {data.logs.map((l, i) => (
                <li key={l.id ?? i} className={l.level === "ERROR" ? "text-rose-400" : l.level === "WARNING" ? "text-amber-300" : "text-zinc-400"}>
                  {toLogTime(l.ts)} [{l.service}] {l.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </details>
  );
}

