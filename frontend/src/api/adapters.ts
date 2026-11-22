// Adapters: convertem as respostas da FastAPI em modelos de tela.
// As páginas não leem campos crus do contrato; leem o que estas funções devolvem.
import type { MeetingDetail, MeetingStatusInfo, MeetingStatus, ObservabilitySummary } from "./types";
import { IN_PROGRESS, STATUS_ICON, STATUS_LABEL, formatDuration, progressLabel } from "../lib/format";

export interface MeetingRowView {
  id: string;
  title: string;
  icon: string;
  status: MeetingStatus;
  label: string;
  inProgress: boolean;
}

export function toMeetingRow(m: MeetingStatusInfo): MeetingRowView {
  return {
    id: m.meeting_id,
    title: m.title,
    icon: STATUS_ICON[m.status],
    status: m.status,
    label: progressLabel(m.status, m.queue_position),
    inProgress: IN_PROGRESS.includes(m.status),
  };
}

export interface MetricView {
  label: string;
  value: string;
  hint?: string;
}

export function toMeetingMetrics(d: MeetingDetail): MetricView[] {
  const summary = d.summary;
  return [
    { label: "⏱ Duração", value: `${Math.round(d.duration_minutes ?? 0)} min` },
    { label: "👥 Participantes", value: String(d.participants?.length || "—") },
    { label: "✅ Tarefas", value: String(summary?.tasks.length ?? 0) },
    { label: "🔑 Decisões", value: String(summary?.decisions.length ?? 0) },
  ];
}

export interface ServiceCardView {
  label: string;
  value: string;
  hint?: string;
  ok: boolean | null;
}

export function toServiceCards(s: ObservabilitySummary): ServiceCardView[] {
  const workerOk = (k: string) => s.workers?.[k] === "ok";
  return [
    { label: "Transcrição", value: workerOk("worker_transcribe") ? "no ar" : "sem worker", ok: workerOk("worker_transcribe") },
    { label: "Resumo (LLM)", value: workerOk("worker_llm") ? "no ar" : "sem worker", ok: workerOk("worker_llm") },
    { label: "Bot", value: workerOk("bot") ? (s.bot?.status ?? "ok") : "sem worker", ok: workerOk("bot") },
    { label: "LLM", value: s.llm?.status ?? "?", hint: s.llm?.model, ok: s.llm?.status ? s.llm.status === "ok" : null },
    { label: "Disco livre", value: `${s.disk?.free_gb ?? "?"} GB`, hint: `${s.disk?.used_pct ?? "?"}% usado`, ok: null },
  ];
}

export function toTotals(s: ObservabilitySummary): MetricView[] {
  const total = Object.values(s.meetings_by_status ?? {}).reduce((a, b) => a + b, 0);
  const errors = s.meetings_by_status?.error ?? 0;
  const requests = Object.values(s.http ?? {}).reduce((a, b) => a + b, 0);
  const http5xx = Math.round(s.http?.["5xx"] ?? 0);
  const emails = Object.values(s.emails ?? {}).reduce((a, b) => a + b, 0);
  return [
    { label: "Reuniões", value: String(total), hint: `${errors} com erro` },
    { label: "Usuários", value: String(s.accounts?.users ?? "—") },
    { label: "Pedidos à API", value: String(Math.round(requests)), hint: `${http5xx} erros 5xx` },
    { label: "E-mails", value: String(Math.round(emails)) },
  ];
}

const PATH_LABEL: Record<string, string> = { cache: "Cache (CAG)", quente: "Trechos quentes", banco: "Índice no disco" };

/** Memória do agente (ADR-022): de onde vieram as respostas do chat e quanto levaram. */
export function toAgentMemory(s: ObservabilitySummary): MetricView[] {
  const m = s.agent_memory;
  if (!m) return [];
  const total = Object.values(m.answers_by_path).reduce((a, b) => a + b, 0);
  const rate = m.cache_hit_rate === null ? "—" : `${Math.round(m.cache_hit_rate * 100)}%`;
  return [
    { label: "Acerto do cache", value: rate, hint: `${Math.round(total)} respostas` },
    ...Object.keys(PATH_LABEL).map((path) => {
      const lat = m.latency_by_path[path];
      return {
        label: PATH_LABEL[path],
        value: lat ? `p50 ${lat.p50.toFixed(1)} s` : "—",
        hint: lat ? `p95 ${lat.p95.toFixed(1)} s · ${Math.round(m.answers_by_path[path] ?? 0)} respostas` : "sem respostas",
      };
    }),
  ];
}

export function toLogTime(ts: string | undefined): string {
  const n = Number(ts);
  if (!ts || Number.isNaN(n)) return ts ?? "";
  return new Date(n * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function toStatusText(status: MeetingStatus): string {
  return `${STATUS_ICON[status]} ${STATUS_LABEL[status]}`;
}

export function toClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export { formatDuration };
