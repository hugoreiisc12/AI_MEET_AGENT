import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import type { ObservabilitySummary } from "../api/types";
import { Alert, Button, Card, Empty, Field, Input, Select, Spinner } from "../components/ui";
import { formatDate } from "../lib/format";
import { toAgentMemory, toLogTime, toServiceCards, toTotals } from "../api/adapters";

type LogRow = Record<string, string>;

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [error, setError] = useState("");

  const load = () =>
    api.observabilitySummary().then(setSummary).catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar"));

  useEffect(() => {
    void load();
  }, []);

  return (
    <>
      <div className="mb-5 flex justify-end">
        <Button onClick={load}>🔄 Atualizar</Button>
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {!summary && !error && <Spinner />}
      {summary && <SummaryCards s={summary} />}
      <div className="mt-6">
        <LogsCard />
      </div>
    </>
  );
}

function Stat({ label, value, hint, tone = "neutral" }: { label: string; value: string; hint?: string; tone?: "ok" | "bad" | "neutral" }) {
  const dot = tone === "ok" ? "bg-emerald-400" : tone === "bad" ? "bg-rose-400" : "bg-zinc-500";
  return (
    <div className="rounded-2xl border border-white/10 bg-panel p-4">
      <p className="flex items-center gap-2 text-xs text-zinc-400">
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />
        {label}
      </p>
      <p className="mt-1 font-mono text-lg font-semibold text-white">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

function SummaryCards({ s }: { s: ObservabilitySummary }) {
  const services = toServiceCards(s);
  const totals = toTotals(s);
  const memory = toAgentMemory(s);
  return (
    <div className="space-y-6">
      <p className="text-xs text-zinc-500">Gerado em {formatDate(s.generated_at)}</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {services.map((c) => (
          <Stat key={c.label} label={c.label} value={c.value} hint={c.hint} tone={c.ok === null ? "neutral" : c.ok ? "ok" : "bad"} />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {totals.map((t) => (
          <Stat key={t.label} label={t.label} value={t.value} hint={t.hint} />
        ))}
      </div>
      {memory.length > 0 && (
        <section aria-label="Memória do agente">
          <h2 className="mb-2 text-sm font-semibold text-zinc-300">Memória do agente</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {memory.map((t) => (
              <Stat key={t.label} label={t.label} value={t.value} hint={t.hint} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function LogsCard() {
  const [service, setService] = useState("");
  const [level, setLevel] = useState("");
  const [meetingId, setMeetingId] = useState("");
  const [text, setText] = useState("");
  const [rows, setRows] = useState<LogRow[] | null>(null);
  const [error, setError] = useState("");

  const search = () => {
    setError("");
    api
      .observabilityLogs({ service, level, meeting_id: meetingId, q: text, limit: "200" })
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Erro ao buscar logs"));
  };

  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card title="Logs">
      <form
        className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-5"
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
      >
        <Field label="Reunião (id)">
          <Input value={meetingId} onChange={(e) => setMeetingId(e.target.value)} />
        </Field>
        <Field label="Serviço">
          <Select value={service} onChange={(e) => setService(e.target.value)}>
            <option value="">Todos</option>
            {["api", "worker-transcribe", "worker-llm", "bot"].map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
        <Field label="Nível mínimo">
          <Select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">Todos</option>
            {["INFO", "WARNING", "ERROR"].map((l) => <option key={l} value={l}>{l}</option>)}
          </Select>
        </Field>
        <Field label="Texto">
          <Input value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="flex items-end">
          <Button type="submit" variant="primary" className="w-full">Filtrar</Button>
        </div>
      </form>

      {error && <Alert tone="error">{error}</Alert>}
      {!rows && !error && <Spinner />}
      {rows && rows.length === 0 && <Empty title="Nenhuma linha com esses filtros." />}
      {rows && rows.length > 0 && (
        <div className="max-h-[480px] overflow-auto rounded-xl border border-white/8">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-panel text-zinc-400">
              <tr>
                <th className="px-3 py-2 font-medium">Hora</th>
                <th className="px-3 py-2 font-medium">Serviço</th>
                <th className="px-3 py-2 font-medium">Nível</th>
                <th className="px-3 py-2 font-medium">Reunião</th>
                <th className="px-3 py-2 font-medium">Mensagem</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/6">
              {rows.map((r) => (
                <tr key={r.id} className="align-top">
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-zinc-400">{toLogTime(r.ts)}</td>
                  <td className="px-3 py-2 text-zinc-300">{r.service}</td>
                  <td className={`px-3 py-2 font-mono ${r.level === "ERROR" ? "text-rose-300" : r.level === "WARNING" ? "text-amber-300" : "text-zinc-300"}`}>{r.level}</td>
                  <td className="px-3 py-2 font-mono text-zinc-500">{(r.meeting_id ?? "").slice(0, 8)}</td>
                  <td className="px-3 py-2 text-zinc-200">{(r.message ?? "").slice(0, 300)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

