<script lang="ts">
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import DropZone from '$lib/DropZone.svelte';
  import ConvertProgress from '$lib/ConvertProgress.svelte';
  import ResultView from '$lib/ResultView.svelte';
  import ModeSwitch from '$lib/ModeSwitch.svelte';
  import DiagnosticsView from '$lib/DiagnosticsView.svelte';
  import BatchQueueView from '$lib/BatchQueueView.svelte';
  import BatchSummaryView from '$lib/BatchSummaryView.svelte';
  import DocViewer from '$lib/DocViewer.svelte';
  import StagingView, { freshStaging } from '$lib/StagingView.svelte';
  import ProvisionView, { type ProvisionProgress } from '$lib/ProvisionView.svelte';
  import type { ConvertCleanup, StagingState, FileInfo } from '$lib/StagingView.svelte';
  import type { BatchItemState } from '$lib/BatchQueueView.svelte';
  import { freshCleanup } from '$lib/cleanup';
  import type { CleanupUIState } from '$lib/cleanup';
  import type { ConvertError } from '$lib/ErrorCard.svelte';
  import type { AppConfig } from '$lib/DiagnosticsView.svelte';
  import { fileStem } from '$lib/naming';

  // ── Types ──────────────────────────────────────────────────────────────────

  type Phase = 'checking' | 'provisioning' | 'health-checking' | 'ready' | 'error';
  type View  = 'main' | 'diagnostics';
  type BatchPhase = 'idle' | 'running' | 'cancelling' | 'done' | 'cancelled';

  interface DownloadDetail { label: string; received: number; total?: number | null; speed: number; }
  interface ProgressPayload { step: string; message: string; pct: number; detail?: DownloadDetail | null; }
  interface ProvisionStatus { state: string; }
  interface HealthReport {
    python_version: string;
    markitdown_version: string | null;
    extras: Record<string, boolean>;
  }
  interface ConvertResult {
    markdown: string;
    detectedFormat: string;
    converterPath: string;
    warnings: string[];
  }

  // ── State ──────────────────────────────────────────────────────────────────

  let phase       = $state<Phase>('checking');
  let view        = $state<View>('main');
  let progress    = $state<ProvisionProgress>({ step: '', message: 'Starting…', pct: 0, detail: null });
  let health      = $state<HealthReport | null>(null);
  let errorMsg    = $state('');
  let errorBtn    = $state('Retry');
  let result      = $state<ConvertResult | null>(null);
  let config      = $state<AppConfig | null>(null);
  let resultSourcePath = $state<string>('');

  // Top-level error banner — surfaces errors in the current view (e.g. open-folder
  // failures from the batch summary, where dropError isn't rendered).
  let errorBanner = $state<string | null>(null);
  let errorBannerTimer: ReturnType<typeof setTimeout>;
  function showBanner(msg: string) {
    clearTimeout(errorBannerTimer);
    errorBanner = msg;
    errorBannerTimer = setTimeout(() => (errorBanner = null), 6000);
  }

  // Single-file cleanup state — lifted here so it survives view changes
  // (opening Diagnostics and returning must not reset the user's cleanup).
  let cleanupState = $state<CleanupUIState>(freshCleanup(''));
  // Source file's base name (no extension) — used as the default save name.
  let resultStem  = $state('output');

  let diagHighlight  = $state<string | null>(null);
  let converting     = $state(false);
  let convStage      = $state('preflight');
  let dropError      = $state<ConvertError | null>(null);
  let cancelledFlash = $state(false);
  let cancelFlashTimer: ReturnType<typeof setTimeout>;

  // Staging + batch state
  let staged           = $state<FileInfo[]>([]);          // files loaded, not yet converted
  let stagingState     = $state<StagingState>(freshStaging());
  let batchItems       = $state<BatchItemState[] | null>(null);
  // Items carried over from a previous run on retry (the done/cancelled ones we keep).
  // Held in state so the batch:done listener can re-merge them instead of dropping them.
  let batchKept        = $state<BatchItemState[]>([]);
  let batchPhase       = $state<BatchPhase>('idle');
  let batchOutputFolder = $state<string | null>(null);
  let batchOutputRule  = $state<string>('next_to_source');
  let batchCleanup     = $state<ConvertCleanup | null>(null);
  let batchCleanupApplied = $state(false);
  let batchCleanupChanges = $state(0);
  let viewing          = $state<{ name: string; markdown: string } | null>(null);

  const EXTRA_LABELS: Record<string, string> = {
    pdf:     'PDF',
    docx:    'Word documents',
    pptx:    'PowerPoint',
    xlsx:    'Excel (.xlsx)',
    xls:     'Excel (.xls)',
    epub:    'EPUB',
  };

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  onMount(() => {
    const unlisteners: Array<() => void> = [];
    let dead = false;

    listen<ProgressPayload>('provision:progress', ({ payload }) => {
      progress = {
        step: payload.step,
        message: payload.message,
        pct: payload.pct,
        detail: payload.detail ?? null,
      };
    }).then(fn => { if (dead) fn(); else unlisteners.push(fn); });

    // Single-file conversion progress
    listen<{ type: string; stage: string; frac: number | null }>(
      'convert:progress',
      ({ payload }) => {
        if (payload.type === 'progress') convStage = payload.stage;
      },
    ).then(fn => { if (dead) fn(); else unlisteners.push(fn); });

    // Batch: per-file status changes
    listen<{
      id: string;
      status: string;
      frac: number | null;
      error: ConvertError | null;
      output_path: string | null;
      warnings?: string[];
    }>('batch:file-status', ({ payload }) => {
      batchItems = batchItems?.map(item =>
        item.id !== payload.id ? item : {
          ...item,
          status: payload.status,
          frac: payload.frac ?? (payload.status === 'done' ? 1 : item.frac),
          error: payload.error ?? item.error,
          output_path: payload.output_path ?? item.output_path,
          warnings: payload.warnings ?? item.warnings,
        }
      ) ?? null;
    }).then(fn => { if (dead) fn(); else unlisteners.push(fn); });

    // Batch: all workers finished
    listen<{
      done: number;
      failed: number;
      cancelled: number;
      items: Array<Omit<BatchItemState, 'frac'>>;
      cleanup_applied: boolean;
      cleanup_changes: number;
    }>('batch:done', ({ payload }) => {
      const incoming = payload.items.map(i => ({
        ...i,
        frac: i.status === 'done' ? 1 : null,
      }));
      const incomingIds = new Set(incoming.map(i => i.id));
      // Keep prior-run items (e.g. already-converted files on a retry) that this
      // run didn't touch, so they don't vanish from the summary.
      batchItems = [...batchKept.filter(k => !incomingIds.has(k.id)), ...incoming];
      batchCleanupApplied = payload.cleanup_applied;
      batchCleanupChanges = payload.cleanup_changes;
      const allCancelled = payload.done + payload.failed === 0 && payload.cancelled > 0;
      batchPhase = allCancelled ? 'cancelled' : 'done';
      // Stage 7: optionally reveal the output folder once files have landed.
      if (config?.open_after_convert && payload.done > 0) openOutputFolder();
    }).then(fn => { if (dead) fn(); else unlisteners.push(fn); });

    boot(false);

    return () => { dead = true; unlisteners.forEach(fn => fn()); };
  });

  // ── Boot / provision ───────────────────────────────────────────────────────

  async function boot(force: boolean) {
    try {
      phase = 'checking';
      const status = await invoke<ProvisionStatus>('get_provision_status');
      if (status.state === 'ready' && !force) {
        await doHealthCheck();
      } else {
        await doProvision(force);
      }
    } catch (e) {
      showError(String(e), 'Retry');
    }
  }

  async function doProvision(force: boolean) {
    phase = 'provisioning';
    progress = { step: '', message: 'Preparing…', pct: 0, detail: null };
    try {
      await invoke('start_provision', { force });
      await doHealthCheck();
    } catch (e) {
      showError(String(e), 'Retry');
    }
  }

  async function doHealthCheck() {
    phase = 'health-checking';
    try {
      health = await invoke<HealthReport>('run_health_check');
      config = await invoke<AppConfig>('get_config');
      // Seed staging defaults from saved output settings — but only if the user
      // hasn't already staged files and chosen per-run overrides. A Repair from
      // the health footer must not silently revert "Mirror folders" + "Rule-based".
      if (staged.length === 0) {
        stagingState = freshStaging({ rule: config.output_rule, folder: config.output_folder || null });
      }
      batchOutputRule = config.output_rule;
      phase = 'ready';
    } catch (e) {
      showError(String(e), 'Restart');
    }
  }

  function showError(msg: string, btn: string) {
    errorMsg = msg;
    errorBtn = btn;
    phase = 'error';
  }

  function allGreen(): boolean {
    if (!health || !health.markitdown_version) return false;
    return Object.values(health.extras).every(Boolean);
  }

  // ── Config management ──────────────────────────────────────────────────────

  async function updateConfig(newConfig: AppConfig) {
    const prev = config;
    config = newConfig;
    try {
      await invoke('set_config', { config: newConfig });
    } catch (e) {
      // Roll back so the UI matches the disk — without this the user's settings
      // silently revert on next launch while appearing to be saved now.
      config = prev;
      showBanner(`Could not save setting: ${e}`);
    }
  }

  // First-run cleanup discovery — persist once the user has seen the highlight.
  async function markCleanupSeen() {
    if (!config || config.cleanup_seen) return;
    await updateConfig({ ...config, cleanup_seen: true });
  }

  // ── Diagnostics navigation ─────────────────────────────────────────────────

  function openDiagnostics(key?: string) {
    diagHighlight = key ?? null;
    view = 'diagnostics';
  }

  function closeDiagnostics() {
    view = 'main';
    diagHighlight = null;
  }

  // ── Single-file conversion ─────────────────────────────────────────────────

  async function startConversion(path: string) {
    result = null;
    dropError = null;
    converting = true;
    convStage = 'preflight';
    resultSourcePath = path;

    try {
      const resp = await invoke<{
        ok: boolean;
        result?: { markdown: string; meta: { detected_format: string; converter_path: string; warnings: string[]; assets_folder?: string } };
        error?: ConvertError;
      }>('convert_file', { path });

      converting = false;
      convStage = 'preflight';

      if (resp.ok && resp.result) {
        result = {
          markdown: resp.result.markdown,
          detectedFormat: resp.result.meta.detected_format,
          converterPath: resp.result.meta.converter_path,
          warnings: resp.result.meta.warnings,
        };
        // Fresh cleanup state for the new file (PDF rules default-on for PDFs).
        cleanupState = freshCleanup(resp.result.meta.detected_format);
        resultStem = fileStem(path);
      } else if (resp.error?.code === 'CANCELLED') {
        clearTimeout(cancelFlashTimer);
        cancelledFlash = true;
        cancelFlashTimer = setTimeout(() => (cancelledFlash = false), 2000);
      } else {
        dropError = resp.error ?? {
          code: 'UNKNOWN',
          title: 'Unknown error',
          detail: 'No details available.',
          suggested_action: 'Try again.',
        };
      }
    } catch (e) {
      converting = false;
      convStage = 'preflight';
      dropError = {
        code: 'INTERNAL_ERROR',
        title: 'Unexpected error',
        detail: String(e),
        suggested_action: 'Restart the app.',
      };
    }
  }

  async function cancelConversion() {
    try {
      await invoke('cancel_conversion');
    } catch {
      // ignore — if sidecar is gone, convert_file will error and clean up
    }
  }

  function onClearResult() {
    result = null;
    dropError = null;
  }

  async function onOpenFile() {
    const path = await invoke<string | null>('pick_file');
    if (path) {
      result = null;
      dropError = null;
      await startConversion(path);
    }
  }

  // ── Staging (load files, convert on button) ─────────────────────────────────

  // Add raw dropped/picked paths to the staging list: expand folders, get
  // metadata, and dedupe by path. Files are NOT converted until the user clicks.
  async function addFiles(rawPaths: string[]) {
    if (rawPaths.length === 0) return;
    dropError = null;
    try {
      const expanded = await invoke<string[]>('list_files', { paths: rawPaths });
      // Nothing supported in the selection (e.g. the user picked an unsupported type
      // via the "All files" filter) — say so instead of silently doing nothing.
      if (expanded.length === 0) {
        dropError = {
          code: 'UNSUPPORTED_FORMAT',
          title: 'Unsupported file type',
          detail: 'None of the selected files are a supported format.',
          suggested_action: 'Choose PDF, DOCX, PPTX, XLSX, EPUB, HTML, CSV, JSON, XML, an image, or audio.',
        };
        return;
      }
      const have = new Set(staged.map(f => f.path));
      const fresh = expanded.filter(p => !have.has(p));
      if (fresh.length === 0) return; // all already staged — nothing to add
      const infos = await invoke<FileInfo[]>('stat_files', { paths: fresh });
      staged = [...staged, ...infos];
    } catch (e) {
      dropError = {
        code: 'INTERNAL_ERROR',
        title: 'Could not add files',
        detail: String(e),
        suggested_action: 'Try again.',
      };
    }
  }

  function removeStaged(path: string) {
    staged = staged.filter(f => f.path !== path);
  }

  function clearStaged() {
    staged = [];
    stagingState = freshStaging({ rule: config?.output_rule, folder: config?.output_folder || null });
  }

  // The single Convert button: one file → rich single-file view; many → batch.
  async function convertStaged(outputFolder: string | null, outputRule: string, cleanup: ConvertCleanup) {
    if (staged.length === 0) return;
    const paths = staged.map(f => f.path);
    if (paths.length === 1) {
      const only = paths[0];
      staged = [];
      await startConversion(only);
    } else {
      // Set batchItems synchronously from staged before clearing, so the UI
      // transitions directly from StagingView to BatchQueueView without a
      // one-frame DropZone flash (staged=[] + batchItems=null → empty state).
      const files = paths;
      batchItems = staged.map(f => ({
        id: '',
        path: f.path,
        filename: f.name,
        status: 'pending',
        frac: null,
        error: null,
        output_path: null,
      }));
      staged = [];
      await startBatch(files, outputFolder, outputRule, cleanup);
    }
  }

  // ── Batch conversion ───────────────────────────────────────────────────────

  // Seed batchItems from a freshly-started run WITHOUT clobbering any status the
  // run's events already applied. The backend starts emitting batch:file-status /
  // batch:done as soon as the run is spawned — for a fast-failing file these can
  // arrive before `invoke(...)` even resolves. So we merge by id: if an item is
  // already present (event-updated), keep it; otherwise take the fresh (pending) one.
  function seedBatchItems(newItems: BatchItemState[], kept: BatchItemState[]) {
    const current = new Map((batchItems ?? []).map(i => [i.id, i]));
    const seeded = newItems.map(ni => current.get(ni.id) ?? ni);
    const seededIds = new Set(seeded.map(i => i.id));
    batchItems = [...kept.filter(k => !seededIds.has(k.id)), ...seeded];
  }

  async function startBatch(files: string[], outputFolder: string | null, outputRule: string, cleanup: ConvertCleanup) {
    if (files.length === 0) return;
    batchOutputFolder = outputFolder;
    batchOutputRule = outputRule;
    batchCleanup = cleanup;
    batchCleanupApplied = false;
    batchCleanupChanges = 0;
    batchKept = []; // fresh batch — nothing carried over
    batchPhase = 'running';
    try {
      const res = await invoke<{ items: Array<Omit<BatchItemState, 'frac'>> }>(
        'start_batch',
        { files, outputFolder, outputRule, cleanup, extractImages: config?.extract_images ?? true },
      );
      seedBatchItems(res.items.map(i => ({ ...i, frac: null })), []);
    } catch (e) {
      batchPhase = 'idle';
      dropError = {
        code: 'INTERNAL_ERROR',
        title: 'Could not start batch',
        detail: String(e),
        suggested_action: 'Restart the app.',
      };
    }
  }

  async function cancelBatch() {
    batchPhase = 'cancelling';
    try {
      await invoke('cancel_batch');
    } catch {
      // If cancel_batch rejects and no batch:done event arrives, the UI would be
      // stuck at 'cancelling' forever. Force-done after 10s as a self-healing fallback.
      setTimeout(() => {
        if (batchPhase === 'cancelling') {
          batchPhase = 'done';
          showBanner('Cancel did not complete — showing the batch summary.');
        }
      }, 10_000);
    }
  }

  async function retryFailed() {
    const failedPaths = batchItems
      ?.filter(i => i.status === 'failed')
      .map(i => i.path) ?? [];
    if (failedPaths.length === 0) return;

    // Keep done/cancelled items; replace failed items with fresh pending ones.
    const kept = (batchItems ?? []).filter(i => i.status !== 'failed');
    batchKept = kept; // so batch:done re-merges them instead of dropping them

    batchPhase = 'running';
    try {
      const res = await invoke<{ items: Array<Omit<BatchItemState, 'frac'>> }>(
        'retry_failed',
        { files: failedPaths, outputFolder: batchOutputFolder, outputRule: batchOutputRule, cleanup: batchCleanup, extractImages: config?.extract_images ?? true },
      );
      seedBatchItems(res.items.map(i => ({ ...i, frac: null })), kept);
    } catch (e) {
      batchPhase = 'done';
      showBanner(`Could not start the retry: ${e}. The original failures are still listed.`);
    }
  }

  function closeBatch() {
    batchItems = null;
    batchKept = [];
    batchPhase = 'idle';
    batchOutputFolder = null;
    batchCleanup = null;
    batchCleanupApplied = false;
    batchCleanupChanges = 0;
    viewing = null;
  }

  // Reveal the batch output in the OS file manager (from the first written file).
  async function openOutputFolder() {
    const done = batchItems?.find(i => i.status === 'done' && i.output_path);
    if (!done?.output_path) return;
    try { await invoke('open_folder', { path: done.output_path }); }
    catch (e) { showBanner(`Could not open the folder: ${e}`); }
  }

  // Open a finished batch item's output .md in the read-only viewer.
  async function openBatchItem(item: BatchItemState) {
    if (item.status !== 'done' || !item.output_path) return;
    try {
      const md = await invoke<string>('read_text_file', { path: item.output_path });
      viewing = { name: item.filename, markdown: md };
    } catch (e) {
      showBanner(`Could not open file: ${e}. The output may have been moved or deleted.`);
    }
  }
</script>

<!-- ── Markup ─────────────────────────────────────────────────────────────── -->

<div class="shell">

  <!-- Header -->
  <header>
    <span class="wordmark">MDFlux</span>
    {#if phase === 'ready'}
      <span class="badge" class:green={allGreen()} class:amber={!allGreen()}>
        {allGreen() ? 'Ready' : 'Partial'}
      </span>
    {/if}
    <div class="header-right">
      {#if phase === 'ready' && config}
        <ModeSwitch mode={config.llm_mode} onModeChange={(m) => updateConfig({ ...config!, llm_mode: m })} />
        <button
          class="diag-btn"
          class:diag-active={view === 'diagnostics'}
          onclick={() => view === 'diagnostics' ? closeDiagnostics() : openDiagnostics()}
          aria-label="Diagnostics"
          title="Diagnostics"
          aria-pressed={view === 'diagnostics'}
        >
          <svg width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <circle cx="7.5" cy="7.5" r="1.5" fill="currentColor"/>
            <circle cx="2.5" cy="7.5" r="1.5" fill="currentColor"/>
            <circle cx="12.5" cy="7.5" r="1.5" fill="currentColor"/>
            <path d="M7.5 2v2M7.5 11v2M2.5 2v2M2.5 11v2M12.5 2v2M12.5 11v2" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"/>
          </svg>
        </button>
      {/if}
    </div>
  </header>

  <!-- Main content -->
  <main>

    {#if errorBanner}
      <div class="error-banner" role="alert" transition:fade={{ duration: 200 }}>
        {errorBanner}
        <button class="banner-close" onclick={() => (errorBanner = null)} aria-label="Dismiss">×</button>
      </div>
    {/if}

    {#if phase === 'checking' || phase === 'health-checking'}
      <div class="centered">
        <div class="spinner" aria-label="Loading"></div>
        <p class="hint">Checking environment…</p>
      </div>

    {:else if phase === 'provisioning'}
      <ProvisionView {progress} />

    {:else if phase === 'ready' && view === 'diagnostics' && config}
      <DiagnosticsView
        onBack={closeDiagnostics}
        highlight={diagHighlight}
        {config}
        onConfigChange={updateConfig}
      />

    {:else if phase === 'ready' && viewing}
      <DocViewer
        name={viewing.name}
        markdown={viewing.markdown}
        onBack={() => (viewing = null)}
      />

    {:else if phase === 'ready' && batchItems !== null && (batchPhase === 'done' || batchPhase === 'cancelled')}
      <BatchSummaryView
        items={batchItems}
        onRetry={retryFailed}
        onClose={closeBatch}
        onOpen={openBatchItem}
        onOpenFolder={openOutputFolder}
        cleanupApplied={batchCleanupApplied}
        cleanupChanges={batchCleanupChanges}
      />

    {:else if phase === 'ready' && batchItems !== null}
      <BatchQueueView
        items={batchItems}
        phase={batchPhase}
        onCancel={cancelBatch}
        onOpen={openBatchItem}
      />

    {:else if phase === 'ready' && result}
      <ResultView
        markdown={result.markdown}
        detectedFormat={result.detectedFormat}
        converterPath={result.converterPath}
        warnings={result.warnings}
        sourceStem={resultStem}
        sourcePath={resultSourcePath}
        extractImages={config?.extract_images ?? true}
        namingTemplate={config?.naming_template ?? '{stem}'}
        namingCase={config?.naming_case ?? 'keep'}
        onClear={onClearResult}
        {onOpenFile}
        llmMode={config?.llm_mode ?? 'off'}
        cleanupSeen={config?.cleanup_seen ?? true}
        onSeenCleanup={markCleanupSeen}
        cleanup={cleanupState}
      />

    {:else if phase === 'ready' && converting}
      <ConvertProgress stage={convStage} onCancel={cancelConversion} />

    {:else if phase === 'ready' && staged.length > 0}
      <StagingView
        files={staged}
        setup={stagingState}
        llmMode={config?.llm_mode ?? 'off'}
        cleanupSeen={config?.cleanup_seen ?? true}
        namingTemplate={config?.naming_template ?? '{stem}'}
        namingCase={config?.naming_case ?? 'keep'}
        onSeenCleanup={markCleanupSeen}
        onAddFiles={addFiles}
        onRemove={removeStaged}
        onClear={clearStaged}
        onConvert={convertStaged}
        onOpenDiagnostics={() => openDiagnostics()}
      />

    {:else if phase === 'ready'}
      {#if cancelledFlash}
        <p class="cancelled-notice" transition:fade={{ duration: 300 }}>Conversion cancelled</p>
      {/if}
      <DropZone
        onAdd={addFiles}
        error={dropError}
        onDismissError={() => (dropError = null)}
        onOpenDiagnostics={(key) => openDiagnostics(key)}
      />


    {:else if phase === 'error'}
      <div class="error-wrap">
        <p class="error-msg">{errorMsg}</p>
        <button class="action-btn" onclick={() => boot(errorBtn === 'Retry')}>
          {errorBtn}
        </button>
      </div>

    {/if}

  </main>

  <!-- Health footer (hidden while in diagnostics, staging, or batch views) -->
  {#if phase === 'ready' && health && view === 'main' && batchItems === null && staged.length === 0 && !result && !converting}
    <details class="health-footer">
      <summary>
        <span>Dependency health</span>
        <span class="health-dots" aria-hidden="true">
          <span class="hdot hdot-green" title="Python {health.python_version}"></span>
          <span class="hdot" class:hdot-green={!!health.markitdown_version} class:hdot-red={!health.markitdown_version} title="MarkItDown {health.markitdown_version ?? 'missing'}"></span>
          {#each Object.entries(EXTRA_LABELS) as [key, label]}
            <span class="hdot" class:hdot-green={health.extras[key]} class:hdot-red={!health.extras[key]} title="{label}: {health.extras[key] ? 'ok' : 'missing'}"></span>
          {/each}
        </span>
        {#if !allGreen()}<span class="warn-badge">Issues found</span>{/if}
      </summary>
      <div class="health-grid">
        {@render HealthRow({ label: 'Python', value: health.python_version, ok: true })}
        {@render HealthRow({ label: 'MarkItDown', value: health.markitdown_version ?? 'not installed', ok: !!health.markitdown_version })}
        {#each Object.entries(EXTRA_LABELS) as [key, label]}
          {@render HealthRow({ label, value: health.extras[key] ? 'installed' : 'missing', ok: health.extras[key] ?? false })}
        {/each}
        {#if !allGreen()}
          <button class="repair-btn" onclick={() => boot(true)}>Repair</button>
        {/if}
      </div>
    </details>
  {/if}

</div>

<!-- HealthRow snippet -->
{#snippet HealthRow({ label, value, ok }: { label: string; value: string; ok: boolean })}
  <div class="health-row">
    <span class="dot" class:dot-green={ok} class:dot-red={!ok} aria-hidden="true"></span>
    <span class="row-label">{label}</span>
    <span class="row-value" class:muted-red={!ok}>{value}</span>
  </div>
{/snippet}

<!-- ── Styles ──────────────────────────────────────────────────────────────── -->
<style>
  .shell {
    display: flex;
    flex-direction: column;
    height: 100vh;
    padding: 0 var(--sp-8) var(--sp-6);
  }

  /* Header */
  header {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-6) 0 var(--sp-4);
    border-bottom: 1px solid var(--border);
    margin-bottom: var(--sp-4);
    flex-shrink: 0;
  }
  .wordmark {
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--text-primary);
  }
  .badge {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 999px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .badge.green { background: color-mix(in srgb, var(--green) 15%, transparent); color: var(--green); }
  .badge.amber { background: color-mix(in srgb, var(--amber) 15%, transparent); color: var(--amber); }
  .header-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-4);
  }

  /* Diagnostics icon button */
  .diag-btn {
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    color: var(--text-secondary);
    cursor: pointer;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast);
  }
  .diag-btn:hover    { color: var(--text-primary); background: var(--surface-3); border-color: #565660; }
  .diag-btn.diag-active { color: #fff; background: var(--accent); border-color: var(--accent-edge); }
  .diag-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }

  /* Main area */
  main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* Error banner — surfaces failures in the current view context */
  .error-banner {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-4);
    background: color-mix(in srgb, var(--red) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--red) 30%, transparent);
    border-radius: var(--radius-sm);
    font-size: 12px;
    color: var(--text-primary);
    margin-bottom: var(--sp-2);
    user-select: text;
  }
  .banner-close {
    background: none; border: none; color: var(--text-muted);
    font-size: 16px; cursor: pointer; padding: 0 var(--sp-1);
    line-height: 1; flex-shrink: 0;
  }
  .banner-close:hover { color: var(--text-primary); }

  /* Cancelled flash */
  .cancelled-notice {
    font-size: 12px;
    color: var(--text-muted);
    text-align: center;
    padding: var(--sp-2) 0;
    flex-shrink: 0;
  }

  /* Spinner */
  .centered {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--sp-4);
  }
  .spinner {
    width: 28px;
    height: 28px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
  @keyframes spin { to { transform: rotate(360deg); } }

  .hint { font-size: 12px; color: var(--text-muted); }

  /* Boot error */
  .error-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--sp-6);
  }
  .error-msg {
    font-size: 13px;
    line-height: 1.6;
    color: var(--text-primary);
    white-space: pre-wrap;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--sp-4);
    user-select: text;
  }
  .action-btn {
    align-self: flex-start;
    padding: var(--sp-2) var(--sp-6);
    font-size: 13px;
    font-weight: 600;
    font-family: var(--font-ui);
    color: #fff;
    background: var(--accent);
    border: 1px solid var(--accent-edge);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition-fast), transform var(--transition-fast);
  }
  .action-btn:hover  { background: var(--accent-hover); }
  .action-btn:active { transform: translateY(1px); }

  /* Health footer */
  .health-footer {
    flex-shrink: 0;
    border-top: 1px solid var(--border);
    margin-top: var(--sp-4);
    padding-top: var(--sp-3);
  }
  .health-footer > summary {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-muted);
    cursor: pointer;
    list-style: none;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    user-select: none;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .health-footer > summary::-webkit-details-marker { display: none; }

  /* Per-dependency status dots in collapsed summary */
  .health-dots {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-left: var(--sp-2);
  }
  .hdot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-muted);
    flex-shrink: 0;
  }
  .hdot-green { background: var(--green); }
  .hdot-red   { background: var(--red); }

  .warn-badge {
    font-size: 10px;
    font-weight: 500;
    color: var(--amber);
    background: color-mix(in srgb, var(--amber) 12%, transparent);
    padding: 1px 6px;
    border-radius: 99px;
    text-transform: none;
    letter-spacing: 0;
  }
  .health-grid {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-top: var(--sp-3);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }
  .health-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 1px solid var(--border);
  }
  .health-row:last-child { border-bottom: none; }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .dot-green { background: var(--green); }
  .dot-red   { background: var(--red); }
  .row-label { flex: 1; font-size: 12px; color: var(--text-secondary); }
  .row-value { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
  .row-value.muted-red { color: var(--red); }
  .repair-btn {
    align-self: flex-start;
    margin: var(--sp-3);
    padding: 7px var(--sp-4);
    font-size: 12.5px;
    font-weight: 600;
    font-family: var(--font-ui);
    color: #fff;
    background: var(--accent);
    border: 1px solid var(--accent-edge);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition-fast);
  }
  .repair-btn:hover { background: var(--accent-hover); }
</style>
