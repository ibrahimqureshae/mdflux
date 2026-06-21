<script lang="ts">
  import type { BatchItemState } from './BatchQueueView.svelte';
  import { onDestroy } from 'svelte';

  let {
    items,
    onRetry,
    onClose,
    onOpen,
    onOpenFolder,
    cleanupApplied = false,
    cleanupChanges = 0,
  }: {
    items: BatchItemState[];
    onRetry: () => void;
    onClose: () => void;
    onOpen?: (item: BatchItemState) => void;
    onOpenFolder?: () => void;
    cleanupApplied?: boolean;
    cleanupChanges?: number;
  } = $props();

  const done      = $derived(items.filter(i => i.status === 'done').length);
  const failed    = $derived(items.filter(i => i.status === 'failed').length);
  const cancelled = $derived(items.filter(i => i.status === 'cancelled').length);
  const warned    = $derived(items.filter(i => i.status === 'done' && (i.warnings?.length ?? 0) > 0).length);
  const total     = $derived(items.length);
  const hasFailed = $derived(failed > 0);

  let copied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout>;
  onDestroy(() => clearTimeout(copyTimer));

  function copyFailures() {
    const text = items
      .filter(i => i.status === 'failed')
      .map(i => `${i.filename}: ${i.error?.detail ?? 'unknown error'}`)
      .join('\n');
    navigator.clipboard.writeText(text).then(() => {
      clearTimeout(copyTimer);
      copied = true;
      copyTimer = setTimeout(() => (copied = false), 1800);
    }).catch(() => {
      copied = false;
    });
  }
</script>

<div class="summary">

  <!-- Stats row -->
  <div class="stats">
    {#if done > 0}
      <span class="stat stat-done">
        <span class="stat-num">{done}</span>
        <span class="stat-label">converted</span>
      </span>
    {/if}
    {#if failed > 0}
      <span class="stat stat-failed">
        <span class="stat-num">{failed}</span>
        <span class="stat-label">failed</span>
      </span>
    {/if}
    {#if cancelled > 0}
      <span class="stat stat-cancelled">
        <span class="stat-num">{cancelled}</span>
        <span class="stat-label">cancelled</span>
      </span>
    {/if}
    {#if warned > 0}
      <span class="stat stat-warned" title="Converted, but the file had no extractable content">
        <span class="stat-num">{warned}</span>
        <span class="stat-label">with notices</span>
      </span>
    {/if}
  </div>

  {#if cleanupApplied && done > 0}
    <div class="cleanup-note">
      <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <path d="M2 7.5L5.5 11L12 3.5" stroke="var(--accent)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span>
        Cleanup applied to every converted file{cleanupChanges > 0 ? ` — ${cleanupChanges.toLocaleString()} change${cleanupChanges === 1 ? '' : 's'} in total` : ''}.
      </span>
    </div>
  {/if}

  <!-- Results list -->
  <ul class="results-list" aria-label="Conversion results">
    {#each items as item (item.id)}
      <li class="result-row"
          class:result-done={item.status === 'done'}
          class:result-failed={item.status === 'failed'}
          class:result-cancelled={item.status === 'cancelled'}>

        <!-- Status dot -->
        <span class="dot"
          class:dot-green={item.status === 'done' && !(item.warnings?.length)}
          class:dot-amber={item.status === 'done' && !!item.warnings?.length}
          class:dot-red={item.status === 'failed'}
          class:dot-muted={item.status === 'cancelled' || item.status === 'pending'}
          aria-hidden="true">
        </span>

        <!-- File info -->
        <div class="result-info">
          <span class="result-filename">{item.filename}</span>
          {#if item.status === 'done' && item.output_path}
            <span class="result-detail result-out">→ {item.output_path}</span>
            {#if item.warnings?.length}
              <span class="result-detail result-warn">⚠ {item.warnings.join(' · ')}</span>
            {/if}
          {:else if item.status === 'failed' && item.error}
            <span class="result-detail result-err">{item.error.title} — {item.error.detail}</span>
          {:else if item.status === 'cancelled'}
            <span class="result-detail result-muted">Cancelled</span>
          {/if}
        </div>

        {#if item.status === 'done' && onOpen}
          <button class="btn-accent-soft btn-sm view-btn" title="View the converted Markdown" onclick={() => onOpen?.(item)}>View</button>
        {/if}

      </li>
    {/each}
  </ul>

  <!-- Actions -->
  <div class="actions">
    {#if hasFailed}
      <button class="btn-primary" title="Re-run only the files that failed, with the same settings" onclick={onRetry}>
        Retry {failed} failed file{failed === 1 ? '' : 's'}
      </button>
      <button class="btn-secondary" title="Copy the list of failed files and their errors" onclick={copyFailures}>
        {copied ? 'Copied!' : 'Copy failures'}
      </button>
    {/if}
    {#if done > 0 && onOpenFolder}
      <button class="btn-secondary" title="Reveal the converted files in your file manager" onclick={onOpenFolder}>
        Open folder
      </button>
    {/if}
    <button class="btn-secondary" title="Clear this summary and start a new conversion" onclick={onClose}>
      Convert more files
    </button>
  </div>

</div>

<style>
  .summary {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    min-height: 0;
  }

  /* Stats */
  .stats {
    display: flex;
    gap: var(--sp-3);
    flex-shrink: 0;
  }
  .cleanup-note {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-shrink: 0;
    font-size: 12px;
    color: var(--text-secondary);
    background: color-mix(in srgb, var(--accent) 7%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
    border-radius: var(--radius-sm);
    padding: var(--sp-2) var(--sp-3);
  }
  .stat {
    display: flex;
    align-items: baseline;
    gap: 5px;
    padding: var(--sp-2) var(--sp-3);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
  }
  .stat-num {
    font-size: 20px;
    font-weight: 700;
    font-family: var(--font-mono);
    line-height: 1;
  }
  .stat-label {
    font-size: 11px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .stat-done    { background: color-mix(in srgb, var(--green) 8%, transparent); }
  .stat-done .stat-num    { color: var(--green); }
  .stat-failed  { background: color-mix(in srgb, var(--red) 8%, transparent); }
  .stat-failed .stat-num  { color: var(--red); }
  .stat-cancelled { background: color-mix(in srgb, var(--text-muted) 8%, transparent); }
  .stat-cancelled .stat-num { color: var(--text-muted); }
  .stat-warned { background: color-mix(in srgb, var(--amber) 8%, transparent); }
  .stat-warned .stat-num { color: var(--amber); }

  /* Results list */
  .results-list {
    flex: 1;
    overflow-y: auto;
    list-style: none;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    contain: content;
  }

  .result-row {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 1px solid var(--border);
  }
  .result-row:last-child { border-bottom: none; }
  .result-failed  { background: color-mix(in srgb, var(--red) 4%, transparent); }
  .result-cancelled { opacity: 0.45; }

  .dot {
    flex-shrink: 0;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    margin-top: 4px;
  }
  .dot-green { background: var(--green); }
  .dot-amber { background: var(--amber); }
  .dot-red   { background: var(--red); }
  .dot-muted { background: var(--text-muted); }

  .result-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .result-filename {
    font-size: 12px;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .result-detail {
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: var(--font-mono);
  }
  .result-out  { color: var(--text-muted); }
  .result-err  { color: var(--red); }
  .result-warn { color: var(--amber); font-family: var(--font-ui); white-space: normal; }
  .result-muted { color: var(--text-muted); font-family: var(--font-ui); }

  /* The View button styling is the global .btn-accent-soft/.btn-sm; only its placement
     in the result row is local. */
  .view-btn { align-self: center; flex-shrink: 0; }

  /* Action buttons (.btn-primary / .btn-secondary / .btn-accent-soft / .btn-sm) and the
     row container come from tokens.css. */
  .actions {
    display: flex;
    gap: var(--sp-2);
    flex-shrink: 0;
    flex-wrap: wrap;
  }
</style>
