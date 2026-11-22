import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CornerDownRight } from "lucide-react";
import { api } from "../api/endpoints";

// Formatos do contrato (§20): "[hh:mm] Nome:" (reunião aberta) e "[Título · dd/mm/aaaa · hh:mm] Nome:".
const CITATION = /\[([^\]\n·]+?) · (\d{2}\/\d{2}\/\d{4}) · (\d{1,2}:\d{2}(?::\d{2})?)\]|\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g;
const QUESTIONS_HEAD = /perguntas para voc[êe]/i;
const LIST_ITEM = /^\s*(?:[-•*]|\d+[.)])\s+(.+)$/;

function ddmmyyyy(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
}

/** Abre a reunião citada no trecho. Outra reunião é achada pelo título e pela data, entre as do usuário. */
function Citation({ label, meetingId, title, date, time }: { label: string; meetingId: string; title?: string; date?: string; time: string }) {
  const navigate = useNavigate();
  const [missing, setMissing] = useState(false);
  const open = async () => {
    let id = meetingId;
    if (title && date) {
      const list = await api.meetings().catch(() => []);
      const found = list.find((m) => m.title.trim() === title.trim() && ddmmyyyy(m.started_at) === date);
      if (!found) {
        setMissing(true);
        return;
      }
      id = found.meeting_id;
    }
    navigate(`/gravacoes/${id}?t=${encodeURIComponent(time)}`);
  };
  return (
    <button
      type="button"
      onClick={open}
      title={missing ? "Reunião não encontrada entre as suas" : "Abrir a reunião neste trecho"}
      className={`rounded px-0.5 font-mono-tabular text-emerald-300 underline decoration-emerald-400/40 underline-offset-2 hover:text-emerald-200 ${missing ? "line-through opacity-60" : ""}`}
    >
      {label}
    </button>
  );
}

function Line({ text, meetingId }: { text: string; meetingId: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(CITATION)) {
    parts.push(text.slice(last, m.index));
    parts.push(
      <Citation key={m.index} label={m[0]} meetingId={meetingId} title={m[1]} date={m[2]} time={m[3] ?? m[4]} />,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

/** Resposta do agente com citações clicáveis e as "Perguntas para você" (§10.1) como botões de resposta. */
export function AnswerText({ text, meetingId, onReply }: { text: string; meetingId: string; onReply?: (question: string) => void }) {
  const lines = text.split("\n");
  const head = lines.findIndex((l) => QUESTIONS_HEAD.test(l));
  const questions = head < 0 ? [] : lines.slice(head + 1).map((l) => LIST_ITEM.exec(l)?.[1]).filter((q): q is string => !!q);
  const body = head < 0 || questions.length === 0 ? lines : lines.slice(0, head);
  return (
    <>
      {body.map((l, i) => (
        <span key={i}>
          <Line text={l} meetingId={meetingId} />
          {i < body.length - 1 && "\n"}
        </span>
      ))}
      {questions.length > 0 && (
        <span className="mt-3 block border-t border-white/8 pt-2">
          <span className="mb-1.5 block text-xs font-semibold text-zinc-400">Perguntas para você</span>
          {questions.map((q, i) =>
            onReply ? (
              <button key={i} type="button" onClick={() => onReply(q)} className="mb-1 flex w-full items-start gap-1.5 rounded-lg border border-emerald-400/20 bg-emerald-400/5 px-2.5 py-1.5 text-left text-xs text-zinc-200 hover:bg-emerald-400/10">
                <CornerDownRight className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" aria-hidden="true" />
                <span><Line text={q} meetingId={meetingId} /></span>
              </button>
            ) : (
              <span key={i} className="block text-xs text-zinc-300">• <Line text={q} meetingId={meetingId} /></span>
            ),
          )}
        </span>
      )}
    </>
  );
}
