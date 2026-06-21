<script lang="ts">
  import { onMount } from 'svelte';
  import { listen } from '@tauri-apps/api/event';
  import { open } from '@tauri-apps/plugin-dialog';
  import type { ConvertError } from './ErrorCard.svelte';
  import ErrorCard from './ErrorCard.svelte';
  import { SUPPORTED_EXTS } from './formats';

  let {
    onAdd,
    error = null,
    onDismissError,
    onOpenDiagnostics,
  }: {
    /** Called with raw dropped/picked paths (files and/or folders). The parent
     *  expands folders and stages them — files are not converted immediately. */
    onAdd: (paths: string[]) => void;
    error?: ConvertError | null;
    onDismissError?: () => void;
    onOpenDiagnostics?: (key: string) => void;
  } = $props();

  type LocalState = 'idle' | 'drag-hover';
  let localState = $state<LocalState>('idle');
  let dropState = $derived(error ? 'error' : localState);

  onMount(() => {
    let unlistenDrop: (() => void) | undefined;
    let unlistenEnter: (() => void) | undefined;
    let unlistenLeave: (() => void) | undefined;
    let dead = false;

    listen<{ paths: string[] }>('tauri://drag-drop', (e) => {
      localState = 'idle';
      const paths = e.payload.paths ?? [];
      if (paths.length) onAdd(paths);
    }).then(fn => { if (dead) fn(); else unlistenDrop = fn; });

    listen('tauri://drag-enter', () => {
      localState = 'drag-hover';
    }).then(fn => { if (dead) fn(); else unlistenEnter = fn; });

    listen('tauri://drag-leave', () => {
      if (localState === 'drag-hover') localState = 'idle';
    }).then(fn => { if (dead) fn(); else unlistenLeave = fn; });

    return () => {
      dead = true;
      unlistenDrop?.();
      unlistenEnter?.();
      unlistenLeave?.();
    };
  });

  async function browse() {
    if (error) return;
    const selected = await open({
      multiple: true,
      filters: [
        { name: 'Supported files', extensions: SUPPORTED_EXTS },
        { name: 'All files', extensions: ['*'] },
      ],
    });
    if (!selected) return;
    const paths = Array.isArray(selected) ? (selected as string[]) : [selected as string];
    if (paths.length) onAdd(paths);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); browse(); }
  }
</script>

<div
  class="zone"
  class:drag-hover={dropState === 'drag-hover'}
  class:error-state={dropState === 'error'}
  role="button"
  tabindex={0}
  aria-label="Drop files or a folder, or click to browse"
  title="Drop one file, several files, or a folder here — or click to pick files"
  onclick={browse}
  onkeydown={onKeyDown}
>
  <!-- Animated gradient border ring -->
  <div class="border-ring" aria-hidden="true"></div>

  {#if dropState === 'error' && error}
    <div class="inner error-inner" role="presentation" onclick={(e) => e.stopPropagation()}>
      <ErrorCard {error} onDismiss={onDismissError ?? (() => {})} {onOpenDiagnostics} />
    </div>
  {:else}
    <div class="inner idle-inner">
      <div class="drop-icon" aria-hidden="true">
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 4v16M9 13l7-7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M5 24h22" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity=".4"/>
          <path d="M5 28h12" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity=".25"/>
        </svg>
      </div>
      <p class="label">Drop files or a folder</p>
      <p class="hint">or <span class="link">browse to choose</span></p>
      <p class="formats">PDF · DOCX · PPTX · XLSX · EPUB · HTML · CSV · JSON · images · audio</p>
    </div>
  {/if}
</div>

<style>
  .zone {
    flex: 1;
    position: relative;
    border-radius: var(--radius-lg);
    background: var(--surface-1);
    cursor: pointer;
    outline: none;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    transition: background var(--transition);
  }
  .zone:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: 3px; }
  .zone.error-state { cursor: default; }

  /* Hover: mouse hover OR drag-enter both brighten the zone */
  .zone:hover,
  .zone.drag-hover { background: var(--surface-2); }

  /* Signature element: animated gradient ring */
  .border-ring {
    position: absolute;
    inset: 0;
    border-radius: var(--radius-lg);
    padding: 1px;
    background: conic-gradient(
      from var(--angle, 0deg),
      var(--accent),
      transparent 30%,
      transparent 70%,
      var(--accent)
    );
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor;
            mask-composite: exclude;
    opacity: 0.35;
    transition: opacity var(--transition);
    animation: rotate-ring 6s linear infinite;
  }
  /* Ring brightens and speeds up on hover */
  .zone:hover .border-ring,
  .zone.drag-hover .border-ring { opacity: 0.85; animation-duration: 2.5s; }
  .zone.error-state .border-ring {
    background: conic-gradient(from var(--angle, 0deg), var(--red), transparent 40%, transparent 60%, var(--red));
    opacity: 0.5;
    animation: none;
  }

  @keyframes rotate-ring { to { --angle: 360deg; } }
  @property --angle {
    syntax: '<angle>';
    inherits: false;
    initial-value: 0deg;
  }
  @media (prefers-reduced-motion: reduce) {
    .border-ring { animation: none; }
  }

  .inner {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-8);
    width: 100%;
  }
  .error-inner {
    padding: var(--sp-6);
    align-items: stretch;
    cursor: default;
  }

  .drop-icon {
    color: var(--text-muted);
    margin-bottom: var(--sp-2);
    transition: color var(--transition);
  }
  /* Icon turns accent on hover */
  .zone:hover .drop-icon,
  .zone.drag-hover .drop-icon { color: var(--accent); }

  .label {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .hint {
    font-size: 13px;
    color: var(--text-secondary);
  }
  .link {
    color: var(--accent);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .formats {
    margin-top: var(--sp-2);
    font-size: 11px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    letter-spacing: 0.02em;
  }
</style>
