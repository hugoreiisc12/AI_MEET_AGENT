import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Lock, Loader2 } from "lucide-react";
import MorphOrb from "../components/ref/ai-thinking-org-and-input";
import { AnswerText } from "../components/answer-text";
import SculptureHero from "../components/ref/liquid-sculpture-hero";
import { BotPanel, UploadPanel } from "../components/intake";
import { api } from "../api/endpoints";
import type { ChatMessage, MeetingDetail, MeetingStatus, MeetingStatusInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { toClock } from "../api/adapters";
import { IN_PROGRESS, formatDate } from "../lib/format";
import { useOrbSpeed } from "../lib/prefs";
import { useTheme } from "../lib/theme";

// Título de status mostrado sobre a escultura, por etapa do pipeline.
const STAGE: Record<MeetingStatus, { title: string; hint: string; tone: string }> = {
  pending: { title: "Na fila", hint: "Aguardando um worker livre.", tone: "text-zinc-300" },
  recording: { title: "Bot gravando", hint: "O bot está na reunião. A transcrição começa quando ela terminar.", tone: "text-rose-300" },
  transcribing: { title: "Transcrevendo", hint: "O áudio está sendo transcrito. Acompanhe o texto ao lado.", tone: "text-amber-300" },
  summarizing: { title: "Gerando o resumo", hint: "Transcrição pronta. O agente está validando decisões e tarefas.", tone: "text-sky-300" },
  done: { title: "Resumo pronto", hint: "Reunião validada e liberada para consulta no chat.", tone: "text-emerald-300" },
  error: { title: "Falha no processamento", hint: "Abra a reunião em Gravações para reprocessar.", tone: "text-rose-400" },
};

export default function StudioPage() {
  const { config, mode } = useAuth();
  const [theme] = useTheme();
  const collab = mode === "collab";
  const [meetings, setMeetings] = useState<MeetingStatusInfo[]>([]);
  // ?reuniao=<id> (vindo de Gravações → Abrir no Chat do Agente) fixa a reunião e leva ao chat.
  const [params] = useSearchParams();
  const requested = params.get("reuniao") ?? "";
  const [trackedId, setTrackedId] = useState(requested);
  const pinned = useRef(!!requested);

  useEffect(() => {
    if (requested) {
      pinned.current = true;
      setTrackedId(requested);
    }
  }, [requested]);

  const loadList = useCallback(() => {
    api
      .meetings()
      .then((list) => {
        setMeetings(list);
        // Sem escolha do usuário, acompanha a reunião em andamento; senão, a mais recente.
        if (!pinned.current) {
          const active = list.find((m) => IN_PROGRESS.includes(m.status));
          setTrackedId((active ?? list[0])?.meeting_id ?? "");
        }
      })
      .catch(() => setMeetings([]));
  }, []);

  useEffect(() => {
    loadList();
    const t = window.setInterval(loadList, 4000);
    return () => window.clearInterval(t);
  }, [loadList]);

  const tracked = meetings.find((m) => m.meeting_id === trackedId) ?? null;

  return (
    <div className="space-y-6">
      <div className={`grid grid-cols-1 gap-6 ${collab ? "" : "lg:grid-cols-12"}`}>
        <div className={collab ? "" : "lg:col-span-7"}>
          <BotPanel calendarEnabled={!!config?.calendar_enabled} />
        </div>
        {!collab && (
          <div className="lg:col-span-5">
            <UploadPanel maxMb={config?.max_upload_mb ?? 500} formats={config?.audio_formats ?? []} />
          </div>
        )}
      </div>

      <section className="overflow-hidden rounded-2xl border border-white/10 bg-panel">
        <div className="flex flex-col gap-3 border-b border-white/8 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0">
            {tracked ? (
              <>
                <p className={`flex items-center gap-2 text-lg font-semibold sm:text-xl ${STAGE[tracked.status].tone}`}>
                  {IN_PROGRESS.includes(tracked.status) && <Loader2 className="h-4 w-4 animate-spin" />}
                  {tracked.status === "recording" && <span className="h-2 w-2 animate-pulse rounded-full bg-rose-400" />}
                  {STAGE[tracked.status].title}
                  {tracked.queue_position ? <span className="text-sm font-normal text-zinc-400">· {tracked.queue_position}º na fila</span> : null}
                </p>
                <p className="mt-0.5 truncate text-xs text-zinc-400">
                  {tracked.title} · {STAGE[tracked.status].hint}
                </p>
              </>
            ) : (
              <>
                <p className="text-lg font-semibold text-zinc-300 sm:text-xl">Nenhuma reunião ainda</p>
                <p className="mt-0.5 text-xs text-zinc-400">Mande o bot para uma reunião para acompanhar o andamento aqui.</p>
              </>
            )}
          </div>
          {meetings.length > 0 && (
            <select
              value={trackedId}
              onChange={(e) => {
                pinned.current = true;
                setTrackedId(e.target.value);
              }}
              aria-label="Reunião acompanhada"
              className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-zinc-100 focus:border-emerald-400 focus:outline-none sm:w-64"
            >
              {meetings.map((m) => (
                <option key={m.meeting_id} value={m.meeting_id}>
                  {m.title} · {formatDate(m.started_at)}
                </option>
              ))}
            </select>
          )}
        </div>
        <SculptureHero
          theme={theme}
          themeToggle={false}
          showNav={false}
          eyebrow=""
          headline=""
          headlineAccent=""
          body=""
          primaryCta={{ label: "", href: "" }}
          secondaryCta={{ label: "", href: "" }}
          hint=""
          hintTouch=""
          height="300px"
          minHeight="240px"
        />
      </section>

      {tracked ? (
        <TrackedMeeting key={tracked.meeting_id} meeting={tracked} onChanged={loadList} focusChat={tracked.meeting_id === requested} />
      ) : (
        <div className="rounded-2xl border border-white/10 bg-panel px-6 py-12 text-center text-sm text-zinc-400">
          A transcrição e o chat aparecem aqui quando houver uma reunião.
        </div>
      )}
    </div>
  );
}

function TrackedMeeting({ meeting, onChanged, focusChat }: { meeting: MeetingStatusInfo; onChanged: () => void; focusChat: boolean }) {
  const [orbSpeed] = useOrbSpeed();
  const [segments, setSegments] = useState<{ start: number; end: number; text: string }[]>([]);
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const status = meeting.status;
  const endRef = useRef<HTMLDivElement>(null);

  // Transcrevendo: lê os trechos parciais a cada 2 s. Depois disso, a transcrição final vem do detalhe.
  useEffect(() => {
    if (status !== "transcribing") return;
    let alive = true;
    const tick = () =>
      api
        .live(meeting.meeting_id)
        .then((r) => {
          if (!alive) return;
          setSegments(r.segments);
          if (r.status !== "transcribing") onChanged();
        })
        .catch(() => {});
    void tick();
    const t = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [status, meeting.meeting_id, onChanged]);

  useEffect(() => {
    if (status === "summarizing" || status === "done" || status === "error") {
      api.meeting(meeting.meeting_id).then(setDetail).catch(() => setDetail(null));
    }
  }, [status, meeting.meeting_id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [segments.length]);

  const finalText = detail?.transcript ?? "";

  return (
    <div className="grid grid-cols-1 items-stretch gap-6 lg:grid-cols-12">
      <section className="flex min-h-[420px] flex-col rounded-2xl border border-white/10 bg-panel p-4 sm:p-5 lg:col-span-5 lg:min-h-[540px]">
        <div className="border-b border-white/8 pb-4">
          <h2 className="text-base font-semibold text-white">Transcrição em tempo real</h2>
          <p className="mt-0.5 text-xs text-zinc-400">
            {status === "transcribing"
              ? `${segments.length} trecho(s) reconhecido(s) até agora`
              : status === "summarizing" || status === "done"
                ? "Transcrição completa"
                : "Aguardando o áudio da reunião"}
          </p>
        </div>

        <div className="max-h-[440px] flex-1 space-y-3 overflow-y-auto py-4 pr-1">
          {(status === "pending" || status === "recording") && (
            <Placeholder text={status === "recording" ? "O bot está gravando. O texto aparece aqui assim que a transcrição começar." : "Na fila para transcrever."} />
          )}

          {status === "transcribing" &&
            (segments.length === 0 ? (
              <Placeholder text="Processando o áudio… os primeiros trechos aparecem em instantes." spinning />
            ) : (
              <>
                {segments.map((s, i) => (
                  <div key={i} className="border-b border-white/5 pb-3 last:border-0">
                    <span className="font-mono-tabular text-xs text-emerald-400">{toClock(s.start)}</span>
                    <p className="text-sm leading-relaxed text-zinc-300">{s.text}</p>
                  </div>
                ))}
                <p className="flex items-center gap-2 text-xs italic text-zinc-400">
                  <Loader2 className="h-3 w-3 animate-spin" /> Transcrevendo…
                </p>
                <div ref={endRef} />
              </>
            ))}

          {(status === "summarizing" || status === "done") &&
            (finalText ? (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-300">{finalText}</pre>
            ) : (
              <Placeholder text="Carregando a transcrição…" spinning />
            ))}

          {status === "error" && <p className="text-sm text-rose-400">{detail?.error || meeting.error || "Falha no processamento."}</p>}
        </div>
      </section>

      <MeetingChat meeting={meeting} speed={orbSpeed} detail={detail} focus={focusChat} />
    </div>
  );
}

function MeetingChat({ meeting, speed, detail, focus }: { meeting: MeetingStatusInfo; speed: number; detail: MeetingDetail | null; focus: boolean }) {
  const navigate = useNavigate();
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (focus) sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus]);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const ready = meeting.status === "done";

  useEffect(() => {
    if (detail) setHistory(detail.chat_history);
  }, [detail]);

  const ask = async (question: string): Promise<string> => {
    try {
      const res = await api.chat(meeting.meeting_id, question);
      const m = await api.meeting(meeting.meeting_id);
      setHistory(m.chat_history);
      return res.answer;
    } catch (err) {
      return err instanceof Error ? err.message : "Não foi possível consultar o agente neste momento.";
    }
  };

  const turns: { q: string; a: string }[] = [];
  for (let i = history.length - 1; i > 0 && turns.length < 3; i--) {
    if (history[i].role === "assistant" && history[i - 1].role === "user") {
      turns.push({ q: history[i - 1].content, a: history[i].content });
      i--;
    }
  }

  return (
    <section ref={sectionRef} id="chat-agente" className="flex min-h-[420px] scroll-mt-24 flex-col rounded-2xl border border-white/10 bg-panel p-4 sm:p-5 lg:col-span-7 lg:min-h-[540px]">
      <div className="mb-4 border-b border-white/8 pb-4">
        <h2 className="text-base font-semibold text-white">Chat interativo com o agente</h2>
        <p className="mt-0.5 truncate text-xs text-zinc-400">
          {ready ? `Consultando: ${meeting.title}` : "Liberado quando o resumo estiver pronto e validado"}
        </p>
      </div>

      <div className="relative min-h-[360px] flex-1 overflow-hidden rounded-2xl border border-white/8">
        {ready ? (
          <MorphOrb
            speed={speed}
            minThinkMs={2200}
            placeholder="Pergunte sobre esta reunião…"
            labels={["Ouvindo", "Buscando", "Analisando", "Compondo"]}
            doneLabel="Concluído"
            answerTitle="Síntese Sona"
            resetLabel="Nova pergunta"
            sendLabel="Enviar pergunta"
            onSubmit={ask}
          />
        ) : (
          <div className="flex h-full min-h-[360px] flex-col items-center justify-center gap-3 bg-[radial-gradient(circle_at_50%_42%,rgba(16,185,129,0.06),transparent_58%)] px-6 text-center">
            <Lock className="h-6 w-6 text-zinc-500" />
            <p className="text-sm text-zinc-300">{STAGE[meeting.status].title}</p>
            <p className="max-w-xs text-xs text-zinc-500">
              {meeting.status === "error" ? "A reunião falhou e não pode ser consultada." : "O chat abre sozinho quando o resumo terminar."}
            </p>
          </div>
        )}
      </div>

      {ready && turns.length > 0 && (
        <div className="mt-4 border-t border-white/8 pt-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-medium text-zinc-400">Últimas respostas registradas</p>
            <button type="button" onClick={() => navigate(`/gravacoes/${meeting.meeting_id}?aba=chat`)} className="text-xs text-emerald-400 hover:text-emerald-300">
              Abrir conversa completa
            </button>
          </div>
          <div className="max-h-28 space-y-2 overflow-y-auto pr-1">
            {turns.map((t, i) => (
              <div key={i} className="rounded-xl border border-white/6 bg-black/25 px-3 py-2 text-xs">
                <p className="truncate font-medium text-zinc-200">{t.q}</p>
                <p className="line-clamp-3 whitespace-pre-wrap text-zinc-300">
                  <AnswerText
                    text={t.a}
                    meetingId={meeting.meeting_id}
                    onReply={(q) => navigate(`/gravacoes/${meeting.meeting_id}?aba=chat&responder=${encodeURIComponent(q)}`)}
                  />
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function Placeholder({ text, spinning = false }: { text: string; spinning?: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      {spinning && <Loader2 className="h-4 w-4 animate-spin text-emerald-400" />}
      <p className="max-w-xs text-xs text-zinc-400">{text}</p>
    </div>
  );
}
