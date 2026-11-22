import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { AnswerText } from "./answer-text";
import { Download, Send, Trash2 } from "lucide-react";
import { api } from "../api/endpoints";
import type { ChatAction, ChatMessage, MeetingDetail } from "../api/types";
import { Alert, Button, Card, Empty, Spinner, TextArea } from "./ui";
import { ApiError } from "../api/client";

export function ChatPanel({ meetingId }: { meetingId: string }) {
  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [params] = useSearchParams();
  // Vindo de uma pergunta do agente no Estúdio: a resposta já começa escrita.
  const [question, setQuestion] = useState(() => (params.get("responder") ? `Sobre "${params.get("responder")}": ` : ""));
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const reply = (q: string) => {
    setQuestion(`Sobre "${q}": `);
    inputRef.current?.focus();
  };
  const [busy, setBusy] = useState(false);
  const [partial, setPartial] = useState("");
  const [notice, setNotice] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const load = () => api.meeting(meetingId).then(setMeeting);

  useEffect(() => {
    void load().catch((e) => setNotice({ tone: "error", text: e instanceof Error ? e.message : "Erro" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [meeting?.chat_history.length, partial]);

  if (!meeting) return <Spinner />;

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setBusy(true);
    setNotice(null);
    setQuestion("");
    setPartial("");
    try {
      await api.chatStream(meetingId, q, (text) => setPartial((p) => p + text));
      await load();
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Não foi possível consultar o agente" });
      setQuestion(q);
    } finally {
      setBusy(false);
      setPartial("");
    }
  };

  const clear = async () => {
    try {
      await api.clearChat(meetingId);
      await load();
      setNotice({ tone: "success", text: "Conversa apagada." });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Não foi possível limpar" });
    }
  };

  return (
    <Card
      title={meeting.title}
      subtitle="Apaga a conversa desta reunião, os documentos gerados nela e os e-mails não enviados."
      actions={
        <Button variant="danger" onClick={clear} disabled={meeting.chat_history.length === 0}>
          <Trash2 className="h-4 w-4" /> Limpar conversa
        </Button>
      }
    >
      <div className="flex h-[65dvh] min-h-[380px] flex-col sm:h-[500px]">
        <div className="flex-1 space-y-4 overflow-y-auto rounded-xl border border-white/8 bg-black/20 p-4">
          {meeting.chat_history.length === 0 && <Empty title="Faça uma pergunta sobre esta reunião." />}
          {meeting.chat_history.map((msg, i) => (
            <MessageBubble key={i} meetingId={meetingId} msg={msg} onChanged={load} onReply={reply} />
          ))}
          {busy &&
            (partial ? (
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl border border-white/10 bg-panel px-4 py-2.5 text-sm leading-relaxed text-zinc-200" aria-live="polite">
                {partial}
                <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-emerald-400/70 align-middle" aria-hidden="true" />
              </div>
            ) : (
              <p className="text-xs text-zinc-500">Pensando...</p>
            ))}
          <div ref={endRef} />
        </div>

        {notice && <div className="mt-3"><Alert tone={notice.tone}>{notice.text}</Alert></div>}

        <form onSubmit={ask} className="mt-3 flex items-end gap-3">
          <div className="flex-1">
            <TextArea
              ref={inputRef}
              rows={2}
              placeholder="Ex: Quais foram as principais decisões?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask(e as unknown as FormEvent);
                }
              }}
            />
          </div>
          <Button type="submit" variant="primary" busy={busy} disabled={!question.trim()} aria-label="Enviar pergunta">
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </Card>
  );
}

export function MessageBubble({ meetingId, msg, onChanged, onReply }: { meetingId: string; msg: ChatMessage; onChanged: () => Promise<unknown>; onReply?: (q: string) => void }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser ? "bg-accent/15 text-zinc-100" : "border border-white/10 bg-panel text-zinc-200"
        }`}
      >
        {isUser ? msg.content : <AnswerText text={msg.content} meetingId={meetingId} onReply={onReply} />}
      </div>
      {msg.action && (
        <div className="w-full max-w-[85%]">
          <ActionCard meetingId={meetingId} action={msg.action} onChanged={onChanged} />
        </div>
      )}
    </div>
  );
}

export function ActionCard({ meetingId, action, onChanged }: { meetingId: string; action: ChatAction; onChanged: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (action.type === "memory") {
    return <p className="text-xs text-zinc-400">🧠 Guardado na sua memória (Minha conta → Memória do agente)</p>;
  }

  if (action.type === "document") {
    return (
      <div className="flex items-center gap-3 text-xs text-zinc-400">
        <Button
          onClick={() =>
            api.downloadDocument(meetingId, action.id, action.filename ?? "documento").catch((e) =>
              setError(e instanceof ApiError ? e.message : "Documento não está mais disponível."),
            )
          }
        >
          <Download className="h-4 w-4" /> Baixar {action.filename}
        </Button>
        {error && <span className="text-rose-300">{error}</span>}
      </div>
    );
  }

  if (action.status === "sent") return <p className="text-xs text-emerald-300">✅ E-mail enviado para {(action.to ?? []).join(", ")}</p>;
  if (action.status === "canceled") return <p className="text-xs text-zinc-500">🗑️ E-mail descartado</p>;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha na ação");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4">
      <div className="space-y-2 text-sm">
        <p className="text-zinc-300"><span className="text-zinc-500">Para:</span> {(action.to ?? []).join(", ")}</p>
        <p className="text-zinc-300"><span className="text-zinc-500">Assunto:</span> {action.subject}</p>
        {action.attachments && action.attachments.length > 0 && (
          <p className="text-xs text-zinc-400">Anexos: {action.attachments.map((a) => `📎 ${a.filename}`).join(", ")}</p>
        )}
        <pre className="whitespace-pre-wrap rounded-lg bg-black/30 p-3 font-sans text-xs text-zinc-300">{action.body}</pre>
      </div>
      {error && <div className="mt-3"><Alert tone="error">{error}</Alert></div>}
      <div className="mt-3 flex gap-2">
        <Button variant="primary" busy={busy} onClick={() => run(() => api.sendAction(meetingId, action.id))}>Enviar e-mail</Button>
        <Button busy={busy} onClick={() => run(() => api.cancelAction(meetingId, action.id))}>Descartar</Button>
      </div>
    </Card>
  );
}
