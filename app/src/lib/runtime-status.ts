/**
 * Runtime status contract shared with the Rust `get_runtime_status` command.

 */

export type Edition = 'lite' | 'full';
export type PlatformId = 'windows-x64' | 'linux-x64-glibc';
export type RuntimeLifecycle = 'missing' | 'installing' | 'ready' | 'invalid' | 'repairable';
export type ComponentState = 'not_installed' | 'installing' | 'installed' | 'failed';
export type RuntimeComponent = 'core' | 'ocr' | 'audio';

export interface RuntimeStatus {
  edition: Edition;
  platform: PlatformId;
  status: RuntimeLifecycle;
  mutable: boolean;
  python_version: string | null;
  components: Record<RuntimeComponent, ComponentState>;
  repair_action: string | null;
}

export interface LegacyProvisionStatus {
  state: string;
}

export interface LegacyEngineState {
  status: string;
  error?: string | null;
}

const RUNTIME_COMPONENTS: RuntimeComponent[] = ['core', 'ocr', 'audio'];

const EDITION_LABELS: Record<Edition, string> = {
  lite: 'Lite',
  full: 'Full',
};

const PLATFORM_LABELS: Record<PlatformId, string> = {
  'windows-x64': 'Windows x64',
  'linux-x64-glibc': 'Linux x64 (glibc)',
};

const LIFECYCLE_LABELS: Record<RuntimeLifecycle, string> = {
  missing: 'Not provisioned',
  installing: 'Installing',
  ready: 'Ready',
  invalid: 'Invalid',
  repairable: 'Repairable',
};

const COMPONENT_LABELS: Record<RuntimeComponent, string> = {
  core: 'Core conversion',
  ocr: 'OCR',
  audio: 'Audio transcription',
};

const COMPONENT_STATE_LABELS: Record<ComponentState, string> = {
  not_installed: 'Not installed',
  installing: 'Installing…',
  installed: 'Installed',
  failed: 'Failed',
};

/** Whether optional component install actions should appear in diagnostics. */
export function allowsComponentInstall(status: RuntimeStatus): boolean {
  return status.edition === 'lite' && status.mutable && status.status === 'ready';
}

/** Whether the UI should offer runtime repair (Lite transactional recovery). */
export function showsRepairAction(status: RuntimeStatus): boolean {
  return (
    status.edition === 'lite'
    && status.mutable
    && (status.status === 'repairable' || status.status === 'invalid')
    && !!status.repair_action
  );
}

/** Full edition bundles core, OCR, and audio; never show package install. */
export function isImmutableFull(status: RuntimeStatus): boolean {
  return status.edition === 'full' && !status.mutable;
}

export function editionLabel(edition: Edition): string {
  return EDITION_LABELS[edition];
}

export function platformLabel(platform: PlatformId): string {
  return PLATFORM_LABELS[platform];
}

export function lifecycleLabel(status: RuntimeLifecycle): string {
  return LIFECYCLE_LABELS[status];
}

export function componentLabel(component: RuntimeComponent): string {
  return COMPONENT_LABELS[component];
}

export function componentStateLabel(state: ComponentState): string {
  return COMPONENT_STATE_LABELS[state];
}

export function componentDotClass(state: ComponentState): 'green' | 'amber' | 'red' {
  if (state === 'installed') return 'green';
  if (state === 'installing') return 'amber';
  if (state === 'failed') return 'red';
  return 'amber';
}

export function lifecycleDotClass(status: RuntimeLifecycle): 'green' | 'amber' | 'red' {
  if (status === 'ready') return 'green';
  if (status === 'installing' || status === 'repairable') return 'amber';
  if (status === 'invalid' || status === 'missing') return 'red';
  return 'amber';
}

function defaultPlatform(): PlatformId {
  if (typeof navigator !== 'undefined' && /Linux/i.test(navigator.userAgent)) {
    return 'linux-x64-glibc';
  }
  return 'windows-x64';
}

function emptyComponents(): Record<RuntimeComponent, ComponentState> {
  return { core: 'not_installed', ocr: 'not_installed', audio: 'not_installed' };
}

function parseComponentState(raw: unknown): ComponentState {
  const v = String(raw ?? '');
  if (v === 'installed' || v === 'installing' || v === 'failed') return v;
  return 'not_installed';
}

function parseRuntimeStatus(raw: unknown): RuntimeStatus | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const edition = o.edition === 'full' ? 'full' : o.edition === 'lite' ? 'lite' : null;
  const platform = o.platform === 'linux-x64-glibc' ? 'linux-x64-glibc'
    : o.platform === 'windows-x64' ? 'windows-x64' : null;
  const status = o.status as RuntimeLifecycle;
  const validLifecycle = ['missing', 'installing', 'ready', 'invalid', 'repairable'].includes(String(status));
  if (!edition || !platform || !validLifecycle) return null;

  const componentsRaw = (o.components ?? {}) as Record<string, unknown>;
  const components: Record<RuntimeComponent, ComponentState> = {
    core: parseComponentState(componentsRaw.core),
    ocr: parseComponentState(componentsRaw.ocr),
    audio: parseComponentState(componentsRaw.audio),
  };

  return {
    edition,
    platform,
    status,
    mutable: Boolean(o.mutable),
    python_version: typeof o.python_version === 'string' ? o.python_version : null,
    components,
    repair_action: typeof o.repair_action === 'string' ? o.repair_action : null,
  };
}

/**
 * Build a Lite runtime status from legacy provision + optional engine IPC while
 * `get_runtime_status` is unavailable.
 */
export function legacyRuntimeStatusFromProvision(
  provision: LegacyProvisionStatus,
  ocr: LegacyEngineState = { status: 'not_installed' },
  audio: LegacyEngineState = { status: 'not_installed' },
  platform: PlatformId = defaultPlatform(),
): RuntimeStatus {
  const components = emptyComponents();
  components.ocr = parseComponentState(ocr.status);
  components.audio = parseComponentState(audio.status);

  if (provision.state === 'ready') {
    components.core = 'installed';
    return {
      edition: 'lite',
      platform,
      status: 'ready',
      mutable: true,
      python_version: null,
      components,
      repair_action: null,
    };
  }

  if (provision.state === 'not_provisioned') {
    return {
      edition: 'lite',
      platform,
      status: 'missing',
      mutable: true,
      python_version: null,
      components,
      repair_action: 'provision',
    };
  }

  return {
    edition: 'lite',
    platform,
    status: 'repairable',
    mutable: true,
    python_version: null,
    components,
    repair_action: 'provision',
  };
}

/** Lite runtime after a failed staged install; previous active runtime still usable. */
export function mockLiteRepairableAfterFailedStaging(
  platform: PlatformId = 'windows-x64',
): RuntimeStatus {
  return {
    edition: 'lite',
    platform,
    status: 'repairable',
    mutable: true,
    python_version: '3.12.11',
    components: {
      core: 'installed',
      ocr: 'failed',
      audio: 'not_installed',
    },
    repair_action: 'repair_component',
  };
}

/** Fetch runtime status from IPC, or synthesize from legacy commands. */
export async function fetchRuntimeStatus(): Promise<RuntimeStatus> {
  const { invoke } = await import('@tauri-apps/api/core');

  try {
    const raw = await invoke<unknown>('get_runtime_status');
    const parsed = parseRuntimeStatus(raw);
    if (parsed) return parsed;
  } catch {
    // Command not registered; fall through to legacy adapter.
  }

  const [provision, ocr, audio] = await Promise.all([
    invoke<LegacyProvisionStatus>('get_provision_status'),
    invoke<LegacyEngineState>('optional_engine_status', { engine: 'ocr' }).catch(() => ({ status: 'not_installed' })),
    invoke<LegacyEngineState>('optional_engine_status', { engine: 'audio' }).catch(() => ({ status: 'not_installed' })),
  ]);

  return legacyRuntimeStatusFromProvision(provision, ocr, audio);
}

// ?? AI cleanup notice classification ?????

export type AiNoticeKind = 'none' | 'applied' | 'cancelled' | 'inactivity' | 'provider' | 'empty' | 'other';

/** Provider inactivity text fragment; do not rewrite as a generic timeout. */
export const PROVIDER_INACTIVITY_FRAGMENT = 'provider sent no response data';

export function classifyAiNotice(notice: string | null | undefined): AiNoticeKind {
  if (!notice?.trim()) return 'none';
  const n = notice.trim();
  if (/cancelled.*kept the original/i.test(n) || /conversion cancelled/i.test(n)) return 'cancelled';
  if (n.includes(PROVIDER_INACTIVITY_FRAGMENT) || /AI cleanup stopped because/i.test(n)) return 'inactivity';
  if (/AI cleanup unavailable:/i.test(n)) return 'provider';
  if (/returned nothing.*kept the original/i.test(n)) return 'empty';
  if (/AI cleanup applied/i.test(n)) return 'applied';
  return 'other';
}

export function aiNoticePresentation(kind: AiNoticeKind): { className: string; prefix: string } {
  switch (kind) {
    case 'cancelled':
      return { className: 'notice-cancelled', prefix: 'Cancelled' };
    case 'inactivity':
      return { className: 'notice-inactivity', prefix: 'Provider inactive' };
    case 'provider':
      return { className: 'notice-provider', prefix: 'Provider error' };
    case 'empty':
      return { className: 'notice-empty', prefix: 'Empty response' };
    default:
      return { className: 'notice-other', prefix: '' };
  }
}

// ?? Typed mocks for tests and local development ???????????????????????????

function mockStatus(
  edition: Edition,
  platform: PlatformId,
  lifecycle: RuntimeLifecycle,
  components: Partial<Record<RuntimeComponent, ComponentState>>,
  repair: string | null = null,
  python: string | null = edition === 'full' ? '3.12.11' : '3.12.11',
): RuntimeStatus {
  return {
    edition,
    platform,
    status: lifecycle,
    mutable: edition === 'lite',
    python_version: python,
    components: { ...emptyComponents(), ...components },
    repair_action: repair,
  };
}

/** Every runtime lifecycle and edition combination used in UI tests. */
export const MOCK_RUNTIME_STATUSES: RuntimeStatus[] = [
  mockStatus('lite', 'windows-x64', 'missing', {}, 'provision', null),
  mockStatus('lite', 'windows-x64', 'installing', { core: 'installing' }, null),
  mockStatus('lite', 'windows-x64', 'ready', { core: 'installed', ocr: 'not_installed', audio: 'not_installed' }),
  mockStatus('lite', 'linux-x64-glibc', 'repairable', { core: 'installed', ocr: 'failed' }, 'repair_component'),
  mockStatus('lite', 'linux-x64-glibc', 'invalid', { core: 'failed' }, 'provision'),
  mockStatus('full', 'windows-x64', 'ready', { core: 'installed', ocr: 'installed', audio: 'installed' }),
  mockStatus('full', 'linux-x64-glibc', 'ready', { core: 'installed', ocr: 'installed', audio: 'installed' }),
];

/** Every component state for Lite ready runtime (diagnostics grid). */
export const MOCK_COMPONENT_MATRIX: Array<Record<RuntimeComponent, ComponentState>> = [
  { core: 'installed', ocr: 'not_installed', audio: 'not_installed' },
  { core: 'installed', ocr: 'installing', audio: 'not_installed' },
  { core: 'installed', ocr: 'installed', audio: 'installing' },
  { core: 'installed', ocr: 'installed', audio: 'installed' },
  { core: 'installed', ocr: 'failed', audio: 'not_installed' },
];

export { RUNTIME_COMPONENTS };
