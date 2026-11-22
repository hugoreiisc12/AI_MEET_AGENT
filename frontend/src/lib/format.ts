import type { MeetingStatus } from "../api/types";

export const STATUS_LABEL: Record<MeetingStatus, string> = {
  pending: "Na fila",
  recording: "Bot gravando a reunião",
  transcribing: "Transcrevendo o áudio",
  summarizing: "Gerando o resumo",
  done: "Concluída",
  error: "Erro",
};

export const STATUS_ICON: Record<MeetingStatus, string> = {
  pending: "⏳",
  recording: "🔴",
  transcribing: "🎤",
  summarizing: "📝",
  done: "✅",
  error: "❌",
};

export const IN_PROGRESS: MeetingStatus[] = ["pending", "recording", "transcribing", "summarizing"];

export const SECTION_META: Record<string, { label: string; emoji: string }> = {
  went_well: { label: "Pontos Fortes (o que deu certo)", emoji: "✅" },
  to_improve: { label: "O que melhorar", emoji: "🔧" },
  action_items: { label: "Ações", emoji: "📌" },
  risks: { label: "Riscos", emoji: "⚠️" },
  delivered: { label: "Entregue", emoji: "📦" },
  not_delivered: { label: "Não entregue", emoji: "⏳" },
  stakeholder_feedback: { label: "Feedback", emoji: "💬" },
  feedbacks: { label: "Feedbacks", emoji: "🔄" },
  strengths: { label: "Pontos Fortes", emoji: "💪" },
  concerns: { label: "Pontos de Atenção", emoji: "🚩" },
  recommendation: { label: "Recomendação", emoji: "🎯" },
  ideas: { label: "Ideias", emoji: "💡" },
};

export function sectionMeta(key: string): { label: string; emoji: string } {
  return SECTION_META[key] ?? { label: key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), emoji: "" };
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s` : `${s} s`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function shortTitle(title: string, max = 30): string {
  return title.length > max ? `${title.slice(0, max)}...` : title;
}

export function progressLabel(status: MeetingStatus, queuePosition?: number): string {
  const base = STATUS_LABEL[status];
  return queuePosition ? `${base} — ${queuePosition}º na fila` : base;
}
