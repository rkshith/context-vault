import type { ChatResponse, Citation, Conversation, DocumentItem, Message, User } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = options.body instanceof FormData;

  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });

  if (response.status === 401 && unauthorizedHandler && !path.startsWith("/api/auth/")) {
    unauthorizedHandler();
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data: unknown = await response.json();
      if (
        typeof data === "object" &&
        data !== null &&
        "detail" in data
      ) {
        const d = (data as { detail: unknown }).detail;
        if (typeof d === "string") detail = d;
        else if (Array.isArray(d)) detail = d.map((item) => String(item)).join(", ");
      }
    } catch {
      // keep default message
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  signup: (data: { email: string; password: string; name: string }) =>
    request<User>("/api/auth/signup", { method: "POST", body: JSON.stringify(data) }),

  login: (data: { email: string; password: string }) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify(data) }),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  me: () => request<User>("/api/auth/me"),

  authConfig: () =>
    request<{ google_enabled: boolean; google_client_id: string | null }>("/api/auth/config"),

  googleLogin: (id_token: string) =>
    request<User>("/api/auth/google", { method: "POST", body: JSON.stringify({ id_token }) }),

  listDocuments: () => request<DocumentItem[]>("/api/documents"),

  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentItem>("/api/documents", { method: "POST", body: form });
  },

  deleteDocument: (id: string) =>
    request<void>(`/api/documents/${id}`, { method: "DELETE" }),

  chat: (data: { message: string; conversation_id?: string | null; document_ids?: string[] }) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ document_ids: [], ...data }),
    }),

  listConversations: () => request<Conversation[]>("/api/conversations"),

  getMessages: (id: string) =>
    request<{ conversation_id: string; messages: Message[] }>(`/api/conversations/${id}/messages`),

  deleteConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  chatStream: async (
    data: { message: string; conversation_id?: string | null; document_ids?: string[] },
    onToken: (text: string) => void,
  ): Promise<{ conversation_id: string; citations: Citation[] }> => {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: [], ...data }),
    });
    if (!response.ok || !response.body) {
      throw new ApiError(response.status, `Chat stream failed (${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let conversation_id = "";
    let citations: Citation[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const eventMatch = raw.match(/^event: (\w+)\ndata: ([\s\S]*)$/);
        if (eventMatch) {
          const [, event, payload] = eventMatch;
          const parsed = JSON.parse(payload) as {
            text?: string;
            conversation_id?: string;
            detail?: string;
          };
          if (event === "citations") citations = JSON.parse(payload) as Citation[];
          else if (event === "token" || event === "answer") onToken(parsed.text ?? "");
          else if (event === "done" && parsed.conversation_id)
            conversation_id = parsed.conversation_id;
          else if (event === "error") throw new ApiError(response.status, parsed.detail ?? "Stream error");
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
    return { conversation_id, citations };
  },
};
