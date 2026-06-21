<script lang="ts">
  import { onMount, onDestroy, untrack } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { buildOutputFilename, type NamingCase } from './naming';

  // ── Types ──────────────────────────────────────────────────────────────────

  interface FormatEntry {
    key: string;
    label: string;
    extensions: string[];
    module: string | null;
    module_version: string | null;
    converter: string | null;
    status: 'available' | 'missing' | 'broken' | 'coming_later';
    error: string | null;
    note?: string | null;
  }

  interface CapabilitiesReport {
    runtime: {
      python_version: string;
      sidecar_version: string;
      markitdown_version: string;
      venv_path: string;
    };
    formats: FormatEntry[];
    optional: {
      ocr:   { status: string; engine: string; size_hint: string; note: string };
      audio: { status: string; engine: string; size_hint: string; note: string };
    };
  }

  interface EngineState {
    status: string; // "not_installed" | "installing" | "installed" | "failed"
    error?: string | null;
  }

  interface EngineInstallProgress {
    engine: string;
    step: string;
    message: string;
    pct: number;
  }

  interface ProviderCheckResult {
    server?: string;
    reachable: boolean;
    detail: string;
    models?: string[];
    usable: boolean;
  }

  export interface AppConfig {
    llm_mode: string;
    local_base_url: string;
    api_type: string;
    api_base_url: string;
    api_key: string;
    cleanup_model: string;
    cleanup_seen: boolean;
    // Stage 6
    conversion_model: string;
    llm_conversion: boolean;
    extract_images: boolean;
    audio_model: string;
    // Stage 7 — output management
    output_rule: string;       // 'next_to_source' | 'fixed_folder' | 'mirror_tree'
    output_folder: string;     // default folder for fixed_folder / mirror_tree
    naming_template: string;   // tokens: {stem} {ext} {date}
    naming_case: string;       // 'keep' | 'lower' | 'slug'
    open_after_convert: boolean;
  }

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    onBack,
    highlight = null,
    config,
    onConfigChange,
  }: {
    onBack: () => void;
    highlight?: string | null;
    config: AppConfig;
    onConfigChange: (c: AppConfig) => Promise<void>;
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let caps = $state<CapabilitiesReport | null>(null);
  let capsLoading = $state(true);
  let capsError = $state<string | null>(null);

  let providerResult = $state<ProviderCheckResult | null>(null);
  let providerChecking = $state(false);

  // Editable copies of config fields (committed on Check/Test).
  // untrack: intentionally capturing initial prop value only.
  let localBaseUrl    = $state(untrack(() => config.local_base_url));
  let apiType         = $state(untrack(() => config.api_type));
  let apiBaseUrl      = $state(untrack(() => config.api_base_url));
  let apiKey          = $state(untrack(() => config.api_key));
  let cleanupModel    = $state(untrack(() => config.cleanup_model));
  let conversionModel = $state(untrack(() => config.conversion_model ?? ''));

  // Stage 7 — output management. Template is edited locally for a live preview,
  // committed on change; rule/case/folder/toggle read config directly (reactive).
  let namingTemplate  = $state(untrack(() => config.naming_template ?? '{stem}'));
  const namePreview = $derived(
    buildOutputFilename('Annual Report.pdf', namingTemplate, (config.naming_case ?? 'keep') as NamingCase),
  );

  // Stage 6: optional engine install state
  let ocrState   = $state<EngineState>({ status: 'not_installed' });
  let audioState = $state<EngineState>({ status: 'not_installed' });
  let installing = $state<string | null>(null);
  let installMsg = $state('');
  let installPct = $state(0);
  let unlistenInstall: (() => void) | null = null;

  // Models offered in the cleanup-model dropdown: the currently-saved one plus
  // whatever the latest provider check returned.
  const modelOptions = $derived.by(() => {
    const set = new Set<string>();
    if (cleanupModel) set.add(cleanupModel);
    for (const m of providerResult?.models ?? []) set.add(m);
    return [...set];
  });

  // Local edits are committed on Check/Test; no continuous sync needed.

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  onMount(async () => {
    let dead = false;
    loadCaps();

    // Load engine states from provision file (includes installing/failed states).
    const [ocr, audio] = await Promise.all([
      invoke<EngineState>('optional_engine_status', { engine: 'ocr' }).catch(() => ({ status: 'not_installed' })),
      invoke<EngineState>('optional_engine_status', { engine: 'audio' }).catch(() => ({ status: 'not_installed' })),
    ]);
    if (dead) return;
    ocrState   = ocr   as EngineState;
    audioState = audio as EngineState;

    listen<EngineInstallProgress>('engine:install-progress', ({ payload }) => {
      installMsg = payload.message;
      installPct = payload.pct;
      if (payload.step === 'installed') {
        if (payload.engine === 'ocr')   ocrState   = { status: 'installed' };
        else                             audioState = { status: 'installed' };
      }
    }).then(fn => { if (dead) fn(); else unlistenInstall = fn; });
  });

  onDestroy(() => { unlistenInstall?.(); });

  // ── Capabilities ───────────────────────────────────────────────────────────

  async function loadCaps() {
    capsLoading = true;
    capsError = null;
    try {
      caps = await invoke<CapabilitiesReport>('get_capabilities');
    } catch (e) {
      capsError = String(e);
    } finally {
      capsLoading = false;
      if (highlight) setTimeout(() => scrollToFormat(highlight!), 80);
    }
  }

  function scrollToFormat(key: string) {
    const el = document.getElementById(`fmt-${key}`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // ── Mode switch ────────────────────────────────────────────────────────────

  async function setMode(m: string) {
    providerResult = null;
    await onConfigChange({ ...config, llm_mode: m });
  }

  async function saveApiType(type: string) {
    apiType = type;
    providerResult = null;
    await onConfigChange({ ...config, api_type: type });
  }

  async function saveCleanupModel(m: string) {
    cleanupModel = m;
    await onConfigChange({ ...config, cleanup_model: m });
  }

  async function saveConversionModel(m: string) {
    conversionModel = m;
    await onConfigChange({ ...config, conversion_model: m });
  }

  async function toggleLlmConversion(enabled: boolean) {
    await onConfigChange({ ...config, llm_conversion: enabled });
  }

  // ── Stage 7: output management ───────────────────────────────────────────────

  async function saveOutputRule(rule: string) {
    await onConfigChange({ ...config, output_rule: rule });
  }
  async function chooseOutputFolder() {
    const sel = await invoke<string | null>('pick_folder');
    if (sel) await onConfigChange({ ...config, output_folder: sel });
  }
  async function clearOutputFolder() {
    await onConfigChange({ ...config, output_folder: '' });
  }
  async function saveNamingTemplate() {
    const t = namingTemplate.trim() || '{stem}';
    namingTemplate = t;
    await onConfigChange({ ...config, naming_template: t });
  }
  function applyTemplatePreset(t: string) {
    namingTemplate = t;
    saveNamingTemplate();
  }
  async function saveNamingCase(c: string) {
    await onConfigChange({ ...config, naming_case: c });
  }
  async function toggleOpenAfter(v: boolean) {
    await onConfigChange({ ...config, open_after_convert: v });
  }

  // ── Engine install ─────────────────────────────────────────────────────────

  async function installEngine(engine: string) {
    installing = engine;
    installMsg = 'Starting installation…';
    installPct = 0;
    if (engine === 'ocr')   ocrState   = { status: 'installing' };
    else                     audioState = { status: 'installing' };
    try {
      await invoke('install_engine', { engine });
      if (engine === 'ocr')   ocrState   = { status: 'installed' };
      else                     audioState = { status: 'installed' };
      loadCaps(); // refresh format table to show new OCR/audio rows as available
    } catch (e) {
      const err = String(e);
      if (engine === 'ocr')   ocrState   = { status: 'failed', error: err };
      else                     audioState = { status: 'failed', error: err };
    } finally {
      installing = null;
      installMsg = '';
      installPct = 0;
    }
  }

  // ── Provider check ─────────────────────────────────────────────────────────

  async function runProviderCheck() {
    providerChecking = true;
    providerResult = null;
    try {
      if (config.llm_mode === 'local') {
        await onConfigChange({ ...config, local_base_url: localBaseUrl });
        providerResult = await invoke<ProviderCheckResult>('check_provider', {
          provider: 'local',
          baseUrl: localBaseUrl,
          key: '',
        });
      } else if (config.llm_mode === 'api') {
        await onConfigChange({
          ...config,
          api_type: apiType,
          api_base_url: apiBaseUrl,
          api_key: apiKey,
        });
        providerResult = await invoke<ProviderCheckResult>('check_provider', {
          provider: apiType === 'anthropic' ? 'api_anthropic' : 'api_openai_compat',
          baseUrl: apiBaseUrl,
          key: apiKey,
        });
      }
    } catch (e) {
      providerResult = { reachable: false, detail: String(e), usable: false };
    } finally {
      providerChecking = false;
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  function dotColor(status: string) {
    if (status === 'available') return 'green';
    if (status === 'coming_later') return 'amber';
    return 'red';
  }

  function badgeLabel(status: string) {
    if (status === 'available') return 'Available';
    if (status === 'coming_later') return 'Later version';
    if (status === 'missing') return 'Missing';
    return 'Broken';
  }

  function detailText(fmt: FormatEntry): string {
    if (fmt.status === 'available') {
      if (!fmt.module) return '';
      return fmt.module + (fmt.module_version ? ` ${fmt.module_version}` : '');
    }
    if (fmt.status === 'missing') return 'Click Repair on the main screen';
    if (fmt.status === 'broken') return fmt.error ?? 'Unknown error';
    return fmt.note ?? '';
  }
</script>

<div class="diag-wrap">

  <!-- Header -->
  <div class="diag-header">
    <button class="back-btn" onclick={onBack} aria-label="Back to main view">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <path d="M9 2L4 7l5 5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      Back
    </button>
    <span class="diag-title">Diagnostics</span>
    <button
      class="refresh-btn"
      onclick={loadCaps}
      disabled={capsLoading}
      aria-label="Refresh capabilities"
      title="Refresh"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true" class:spinning={capsLoading}>
        <path d="M12 7A5 5 0 1 1 7 2a5 5 0 0 1 3.54 1.46L12 2v4H8l1.59-1.59A3 3 0 1 0 10 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
  </div>

  <!-- Scrollable body -->
  <div class="diag-body">

    {#if capsLoading}
      <div class="loading-state">
        <div class="spinner-sm" aria-label="Loading"></div>
        <span>Checking capabilities…</span>
      </div>
    {:else if capsError}
      <div class="load-error">
        <span>Could not load capabilities: {capsError}</span>
        <button class="retry-btn" onclick={loadCaps}>Retry</button>
      </div>
    {:else if caps}

      <!-- Runtime section -->
      <section class="section">
        <h2 class="section-title">Runtime</h2>
        <div class="runtime-grid">
          <div class="runtime-item">
            <span class="runtime-label">Python</span>
            <span class="runtime-value">{caps.runtime.python_version}</span>
          </div>
          <div class="runtime-item">
            <span class="runtime-label">MarkItDown</span>
            <span class="runtime-value">{caps.runtime.markitdown_version}</span>
          </div>
          <div class="runtime-item">
            <span class="runtime-label">Sidecar</span>
            <span class="runtime-value">{caps.runtime.sidecar_version}</span>
          </div>
          <div class="runtime-item span2">
            <span class="runtime-label">Venv</span>
            <span class="runtime-value mono ellipsis" title={caps.runtime.venv_path}>{caps.runtime.venv_path}</span>
          </div>
        </div>
      </section>

      <!-- Format support section -->
      <section class="section">
        <h2 class="section-title">Format support</h2>
        <div class="cap-list">
          {#each caps.formats as fmt}
            <div
              id="fmt-{fmt.key}"
              class="cap-row"
              class:highlighted={highlight === fmt.key}
            >
              <span class="dot dot-{dotColor(fmt.status)}" aria-hidden="true"></span>
              <span class="cap-label">{fmt.label}</span>
              <span class="cap-exts">{fmt.extensions.join(' · ')}</span>
              <span class="cap-badge badge-{dotColor(fmt.status)}">{badgeLabel(fmt.status)}</span>
              {#if detailText(fmt)}
                <span class="cap-detail" class:cap-detail-red={fmt.status === 'missing' || fmt.status === 'broken'}>
                  {detailText(fmt)}
                </span>
              {/if}
            </div>
          {/each}
        </div>
      </section>

      <!-- Optional capabilities (install-on-demand engines) -->
      <section class="section">
        <h2 class="section-title">Optional capabilities</h2>
        <div class="cap-list">
          <!-- OCR row -->
          <div class="cap-row cap-row-wrap">
            <span class="dot dot-{ocrState.status === 'installed' ? 'green' : ocrState.status === 'failed' ? 'red' : 'amber'}" aria-hidden="true"></span>
            <span class="cap-label">OCR · Images &amp; scanned PDFs</span>
            <span class="cap-exts">{caps.optional.ocr.engine}</span>
            {#if ocrState.status === 'installed'}
              <span class="cap-badge badge-green">Installed</span>
            {:else if ocrState.status === 'installing' && installing === 'ocr'}
              <span class="cap-badge badge-amber">Installing…</span>
            {:else if ocrState.status === 'failed'}
              <span class="cap-badge badge-red">Failed</span>
            {:else}
              <span class="cap-badge badge-amber">Not installed</span>
              <button class="install-btn" onclick={() => installEngine('ocr')} disabled={installing !== null}>
                Install <span class="install-size">· {caps.optional.ocr.size_hint}</span>
              </button>
            {/if}
            {#if installing === 'ocr' && ocrState.status === 'installing'}
              <div class="install-progress-wrap">
                <div class="install-track"><div class="install-indet"></div></div>
                <span class="install-progress-msg">{installMsg}</span>
              </div>
            {:else if ocrState.status === 'failed' && ocrState.error}
              <div class="install-error">
                <span>{ocrState.error.split('\n')[0]}</span>
                <button class="install-btn" onclick={() => installEngine('ocr')} disabled={installing !== null}>Retry</button>
              </div>
            {:else}
              <span class="cap-detail">{caps.optional.ocr.note}</span>
            {/if}
          </div>

          <!-- Audio row -->
          <div class="cap-row cap-row-wrap">
            <span class="dot dot-{audioState.status === 'installed' ? 'green' : audioState.status === 'failed' ? 'red' : 'amber'}" aria-hidden="true"></span>
            <span class="cap-label">Audio transcription</span>
            <span class="cap-exts">{caps.optional.audio.engine}</span>
            {#if audioState.status === 'installed'}
              <span class="cap-badge badge-green">Installed</span>
            {:else if audioState.status === 'installing' && installing === 'audio'}
              <span class="cap-badge badge-amber">Installing…</span>
            {:else if audioState.status === 'failed'}
              <span class="cap-badge badge-red">Failed</span>
            {:else}
              <span class="cap-badge badge-amber">Not installed</span>
              <button class="install-btn" onclick={() => installEngine('audio')} disabled={installing !== null}>
                Install <span class="install-size">· {caps.optional.audio.size_hint}</span>
              </button>
            {/if}
            {#if installing === 'audio' && audioState.status === 'installing'}
              <div class="install-progress-wrap">
                <div class="install-track"><div class="install-indet"></div></div>
                <span class="install-progress-msg">{installMsg}</span>
              </div>
            {:else if audioState.status === 'failed' && audioState.error}
              <div class="install-error">
                <span>{audioState.error.split('\n')[0]}</span>
                <button class="install-btn" onclick={() => installEngine('audio')} disabled={installing !== null}>Retry</button>
              </div>
            {:else}
              <span class="cap-detail">{caps.optional.audio.note}</span>
            {/if}
          </div>
        </div>
        <p class="optional-note">Installed via uv pip into the app's isolated Python environment. Internet required. No system packages needed.</p>
      </section>

    {/if}

    <!-- Output management (Stage 7) — always shown -->
    <section class="section">
      <h2 class="section-title">Output</h2>

      <!-- Where batch output is saved -->
      <div class="provider-fields">
        <span class="field-label">Where to save (batch)</span>
        <div class="seg" role="group" aria-label="Output location rule">
          <button class="seg-btn" class:active={config.output_rule === 'next_to_source'} aria-pressed={config.output_rule === 'next_to_source'}
            title="Write each .md beside its source file" onclick={() => saveOutputRule('next_to_source')}>Next to source</button>
          <button class="seg-btn" class:active={config.output_rule === 'fixed_folder'} aria-pressed={config.output_rule === 'fixed_folder'}
            title="Write all .md files into one chosen folder" onclick={() => saveOutputRule('fixed_folder')}>One folder</button>
          <button class="seg-btn" class:active={config.output_rule === 'mirror_tree'} aria-pressed={config.output_rule === 'mirror_tree'}
            title="Recreate the source folder structure under a chosen root" onclick={() => saveOutputRule('mirror_tree')}>Mirror folders</button>
        </div>

        {#if config.output_rule !== 'next_to_source'}
          <div class="folder-row">
            <svg class="folder-icon" width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M1.5 4.5A1 1 0 0 1 2.5 3.5h3.086a1 1 0 0 1 .707.293l.914.914H13.5a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4.5z" stroke="currentColor" stroke-width="1.25" fill="none"/>
            </svg>
            <span class="folder-value" class:folder-unset={!config.output_folder} title={config.output_folder || 'No folder chosen yet'}>
              {config.output_folder || 'No folder chosen — choose one'}
            </span>
            {#if config.output_folder}
              <button class="mini-x" title="Clear" aria-label="Clear folder" onclick={clearOutputFolder}>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              </button>
            {/if}
            <button class="change-btn" onclick={chooseOutputFolder}>{config.output_folder ? 'Change…' : 'Choose folder…'}</button>
          </div>
          {#if config.output_rule === 'mirror_tree'}
            <p class="field-hint">Sub-folders of the dropped folder are recreated under this root.</p>
          {/if}
        {/if}
        <p class="field-hint">Single files are saved with a Save dialog; this rule applies to batch conversions.</p>
      </div>

      <!-- Naming convention -->
      <div class="provider-fields cleanup-model-block">
        <label class="field-label" for="naming-template">File name</label>
        <input
          id="naming-template"
          class="field-input"
          bind:value={namingTemplate}
          onchange={saveNamingTemplate}
          spellcheck="false"
          autocomplete="off"
          placeholder="{'{stem}'}"
        />
        <div class="preset-row">
          <button class="preset" title="The source file name" onclick={() => applyTemplatePreset('{stem}')}>{'{stem}'}</button>
          <button class="preset" title="Name plus original format" onclick={() => applyTemplatePreset('{stem}_{ext}')}>{'{stem}_{ext}'}</button>
          <button class="preset" title="Name plus today's date" onclick={() => applyTemplatePreset('{stem}-{date}')}>{'{stem}-{date}'}</button>
        </div>
        <p class="field-hint">Tokens: <code>{'{stem}'}</code> name · <code>{'{ext}'}</code> format · <code>{'{date}'}</code> today. <code>.md</code> is added automatically.</p>

        <span class="field-label">Letter case</span>
        <div class="seg" role="group" aria-label="Filename case">
          <button class="seg-btn" class:active={config.naming_case === 'keep'} aria-pressed={config.naming_case === 'keep'} title="Leave the name as-is" onclick={() => saveNamingCase('keep')}>Keep</button>
          <button class="seg-btn" class:active={config.naming_case === 'lower'} aria-pressed={config.naming_case === 'lower'} title="Lowercase the name" onclick={() => saveNamingCase('lower')}>lowercase</button>
          <button class="seg-btn" class:active={config.naming_case === 'slug'} aria-pressed={config.naming_case === 'slug'} title="Lowercase and replace spaces/symbols with hyphens" onclick={() => saveNamingCase('slug')}>slug-case</button>
        </div>

        <p class="name-preview"><span class="np-from">Annual Report.pdf</span> <span class="np-arrow" aria-hidden="true">→</span> <span class="np-to">{namePreview}</span></p>
      </div>

      <!-- Open folder after a batch -->
      <div class="provider-fields cleanup-model-block">
        <div class="toggle-row">
          <label class="toggle-label" for="open-after">Open the output folder when a batch finishes</label>
          <button
            id="open-after"
            role="switch"
            aria-checked={config.open_after_convert}
            class="toggle-btn"
            class:toggle-on={config.open_after_convert}
            onclick={() => toggleOpenAfter(!config.open_after_convert)}
            title="Reveal the converted files in your file manager after a batch run."
          >
            <span class="toggle-thumb"></span>
          </button>
        </div>
      </div>
    </section>

    <!-- LLM Provider — always shown -->
    <section class="section">
      <h2 class="section-title">LLM provider</h2>

      <!-- Mode tabs -->
      <div class="mode-tabs" role="group" aria-label="LLM mode">
        {#each [['off','Off'],['local','Local'],['api','API']] as [m, label]}
          <button
            class="mode-tab"
            class:active={config.llm_mode === m}
            aria-pressed={config.llm_mode === m}
            onclick={() => setMode(m)}
          >
            {label}
          </button>
        {/each}
      </div>

      {#if config.llm_mode === 'off'}
        <p class="provider-note">No intelligence features active. Conversions use MarkItDown only.</p>

      {:else if config.llm_mode === 'local'}
        <div class="provider-fields">
          <label class="field-label" for="local-url">Server URL</label>
          <div class="field-row">
            <input
              id="local-url"
              class="field-input"
              bind:value={localBaseUrl}
              placeholder="http://localhost:11434"
              spellcheck="false"
              autocomplete="off"
            />
            <button class="check-btn" title="Test the connection and list available models" onclick={runProviderCheck} disabled={providerChecking}>
              {providerChecking ? 'Checking…' : 'Check'}
            </button>
          </div>
          <p class="field-hint">Works with Ollama, LM Studio, Jan, and any OpenAI-compatible local server</p>
          {#if providerResult}
            <div class="provider-result" class:result-ok={providerResult.usable} class:result-fail={!providerResult.usable}>
              <span class="dot dot-{providerResult.usable ? 'green' : 'red'}" aria-hidden="true"></span>
              <span>{providerResult.detail}</span>
            </div>
          {/if}
        </div>

      {:else}
        <div class="provider-fields">
          <label class="field-label" for="api-type">Type</label>
          <select id="api-type" class="field-select" value={apiType} onchange={(e) => saveApiType((e.target as HTMLSelectElement).value)}>
            <option value="openai_compat">OpenAI-compatible</option>
            <option value="anthropic">Anthropic</option>
          </select>

          {#if apiType === 'openai_compat'}
            <label class="field-label" for="api-url">Base URL</label>
            <input
              id="api-url"
              class="field-input"
              bind:value={apiBaseUrl}
              placeholder="https://api.openai.com/v1"
              spellcheck="false"
              autocomplete="off"
            />
            <p class="field-hint">Works with OpenAI, Groq, Together, Mistral, Fireworks, and any OpenAI-compatible API</p>
          {:else}
            <p class="field-hint">Connects to api.anthropic.com — keys begin with sk-ant-</p>
          {/if}

          <label class="field-label" for="api-key">API Key</label>
          <div class="field-row">
            <input
              id="api-key"
              type="password"
              class="field-input"
              bind:value={apiKey}
              placeholder="Paste your key here"
              autocomplete="off"
            />
            <button class="check-btn" title="Test the API key and list available models" onclick={runProviderCheck} disabled={providerChecking}>
              {providerChecking ? 'Testing…' : 'Test'}
            </button>
          </div>
          <p class="field-hint">Key stored in your app data folder and sent only to the endpoint above</p>

          {#if providerResult}
            <div class="provider-result" class:result-ok={providerResult.usable} class:result-fail={!providerResult.usable}>
              <span class="dot dot-{providerResult.usable ? 'green' : 'red'}" aria-hidden="true"></span>
              <span>{providerResult.detail}</span>
            </div>
          {/if}
        </div>
      {/if}

      {#if config.llm_mode !== 'off'}
        <div class="provider-fields cleanup-model-block">
          <label class="field-label" for="cleanup-model">AI cleanup model</label>
          <select
            id="cleanup-model"
            class="field-select"
            title="Which model the AI cleanup uses. Larger models clean more reliably."
            value={cleanupModel}
            onchange={(e) => saveCleanupModel((e.target as HTMLSelectElement).value)}
          >
            <option value="">Auto — first available</option>
            {#each modelOptions as m}
              <option value={m}>{m}</option>
            {/each}
          </select>
          {#if modelOptions.length === 0}
            <p class="field-hint">Run a check above to list models. Until then, AI cleanup auto-picks the first available model.</p>
          {:else}
            <p class="field-hint">Used for the optional AI cleanup pass on extracted Markdown.</p>
          {/if}
          {#if config.llm_mode === 'local'}
            <p class="field-hint rec-hint">Recommended: <b>llama3.1:8b</b> or larger. Small models (under ~7B) tend to summarize instead of clean.</p>
          {/if}
        </div>

        <div class="provider-fields cleanup-model-block">
          <div class="toggle-row">
            <label class="toggle-label" for="llm-conversion">LLM image description during conversion</label>
            <button
              id="llm-conversion"
              role="switch"
              aria-checked={config.llm_conversion}
              class="toggle-btn"
              class:toggle-on={config.llm_conversion}
              onclick={() => toggleLlmConversion(!config.llm_conversion)}
              title="When on, the LLM describes images found in documents during conversion. Uses the conversion model."
            >
              <span class="toggle-thumb"></span>
            </button>
          </div>
          <p class="field-hint">Adds image descriptions to the converted Markdown. May increase cost for API providers.</p>

          {#if config.llm_conversion}
            <label class="field-label" for="conversion-model">Conversion model</label>
            <select
              id="conversion-model"
              class="field-select"
              title="Which model describes images during conversion."
              value={conversionModel}
              onchange={(e) => saveConversionModel((e.target as HTMLSelectElement).value)}
            >
              <option value="">Auto — first available</option>
              {#each modelOptions as m}
                <option value={m}>{m}</option>
              {/each}
            </select>
            <p class="field-hint">Uses the same provider as AI cleanup. A vision-capable model works best for image description.</p>
          {/if}
        </div>
      {/if}
    </section>

  </div>
</div>

<style>
  .diag-wrap {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  /* Header */
  .diag-header {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding-bottom: var(--sp-4);
    border-bottom: 1px solid var(--border);
    margin-bottom: var(--sp-4);
    flex-shrink: 0;
  }
  .back-btn {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    color: var(--text-primary);
    font-size: 12.5px;
    font-weight: 600;
    font-family: var(--font-ui);
    cursor: pointer;
    padding: 6px 12px;
    border-radius: var(--radius-sm);
    transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast);
  }
  .back-btn:hover { background: var(--surface-3); border-color: #565660; }
  .back-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }
  .diag-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    flex: 1;
  }
  .refresh-btn {
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    color: var(--text-secondary);
    cursor: pointer;
    width: 32px;
    height: 32px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast);
  }
  .refresh-btn:hover { color: var(--text-primary); background: var(--surface-3); border-color: #565660; }
  .refresh-btn:disabled { opacity: 0.4; cursor: default; }
  .refresh-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }
  .spinning { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spinning { animation: none; } }

  /* Body */
  .diag-body {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--sp-6);
    padding-right: var(--sp-1);
  }

  /* Loading / error states */
  .loading-state {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-6);
    color: var(--text-muted);
    font-size: 13px;
  }
  .spinner-sm {
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    flex-shrink: 0;
    animation: spin 0.7s linear infinite;
  }
  @media (prefers-reduced-motion: reduce) { .spinner-sm { animation: none; } }
  .load-error {
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    padding: var(--sp-4);
    font-size: 12px;
    color: var(--red);
    background: color-mix(in srgb, var(--red) 8%, var(--surface-1));
    border: 1px solid color-mix(in srgb, var(--red) 25%, transparent);
    border-radius: var(--radius-sm);
  }
  .retry-btn {
    background: var(--surface-2);
    border: 1px solid var(--border-strong);
    font-size: 11.5px;
    font-weight: 600;
    font-family: var(--font-ui);
    color: var(--text-primary);
    padding: 5px var(--sp-3);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast);
  }
  .retry-btn:hover { background: var(--surface-3); border-color: #565660; }

  /* Section */
  .section { display: flex; flex-direction: column; gap: var(--sp-3); }
  .section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
  }

  /* Runtime grid */
  .runtime-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }
  .runtime-item {
    background: var(--surface-1);
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--sp-2) var(--sp-3);
  }
  .runtime-item.span2 { grid-column: span 2; }
  .runtime-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }
  .runtime-value {
    font-size: 12px;
    color: var(--text-primary);
    font-family: var(--font-mono);
  }
  .runtime-value.ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Capability list */
  .cap-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }
  .cap-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 7px var(--sp-3);
    border-bottom: 1px solid var(--border);
    transition: background var(--transition-fast);
  }
  .cap-row:last-child { border-bottom: none; }
  .cap-row.highlighted {
    background: color-mix(in srgb, var(--accent) 8%, var(--surface-1));
    animation: pulse-row 1.2s ease-out;
  }
  @keyframes pulse-row {
    0%   { background: color-mix(in srgb, var(--accent) 20%, var(--surface-1)); }
    100% { background: color-mix(in srgb, var(--accent) 8%,  var(--surface-1)); }
  }
  @media (prefers-reduced-motion: reduce) { .cap-row.highlighted { animation: none; } }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .dot-green { background: var(--green); }
  .dot-amber { background: var(--amber); }
  .dot-red   { background: var(--red); }

  .cap-label { font-size: 12px; color: var(--text-primary); flex: 1; min-width: 0; }
  .cap-exts  { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); white-space: nowrap; }
  .cap-badge {
    font-size: 10px;
    font-weight: 500;
    padding: 1px 6px;
    border-radius: 99px;
    white-space: nowrap;
  }
  .badge-green { background: color-mix(in srgb, var(--green) 15%, transparent); color: var(--green); }
  .badge-amber { background: color-mix(in srgb, var(--amber) 15%, transparent); color: var(--amber); }
  .badge-red   { background: color-mix(in srgb, var(--red)   15%, transparent); color: var(--red); }
  .cap-detail {
    font-size: 11px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 180px;
  }
  .cap-detail-red { color: var(--red); font-family: var(--font-ui); }

  /* LLM provider section */
  .mode-tabs {
    display: flex;
    background: var(--surface-1);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    padding: 3px;
    gap: 3px;
    align-self: flex-start;
  }
  .mode-tab {
    padding: 6px 16px;
    font-size: 12.5px;
    font-weight: 600;
    font-family: var(--font-ui);
    border: none;
    border-radius: 5px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
  }
  .mode-tab:hover:not(.active) { color: var(--text-primary); background: var(--surface-2); }
  .mode-tab.active { background: var(--accent); color: #fff; }
  .mode-tab:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: 1px; }

  .provider-note {
    font-size: 12px;
    color: var(--text-muted);
    padding: var(--sp-2) 0;
  }

  .provider-fields {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .field-row {
    display: flex;
    gap: var(--sp-2);
  }
  .field-input {
    flex: 1;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 6px var(--sp-3);
    font-size: 12px;
    font-family: var(--font-mono);
    color: var(--text-primary);
    outline: none;
    transition: border-color var(--transition-fast);
  }
  .field-input:focus { border-color: var(--accent); }
  .field-input::placeholder { color: var(--text-muted); }
  .field-select {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 6px var(--sp-3);
    font-size: 12px;
    font-family: var(--font-ui);
    color: var(--text-primary);
    outline: none;
    cursor: pointer;
    align-self: flex-start;
  }
  .field-select:focus { border-color: var(--accent); }
  .field-hint {
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.5;
  }
  .check-btn {
    padding: 7px var(--sp-4);
    font-size: 12.5px;
    font-weight: 600;
    font-family: var(--font-ui);
    background: var(--accent);
    color: #fff;
    border: 1px solid var(--accent-edge);
    border-radius: var(--radius-sm);
    cursor: pointer;
    white-space: nowrap;
    transition: background var(--transition-fast);
  }
  .check-btn:hover { background: var(--accent-hover); }
  .check-btn:disabled { opacity: 0.45; cursor: default; }
  .check-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: 2px; }

  .provider-result {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    border-radius: var(--radius-sm);
    font-size: 12px;
  }
  .result-ok   { background: color-mix(in srgb, var(--green) 10%, var(--surface-1)); color: var(--text-primary); }
  .result-fail { background: color-mix(in srgb, var(--red)   10%, var(--surface-1)); color: var(--text-primary); }

  .cleanup-model-block {
    margin-top: var(--sp-3);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--border);
  }
  .rec-hint b { color: var(--text-secondary); }

  /* Stage 7 — output management */
  .folder-row { display: flex; align-items: center; gap: var(--sp-2); padding: var(--sp-2) var(--sp-3); background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .folder-icon { flex-shrink: 0; color: var(--accent); }
  .folder-value { flex: 1; min-width: 0; font-size: 12px; color: var(--text-primary); font-family: var(--font-mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .folder-unset { color: var(--text-muted); font-family: var(--font-ui); font-style: italic; }
  .mini-x { flex-shrink: 0; display: flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; border: none; background: var(--surface-2); color: var(--text-muted); cursor: pointer; }
  .mini-x:hover { color: var(--text-primary); background: var(--border); }
  .change-btn { flex-shrink: 0; padding: 6px 13px; font-size: 12px; font-weight: 600; font-family: var(--font-ui); color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent); border-radius: var(--radius-sm); cursor: pointer; transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast); }
  .change-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }

  .preset-row { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  .preset { font-size: 11px; font-family: var(--font-mono); color: var(--text-secondary); background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 3px 9px; cursor: pointer; transition: color var(--transition-fast), border-color var(--transition-fast); }
  .preset:hover { color: var(--text-primary); border-color: var(--border-strong); }
  .preset:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }
  .field-hint code { font-family: var(--font-mono); font-size: 10.5px; background: var(--surface-2); padding: 0 4px; border-radius: 3px; color: var(--text-secondary); }

  .name-preview { display: flex; align-items: center; gap: var(--sp-2); font-size: 12px; font-family: var(--font-mono); margin-top: var(--sp-1); padding: var(--sp-2) var(--sp-3); background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .np-from { color: var(--text-muted); }
  .np-arrow { color: var(--text-muted); }
  .np-to { color: var(--accent); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* Optional engine install UI */
  .cap-row-wrap { flex-wrap: wrap; gap: var(--sp-2) var(--sp-2); }
  .install-btn {
    padding: 6px 13px;
    font-size: 12px;
    font-weight: 600;
    font-family: var(--font-ui);
    background: var(--accent);
    color: #fff;
    border: 1px solid var(--accent-edge);
    border-radius: var(--radius-sm);
    cursor: pointer;
    white-space: nowrap;
    transition: background var(--transition-fast);
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .install-btn:hover { background: var(--accent-hover); }
  .install-btn:disabled { opacity: 0.45; cursor: default; }
  .install-size { opacity: 0.75; font-weight: 400; }
  .install-progress-wrap {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--sp-2) var(--sp-3);
  }
  /* Install has no real percentage (uv pip install doesn't stream granular progress),
     so the bar is indeterminate — honest "working" feedback rather than a fake number. */
  .install-track {
    position: relative;
    height: 3px;
    background: var(--surface-2);
    border-radius: 99px;
    overflow: hidden;
  }
  .install-indet {
    position: absolute;
    top: 0;
    height: 100%;
    width: 35%;
    background: var(--accent);
    border-radius: 99px;
    animation: install-indet 1.1s ease-in-out infinite;
  }
  @keyframes install-indet {
    0%   { left: -35%; }
    100% { left: 100%; }
  }
  @media (prefers-reduced-motion: reduce) {
    .install-indet { animation: none; left: 0; width: 100%; opacity: 0.45; }
  }
  .install-progress-msg {
    font-size: 11px;
    color: var(--text-muted);
  }
  .install-error {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    font-size: 11px;
    color: var(--red);
    padding: var(--sp-1) 0;
  }
  .optional-note {
    font-size: 11px;
    color: var(--text-muted);
    padding: var(--sp-1) 0 0;
  }

  /* LLM conversion toggle */
  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
  }
  .toggle-label {
    font-size: 12px;
    color: var(--text-primary);
    cursor: pointer;
    flex: 1;
  }
  .toggle-btn {
    position: relative;
    width: 34px;
    height: 18px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 99px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background var(--transition-fast), border-color var(--transition-fast);
  }
  .toggle-btn.toggle-on { background: var(--accent); border-color: var(--accent); }
  .toggle-thumb {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 12px;
    height: 12px;
    background: #fff;
    border-radius: 50%;
    transition: transform var(--transition-fast);
  }
  .toggle-btn.toggle-on .toggle-thumb { transform: translateX(16px); }
  .toggle-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: 2px; }
</style>
