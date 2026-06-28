"use client";

import { useState } from "react";

export interface FormValues {
  topic: string;
  depth: number;
  format: string;
  zoteroCollection: string;
  llmBackend: string;
}

interface Props {
  onSubmit: (values: FormValues) => void;
  isRunning: boolean;
}

const FORMAT_OPTIONS = [
  { value: "md",   label: "Markdown (.md)" },
  { value: "docx", label: "Word (.docx)" },
  { value: "pdf",  label: "PDF (.pdf)" },
];

const LLM_OPTIONS = [
  { value: "claude", label: "Claude Code" },
  { value: "gemini_flash", label: "Gemini 2.5 Flash (OpenRouter paid)" },
  { value: "openrouter_free", label: "OpenRouter Free Router (auto)" },
  { value: "qwen3_coder_free", label: "Qwen3 Coder 480B A35B (free)" },
  { value: "nemotron_ultra_free", label: "NVIDIA Nemotron 3 Ultra (free)" },
  { value: "nemotron_super_free", label: "NVIDIA Nemotron 3 Super (free)" },
];

export default function ReviewForm({ onSubmit, isRunning }: Props) {
  const [topic, setTopic] = useState("");
  const [depth, setDepth] = useState(20);
  const [format, setFormat] = useState("md");
  const [zoteroCollection, setZoteroCollection] = useState("");
  const [llmBackend, setLlmBackend] = useState("claude");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    onSubmit({
      topic: topic.trim(),
      depth,
      format,
      zoteroCollection: zoteroCollection.trim(),
      llmBackend,
    });
  };

  const adjustDepth = (delta: number) => {
    setDepth((d) => Math.min(100, Math.max(5, d + delta)));
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
      {/* Instructions banner */}
      <div className="bg-slate-50 border-b border-slate-200 px-6 py-4">
        <h2 className="text-sm font-semibold text-slate-700 mb-2">How it works</h2>
        <ol className="text-sm text-slate-500 space-y-1 list-decimal list-inside">
          <li>Enter your research topic — be specific and descriptive for best results.</li>
          <li>Set the search depth (total papers to retrieve across subtopics).</li>
          <li>Optionally name a Zotero collection; one is auto-created if left blank.</li>
          <li>
            Click <span className="font-medium text-slate-700">Generate</span> and watch
            the workflow run live: Search → Synthesize → Verify → Save to Zotero.
          </li>
          <li>Download the finished review in your chosen format.</li>
        </ol>
        <p className="text-xs text-slate-400 mt-2">
          Typical run time: 3–8 minutes depending on depth and topic complexity.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="px-6 py-6 space-y-6">
        {/* Topic */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Research topic <span className="text-red-500">*</span>
          </label>
          <textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            rows={4}
            placeholder="e.g. What are the impacts of permafrost thaw on Arctic carbon emissions? Include quantitative projections and feedback mechanisms."
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-slate-400 resize-y
                       placeholder:text-slate-400"
            required
            disabled={isRunning}
          />
        </div>

        {/* LLM backend */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            LLM backend
          </label>
          <select
            value={llmBackend}
            onChange={(e) => setLlmBackend(e.target.value)}
            disabled={isRunning}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-slate-400 bg-white"
          >
            {LLM_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-slate-400 mt-1">
            Claude uses the local CLI. OpenRouter Free auto-routes among free models; Gemini Flash is currently paid.
          </p>
        </div>

        {/* Depth + Format row */}
        <div className="grid grid-cols-2 gap-4">
          {/* Depth counter */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Search depth (papers)
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => adjustDepth(-5)}
                disabled={depth <= 5 || isRunning}
                className="w-8 h-8 rounded-md border border-slate-300 text-slate-600
                           flex items-center justify-center font-bold text-lg
                           hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                −
              </button>
              <span className="w-12 text-center font-semibold text-slate-800 text-lg tabular-nums">
                {depth}
              </span>
              <button
                type="button"
                onClick={() => adjustDepth(5)}
                disabled={depth >= 100 || isRunning}
                className="w-8 h-8 rounded-md border border-slate-300 text-slate-600
                           flex items-center justify-center font-bold text-lg
                           hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                +
              </button>
            </div>
            <p className="text-xs text-slate-400 mt-1">5–100, step 5. Recommend 20–30.</p>
          </div>

          {/* Download format */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Download format
            </label>
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              disabled={isRunning}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-slate-400 bg-white"
            >
              {FORMAT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-400 mt-1">
              Review always renders in-browser. DOCX/PDF require extra pip packages.
            </p>
          </div>
        </div>

        {/* Zotero collection */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Zotero collection name{" "}
            <span className="text-slate-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={zoteroCollection}
            onChange={(e) => setZoteroCollection(e.target.value)}
            placeholder="e.g. 2026-06 Arctic Carbon — leave blank to auto-generate"
            disabled={isRunning}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-slate-400
                       placeholder:text-slate-400"
          />
          <p className="text-xs text-slate-400 mt-1">
            If the collection doesn&apos;t exist yet it will be created with this exact name.
          </p>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={isRunning || !topic.trim()}
          className="w-full rounded-xl bg-slate-800 text-white py-3 px-4 font-medium
                     hover:bg-slate-700 active:bg-slate-900 transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2"
        >
          {isRunning ? (
            <>
              <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Running workflow…
            </>
          ) : (
            <>🔬 Generate Literature Review</>
          )}
        </button>
      </form>
    </div>
  );
}
