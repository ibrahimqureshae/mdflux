// Stage 5 — shared cleanup rule metadata and defaults.
// Mirrors the sidecar's RULE_ORDER (cleanup.py). Single source of truth for the UI.

export interface CleanupRuleDef {
  key: string;
  label: string;
  hint: string;
  /** PDF-oriented rules default-on only when the source is a PDF (context-aware). */
  pdfOnly: boolean;
}

export const CLEANUP_RULES: CleanupRuleDef[] = [
  { key: 'strip_cid',       label: 'Remove (cid:N) markers', hint: 'Strips PDF glyph artifacts like (cid:12)',                pdfOnly: true  },
  { key: 'dedup_lines',     label: 'Remove duplicate lines', hint: 'Drops repeated headers, footers, and page numbers',      pdfOnly: true  },
  { key: 'repair_lines',    label: 'Rejoin broken lines',    hint: 'Reconnects sentences split across lines or columns',     pdfOnly: true  },
  { key: 'collapse_blanks', label: 'Collapse blank runs',    hint: 'Normalises long runs of empty lines',                    pdfOnly: false },
  { key: 'detect_headings', label: 'Detect headings',        hint: 'Promotes clear heading lines to Markdown (conservative)', pdfOnly: false },
];

/**
 * Default rule set when cleanup is switched on. Per the locked decision, "cleanup on"
 * means all applicable rules on — but PDF-oriented rules only default-on for PDFs.
 */
export function defaultRules(sourceFormat: string): Record<string, boolean> {
  const isPdf = (sourceFormat || '').toLowerCase().includes('pdf');
  const out: Record<string, boolean> = {};
  for (const r of CLEANUP_RULES) out[r.key] = r.pdfOnly ? isPdf : true;
  return out;
}

export interface CleanupRuleSummary {
  key: string;
  label: string;
  applied: boolean;
  changes: number;
}

export interface CleanupSummary {
  rules: CleanupRuleSummary[];
  char_delta: number;
  line_delta: number;
}

export interface CleanupResult {
  markdown: string;
  summary: CleanupSummary;
  llm_applied: boolean;
  llm_notice: string | null;
}

/** Total changes across applied rules — used for headline counts. */
export function totalChanges(summary: CleanupSummary | null): number {
  if (!summary) return 0;
  return summary.rules.filter(r => r.applied).reduce((n, r) => n + r.changes, 0);
}

// ── Cleanup method + shared UI state ────────────────────────────────────────

export type CleanupMethod = 'none' | 'rules' | 'ai';
export type ViewMode = 'preview' | 'source' | 'split' | 'changes';

/**
 * Single-file cleanup state. Lifted to the page so it survives view changes.
 * Rule-based and AI results are cached separately so switching methods (or
 * toggling the diff) never silently re-runs a slow/costly AI pass.
 */
export interface CleanupUIState {
  method: CleanupMethod;
  rules: Record<string, boolean>;
  rulesCleaned: string | null;
  rulesSummary: CleanupSummary | null;
  aiCleaned: string | null;
  aiApplied: boolean;
  aiNotice: string | null;
  showAdvanced: boolean;
  /** How the content area renders the active markdown. */
  viewMode: ViewMode;
  /** True while a cleanup pass is in flight. Lifted here so it survives view
   *  changes (e.g. opening Diagnostics mid-run and returning). */
  running: boolean;
}

export function freshCleanup(sourceFormat: string): CleanupUIState {
  return {
    method: 'none',
    rules: defaultRules(sourceFormat),
    rulesCleaned: null,
    rulesSummary: null,
    aiCleaned: null,
    aiApplied: false,
    aiNotice: null,
    showAdvanced: false,
    viewMode: 'preview',
    running: false,
  };
}
