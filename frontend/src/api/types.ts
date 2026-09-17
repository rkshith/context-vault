export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  auth_provider: string;
  created_at: string;
}

export interface DocumentItem {
  id: string;
  original_filename: string;
  file_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  page_count: number | null;
  chunk_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  document_id: string;
  filename: string;
  page_number: number;
  chunk_index: number;
  score: number;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  citations: Citation[];
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
}
