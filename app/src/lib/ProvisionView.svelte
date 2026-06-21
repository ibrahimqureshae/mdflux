<script lang="ts" module>
  export interface DownloadDetail {
    label: string;
    received: number;
    total?: number | null;
    speed: number; // bytes per second
  }
  export interface ProvisionProgress {
    step: string;
    message: string;
    pct: number;
    detail?: DownloadDetail | null;
  }
</script>

<script lang="ts">
  import Stepper, { type Step } from '$lib/Stepper.svelte';

  let { progress }: { progress: ProvisionProgress } = $props();

  const STEPS: Step[] = [
    { title: 'Setup tools',  description: 'Download uv' },
    { title: 'Python 3.12',  description: 'Runtime' },
    { title: 'Packages',     description: 'Converters' },
  ];

  // Map the backend step key onto the stepper index.
  const STEP_INDEX: Record<string, number> = {
    downloading_uv:     0,
    creating_env:       1,
    installing_packages: 2,
    done:               3,
  };

  let current = $derived(STEP_INDEX[progress.step] ?? 0);
  let done    = $derived(progress.step === 'done' || progress.pct >= 1);
  let detail  = $derived(progress.detail ?? null);
  // A determinate bar only when we know the total size (the uv download). Other
  // steps are driven by uv and report no byte totals, so they stay indeterminate.
  let hasTotal = $derived(!!detail && typeof detail.total === 'number' && detail.total! > 0);
  let frac     = $derived(hasTotal ? Math.min(1, detail!.received / detail!.total!) : 0);

  // What ships in the "Packages" step — shown so the user sees exactly what's
  // being installed, not just a spinner.
  const PACKAGES = [
    { name: 'markitdown',  note: 'core document converter' },
    { name: 'PDF · Word · PowerPoint · Excel', note: 'format support' },
    { name: 'openai',      note: 'AI cleanup client' },
  ];

  function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }
  function formatSpeed(bps: number): string {
    if (bps <= 0) return '';
    if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
    return `${(bps / (1024 * 1024)).toFixed(1)} MB/s`;
  }

  let sizeText = $derived(
    detail
      ? hasTotal
        ? `${formatBytes(detail.received)} / ${formatBytes(detail.total!)}`
        : detail.received > 0
          ? formatBytes(detail.received)
          : ''
      : ''
  );
  let speedText = $derived(detail ? formatSpeed(detail.speed) : '');
</script>

<div class="provision">
  <header class="head">
    <h1>Setting up MDFlux</h1>
    <p class="sub">One-time setup of the local conversion engine.</p>
  </header>

  <Stepper steps={STEPS} {current} {done} />

  <div class="detail-card" aria-live="polite">
    <p class="status">{done ? 'Setup complete.' : progress.message}</p>

    {#if detail && !done}
      <p class="what">{detail.label}</p>
    {/if}

    {#if hasTotal && !done}
      <div class="bar" role="progressbar"
           aria-valuenow={Math.round(frac * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div class="bar-fill" style="width: {frac * 100}%"></div>
      </div>
    {:else if !done}
      <div class="bar" role="progressbar" aria-busy="true" aria-label={progress.message}>
        <div class="bar-fill indeterminate"></div>
      </div>
    {/if}

    {#if !done && (sizeText || speedText)}
      <div class="metrics">
        {#if sizeText}<span class="metric">{sizeText}</span>{/if}
        {#if hasTotal}<span class="metric">{Math.round(frac * 100)}%</span>{/if}
        {#if speedText}<span class="metric speed">↓ {speedText}</span>{/if}
      </div>
    {/if}

    {#if current === 2 && !done}
      <ul class="pkg-list">
        {#each PACKAGES as p}
          <li><span class="pkg-name">{p.name}</span><span class="pkg-note">{p.note}</span></li>
        {/each}
      </ul>
    {/if}
  </div>

  <p class="hint">Internet required · this runs once</p>
</div>

<style>
  .provision {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--sp-6);
    width: min(520px, 92%);
    margin: 0 auto;
    padding: var(--sp-6) 0;
  }

  .head { text-align: center; }
  .head h1 {
    font-size: 19px;
    font-weight: 700;
    color: var(--text-primary);
  }
  .sub {
    margin-top: var(--sp-1);
    font-size: 13px;
    color: var(--text-secondary);
  }

  .detail-card {
    width: 100%;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .status {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-primary);
    min-height: 1.4em;
  }
  .what {
    font-size: 12px;
    color: var(--text-secondary);
    font-family: var(--font-mono);
    word-break: break-word;
  }

  .bar {
    height: 6px;
    background: var(--surface-3);
    border-radius: 999px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
    transition: width 150ms linear;
    transform-origin: left center;
  }
  .bar-fill.indeterminate {
    width: 45%;
    animation: indeterminate 1.5s ease-in-out infinite;
  }
  @keyframes indeterminate {
    0%   { transform: translateX(-120%); }
    100% { transform: translateX(260%); }
  }

  .metrics {
    display: flex;
    gap: var(--sp-4);
    font-size: 12px;
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
  }
  .metric.speed { color: var(--accent); font-weight: 600; margin-left: auto; }

  .pkg-list {
    list-style: none;
    margin: var(--sp-1) 0 0;
    padding: var(--sp-3) 0 0;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .pkg-list li {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    font-size: 12px;
  }
  .pkg-name { color: var(--text-primary); font-weight: 600; }
  .pkg-note { color: var(--text-muted); }

  .hint {
    font-size: 12px;
    color: var(--text-muted);
  }

  @media (prefers-reduced-motion: reduce) {
    .bar-fill.indeterminate { animation: none; width: 100%; opacity: 0.35; }
  }
</style>
