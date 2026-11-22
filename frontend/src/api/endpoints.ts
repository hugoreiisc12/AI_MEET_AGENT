import { request, jsonBody, downloadBlob, streamLines } from "./client";
import type {
  AppMode,
  BotStatus, CalendarEvent, ChatReply, Config, MeetingDetail, MeetingStatusInfo,
  LiveTranscript, MeetingTimeline, MemoryNote, ObservabilitySummary, Session, SessionResponse, User, UploadResponse,
} from "./types";

export const api = {
  config: () => request<Config>("/config"),
  health: () => request<Record<string, unknown>>("/health"),

  login: (email: string, password: string) =>
    request<SessionResponse>("/auth/login", jsonBody({ email, password })),
  register: (name: string, email: string, password: string) =>
    request<SessionResponse>("/auth/register", jsonBody({ name, email, password })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  forgotPassword: (email: string) => request<void>("/auth/password/forgot", jsonBody({ email })),
  resetPassword: (email: string, code: string, new_password: string) =>
    request<void>("/auth/password/reset", jsonBody({ email, code, new_password })),
  changePassword: (current_password: string, new_password: string) =>
    request<{ count: number }>("/auth/password", jsonBody({ current_password, new_password })),
  sessions: () => request<Session[]>("/auth/sessions"),
  endSession: (sid: string) => request<void>(`/auth/sessions/${sid}`, { method: "DELETE" }),
  endOtherSessions: () => request<{ count: number }>("/auth/sessions", { method: "DELETE" }),
  purgeSessions: (scope: "expired" | "user" | "all_but_mine", user_id: string) =>
    request<{ count: number }>("/admin/sessions/purge", jsonBody({ confirm: "LIMPAR", scope, user_id })),
  users: () => request<User[]>("/admin/users"),
  switchMode: (mode: AppMode) => request<{ mode: AppMode; message: string }>("/admin/mode", jsonBody({ mode })),

  meetings: () => request<MeetingStatusInfo[]>("/meetings/"),
  meeting: (id: string) => request<MeetingDetail>(`/meetings/${id}`),
  meetingStatus: (id: string) => request<MeetingStatusInfo>(`/meetings/${id}/status`),
  live: (id: string) => request<LiveTranscript>(`/meetings/${id}/live`),
  deleteMeeting: (id: string) => request<void>(`/meetings/${id}`, { method: "DELETE" }),
  reprocess: (id: string) => request<UploadResponse>(`/meetings/${id}/process`, { method: "POST" }),
  resume: (id: string) => request<UploadResponse>(`/meetings/${id}/resume`, { method: "POST" }),
  setTaskDone: (id: string, index: number, done: boolean) =>
    request<MeetingStatusInfo>(`/meetings/${id}/tasks/${index}`, {
      method: "PATCH",
      body: JSON.stringify({ done }),
      headers: { "Content-Type": "application/json" },
    }),
  emailTasks: (id: string, to: string) =>
    request<{ ok: boolean; to: string }>(`/meetings/${id}/tasks/email`, jsonBody({ to })),
  upload: (title: string, file: File) => {
    const form = new FormData();
    form.append("title", title);
    form.append("file", file);
    return request<UploadResponse>("/meetings/upload", { method: "POST", body: form });
  },
  sendBot: (meeting_url: string, title?: string) =>
    request<UploadResponse>("/meetings/bot", jsonBody({ meeting_url, title: title || undefined })),
  downloadMarkdown: (id: string, title: string) =>
    downloadBlob(`/meetings/${id}/export.md`, `${title}.md`),

  chat: (id: string, question: string) => request<ChatReply>(`/meetings/${id}/chat`, jsonBody({ question })),
  /** Mesma pergunta, com o texto chegando aos pedaços. Vale a resposta devolvida no fim (pode ser a corrigida). */
  chatStream: async (id: string, question: string, onDelta: (text: string) => void): Promise<ChatReply> => {
    let final: ChatReply | null = null;
    let error = "";
    await streamLines(`/meetings/${id}/chat/stream`, { question }, (e) => {
      if (typeof e.delta === "string") onDelta(e.delta);
      else if (e.done) final = e.done as ChatReply;
      else if (typeof e.error === "string") error = e.error;
    });
    if (!final) throw new Error(error || "A resposta do agente chegou incompleta.");
    return final;
  },
  clearChat: (id: string) => request<void>(`/meetings/${id}/chat`, { method: "DELETE" }),
  sendAction: (id: string, actionId: string) =>
    request<unknown>(`/meetings/${id}/actions/${actionId}/send`, { method: "POST" }),
  cancelAction: (id: string, actionId: string) =>
    request<unknown>(`/meetings/${id}/actions/${actionId}/cancel`, { method: "POST" }),
  downloadDocument: (id: string, actionId: string, filename: string) =>
    downloadBlob(`/meetings/${id}/actions/${actionId}/document`, filename),

  botStatus: () => request<BotStatus>("/bot/status"),
  botSetup: () => request<BotStatus>("/bot/setup", { method: "POST" }),
  calendar: (limit = 6) => request<CalendarEvent[]>(`/calendar/events?limit=${limit}`),

  memory: () => request<MemoryNote[]>("/memory/"),
  deleteMemory: (id: string) => request<void>(`/memory/${id}`, { method: "DELETE" }),

  observabilitySummary: () => request<ObservabilitySummary>("/observability/summary"),
  meetingTimeline: (id: string) => request<MeetingTimeline>(`/observability/meetings/${id}`),
  observabilityLogs: (params: Record<string, string>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return request<Record<string, string>[]>(`/observability/logs?${q}`);
  },
};
