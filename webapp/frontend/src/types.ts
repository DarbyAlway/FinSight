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

export interface User {
  id: string;
  email: string;
  is_owner: boolean;
  tokens_used: number;
}

export type AuthStatus = 'loading' | 'authed' | 'anon';

export type StreamStatus = 'idle' | 'streaming' | 'error';

export interface StageInfo {
  stage: string;
  detail: string;
}
