<script lang="ts">
  import { renderMarkdown } from './mdpreview';
  import { onDestroy } from 'svelte';

  let {
    name,
    markdown,
    onBack,
  }: {
    name: string;
    markdown: string;
    onBack: () => void;
  } = $props();

  let view = $state<'preview' | 'source'>('preview');
  const previewHtml = $derived(view === 'preview' ? renderMarkdown(markdown) : '');

  let copyLabel = $state('Copy');
  let copyTimer: ReturnType<typeof setTimeout>;
  onDestroy(() => clearTimeout(copyTimer));
  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown);
      clearTimeout(copyTimer); copyLabel = 'Copied!';
      copyTimer = setTimeout(() => (copyLabel = 'Copy'), 1800);
    } catch { copyLabel = 'Failed'; copyTimer = setTimeout(() => (copyLabel = 'Copy'), 1800); }
  }

  function onPreviewClick(e: MouseEvent) {
    const a = (e.target as HTMLElement)?.closest('a');
    if (a) e.preventDefault();
  }
</script>

<div class="viewer">
  <div class="vhead">
    <button class="back" onclick={onBack} title="Back to the batch summary">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M9 2L4 7l5 5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/></svg>
      Back
    </button>
    <span class="vname" title={name}>{name}</span>
    <div class="seg" role="group" aria-label="View mode">
      <button class="seg-btn" class:active={view === 'preview'} title="Rendered Markdown" onclick={() => (view = 'preview')}>Preview</button>
      <button class="seg-btn" class:active={view === 'source'} title="Raw Markdown text" onclick={() => (view = 'source')}>Source</button>
    </div>
    <button class="copy" onclick={copy} title="Copy the Markdown">{copyLabel}</button>
  </div>

  <div class="vbody" tabindex="0" role="region" aria-label="Document">
    {#if view === 'preview'}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <div class="preview" onclick={onPreviewClick}>{@html previewHtml}</div>
    {:else}
      <pre class="source">{markdown}</pre>
    {/if}
  </div>
</div>

<style>
  .viewer { flex: 1; display: flex; flex-direction: column; min-height: 0; background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
  .vhead { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-2) var(--sp-4); border-bottom: 1px solid var(--border); background: var(--surface-2); flex-shrink: 0; }
  .back { display: flex; align-items: center; gap: var(--sp-1); background: var(--surface-1); border: 1px solid var(--border-strong); color: var(--text-primary); font-size: 12.5px; font-weight: 600; font-family: var(--font-ui); cursor: pointer; padding: 6px 12px; border-radius: var(--radius-sm); transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast); }
  .back:hover { background: var(--surface-3); border-color: #565660; }
  .vname { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* Segmented control — base .seg/.seg-btn in tokens.css; local: no-shrink only. */
  .seg { flex-shrink: 0; }

  .copy { padding: 6px 13px; font-size: 12.5px; font-weight: 600; font-family: var(--font-ui); background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); cursor: pointer; flex-shrink: 0; transition: background var(--transition-fast), border-color var(--transition-fast); }
  .copy:hover { background: var(--surface-3); border-color: #565660; }

  .vbody { flex: 1; overflow-y: auto; padding: var(--sp-5) var(--sp-6); min-height: 0; outline: none; }
  .vbody:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: -2px; }
  .source { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.65; color: var(--text-primary); white-space: pre-wrap; word-break: break-word; user-select: text; margin: 0; }

  .preview { color: var(--text-primary); font-size: 14px; line-height: 1.65; user-select: text; max-width: 760px; }
  .preview :global(h1) { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 var(--sp-3); padding-bottom: var(--sp-2); border-bottom: 1px solid var(--border); }
  .preview :global(h2) { font-size: 20px; font-weight: 700; margin: var(--sp-6) 0 var(--sp-2); }
  .preview :global(h3) { font-size: 16px; font-weight: 600; margin: var(--sp-5) 0 var(--sp-2); }
  .preview :global(h4), .preview :global(h5), .preview :global(h6) { font-size: 14px; font-weight: 600; margin: var(--sp-4) 0 var(--sp-1); }
  .preview :global(p) { margin: 0 0 var(--sp-3); }
  .preview :global(ul), .preview :global(ol) { margin: 0 0 var(--sp-3); padding-left: var(--sp-6); }
  .preview :global(li) { margin: 2px 0; }
  .preview :global(a) { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .preview :global(strong) { font-weight: 700; }
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
</style>
