<script lang="ts">
  const MODE_LABELS: Record<string, string> = { off: 'Off', local: 'Local', api: 'API' };
  const MODE_TIPS: Record<string, string> = {
    off:   'No AI — fully offline. Only rule-based cleanup is available.',
    local: 'Use a local model (e.g. Ollama) for AI cleanup. Stays on your machine.',
    api:   'Use a cloud API model for AI cleanup. Sends text to your provider.',
  };

  let {
    mode = 'off',
    onModeChange,
  }: {
    mode?: string;
    onModeChange?: (m: string) => void;
  } = $props();
</script>

<div class="switch-wrap" title="Intelligence mode">
  <span class="label">Intelligence</span>
  <div class="pills" aria-label="Intelligence mode" role="group">
    {#each Object.keys(MODE_LABELS) as m}
      <button
        class="pill"
        class:active={mode === m}
        aria-pressed={mode === m}
        title={MODE_TIPS[m]}
        onclick={() => onModeChange?.(m)}
      >
        {MODE_LABELS[m]}
      </button>
    {/each}
  </div>
</div>

<style>
  .switch-wrap {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
  }
  .label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .pills {
    display: flex;
    background: var(--surface-1);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    padding: 3px;
    gap: 3px;
  }
  .pill {
    padding: 5px 13px;
    font-size: 12px;
    font-weight: 600;
    font-family: var(--font-ui);
    border: none;
    border-radius: 5px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
  }
  .pill:hover:not(.active) { color: var(--text-primary); background: var(--surface-2); }
  .pill.active {
    background: var(--accent);
    color: #fff;
  }
  .pill:focus-visible {
    outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent);
    outline-offset: 1px;
  }
</style>
