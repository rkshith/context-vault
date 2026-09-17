import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { DocumentItem } from "../api/types";

const SETTLED = new Set(["ready", "failed"]);

export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const busy = documents.some((d) => !SETTLED.has(d.status));

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  return { documents, loading, error, refresh };
}
