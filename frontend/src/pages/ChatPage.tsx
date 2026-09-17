import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, errorMessage } from "../api/client";
import { Spinner } from "../components/Spinner";
import { useDocuments } from "../hooks/useDocuments";
import type { Citation, Conversation, Message } from "../api/types";

const ACCEPT = ".pdf,.docx,.xlsx,.csv,.txt";

function CitationChips({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">Sources</p>
      <div className="flex flex-wrap gap-1.5">
        {citations.map((citation, index) => (
          <span
            key={`${citation.document_id}-${citation.chunk_index}-${index}`}
            className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
            title={`score ${Math.round(citation.score * 100)}%`}
          >
            <span className="font-medium text-slate-800">[{index + 1}]</span>{" "}
            {citation.filename} · p.{citation.page_number}
          </span>
        ))}
      </div>
    </div>
  );
}

function AssistantMessage({ content, citations }: { content: string; citations: Citation[] | null }) {
  return (
    <div className="max-w-2xl space-y-3 text-sm leading-relaxed text-slate-800">
      <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
      {citations && <CitationChips citations={citations} />}
    </div>
  );
}

export default function ChatPage() {
  const { documents, refresh: refreshDocuments } = useDocuments();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api
      .listConversations()
      .then(setConversations)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const toggleDocument = (id: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const loadConversation = async (id: string) => {
    try {
      const data = await api.getMessages(id);
      setActiveConversationId(id);
      setMessages(data.messages);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const startNewChat = () => {
    setActiveConversationId(null);
    setMessages([]);
    setError(null);
  };

  const deleteConversation = async (id: string) => {
    await api.deleteConversation(id).catch(() => undefined);
    setConversations((previous) => previous.filter((c) => c.id !== id));
    if (activeConversationId === id) startNewChat();
  };

  const handleUploadFiles = async (files: FileList) => {
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await api.uploadDocument(file);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
      setUploading(false);
      void refreshDocuments();
    }
  };

  const send = async (text: string) => {
    const optimistic: Message = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text,
      citations: null,
      created_at: new Date().toISOString(),
    };
    setMessages((previous) => [...previous, optimistic]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const assistantId = `answer-${Date.now()}`;
      setMessages((previous) => [
        ...previous,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          citations: [],
          created_at: new Date().toISOString(),
        },
      ]);
      const { conversation_id, citations } = await api.chatStream(
        {
          message: text,
          conversation_id: activeConversationId,
          document_ids: Array.from(selectedIds),
        },
        (token) => {
          setMessages((previous) =>
            previous.map((m) => (m.id === assistantId ? { ...m, content: m.content + token } : m)),
          );
        },
      );
      setMessages((previous) =>
        previous.map((m) => (m.id === assistantId ? { ...m, citations } : m)),
      );
      if (conversation_id) setActiveConversationId(conversation_id);
      void api
        .listConversations()
        .then(setConversations)
        .catch(() => undefined);
    } catch (err) {
      setError(errorMessage(err));
      setMessages((previous) => previous.filter((m) => m.id !== optimistic.id));
      setInput(text);
    } finally {
      setSending(false);
    }
  };

  const handleSend = async (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    await send(text);
  };

  const readyDocuments = documents.filter((d) => d.status === "ready");

  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <aside className="space-y-4">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Documents</h2>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              multiple
              hidden
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  void handleUploadFiles(e.target.files);
                }
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
            >
              {uploading ? "Uploading…" : "+ Upload"}
            </button>
          </div>
          {documents.length === 0 ? (
            <p className="text-xs text-slate-500">
              No documents yet. Upload one to get started.
            </p>
          ) : (
            <>
              <ul className="space-y-1.5">
                {documents.map((document) => (
                  <li key={document.id}>
                    <label
                      className={`flex items-center gap-2 text-sm ${
                        document.status === "ready" ? "cursor-pointer" : "opacity-50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="accent-slate-900"
                        disabled={document.status !== "ready"}
                        checked={selectedIds.has(document.id)}
                        onChange={() => toggleDocument(document.id)}
                      />
                      <span className="truncate" title={document.original_filename}>
                        {document.original_filename}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-slate-400">
                {selectedIds.size === 0
                  ? "Searching all documents."
                  : `Searching ${selectedIds.size} selected document${selectedIds.size === 1 ? "" : "s"}.`}
              </p>
            </>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Conversations</h2>
            <button
              onClick={startNewChat}
              className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200"
            >
              + New
            </button>
          </div>
          {conversations.length === 0 ? (
            <p className="text-xs text-slate-500">No conversations yet.</p>
          ) : (
            <ul className="space-y-1">
              {conversations.map((conversation) => (
                <li key={conversation.id} className="group flex items-center gap-1">
                  <button
                    onClick={() => void loadConversation(conversation.id)}
                    className={`flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm ${
                      activeConversationId === conversation.id
                        ? "bg-slate-900 text-white"
                        : "text-slate-700 hover:bg-slate-100"
                    }`}
                    title={conversation.title}
                  >
                    {conversation.title}
                  </button>
                  <button
                    onClick={() => void deleteConversation(conversation.id)}
                    className="rounded-md px-1.5 py-1 text-xs text-slate-400 opacity-0 hover:text-red-600 group-hover:opacity-100"
                    aria-label="Delete conversation"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>

      <section className="flex h-[calc(100vh-8.5rem)] min-h-[420px] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex-1 space-y-6 overflow-y-auto p-6">
          {messages.length === 0 && !sending && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <p className="text-sm font-medium text-slate-700">
                Ask a question about your documents.
              </p>
              <p className="mt-1 max-w-sm text-xs text-slate-500">
                Answers are grounded in passages retrieved from the files you select, with page
                citations.
              </p>
            </div>
          )}

          {messages.map((message) =>
            message.role === "user" ? (
              <div key={message.id} className="flex justify-end">
                <div className="max-w-xl rounded-2xl rounded-br-md bg-slate-900 px-4 py-2.5 text-sm text-white">
                  {message.content}
                </div>
              </div>
            ) : (
              <div key={message.id} className="rounded-lg bg-slate-50 p-4">
                <AssistantMessage content={message.content} citations={message.citations} />
              </div>
            ),
          )}

          {sending && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Spinner className="h-4 w-4" />
              Searching documents and generating an answer…
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && (
          <p className="mx-6 mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        )}

        <form onSubmit={handleSend} className="border-t border-slate-200 p-4">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  const text = input.trim();
                  if (text && !sending) void send(text);
                }
              }}
              rows={1}
              placeholder="Ask about your documents…"
              className="max-h-32 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-slate-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={sending || input.trim().length === 0}
              className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Send
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            {readyDocuments.length} document{readyDocuments.length === 1 ? "" : "s"} ready ·
            answers cite the pages they come from
          </p>
        </form>
      </section>
    </div>
  );
}
