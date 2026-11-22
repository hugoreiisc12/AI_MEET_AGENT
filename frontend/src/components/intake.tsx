import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { Button, Card, Empty, Field, Input, Alert, Spinner } from "./ui";
import { api } from "../api/endpoints";
import { ApiError } from "../api/client";
import type { BotStatus, CalendarEvent } from "../api/types";
import { formatDate } from "../lib/format";

export function UploadPanel({ maxMb, formats }: { maxMb: number; formats: string[] }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || !title.trim()) return;
    if (file.size > maxMb * 1024 * 1024) {
      setError(`Arquivo acima do limite de ${maxMb} MB.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await api.upload(title.trim(), file);
      navigate(`/gravacoes/${res.meeting_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha no envio");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Nova reunião" subtitle="O áudio é transcrito, identificado por quem falou e resumido.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Título">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Sprint Planning — Semana 22" />
        </Field>
        <Field label="Arquivo de áudio" hint={`Formatos: ${formats.join(", ") || "wav, mp3, m4a, webm, mkv, ogg"} · até ${maxMb} MB`}>
          <input
            type="file"
            accept={formats.map((f) => `.${f}`).join(",") || undefined}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-zinc-300 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-zinc-100"
          />
        </Field>
        {error && <Alert tone="error">{error}</Alert>}
        <Button type="submit" variant="primary" busy={busy} disabled={!file || !title.trim()}>
          {busy ? "Enviando..." : "🚀 Processar"}
        </Button>
      </form>
    </Card>
  );
}

export function BotPanel({ calendarEnabled }: { calendarEnabled: boolean }) {
  const navigate = useNavigate();
  const [bot, setBot] = useState<BotStatus | null>(null);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const ready = bot?.status === "ready";

  const refreshBot = () => api.botStatus().then(setBot).catch(() => {});

  useEffect(() => {
    void refreshBot();
    const id = window.setInterval(refreshBot, 3000);
    return () => window.clearInterval(id);
  }, []);

  const credential = async () => {
    setSetupBusy(true);
    try {
      setBot(await api.botSetup());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao credenciar o bot");
    } finally {
      setSetupBusy(false);
    }
  };

  const sendBot = async (meeting_url: string, meetingTitle?: string) => {
    setBusy(true);
    setError("");
    try {
      const res = await api.sendBot(meeting_url, meetingTitle);
      navigate(`/gravacoes/${res.meeting_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Não foi possível enviar o bot");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card title={<span className="flex items-center gap-2"><img src="/icon-64.png" alt="" className="h-6 w-6" />Enviar bot</span>} subtitle="Google Meet. Teams e Zoom são aceitos, mas ainda não foram validados em reunião real.">
        <div className="space-y-4">
          <BotCredentialBlock bot={bot} busy={setupBusy} onSetup={credential} />
          <Field label="Link da reunião">
            <Input placeholder="https://meet.google.com/xxx-yyyy-zzz" value={url} onChange={(e) => setUrl(e.target.value)} />
          </Field>
          <Field label="Título da reunião">
            <Input placeholder="Sprint Planning — Semana 22" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          <Button variant="primary" busy={busy} disabled={!ready || !url.trim()} onClick={() => sendBot(url.trim(), title.trim())}>
            <Play className="h-4 w-4" /> Enviar bot para a reunião
          </Button>
        </div>
      </Card>
      {calendarEnabled && <CalendarPanel ready={ready} onSend={(u, t) => sendBot(u, t)} />}
    </div>
  );
}

function BotCredentialBlock({ bot, busy, onSetup }: { bot: BotStatus | null; busy: boolean; onSetup: () => void }) {
  if (!bot) return <Spinner />;
  if (bot.status === "ready") return <Alert tone="success">Bot credenciado e pronto.</Alert>;
  if (bot.status === "creating") return <Alert tone="info">⏳ Criando bot... {bot.message}</Alert>;
  if (bot.status === "waiting_login") {
    return (
      <Alert tone="warning">
        🔐 {bot.message || "Entre na conta do Google do bot."}{" "}
        {bot.vnc_url && (
          <a href={bot.vnc_url} target="_blank" rel="noreferrer" className="underline">
            Abrir a tela do navegador do bot
          </a>
        )}
      </Alert>
    );
  }
  if (bot.status === "error") return <Alert tone="error">{bot.message}</Alert>;
  if (bot.status === "offline") return <Alert tone="warning">⚠️ {bot.message}</Alert>;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-zinc-400">O bot ainda não está conectado a uma conta do Google.</p>
      <Button variant="primary" busy={busy} onClick={onSetup}>🤖 Credenciar bot</Button>
    </div>
  );
}

function CalendarPanel({ ready, onSend }: { ready: boolean; onSend: (url: string, title?: string) => void }) {
  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.calendar().then(setEvents).catch((e) => setError(e instanceof Error ? e.message : "Erro na agenda"));
  }, []);

  return (
    <Card title="📅 Próximas reuniões da agenda">
      {error && <Alert tone="warning">{error}</Alert>}
      {!error && !events && <Spinner />}
      {events && events.length === 0 && <Empty title="Nenhuma reunião com link (Meet, Zoom ou Teams) nas próximas da agenda." />}
      {events && events.length > 0 && (
        <ul className="divide-y divide-white/8">
          {events.map((ev) => (
            <li key={ev.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-white">{ev.title}</p>
                <p className="text-xs text-zinc-400">{formatDate(ev.start)}</p>
              </div>
              <Button disabled={!ready} onClick={() => onSend(ev.meeting_url, ev.title)}>🤖 Mandar</Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
