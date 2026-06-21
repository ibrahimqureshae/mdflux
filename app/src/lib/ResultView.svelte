<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { CLEANUP_RULES, totalChanges } from './cleanup';
  import type { CleanupResult, CleanupMethod, CleanupUIState, ViewMode } from './cleanup';
  import { lineDiff } from './diff';
  import type { DiffResult } from './diff';
  import { renderMarkdown } from './mdpreview';
  import { buildOutputFilename, type NamingCase } from './naming';
  import { onDestroy } from 'svelte';

  let {
    markdown,
    detectedFormat,
    converterPath,
    warnings = [],
    sourceStem = 'output',
    sourcePath = '',
    extractImages = true,
    namingTemplate = '{stem}',
    namingCase = 'keep',
    onClear,
    onOpenFile,
    llmMode = 'off',
    cleanupSeen = true,
    onSeenCleanup,
    cleanup,
  }: {
    markdown: string;
    detectedFormat: string;
    converterPath: string;
    warnings?: string[];
    sourceStem?: string;
    sourcePath?: string;
    extractImages?: boolean;
    namingTemplate?: string;
    namingCase?: string;
    onClear: () => void;
    onOpenFile: () => Promise<void>;
    llmMode?: string;
    cleanupSeen?: boolean;
    onSeenCleanup?: () => void;
    cleanup: CleanupUIState;
  } = $props();

  // Save name follows the configured naming convention ({stem}/{ext}/{date} + case).
  const outName = $derived(
    buildOutputFilename(`${sourceStem}.${(detectedFormat || '').toLowerCase()}`, namingTemplate, namingCase as NamingCase),
  );

  const running = $derived(cleanup.running);
  const llmAvailable = $derived(llmMode === 'local' || llmMode === 'api');

  // The cleaned text for the active method (null until produced).
  const activeCleaned = $derived(
    cleanup.method === 'rules' ? cleanup.rulesCleaned
    : cleanup.method === 'ai' ? cleanup.aiCleaned
    : null,
  );
  const activeMarkdown = $derived(activeCleaned ?? markdown);
  const hasChanges = $derived(cleanup.method !== 'none' && activeCleaned !== null);

  const diff = $derived<DiffResult | null>(
    hasChanges && cleanup.viewMode === 'changes' ? lineDiff(markdown, activeCleaned as string) : null,
  );
  const previewHtml = $derived(
    cleanup.viewMode === 'preview' ? renderMarkdown(activeMarkdown) : '',
  );
  // Split view = before/after cleanup, rendered side by side.
  const beforeHtml = $derived(cleanup.viewMode === 'split' ? renderMarkdown(markdown) : '');
  const afterHtml  = $derived(cleanup.viewMode === 'split' ? renderMarkdown(activeMarkdown) : '');

  // Tracks whether the active markdown has been saved to disk. Reset synchronously
  // at each content-mutating handler (not via $effect — writing $state in $effect
  // is a Svelte 5 anti-pattern that can cascade).
  let saved = $state(false);

  // ── Split view scroll-sync ───────────────────────────────────────────────────
  let splitSrcEl = $state<HTMLElement | null>(null);
  let splitPrevEl = $state<HTMLElement | null>(null);
  let syncing = false;
  function syncScroll(from: 'src' | 'prev') {
    if (syncing) return;
    const a = from === 'src' ? splitSrcEl : splitPrevEl;
    const b = from === 'src' ? splitPrevEl : splitSrcEl;
    if (!a || !b) return;
    const ratio = a.scrollTop / Math.max(1, a.scrollHeight - a.clientHeight);
    syncing = true;
    b.scrollTop = ratio * Math.max(1, b.scrollHeight - b.clientHeight);
    requestAnimationFrame(() => { syncing = false; });
  }

  const ruleChanges = $derived(totalChanges(cleanup.rulesSummary));
  const ruleCounts = $derived(
    Object.fromEntries((cleanup.rulesSummary?.rules ?? []).map(r => [r.key, r.changes])),
  );

  function setView(v: ViewMode) { cleanup.viewMode = v; }

  // ── Cleanup method ─────────────────────────────────────────────────────────
  async function selectMethod(m: CleanupMethod) {
    if (cleanup.method === m) return;
    cleanup.method = m;
    saved = false;
    // Split/Changes are before-vs-after views — meaningless with no cleanup.
    if (m === 'none' && (cleanup.viewMode === 'split' || cleanup.viewMode === 'changes')) {
      cleanup.viewMode = 'preview';
    }
    if (m !== 'none' && !cleanupSeen) onSeenCleanup?.();
    if (m === 'rules' && cleanup.rulesCleaned === null) await runRules();
  }

  async function runRules() {
    cleanup.running = true;
    saved = false;
    try {
      const res = await invoke<CleanupResult>('cleanup_markdown', {
        markdown, sourceFormat: detectedFormat, method: 'rules', rules: cleanup.rules,
      });
      cleanup.rulesCleaned = res.markdown;
      cleanup.rulesSummary = res.summary;
    } catch (e) {
      cleanup.rulesCleaned = markdown;
      cleanup.rulesSummary = null;
    } finally {
      cleanup.running = false;
    }
  }

  let cancelRequested = $state(false);

  async function runAi() {
    cleanup.running = true;
    cancelRequested = false;
    saved = false;
    try {
      const res = await invoke<CleanupResult>('cleanup_markdown', {
        markdown, sourceFormat: detectedFormat, method: 'ai', rules: {},
      });
      cleanup.aiCleaned = res.markdown;
      cleanup.aiApplied = res.llm_applied;
      cleanup.aiNotice = res.llm_notice;
    } catch (e) {
      if (cancelRequested) {
        cleanup.aiCleaned = null;
        cleanup.aiApplied = false;
        cleanup.aiNotice = 'AI cleanup cancelled — kept the original text.';
      } else {
        cleanup.aiCleaned = markdown;
        cleanup.aiApplied = false;
        cleanup.aiNotice = `AI cleanup failed: ${e}`;
      }
    } finally {
      cleanup.running = false;
      cancelRequested = false;
    }
  }

  async function cancelAi() {
    cancelRequested = true;
    try { await invoke('cancel_conversion'); } catch { /* will resolve/reject */ }
  }

  async function toggleRule(key: string) {
    cleanup.rules = { ...cleanup.rules, [key]: !cleanup.rules[key] };
    saved = false;
    await runRules();
  }

  // ── Copy / Save (operate on the active markdown) ─────────────────────────────
  let copyLabel = $state('Copy');
  let copyTimeout: ReturnType<typeof setTimeout>;
  let confirming = $state(false);

  onDestroy(() => clearTimeout(copyTimeout));

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(activeMarkdown);
      clearTimeout(copyTimeout);
      copyLabel = 'Copied!';
      copyTimeout = setTimeout(() => (copyLabel = 'Copy'), 2000);
    } catch {
      copyLabel = 'Failed';
      copyTimeout = setTimeout(() => (copyLabel = 'Copy'), 2000);
    }
  }
  let saveError = $state<string | null>(null);

  async function saveMarkdown(): Promise<boolean> {
    saveError = null;
    try {
      const ok = await invoke<boolean>('save_markdown', {
        content: activeMarkdown,
        suggestedName: outName,
        sourcePath: sourcePath || null,
        extractImages,
      });
      if (ok) saved = true;
      return ok;
    } catch (e) {
      saveError = `Could not save: ${e}`;
      return false;
    }
  }
  async function saveAndOpen() {
    const ok = await saveMarkdown();
    if (ok) { confirming = false; await onOpenFile(); }
  }
  function discardAndOpen() { confirming = false; onClear(); }

  // "Open a New File": only warn about losing the result if it isn't already saved.
  function requestOpenNew() {
    if (saved) onOpenFile();
    else confirming = true;
  }

  let modalEl = $state<HTMLElement | null>(null);
  let openNewBtnEl = $state<HTMLButtonElement | null>(null);

  // Modal focus management: focus the modal on open, trap Tab, close on Escape,
  // restore focus to the trigger on close.
  $effect(() => {
    if (confirming && modalEl) {
      modalEl.focus();
    }
  });

  function onModalKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      confirming = false;
      openNewBtnEl?.focus();
      return;
    }
    if (e.key === 'Tab' && modalEl) {
      const focusable = modalEl.querySelectorAll<HTMLElement>('button, [tabindex]:not([tabindex="-1"])');
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      // Handle Tab from the modal container itself (the initially-focused element).
      if (document.activeElement === modalEl) {
        e.preventDefault();
        if (e.shiftKey) last.focus(); else first.focus();
      } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  // Intercept link clicks in the preview so they don't navigate the app webview.
  function onPreviewClick(e: MouseEvent) {
    const a = (e.target as HTMLElement)?.closest('a');
    if (a) e.preventDefault();
  }
</script>

<div class="result-wrap">

  <!-- Header: filename + view toggle -->
  <div class="result-header">
    <div class="file-title" title={sourceStem}>
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
        <path d="M3 1.5h6L12 4.5V13a.5.5 0 0 1-.5.5h-8A.5.5 0 0 1 3 13V1.5z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>
        <path d="M8.5 1.5V5h3.5" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>
      </svg>
      <span class="filename">{sourceStem}</span>
    </div>

    <div class="seg view-seg" role="group" aria-label="View mode">
      <button class="seg-btn" class:active={cleanup.viewMode === 'preview'} aria-pressed={cleanup.viewMode === 'preview'} title="Rendered Markdown" onclick={() => setView('preview')}>Preview</button>
      <button class="seg-btn" class:active={cleanup.viewMode === 'source'} aria-pressed={cleanup.viewMode === 'source'} title="Raw Markdown text" onclick={() => setView('source')}>Source</button>
      {#if hasChanges}
        <button class="seg-btn" class:active={cleanup.viewMode === 'split'} aria-pressed={cleanup.viewMode === 'split'} title="Before and after cleanup, side by side" onclick={() => setView('split')}>Split</button>
        <button class="seg-btn" class:active={cleanup.viewMode === 'changes'} aria-pressed={cleanup.viewMode === 'changes'} title="What cleanup changed vs the original" onclick={() => setView('changes')}>Changes</button>
      {/if}
    </div>
  </div>

  <!-- Cleanup bar -->
  <div class="cleanup-bar">
    <div class="cleanup-head">
      <span class="cleanup-title">Clean up</span>
      <div class="seg seg-lg" role="group" aria-label="Cleanup method">
        <button class="seg-btn" class:active={cleanup.method === 'none'} aria-pressed={cleanup.method === 'none'} title="Show the raw conversion, unchanged" onclick={() => selectMethod('none')}>Off</button>
        <button class="seg-btn" class:active={cleanup.method === 'rules'} aria-pressed={cleanup.method === 'rules'} title="Clean up using fast, offline rules" onclick={() => selectMethod('rules')}>Rule-based</button>
        <button class="seg-btn" class:active={cleanup.method === 'ai'} aria-pressed={cleanup.method === 'ai'}
          onclick={() => selectMethod('ai')} disabled={!llmAvailable}
          title={llmAvailable ? 'Clean up with your configured AI model' : 'Switch to Local or API mode to enable AI cleanup'}>AI</button>
      </div>
      {#if !cleanupSeen && cleanup.method === 'none'}
        <span class="new-badge" aria-hidden="true">New</span>
      {/if}
    </div>

    {#if cleanup.method === 'rules'}
      <p class="cleanup-desc">
        Fast, offline rules — nothing leaves your machine. Toggle any rule to re-run.
        {#if running}<span class="muted">Cleaning…</span>
        {:else if cleanup.rulesSummary}<span class="muted" title="Total edits across all enabled rules">{ruleChanges === 0 ? 'No changes needed.' : `${ruleChanges.toLocaleString()} change${ruleChanges === 1 ? '' : 's'} total.`}</span>{/if}
      </p>
      <div class="rules-list">
        {#each CLEANUP_RULES as rule}
          <label class="rule-row" title="{rule.hint}. {cleanup.rules[rule.key] ? 'On' : 'Off'} — click to toggle.">
            <input type="checkbox" checked={cleanup.rules[rule.key]} onchange={() => toggleRule(rule.key)} disabled={running} />
            <span class="rule-text">
              <span class="rule-label">{rule.label}</span>
              <span class="rule-hint">{rule.hint}</span>
            </span>
            {#if cleanup.rulesSummary && cleanup.rules[rule.key]}
              {@const c = ruleCounts[rule.key] ?? 0}
              <span class="rule-count" class:rule-count-zero={c === 0} title="{c.toLocaleString()} {c === 1 ? 'edit' : 'edits'} this rule made">{c.toLocaleString()}</span>
            {/if}
          </label>
        {/each}
      </div>

    {:else if cleanup.method === 'ai'}
      {#if running}
        <div class="ai-running-row">
          <p class="cleanup-desc"><span class="spinner-inline" aria-hidden="true"></span> Cleaning with AI… large documents on a local model can take a few minutes.</p>
          <button class="btn-cancel" onclick={cancelAi} disabled={cancelRequested} title="Stop the AI cleanup and keep the original text">
            {cancelRequested ? 'Cancelling…' : 'Cancel'}
          </button>
        </div>
      {:else if cleanup.aiCleaned === null}
        <div class="ai-panel">
          <p class="cleanup-desc">Cleans the document with your {llmMode === 'api' ? 'configured API model' : 'local model'}, in one pass. Your raw result is kept.</p>
          {#if llmMode === 'api'}<p class="cost-warning">⚠ This sends the document text to your configured API provider.</p>{/if}
          <button class="btn-primary btn-sm" title="Send the document to your AI model and clean it up" onclick={runAi}>Run AI cleanup</button>
        </div>
      {:else}
        <p class="cleanup-desc">
          {#if cleanup.aiApplied}<span class="ok">AI cleanup applied.</span>{/if}
          <button class="link-btn" title="Run the AI cleanup again on the original text" onclick={runAi}>Run again</button>
        </p>
        {#if cleanup.aiNotice}<p class="warn">{cleanup.aiNotice}</p>{/if}
      {/if}
    {/if}
  </div>

  <!-- Content -->
  {#if cleanup.viewMode === 'split' && hasChanges}
    <div class="split">
      <div class="split-col">
        <div class="split-label">Before cleanup</div>
        <div class="split-pane split-source" bind:this={splitSrcEl} onscroll={() => syncScroll('src')} tabindex="0" role="region" aria-label="Before cleanup">
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="preview" onclick={onPreviewClick}>{@html beforeHtml}</div>
        </div>
      </div>
      <div class="split-col">
        <div class="split-label">After cleanup</div>
        <div class="split-pane" bind:this={splitPrevEl} onscroll={() => syncScroll('prev')} tabindex="0" role="region" aria-label="After cleanup">
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="preview" onclick={onPreviewClick}>{@html afterHtml}</div>
        </div>
      </div>
    </div>
  {:else}
  <div class="scroll-area" tabindex="0" role="region" aria-label="Markdown result">
    {#if cleanup.viewMode === 'changes' && diff}
      {#if diff.kind === 'summary'}
        <div class="diff-summary">
          <p>{diff.note}</p>
          <p class="diff-counts"><span class="add-count">+{diff.added.toLocaleString()}</span> <span class="del-count">−{diff.removed.toLocaleString()}</span> lines</p>
        </div>
      {:else}
        <div class="diff-view">
          {#each diff.rows as row}
            <div class="diff-row diff-{row.type}">
              <span class="diff-gutter" aria-hidden="true">{row.type === 'add' ? '+' : row.type === 'del' ? '−' : ''}</span>
              <span class="diff-text">{row.text || ' '}</span>
            </div>
          {/each}
        </div>
      {/if}
    {:else if cleanup.viewMode === 'preview'}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <div class="preview" onclick={onPreviewClick}>{@html previewHtml}</div>
    {:else}
      <pre class="markdown-view">{activeMarkdown}</pre>
    {/if}
  </div>
  {/if}

  <!-- Bottom bar -->
  <div class="bottom-bar">
    <span class="source-badge" title="Source format · {converterPath}">
      From: {detectedFormat}{#if warnings.length}<span class="warn-dot" title={warnings.join('\n')}>⚠</span>{/if}
    </span>
    <div class="actions">
      <button class="btn-secondary" title="Discard this result and convert a different file" onclick={requestOpenNew} bind:this={openNewBtnEl}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3 1.5h5L11 4.5V12a.5.5 0 0 1-.5.5h-7A.5.5 0 0 1 3 12V1.5z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M7 6.2v3.6M5.2 8h3.6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        Open a New File
      </button>
      <button class="btn-secondary" title="Copy the current Markdown to the clipboard" onclick={copyMarkdown}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><rect x="4.5" y="4.5" width="7.5" height="7.5" rx="1.3" stroke="currentColor" stroke-width="1.2"/><path d="M9.5 4.5V3a1 1 0 0 0-1-1h-5a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1H4.5" stroke="currentColor" stroke-width="1.2"/></svg>
        {copyLabel}
      </button>
      {#if saveError}<p class="save-error">{saveError}</p>{/if}
      <button class="btn-primary" title="Save the current Markdown to a .md file" onclick={saveMarkdown}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M7 1.5v7M4 6l3 3 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.5 11.5h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        Save as .md
      </button>
    </div>
  </div>
</div>

{#if confirming}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="modal-backdrop" onclick={() => { confirming = false; openNewBtnEl?.focus(); }}>
    <div class="modal" bind:this={modalEl} onclick={(e) => e.stopPropagation()} onkeydown={onModalKeydown} role="dialog" aria-modal="true" aria-labelledby="modal-title" tabindex="-1">
      <p id="modal-title" class="modal-title">Open a new file?</p>
      <p class="modal-body">Your current result will be lost unless you save it first.</p>
      <div class="modal-actions">
        <button class="btn-secondary" onclick={() => { confirming = false; openNewBtnEl?.focus(); }}>Cancel</button>
        <button class="btn-secondary" onclick={discardAndOpen}>Discard</button>
        <button class="btn-primary" onclick={saveAndOpen}>Save &amp; Open</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .result-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }

  /* Header */
  .result-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    border-bottom: 1px solid var(--border);
    background: var(--surface-2);
    flex-shrink: 0;
  }
  .file-title { display: flex; align-items: center; gap: var(--sp-2); min-width: 0; color: var(--text-muted); }
  .filename {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Segmented control — base .seg/.seg-btn in tokens.css; local: no-shrink + large variant. */
  .seg { flex-shrink: 0; }
  .seg-lg .seg-btn { padding: 7px 22px; font-size: 13px; }

  /* Cleanup bar */
  .cleanup-bar {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-4);
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--surface-2) 40%, var(--surface-1));
  }
  .cleanup-head { display: flex; align-items: center; gap: var(--sp-3); }
  .cleanup-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }

  .new-badge {
    font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    color: #fff; background: var(--accent); padding: 1px 6px; border-radius: 999px;
    animation: new-pulse 1.6s ease-in-out infinite;
  }
  @keyframes new-pulse {
    0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 50%, transparent); }
    50%      { box-shadow: 0 0 0 4px transparent; }
  }
  @media (prefers-reduced-motion: reduce) { .new-badge { animation: none; } }

  .cleanup-desc { font-size: 12px; color: var(--text-secondary); line-height: 1.5; margin: 0; }
  .muted { color: var(--text-muted); margin-left: var(--sp-1); }
  .ok { color: var(--green); }
  .warn { font-size: 11px; color: var(--amber); line-height: 1.5; margin: 0; }

  .spinner-inline {
    display: inline-block; width: 11px; height: 11px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: -1px; margin-right: 4px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spinner-inline { animation: none; } }

  .rules-list { display: flex; flex-direction: column; gap: 2px; padding: var(--sp-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .rule-row { display: flex; align-items: flex-start; gap: var(--sp-2); cursor: pointer; padding: 3px var(--sp-1); border-radius: var(--radius-sm); }
  .rule-row:hover { background: color-mix(in srgb, var(--surface-2) 60%, transparent); }
  .rule-row input { margin-top: 2px; accent-color: var(--accent); cursor: pointer; }
  .rule-text { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
  .rule-label { font-size: 12px; color: var(--text-primary); }
  .rule-hint  { font-size: 10px; color: var(--text-muted); }
  .rule-count { flex-shrink: 0; align-self: center; font-size: 11px; font-family: var(--font-mono); font-weight: 600; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); padding: 1px 7px; border-radius: 999px; min-width: 22px; text-align: center; }
  .rule-count-zero { color: var(--text-muted); background: var(--surface-2); }

  .ai-panel { display: flex; flex-direction: column; gap: var(--sp-2); align-items: flex-start; }
  .ai-running-row { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); }
  .cost-warning { font-size: 11px; color: var(--amber); line-height: 1.5; background: color-mix(in srgb, var(--amber) 10%, transparent); border: 1px solid color-mix(in srgb, var(--amber) 30%, transparent); border-radius: var(--radius-sm); padding: var(--sp-2); margin: 0; }
  .btn-cancel { flex-shrink: 0; padding: 4px var(--sp-4); font-size: 12px; font-weight: 600; font-family: var(--font-ui); color: #fff; background: var(--red); border: 1px solid transparent; border-radius: var(--radius-sm); cursor: pointer; transition: opacity var(--transition-fast); }
  .btn-cancel:hover { opacity: 0.85; }
  .btn-cancel:disabled { opacity: 0.55; cursor: default; }
  .btn-cancel:focus-visible { outline: 2px solid color-mix(in srgb, var(--red) 60%, transparent); outline-offset: 1px; }

  /* Content */
  .scroll-area { flex: 1; overflow-y: auto; padding: var(--sp-5) var(--sp-6); min-height: 0; outline: none; }
  .scroll-area:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: -2px; }

  /* Split view — before vs after cleanup, rendered side by side, scroll-synced. */
  .split { flex: 1; display: flex; min-height: 0; }
  .split-col { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
  .split-col + .split-col { border-left: 1px solid var(--border); }
  .split-label {
    flex-shrink: 0; padding: 6px var(--sp-6); font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted);
    background: var(--surface-2); border-bottom: 1px solid var(--border);
  }
  .split-pane { flex: 1; min-width: 0; overflow-y: auto; padding: var(--sp-5) var(--sp-6); min-height: 0; outline: none; }
  .split-pane:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: -2px; }
  .split-source { background: color-mix(in srgb, var(--surface-2) 30%, var(--surface-1)); }
  @media (max-width: 720px) {
    .split { flex-direction: column; }
    .split-col + .split-col { border-left: none; border-top: 1px solid var(--border); }
  }
  .markdown-view {
    font-family: var(--font-mono); font-size: 12.5px; line-height: 1.65; color: var(--text-primary);
    white-space: pre-wrap; word-break: break-word; user-select: text; background: transparent; border: none; tab-size: 2; margin: 0;
  }

  /* Rendered preview — {@html}, so descendants need :global() */
  .preview { color: var(--text-primary); font-size: 14px; line-height: 1.65; user-select: text; max-width: 760px; }
  .preview :global(h1) { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 var(--sp-3); padding-bottom: var(--sp-2); border-bottom: 1px solid var(--border); }
  .preview :global(h2) { font-size: 20px; font-weight: 700; margin: var(--sp-6) 0 var(--sp-2); }
  .preview :global(h3) { font-size: 16px; font-weight: 600; margin: var(--sp-5) 0 var(--sp-2); }
  .preview :global(h4), .preview :global(h5), .preview :global(h6) { font-size: 14px; font-weight: 600; margin: var(--sp-4) 0 var(--sp-1); }
  .preview :global(p) { margin: 0 0 var(--sp-3); }
  .preview :global(ul), .preview :global(ol) { margin: 0 0 var(--sp-3); padding-left: var(--sp-6); }
  .preview :global(li) { margin: 2px 0; }
  .preview :global(a) { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .preview :global(strong) { font-weight: 700; color: var(--text-primary); }
  .preview :global(em) { font-style: italic; }
  .preview :global(blockquote) { margin: 0 0 var(--sp-3); padding: var(--sp-1) var(--sp-4); border-left: 3px solid var(--border); color: var(--text-secondary); }
  .preview :global(hr) { border: none; border-top: 1px solid var(--border); margin: var(--sp-5) 0; }
  .preview :global(code) { font-family: var(--font-mono); font-size: 0.88em; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
  .preview :global(pre) { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: var(--sp-3); overflow-x: auto; margin: 0 0 var(--sp-3); }
  .preview :global(pre code) { background: none; padding: 0; }
  .preview :global(table) { border-collapse: collapse; margin: 0 0 var(--sp-3); font-size: 13px; display: block; overflow-x: auto; }
  .preview :global(th), .preview :global(td) { border: 1px solid var(--border); padding: 5px 10px; text-align: left; }
  .preview :global(th) { background: var(--surface-2); font-weight: 600; }
  .preview :global(img) { max-width: 100%; }

  /* Diff */
  .diff-view { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.6; user-select: text; }
  .diff-row { display: flex; gap: var(--sp-2); white-space: pre-wrap; word-break: break-word; padding: 0 var(--sp-1); }
  .diff-gutter { flex-shrink: 0; width: 10px; text-align: center; color: var(--text-muted); user-select: none; }
  .diff-text { flex: 1; min-width: 0; }
  .diff-same { color: var(--text-secondary); }
  .diff-add  { background: color-mix(in srgb, var(--green) 12%, transparent); }
  .diff-add .diff-text, .diff-add .diff-gutter { color: var(--green); }
  .diff-del  { background: color-mix(in srgb, var(--red) 12%, transparent); }
  .diff-del .diff-text, .diff-del .diff-gutter { color: var(--red); }
  .diff-summary { font-size: 13px; color: var(--text-secondary); display: flex; flex-direction: column; gap: var(--sp-2); }
  .diff-counts { font-family: var(--font-mono); }
  .add-count { color: var(--green); }
  .del-count { color: var(--red); margin-left: var(--sp-2); }

  /* Bottom bar */
  .bottom-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-4);
    border-top: 1px solid var(--border);
    background: var(--surface-2);
    flex-shrink: 0;
  }
  .source-badge {
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--text-muted);
    background: var(--surface-1);
    border: 1px solid var(--border);
    padding: 2px 10px;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .warn-dot { color: var(--amber); cursor: help; }
  .actions { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; }
  .save-error { font-size: 11px; color: var(--red); margin: 0; }

  /* Modal */
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: flex; align-items: center; justify-content: center; z-index: 100; }
  .modal { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius); padding: var(--sp-6); width: 340px; display: flex; flex-direction: column; gap: var(--sp-3); box-shadow: 0 8px 32px rgba(0,0,0,0.4); }
  .modal-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
  .modal-body { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
  .modal-actions { display: flex; justify-content: flex-end; gap: var(--sp-2); margin-top: var(--sp-2); }

  /* Buttons: .btn-primary / .btn-secondary / .btn-sm come from tokens.css. */
  .link-btn { background: none; border: none; padding: 0; font-size: 11px; font-family: var(--font-ui); color: var(--accent); text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
  .link-btn:hover { opacity: 0.8; }
  .link-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); border-radius: 2px; }
</style>
