<script module lang="ts">
  import { defaultRules } from './cleanup';
  import type { CleanupMethod } from './cleanup';
  import type { OutputRule } from './naming';

  export interface FileInfo {
    path: string;
    name: string;
    ext: string;   // uppercase, e.g. "PDF"
    size: number;  // bytes
  }

  export interface ConvertCleanup {
    method: CleanupMethod;            // 'none' | 'rules' | 'ai'
    rules: Record<string, boolean>;
  }

  // Lifted to the parent so it survives view changes (e.g. opening Diagnostics).
  export interface StagingState {
    outputFolder: string | null;
    outputRule: OutputRule;           // Stage 7 — per-run output location rule
    method: CleanupMethod;
    rules: Record<string, boolean>;
  }

  // Seeded from config (output defaults) when available; falls back to old behavior.
  export function freshStaging(seed?: { rule?: string; folder?: string | null }): StagingState {
    return {
      outputFolder: seed?.folder ?? null,
      outputRule: (seed?.rule as OutputRule) ?? 'next_to_source',
      method: 'none',
      rules: defaultRules('pdf'),
    };
  }

  function fmtSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import { listen } from '@tauri-apps/api/event';
  import { open } from '@tauri-apps/plugin-dialog';
  import { CLEANUP_RULES } from './cleanup';
  import { SUPPORTED_EXTS, isHeavyExt } from './formats';
  import { buildOutputFilename, type NamingCase } from './naming';

  let {
    files,
    setup,
    llmMode = 'off',
    cleanupSeen = true,
    namingTemplate = '{stem}',
    namingCase = 'keep',
    onSeenCleanup,
    onAddFiles,
    onRemove,
    onClear,
    onConvert,
    onOpenDiagnostics,
  }: {
    files: FileInfo[];
    setup: StagingState;
    llmMode?: string;
    cleanupSeen?: boolean;
    namingTemplate?: string;
    namingCase?: string;
    onSeenCleanup?: () => void;
    onAddFiles: (rawPaths: string[]) => void;
    onRemove: (path: string) => void;
    onClear: () => void;
    onConvert: (outputFolder: string | null, outputRule: string, cleanup: ConvertCleanup) => void;
    onOpenDiagnostics?: () => void;
  } = $props();

  const isBatch = $derived(files.length > 1);
  // Live preview of the output filename using the configured naming convention,
  // sampled on the first staged file.
  const namePreview = $derived(
    files.length ? buildOutputFilename(files[0].name, namingTemplate, namingCase as NamingCase) : '',
  );
  const llmAvailable = $derived(llmMode === 'local' || llmMode === 'api');
  // Files that need a heavy optional engine (OCR / transcription) — slower, and the
  // model loads on first use. Used to warn before a long run.
  const heavyCount = $derived(files.filter(f => isHeavyExt(f.ext)).length);

  let dragHover = $state(false);

  onMount(() => {
    let unDrop: (() => void) | undefined;
    let unEnter: (() => void) | undefined;
    let unLeave: (() => void) | undefined;
    let dead = false;
    listen<{ paths: string[] }>('tauri://drag-drop', (e) => {
      dragHover = false;
      const paths = e.payload.paths ?? [];
      if (paths.length) onAddFiles(paths);
    }).then(fn => { if (dead) fn(); else unDrop = fn; });
    listen('tauri://drag-enter', () => (dragHover = true)).then(fn => { if (dead) fn(); else unEnter = fn; });
    listen('tauri://drag-leave', () => (dragHover = false)).then(fn => { if (dead) fn(); else unLeave = fn; });
    return () => { dead = true; unDrop?.(); unEnter?.(); unLeave?.(); };
  });

  async function browseFiles() {
    const sel = await open({
      multiple: true,
      filters: [
        { name: 'Supported files', extensions: SUPPORTED_EXTS },
        { name: 'All files', extensions: ['*'] },
      ],
    });
    if (!sel) return;
    onAddFiles(Array.isArray(sel) ? (sel as string[]) : [sel as string]);
  }
  async function browseFolder() {
    const sel = await open({ directory: true, multiple: false });
    if (!sel) return;
    onAddFiles([typeof sel === 'string' ? sel : (sel as string[])[0]]);
  }

  async function chooseFolder() {
    const sel = await open({ directory: true, multiple: false });
    if (!sel) return;
    setup.outputFolder = typeof sel === 'string' ? sel : (sel as string[])[0];
  }

  function setRule(r: OutputRule) {
    setup.outputRule = r;
  }

  function selectMethod(m: CleanupMethod) {
    setup.method = m;
    if (m !== 'none' && !cleanupSeen) onSeenCleanup?.();
  }

  function convert() {
    onConvert(setup.outputFolder, setup.outputRule, { method: setup.method, rules: setup.rules });
  }
</script>

<div class="staging">
  <div class="head">
    <span class="count">{files.length}</span>
    <span class="count-label">file{files.length === 1 ? '' : 's'} ready</span>
    <button class="link-btn clear-all" onclick={onClear} title="Remove all staged files">Clear all</button>
  </div>

  <!-- File list (drop more anywhere on this view) -->
  <div class="file-list" class:drag={dragHover}>
    {#each files as f (f.path)}
      <div class="file-chip">
        <span class="ftype" data-ext={f.ext.toLowerCase()}>{f.ext || 'FILE'}</span>
        <span class="fname" title={f.path}>{f.name}</span>
        <span class="fsize">{fmtSize(f.size)}</span>
        <button class="remove" title="Remove {f.name}" aria-label="Remove {f.name}" onclick={() => onRemove(f.path)}>
          <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden="true"><path d="M2 2l7 7M9 2l-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>
    {/each}
  </div>

  <!-- Add more -->
  <div class="add-row">
    <span class="add-hint">Add more — drop files anywhere, or</span>
    <button class="add-btn" onclick={browseFiles}>Choose files…</button>
    <button class="add-btn" onclick={browseFolder}>Choose folder…</button>
  </div>

  {#if isBatch}
    <!-- Output destination (batch only; a single file is saved from the result view) -->
    <div class="section">
      <span class="section-label">Save output to</span>
      <div class="seg" role="group" aria-label="Output location">
        <button class="seg-btn" class:active={setup.outputRule === 'next_to_source'} aria-pressed={setup.outputRule === 'next_to_source'}
          title="Each .md is saved beside its source file" onclick={() => setRule('next_to_source')}>Next to source</button>
        <button class="seg-btn" class:active={setup.outputRule === 'fixed_folder'} aria-pressed={setup.outputRule === 'fixed_folder'}
          title="All .md files go into one chosen folder" onclick={() => setRule('fixed_folder')}>One folder</button>
        <button class="seg-btn" class:active={setup.outputRule === 'mirror_tree'} aria-pressed={setup.outputRule === 'mirror_tree'}
          title="Recreate the source folder structure under a chosen root" onclick={() => setRule('mirror_tree')}>Mirror folders</button>
      </div>

      {#if setup.outputRule !== 'next_to_source'}
        <div class="folder-row">
          <svg class="folder-icon" width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M1.5 4.5A1 1 0 0 1 2.5 3.5h3.086a1 1 0 0 1 .707.293l.914.914H13.5a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4.5z" stroke="currentColor" stroke-width="1.25" fill="none"/>
          </svg>
          <span class="folder-value" class:folder-default={!setup.outputFolder} title={setup.outputFolder ?? 'Choose a folder'}>
            {setup.outputFolder ?? 'No folder chosen'}
          </span>
          {#if setup.outputFolder}
            <button class="mini-x" title="Clear" aria-label="Clear folder" onclick={() => (setup.outputFolder = null)}>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          {/if}
          <button class="change-btn" title="Pick the folder to save into" onclick={chooseFolder}>{setup.outputFolder ? 'Change…' : 'Choose folder…'}</button>
        </div>
        {#if setup.outputRule === 'mirror_tree'}
          <span class="output-hint">Sub-folders of the dropped folder are recreated under this root.</span>
        {/if}
      {/if}

      {#if namePreview}
        <div class="name-line">
          <span class="name-line-label">Named</span>
          <span class="name-line-val">{namePreview}</span>
          {#if onOpenDiagnostics}<button class="link-btn" title="Change the naming convention in Diagnostics" onclick={onOpenDiagnostics}>Change…</button>{/if}
        </div>
      {/if}
    </div>

    <!-- Cleanup method (batch applies one choice to every file) -->
    <div class="section">
      <div class="cleanup-head">
        <span class="section-label">Clean up</span>
        <div class="seg seg-lg" role="group" aria-label="Cleanup method">
          <button class="seg-btn" class:active={setup.method === 'none'} aria-pressed={setup.method === 'none'} title="Convert files as-is, no cleanup" onclick={() => selectMethod('none')}>Off</button>
          <button class="seg-btn" class:active={setup.method === 'rules'} aria-pressed={setup.method === 'rules'} title="Clean every file with fast, offline rules" onclick={() => selectMethod('rules')}>Rule-based</button>
          <button class="seg-btn" class:active={setup.method === 'ai'} aria-pressed={setup.method === 'ai'} disabled={!llmAvailable}
            title={llmAvailable ? 'Clean every file with your configured AI model' : 'Switch to Local or API mode to enable AI cleanup'} onclick={() => selectMethod('ai')}>AI</button>
        </div>
        {#if !cleanupSeen && setup.method === 'none'}<span class="new-badge" aria-hidden="true">New</span>{/if}
      </div>
      {#if setup.method === 'rules'}
        <div class="rules-list">
          {#each CLEANUP_RULES as rule}
            <label class="rule-row" title="{rule.hint}. {setup.rules[rule.key] ? 'On' : 'Off'} — click to toggle.">
              <input type="checkbox" bind:checked={setup.rules[rule.key]} />
              <span class="rule-text"><span class="rule-label">{rule.label}</span><span class="rule-hint">{rule.hint}</span></span>
            </label>
          {/each}
        </div>
      {:else if setup.method === 'ai' && llmMode === 'api'}
        <p class="cost-warning">⚠ AI cleanup sends the text of all {files.length} files to your configured API provider — cost and privacy implications, once per file.</p>
      {/if}
    </div>
  {/if}

  {#if heavyCount > 0}
    <div class="heavy-notice">
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="6.3" stroke="currentColor" stroke-width="1.3"/>
        <path d="M8 4.5V8l2.3 1.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span>
        {heavyCount} {heavyCount === 1 ? 'file needs' : 'files need'} OCR or transcription — expect a longer run{isBatch ? ' across the batch' : ''}, and the engine's model loads on first use.
      </span>
    </div>
  {/if}

  <button class="convert-btn" onclick={convert}>
    <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M10 2.5l1.6 4.1 4.4.3-3.4 2.8 1.1 4.3L10 11.8 6.3 14l1.1-4.3L4 6.9l4.4-.3L10 2.5z" fill="currentColor"/>
    </svg>
    Convert to AI-Ready Markdown
  </button>
</div>

<style>
  .staging {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    max-width: 620px;
    margin: 0 auto;
    width: 100%;
    padding: var(--sp-4) 0;
    overflow-y: auto;
    min-height: 0;
  }

  .head { display: flex; align-items: baseline; gap: var(--sp-2); }
  .count { font-size: 24px; font-weight: 700; font-family: var(--font-mono); color: var(--text-primary); line-height: 1; }
  .count-label { font-size: 14px; color: var(--text-secondary); }
  .clear-all { margin-left: auto; }

  .file-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-2);
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    transition: border-color var(--transition-fast), background var(--transition-fast);
  }
  .file-list.drag { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 6%, transparent); }

  .file-chip {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }
  .ftype {
    flex-shrink: 0;
    font-size: 10px;
    font-weight: 700;
    font-family: var(--font-mono);
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    padding: 2px 7px;
    border-radius: 4px;
    min-width: 38px;
    text-align: center;
  }
  .fname { flex: 1; min-width: 0; font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fsize { flex-shrink: 0; font-size: 11px; font-family: var(--font-mono); color: var(--text-muted); }
  .remove {
    flex-shrink: 0; display: flex; align-items: center; justify-content: center;
    width: 20px; height: 20px; border-radius: 50%; border: none;
    background: var(--surface-2); color: var(--text-muted); cursor: pointer;
    transition: color var(--transition-fast), background var(--transition-fast);
  }
  .remove:hover { color: var(--red); background: color-mix(in srgb, var(--red) 14%, transparent); }

  .add-row { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
  .add-hint { font-size: 12px; color: var(--text-muted); }
  .add-btn {
    font-size: 12.5px; font-weight: 600; font-family: var(--font-ui);
    color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent);
    padding: 6px 13px; border-radius: var(--radius-sm); cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
  }
  .add-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
  .add-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }

  .section { display: flex; flex-direction: column; gap: var(--sp-2); }
  .section-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }

  .folder-row { display: flex; align-items: center; gap: var(--sp-2); padding: var(--sp-2) var(--sp-3); background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius); }
  .folder-icon { flex-shrink: 0; color: var(--accent); }
  .folder-value { flex: 1; font-size: 12px; color: var(--text-primary); font-family: var(--font-mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .folder-default { color: var(--text-muted); font-family: var(--font-ui); font-style: italic; }
  .mini-x { flex-shrink: 0; display: flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; border: none; background: var(--surface-2); color: var(--text-muted); cursor: pointer; }
  .mini-x:hover { color: var(--text-primary); background: var(--border); }
  .change-btn { flex-shrink: 0; padding: 6px 13px; font-size: 12px; font-weight: 600; font-family: var(--font-ui); color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent); border-radius: var(--radius-sm); cursor: pointer; transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast); }
  .change-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }

  .output-hint { font-size: 11px; color: var(--text-muted); line-height: 1.5; }
  .name-line { display: flex; align-items: center; gap: var(--sp-2); font-size: 12px; }
  .name-line-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }
  .name-line-val { font-family: var(--font-mono); color: var(--accent); font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .cleanup-head { display: flex; align-items: center; gap: var(--sp-3); }
  /* Segmented control — base .seg/.seg-btn in tokens.css; local: large variant only. */
  .seg-lg .seg-btn { padding: 7px 22px; font-size: 13px; }

  .new-badge { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #fff; background: var(--accent); padding: 1px 6px; border-radius: 999px; }

  .rules-list { display: flex; flex-direction: column; gap: 2px; padding: var(--sp-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .rule-row { display: flex; align-items: flex-start; gap: var(--sp-2); cursor: pointer; padding: 3px; }
  .rule-row input { margin-top: 2px; accent-color: var(--accent); cursor: pointer; }
  .rule-text { display: flex; flex-direction: column; gap: 1px; }
  .rule-label { font-size: 12px; color: var(--text-primary); }
  .rule-hint { font-size: 10px; color: var(--text-muted); }

  .cost-warning { font-size: 11px; color: var(--amber); line-height: 1.5; background: color-mix(in srgb, var(--amber) 10%, transparent); border: 1px solid color-mix(in srgb, var(--amber) 30%, transparent); border-radius: var(--radius-sm); padding: var(--sp-2); margin: 0; }

  .heavy-notice {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-secondary);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
    border-radius: var(--radius-sm);
    padding: var(--sp-2) var(--sp-3);
  }
  .heavy-notice svg { flex-shrink: 0; color: var(--accent); }

  .convert-btn {
    margin-top: var(--sp-4);
    width: 100%;
    min-height: 56px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--sp-2);
    padding: 18px 28px;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.01em;
    font-family: var(--font-ui);
    color: #fff;
    background: var(--accent);
    border: 1px solid var(--accent-edge);
    border-radius: 12px;
    cursor: pointer;
    box-shadow: 0 4px 20px color-mix(in srgb, var(--accent) 40%, transparent);
    transition: background var(--transition-fast), transform var(--transition-fast), box-shadow var(--transition-fast);
  }
  .convert-btn:hover { background: var(--accent-hover); box-shadow: 0 6px 26px color-mix(in srgb, var(--accent) 48%, transparent); }
  .convert-btn:active { transform: translateY(1px); }
  .convert-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: 2px; }

  .link-btn { background: none; border: none; padding: 0; font-size: 11px; font-family: var(--font-ui); color: var(--accent); text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
  .link-btn:hover { opacity: 0.8; }
</style>
