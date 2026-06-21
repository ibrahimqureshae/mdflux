<script lang="ts">
  export interface ConvertError {
    code: string;
    title: string;
    detail: string;
    suggested_action: string;
    diagnostics_key?: string;
  }

  let {
    error,
    onDismiss,
    onOpenDiagnostics,
  }: {
    error: ConvertError;
    onDismiss: () => void;
    onOpenDiagnostics?: (key: string) => void;
  } = $props();
</script>

<div class="card" role="alert">
  <div class="header">
    <span class="icon" aria-hidden="true">✕</span>
    <span class="title">{error.title}</span>
    <button class="close" onclick={onDismiss} aria-label="Dismiss error">✕</button>
  </div>
  <p class="detail">{error.detail}</p>
  <div class="footer">
    <p class="action">{error.suggested_action}</p>
    {#if error.diagnostics_key && onOpenDiagnostics}
      <button
        class="diag-link"
        onclick={() => onOpenDiagnostics!(error.diagnostics_key!)}
      >
        View in Diagnostics →
      </button>
    {/if}
  </div>
</div>

<style>
  .card {
    background: color-mix(in srgb, var(--red) 8%, var(--surface-1));
    border: 1px solid color-mix(in srgb, var(--red) 30%, transparent);
    border-radius: var(--radius);
    padding: var(--sp-4);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .header {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .icon {
    font-size: 13px;
    color: var(--red);
    flex-shrink: 0;
    font-style: normal;
  }
  .title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    flex: 1;
  }
  .close {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 12px;
    padding: 2px var(--sp-1);
    border-radius: var(--radius-sm);
    transition: color var(--transition-fast);
    font-family: var(--font-ui);
  }
  .close:hover { color: var(--text-primary); }
  .detail {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
    user-select: text;
  }
  .footer {
    display: flex;
    align-items: baseline;
    gap: var(--sp-4);
    flex-wrap: wrap;
  }
  .action {
    font-size: 12px;
    color: var(--accent);
    font-weight: 500;
  }
  .diag-link {
    font-size: 12px;
    font-weight: 600;
    font-family: var(--font-ui);
    color: var(--accent);
    cursor: pointer;
    padding: 5px 11px;
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
    border-radius: var(--radius-sm);
    transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
  }
  .diag-link:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
  .diag-link:focus-visible {
    outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent);
    border-radius: 2px;
  }
</style>
