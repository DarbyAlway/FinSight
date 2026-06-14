export type Role = 'user' | 'assistant';

export interface Message {
  role: Role;
  content: string;
  created_at?: string;
}

export interface Chat {
  id: string;
  title: string;
  updated_at: string;
}

export interface ChatDetail extends Chat {
  created_at: string;
  messages: Message[];
}

export type StreamStatus = 'idle' | 'streaming' | 'error';

export interface StageInfo {
  stage: string;
  detail: string;
}
