"use client";

import { useState, useCallback } from "react";
import ReviewForm, { FormValues } from "@/components/ReviewForm";
import ProgressPanel, { ProgressEvent } from "@/components/ProgressPanel";
import ReviewOutput from "@/components/ReviewOutput";

type AppState = "idle" | "running" | "done" | "error";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export default function Home() {
  const [appState, setAppState] = useState<AppState>("idle");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [heartbeat, setHeartbeat] = useState<{ phase: string; message: string } | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [filename, setFilename] = useState("");
  const [downloadFormat, setDownloadFormat] = useState("md");
  const [errorMsg, setErrorMsg] = useState("");

  const handleSubmit = useCallback(async (values: FormValues) => {
    setAppState("running");
    setEvents([]);
    setHeartbeat(null);
    setMarkdown("");
    setFilename("");
    setErrorMsg("");
    setDownloadFormat(values.format);
    setHeartbeat({ phase: "start", message: "Connecting to workflow stream..." });

    try {
      const res = await fetch(`${API_BASE_URL}/api/review`, {
        method: "POST",
        headers: {
          "Accept": "text/event-stream",
          "Cache-Control": "no-cache",
          "Content-Type": "application/json",
        },
        cache: "no-store",
        body: JSON.stringify({
          topic: values.topic,
          depth: values.depth,
          format: values.format,
          zotero_collection: values.zoteroCollection,
          llm_backend: values.llmBackend,
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`API request failed (${res.status}): ${text || res.statusText}`);
      }
      const contentType = res.headers.get("content-type") ?? "";
      if (!contentType.includes("text/event-stream")) {
        const text = await res.text();
        throw new Error(`Expected event stream from API, got ${contentType || "unknown content type"}: ${text}`);
      }
      if (!res.body) throw new Error("No response stream");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let sawTerminalEvent = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));

            if (event.type === "status") {
              setHeartbeat(null); // clear heartbeat on real progress
              setEvents((prev) => [...prev, event as ProgressEvent]);
            } else if (event.type === "heartbeat") {
              setHeartbeat({ phase: event.phase, message: event.message });
            } else if (event.type === "result") {
              sawTerminalEvent = true;
              setHeartbeat(null);
              setMarkdown(event.markdown);
              setFilename(event.filename);
              setAppState("done");
            } else if (event.type === "error") {
              sawTerminalEvent = true;
              setHeartbeat(null);
              setErrorMsg(event.message);
              setAppState("error");
            }
          } catch {
            // malformed SSE line — ignore
          }
        }
      }

      if (!sawTerminalEvent) {
        throw new Error("API stream ended before returning a result or error.");
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setAppState("error");
    }
  }, []);

  const handleReset = useCallback(() => {
    setAppState("idle");
    setEvents([]);
    setHeartbeat(null);
    setMarkdown("");
    setFilename("");
    setErrorMsg("");
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-slate-800 text-white px-6 py-4 flex items-center gap-3">
        <span className="text-2xl">📚</span>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Auto Literature Review</h1>
          <p className="text-slate-400 text-sm">
            Scopus · Zotero · Selectable LLM
          </p>
        </div>
      </header>

      <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-8 flex flex-col gap-8">
        {/* Form — always visible unless done */}
        {appState !== "done" && (
          <ReviewForm
            onSubmit={handleSubmit}
            isRunning={appState === "running"}
          />
        )}

        {/* Progress panel */}
        {(appState === "running" || appState === "error") && (
          <ProgressPanel
            events={events}
            isRunning={appState === "running"}
            heartbeat={heartbeat}
            error={errorMsg}
          />
        )}

        {/* Result */}
        {appState === "done" && (
          <ReviewOutput
            markdown={markdown}
            filename={filename}
            defaultFormat={downloadFormat}
            onReset={handleReset}
          />
        )}
      </main>

      <footer className="text-center text-slate-400 text-xs py-4">
        Auto Literature Review · Local instance · Powered by Scopus, Zotero &amp; selectable LLMs
      </footer>
    </div>
  );
}
