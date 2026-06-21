<script lang="ts">
  // Horizontal multi-step indicator, modelled on Nuxt UI's <UStepper>.
  // Steps before `current` render as complete (check), `current` is active,
  // the rest are pending. When `error` is set, the active step turns red.
  export interface Step {
    title: string;
    description?: string;
  }

  let {
    steps,
    current,
    error = false,
    done = false,
  }: {
    steps: Step[];
    current: number;
    error?: boolean;
    done?: boolean;
  } = $props();

  function stateOf(i: number): 'complete' | 'active' | 'error' | 'pending' {
    if (done) return 'complete';
    if (i < current) return 'complete';
    if (i === current) return error ? 'error' : 'active';
    return 'pending';
  }
</script>

<ol class="stepper" role="list">
  {#each steps as step, i}
    {@const st = stateOf(i)}
    <li class="step" data-state={st}>
      <div class="marker-row">
        <span class="line line-left" class:filled={i <= current && i > 0}></span>
        <span class="marker" aria-hidden="true">
          {#if st === 'complete'}
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
                 stroke="currentColor" stroke-width="3"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M5 13l4 4L19 7" />
            </svg>
          {:else if st === 'error'}
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
                 stroke="currentColor" stroke-width="3"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          {:else if st === 'active'}
            <span class="pulse"></span>
          {:else}
            <span class="num">{i + 1}</span>
          {/if}
        </span>
        <span class="line line-right" class:filled={i < current}></span>
      </div>
      <div class="label">
        <span class="title">{step.title}</span>
        {#if step.description}
          <span class="desc">{step.description}</span>
        {/if}
      </div>
    </li>
  {/each}
</ol>

<style>
  .stepper {
    display: flex;
    list-style: none;
    width: 100%;
    margin: 0;
    padding: 0;
  }
  .step {
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    min-width: 0;
  }

  .marker-row {
    display: flex;
    align-items: center;
    width: 100%;
  }
  .line {
    flex: 1 1 auto;
    height: 2px;
    background: var(--border);
    transition: background var(--transition);
  }
  .line.filled { background: var(--accent); }
  /* First step has no incoming line, last has no outgoing — keep them invisible
     but present so every marker sits dead-centre in its column. */
  .step:first-child .line-left,
  .step:last-child  .line-right { visibility: hidden; }

  .marker {
    flex: 0 0 auto;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    border: 2px solid var(--border-strong);
    background: var(--surface-1);
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 700;
    font-family: var(--font-ui);
    transition: background var(--transition), border-color var(--transition),
                color var(--transition);
  }
  .num { line-height: 1; }

  .step[data-state='complete'] .marker {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  .step[data-state='active'] .marker {
    border-color: var(--accent);
    color: var(--accent);
    box-shadow: 0 0 0 4px var(--accent-dim);
  }
  .step[data-state='error'] .marker {
    background: var(--red);
    border-color: var(--red);
    color: #fff;
  }

  .pulse {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--accent);
    animation: pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { transform: scale(0.7); opacity: 0.6; }
    50%      { transform: scale(1);   opacity: 1; }
  }

  .label {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-top: var(--sp-2);
    padding: 0 var(--sp-1);
  }
  .title {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
    transition: color var(--transition);
  }
  .step[data-state='active'] .title { color: var(--text-primary); }
  .step[data-state='complete'] .title { color: var(--text-secondary); }
  .step[data-state='error'] .title { color: var(--red); }
  .desc {
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.3;
  }

  @media (prefers-reduced-motion: reduce) {
    .pulse { animation: none; }
  }
</style>
