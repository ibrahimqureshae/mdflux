<script lang="ts">
  import type { ConvertError } from './ErrorCard.svelte';

  export interface BatchItemState {
    id: string;
    path: string;
    filename: string;
    status: string;
    frac: number | null;
    output_path: string | null;
    error: ConvertError | null;
    warnings?: string[];
  }

  let {
    items,
    phase,
    onCancel,
    onOpen,
  }: {
    items: BatchItemState[];
    phase: string;
    onCancel: () => void;
    onOpen?: (item: BatchItemState) => void;
  } = $props();

  const done      = $derived(items.filter(i => i.status === 'done').length);
  const failed    = $derived(items.filter(i => i.status === 'failed').length);
  const finished  = $derived(items.filter(i => i.status !== 'pending' && i.status !== 'running').length);
  const total     = $derived(items.length);
  const progress  = $derived(total > 0 ? finished / total : 0);
  const isCancelling = $derived(phase === 'cancelling');

  const STATUS_LABELS: Record<string, string> = {
    pending:    'Queued',
    running:    'Converting…',
    done:       'Done',
    failed:     'Failed',
    cancelled:  'Cancelled',
  };
</script>

<div class="batch-queue">

  <!-- Header -->
  <div class="queue-header">
    <div class="queue-title-row">
      <span class="queue-title">Converting {total} file{total === 1 ? '' : 's'}</span>
      <span class="queue-counts">
        {done} done{failed > 0 ? ` · ${failed} failed` : ''}
      </span>
    </div>

    <!-- Overall progress bar -->
    <div class="overall-bar" role="progressbar"
         aria-valuenow={Math.round(progress * 100)}
         aria-valuemin={0} aria-valuemax={100}
         aria-label="Overall batch progress">
      <div class="overall-fill" style="width: {progress * 100}%"></div>
    </div>

    <!-- Cancel -->
    <button
      class="cancel-btn"
      onclick={onCancel}
      disabled={isCancelling}
      aria-label={isCancelling ? 'Cancelling…' : 'Cancel batch'}
      title="Stop the whole batch. Files already finished are kept."
    >
      {isCancelling ? 'Cancelling…' : 'Cancel'}
    </button>
  </div>

  <!-- File list -->
  <ul class="file-list" aria-label="Conversion queue">
    {#each items as item (item.id)}
      <li class="file-row"
          class:row-failed={item.status === 'failed'}
          class:row-cancelled={item.status === 'cancelled'}>

        <!-- Status icon -->
        <span class="status-icon" aria-hidden="true">
          {#if item.status === 'done'}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" fill="color-mix(in srgb, var(--green) 18%, transparent)" stroke="var(--green)" stroke-width="1"/>
              <path d="M4.5 7l1.8 1.8L9.5 5" stroke="var(--green)" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          {:else if item.status === 'failed'}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" fill="color-mix(in srgb, var(--red) 18%, transparent)" stroke="var(--red)" stroke-width="1"/>
              <path d="M5 5l4 4M9 5l-4 4" stroke="var(--red)" stroke-width="1.3" stroke-linecap="round"/>
            </svg>
          {:else if item.status === 'cancelled'}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" stroke="var(--text-muted)" stroke-width="1"/>
              <path d="M5 7h4" stroke="var(--text-muted)" stroke-width="1.3" stroke-linecap="round"/>
            </svg>
          {:else if item.status === 'running'}
            <span class="spinner-sm" aria-label="Converting"></span>
          {:else}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" stroke="var(--border)" stroke-width="1"/>
              <circle cx="7" cy="7" r="2" fill="var(--border)"/>
            </svg>
          {/if}
        </span>

        <!-- Filename + status -->
        <div class="file-info">
          <span class="file-name">{item.filename}</span>

          {#if item.status === 'running' && item.frac !== null}
            <div class="file-bar" role="progressbar"
                 aria-valuenow={Math.round((item.frac ?? 0) * 100)}
                 aria-valuemin={0} aria-valuemax={100}>
              <div class="file-fill" style="width: {(item.frac ?? 0) * 100}%"></div>
            </div>
          {:else if item.status === 'running'}
            <div class="file-bar indeterminate" role="progressbar" aria-label="Converting"></div>
          {:else if item.status === 'failed' && item.error}
            <span class="file-error">{item.error.title} — {item.error.detail}</span>
          {:else}
            <span class="file-status">{STATUS_LABELS[item.status] ?? item.status}</span>
          {/if}
        </div>

        {#if item.status === 'done' && onOpen}
          <button class="btn-accent-soft btn-sm view-btn" title="View the converted Markdown" onclick={() => onOpen?.(item)}>View</button>
        {/if}

      </li>
    {/each}
  </ul>

</div>

<style>
  .batch-queue {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    gap: var(--sp-4);
  }

  /* Header */
  .queue-header {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    flex-shrink: 0;
  }
  .queue-title-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }
  .queue-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .queue-counts {
    font-size: 12px;
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }

  /* Overall progress */
  .overall-bar {
    height: 3px;
    background: var(--border);
    border-radius: 999px;
    overflow: hidden;
  }
  .overall-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
    transition: width 0.4s ease;
  }
  @media (prefers-reduced-motion: reduce) { .overall-fill { transition: none; } }

  /* Cancel button */
  .cancel-btn {
    align-self: flex-end;
    height: 34px;
    padding: 0 16px;
    font-size: 12.5px;
    font-weight: 600;
    font-family: var(--font-ui);
    color: var(--text-primary);
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast);
  }
  .cancel-btn:hover:not(:disabled) { color: #fff; background: var(--red); border-color: var(--red); }
  .cancel-btn:disabled { opacity: 0.55; cursor: default; }
  .cancel-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }

  /* File list */
  .file-list {
    flex: 1;
    overflow-y: auto;
    list-style: none;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    contain: content;
  }

  .file-row {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 1px solid var(--border);
    transition: background var(--transition-fast);
  }
  .file-row:last-child { border-bottom: none; }
  .file-row.row-failed  { background: color-mix(in srgb, var(--red) 4%, transparent); }
  .file-row.row-cancelled { opacity: 0.5; }

  /* View button styling is global (.btn-accent-soft/.btn-sm); only placement is local. */
  .view-btn { flex-shrink: 0; align-self: center; }

  /* Status icon */
  .status-icon {
    flex-shrink: 0;
    width: 14px;
    height: 14px;
    margin-top: 2px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .spinner-sm {
    width: 12px;
    height: 12px;
    border: 1.5px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: block;
  }
  @media (prefers-reduced-motion: reduce) { .spinner-sm { animation: none; } }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* File info */
  .file-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .file-name {
    font-size: 12px;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .file-status {
    font-size: 11px;
    color: var(--text-muted);
  }
  .file-error {
    font-size: 11px;
    color: var(--red);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Per-file progress bar */
  .file-bar {
    height: 2px;
    background: var(--border);
    border-radius: 999px;
    overflow: hidden;
  }
  .file-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
    transition: width 0.3s ease;
  }
  @media (prefers-reduced-motion: reduce) { .file-fill { transition: none; } }
  .file-bar.indeterminate {
    background: linear-gradient(90deg, var(--border) 0%, var(--accent) 50%, var(--border) 100%);
    background-size: 200% 100%;
    animation: shimmer 1.4s ease infinite;
  }
  @keyframes shimmer { to { background-position: -200% 0; } }
  @media (prefers-reduced-motion: reduce) {
    .file-bar.indeterminate { animation: none; background: var(--border); }
  }
</style>
