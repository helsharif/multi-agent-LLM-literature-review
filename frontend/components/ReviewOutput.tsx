"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  markdown: string;
  filename: string;
  defaultFormat: string;
  onReset: () => void;
}

const FORMAT_OPTIONS = [
  { value: "md",   label: "Markdown (.md)" },
  { value: "docx", label: "Word (.docx)" },
  { value: "pdf",  label: "PDF (.pdf)" },
];

export default function ReviewOutput({ markdown, filename, defaultFormat, onReset }: Props) {
  const [downloadFormat, setDownloadFormat] = useState(defaultFormat);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  const handleDownload = async () => {
    setDownloading(true);
    setDownloadError("");
    try {
      const res = await fetch(`/api/download/${filename}?format=${downloadFormat}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${filename}.${downloadFormat}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 px-6 py-4
                      flex flex-wrap items-center gap-3">
        <span className="text-sm font-semibold text-slate-700 flex-1">
          ✓ Literature review complete
          <span className="ml-2 font-normal text-slate-400 text-xs">{filename}</span>
        </span>

        {/* Format picker + download */}
        <div className="flex items-center gap-2">
          <select
            value={downloadFormat}
            onChange={(e) => { setDownloadFormat(e.target.value); setDownloadError(""); }}
            className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-slate-400 bg-white"
          >
            {FORMAT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <button
            onClick={handleDownload}
            disabled={downloading}
            className="rounded-lg bg-slate-800 text-white px-4 py-1.5 text-sm font-medium
                       hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed
                       flex items-center gap-1.5 transition-colors"
          >
            {downloading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Downloading…
              </>
            ) : (
              <>⬇ Download</>
            )}
          </button>
        </div>

        <button
          onClick={onReset}
          className="rounded-lg border border-slate-300 text-slate-600 px-4 py-1.5 text-sm
                     hover:bg-slate-50 transition-colors"
        >
          New review
        </button>
      </div>

      {downloadError && (
        <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs px-4 py-2">
          <span className="font-semibold">Download error: </span>{downloadError}
        </div>
      )}

      {/* Rendered review */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 px-8 py-8">
        <div className="prose prose-slate prose-sm max-w-none
                        prose-headings:font-semibold prose-headings:text-slate-800
                        prose-table:text-xs prose-td:py-1 prose-th:py-1
                        prose-a:text-blue-600 prose-code:text-slate-700
                        prose-code:bg-slate-100 prose-code:px-1 prose-code:rounded">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {markdown}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
