export type MeetingStatus = "pending" | "recording" | "transcribing" | "summarizing" | "done" | "error";

export interface User {
  id: string;
  name: string;
  email: string;
  created_at: string;
  role?: string;
}

export interface Session {
  id: string;
  created_at: string;
  expires_at: string;
  current: boolean;
  ip?: string;
  user_agent?: string;
}

export interface SessionResponse {
  token: string;
  user: User;
}

export type AppMode = "solo" | "collab";

export interface Config {
  mode: AppMode;
  login_enabled: boolean;
  registration_open: boolean;
  email_enabled: boolean;
  calendar_enabled: boolean;
  max_upload_mb: number;
  audio_formats: string[];
  platforms: { key: string; label: string; example: string; speaker_names: boolean; validated: boolean }[];
}

export interface Task {
  description: string;
  responsible: string;
  deadline?: string | null;
  done?: boolean;
}

export interface Decision {
  description: string;
  context?: string;
  status?: string;
}

export interface Summary {
  overview: string;
  topics: string[];
  tasks: Task[];
  decisions: Decision[];
  contributions?: { speaker: string; points: string[] }[];
  topic_decisions?: { topic: string; decision: string; effect: string }[];
  open_questions?: string[];
  extra_sections?: Record<string, unknown>;
}

export interface ChatAction {
  id: string;
  type: string;
  status: string;
  title?: string;
  to?: string[];
  subject?: string;
  body?: string;
  filename?: string;
  format?: string;
  attachments?: { filename: string; format: string; id: string }[];
  sent_at?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  action?: ChatAction | null;
}

export interface MeetingStatusInfo {
  meeting_id: string;
  title: string;
  status: MeetingStatus;
  started_at: string;
  error?: string;
  platform?: string;
  duration_minutes?: number;
  participants?: unknown[];
  queue_position?: number;
  stalled?: boolean;
  stage_elapsed_s?: number | null;
  stage_typical_s?: number | null;
  summary?: Summary | null;
}

export interface MeetingDetail extends MeetingStatusInfo {
  transcript?: string;
  has_audio?: boolean;
  chat_history: ChatMessage[];
}

export interface UploadResponse {
  meeting_id: string;
  message: string;
  status: MeetingStatus;
}

export interface BotStatus {
  status: string;
  message?: string;
  vnc_url?: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  meeting_url: string;
  participants?: unknown[];
}

export interface LiveTranscript {
  meeting_id: string;
  status: MeetingStatus;
  segments: { start: number; end: number; text: string }[];
}

export interface MemoryNote {
  id: string;
  text: string;
  created_at: string;
  meeting_id?: string;
}

export interface ChatReply {
  meeting_id: string;
  answer: string;
  action?: ChatAction | null;
}

export interface MeetingTimeline {
  meeting_id: string;
  status: MeetingStatus;
  error?: string;
  metrics?: Record<string, number>;
  queue_position?: number;
  logs: Record<string, string>[];
}

export interface ObservabilitySummary {
  generated_at: string;
  workers: Record<string, string>;
  bot: { status?: string };
  llm: { status?: string; model?: string };
  disk: { free_gb: number; used_pct: number };
  meetings_by_status: Record<string, number>;
  accounts: { users?: number };
  http: Record<string, number>;
  emails: Record<string, number>;
  documents: Record<string, number>;
  queues: Record<string, number>;
  agent_memory?: {
    answers_by_path: Record<string, number>;
    cache_hit_rate: number | null;
    latency_by_path: Record<string, { count: number; p50: number; p95: number; max: number }>;
  };
}
