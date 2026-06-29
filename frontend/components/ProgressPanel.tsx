"use client";

export interface ProgressEvent {
  type: "status";
  phase: string;
  message: string;
}

interface Props {
  events: ProgressEvent[];
  isRunning: boolean;
  heartbeat?: { phase: string; message: string } | null;
  error?: string;
}

const PHASE_META: Record<string, { label: string; color: string }> = {
  start:          { label: "Starting",      color: "bg-slate-400"   },
  llm_setup:      { label: "LLM",           color: "bg-cyan-500"    },
  zotero_setup:   { label: "Zotero",        color: "bg-violet-500"  },
  decompose:      { label: "Planning",      color: "bg-indigo-500"  },
  search:         { label: "Searching",     color: "bg-blue-500"    },
  classify:       { label: "Classifying",   color: "bg-fuchsia-500" },
  synthesize:     { label: "Synthesizing",  color: "bg-amber-500"   },
  verify:         { label: "Verifying",     color: "bg-orange-500"  },
  zotero_save:    { label: "Saving",        color: "bg-emerald-500" },
  bibliography:   { label: "Bibliography",  color: "bg-teal-500"    },
  saving:         { label: "Finalising",    color: "bg-slate-500"   },
  // legacy / fallback tool-call phases kept for compatibility
  create_collection:          { label: "Zotero",       color: "bg-violet-500"  },
  get_collection_key_by_name: { label: "Zotero",       color: "bg-violet-500"  },
  get_collection_items:       { label: "Zotero",       color: "bg-violet-500"  },
  search_papers:              { label: "Searching",    color: "bg-blue-500"    },
  verify_doi:                 { label: "Verifying",    color: "bg-orange-500"  },
  get_abstract:               { label: "Verifying",    color: "bg-orange-500"  },
  add_item:                   { label: "Saving",       color: "bg-emerald-500" },
  export_bibliography:        { label: "Bibliography", color: "bg-teal-500"    },
};

function dotColor(phase: string) {
  return PHASE_META[phase]?.color ?? "bg-slate-400";
}

function label(phase: string) {
  return PHASE_META[phase]?.label ?? phase;
}

export default function ProgressPanel({ events, isRunning, heartbeat, error }: Props) {
  // The last event is "current" only when there's no heartbeat active
  const currentEvent = isRunning && !heartbeat ? events[events.length - 1] ?? null : null;
  const completedEvents = isRunning
    ? heartbeat ? events : events.slice(0, -1)
    : events;

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
        <h2 className="font-semibold text-slate-700">Workflow progress</h2>
        {isRunning && (
          <span className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            Running
          </span>
        )}
        {error && <span className="text-xs text-red-500 font-medium">Error</span>}
        {!isRunning && !error && events.length > 0 && (
          <span className="text-xs text-emerald-600 font-medium">✓ Complete</span>
        )}
      </div>

      <div className="px-6 py-4 max-h-96 overflow-y-auto space-y-1 text-sm font-mono">
        {/* Completed steps */}
        {completedEvents.map((ev, idx) => (
          <div key={idx} className="flex items-start gap-2 text-slate-400">
            <span className={`mt-1.5 flex-shrink-0 w-2 h-2 rounded-full ${dotColor(ev.phase)}`} />
            <span>
              <span className="text-slate-300 text-xs mr-1">[{label(ev.phase)}]</span>
              {ev.message}
            </span>
          </div>
        ))}

        {/* Heartbeat */}
        {heartbeat && isRunning && (
          <div className="flex items-start gap-2 text-slate-700 font-medium">
            <span className={`mt-1.5 flex-shrink-0 w-2 h-2 rounded-full ${dotColor(heartbeat.phase)} animate-pulse`} />
            <span>
              <span className="text-slate-400 text-xs mr-1">[{label(heartbeat.phase)}]</span>
              {heartbeat.message}
              <span className="ml-1 inline-flex gap-0.5">
                <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
              </span>
            </span>
          </div>
        )}

        {/* Current step (when no heartbeat) */}
        {currentEvent && (
          <div className="flex items-start gap-2 text-slate-800 font-medium">
            <span className={`mt-1.5 flex-shrink-0 w-2 h-2 rounded-full ${dotColor(currentEvent.phase)} animate-pulse`} />
            <span>
              <span className="text-slate-500 text-xs mr-1">[{label(currentEvent.phase)}]</span>
              {currentEvent.message}
            </span>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mt-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs font-sans not-italic whitespace-pre-wrap">
            <span className="font-semibold">Error: </span>{error}
          </div>
        )}
      </div>
    </div>
  );
}
