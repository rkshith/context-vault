import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, errorMessage } from "../api/client";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { useDocuments } from "../hooks/useDocuments";
import type { DocumentItem } from "../api/types";

const ACCEPT = ".pdf,.docx,.xlsx,.csv,.txt";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function DocumentRow({
  document,
  onDeleted,
}: {
  document: DocumentItem;
  onDeleted: (id: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${document.original_filename}" and all of its data?`)) return;
    setDeleting(true);
    try {
      await api.deleteDocument(document.id);
      onDeleted(document.id);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="max-w-[240px] truncate px-4 py-3 font-medium" title={document.original_filename}>
        {document.original_filename}
      </td>
      <td className="px-4 py-3 uppercase text-slate-500">{document.file_type}</td>
      <td className="px-4 py-3 text-slate-500">{formatSize(document.size_bytes)}</td>
      <td className="px-4 py-3">
        <StatusBadge status={document.status} />
        {document.error && <p className="mt-1 text-xs text-red-600">{document.error}</p>}
      </td>
      <td className="px-4 py-3 text-slate-500">
        {document.page_count ?? "–"} pages · {document.chunk_count ?? "–"} chunks
      </td>
      <td className="px-4 py-3 text-slate-500">{formatDate(document.created_at)}</td>
      <td className="px-4 py-3 text-right">
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="rounded-md px-2 py-1 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
        >
          Delete
        </button>
      </td>
    </tr>
  );
}

export default function DocumentsPage() {
  const { documents, loading, error, refresh } = useDocuments();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const handleUpload = async (event: FormEvent) => {
    event.preventDefault();
    const files = fileInputRef.current?.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    setUploadError(null);
    try {
      for (const file of Array.from(files)) {
        await api.uploadDocument(file);
      }
    } catch (err) {
      setUploadError(errorMessage(err));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
      setUploading(false);
      void refresh();
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Documents</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            PDF, DOCX, XLSX, CSV and TXT up to 25 MB each.
          </p>
        </div>
        <form onSubmit={handleUpload} className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="block w-56 text-sm text-slate-500 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
          />
          <button
            type="submit"
            disabled={uploading}
            className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {uploading && <Spinner className="h-4 w-4 text-white" />}
            Upload
          </button>
        </form>
      </div>

      {(error || uploadError) && (
        <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{uploadError ?? error}</p>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : documents.length === 0 ? (
          <div className="py-16 text-center text-sm text-slate-500">
            No documents yet. Upload your first file to start asking questions.
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Filename</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Size</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Details</th>
                <th className="px-4 py-3">Uploaded</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <DocumentRow
                  key={document.id}
                  document={document}
                  onDeleted={() => void refresh()}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
