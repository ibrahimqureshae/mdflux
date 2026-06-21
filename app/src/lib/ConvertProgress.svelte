<script lang="ts">
  let {
    stage = 'converting',
    onCancel,
  }: {
    stage?: string;
    onCancel: () => void;
  } = $props();

  const STAGE_LABELS: Record<string, string> = {
    downloading: 'Downloading from the cloud…',
    preflight:  'Checking file…',
    extracting: 'Extracting content…',
    formatting: 'Finishing up…',
  };

  let cancelPending = $state(false);

  function handleCancel() {
    cancelPending = true;
    onCancel();
  }
</script>

<div class="wrap">
  <p class="stage-label">{STAGE_LABELS[stage] ?? 'Converting…'}</p>

  <div class="track" role="progressbar" aria-label="Conversion in progress" aria-busy="true">
    <div class="fill"></div>
  </div>

  <button
    class="cancel-btn"
    onclick={handleCancel}
    disabled={cancelPending}
    aria-label="Cancel conversion"
  >
    {cancelPending ? 'Cancelling…' : 'Cancel'}
  </button>
</div>

<style>
  .wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--sp-4);
  }

  .stage-label {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
    min-height: 1.4em;
  }

  .track {
    width: min(320px, 80%);
    height: 3px;
    background: var(--border);
    border-radius: 999px;
    overflow: hidden;
  }

  .fill {
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
    animation: indeterminate 1.6s ease-in-out infinite;
    transform-origin: left center;
  }

  @keyframes indeterminate {
    0%   { transform: translateX(-100%) scaleX(0.4); }
    50%  { transform: translateX(60%)   scaleX(0.6); }
    100% { transform: translateX(200%) scaleX(0.4); }
  }

  @media (prefers-reduced-motion: reduce) {
    .fill { animation: none; width: 100%; opacity: 0.35; }
  }

  .cancel-btn {
    padding: var(--sp-2) var(--sp-6);
    font-size: 13px;
    font-weight: 600;
    font-family: var(--font-ui);
    color: var(--text-primary);
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
  }
  .cancel-btn:hover:not(:disabled) {
    background: var(--red);
    border-color: var(--red);
    color: #fff;
  }
  .cancel-btn:disabled {
    opacity: 0.5;
    cursor: wait;
  }
  .cancel-btn:focus-visible {
    outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent);
    outline-offset: 3px;
    border-radius: var(--radius-sm);
  }
</style>
