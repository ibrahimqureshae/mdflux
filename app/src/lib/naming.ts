// Stage 7 — output filename builder. Mirrors the Rust `build_output_name`
// (lib.rs) so the live preview in the UI matches what a batch actually writes.
// Tokens: {stem} {ext} {date}. The ".md" extension is always appended.

export type NamingCase = 'keep' | 'lower' | 'slug';
export type OutputRule = 'next_to_source' | 'fixed_folder' | 'mirror_tree';

/** Strip directory + extension from a path (handles \ and /). */
export function fileStem(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? path;
  const dot = base.lastIndexOf('.');
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return stem || 'output';
}

/** Lowercase extension without the dot, or '' if none. */
export function fileExt(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? path;
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function sanitize(s: string): string {
  return s
    // eslint-disable-next-line no-control-regex
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, '-')
    .trim()
    .replace(/\.+$/, '')
    .trim();
}

function todayDate(): string {
  // UTC to match the Rust `today_date_string()` (civil-from-days, UTC). Without this
  // the live preview filename can differ from the actual output by one day near midnight.
  const d = new Date();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${d.getUTCFullYear()}-${m}-${day}`;
}

/** Base filename (no extension) from a source path + template + case. */
export function buildOutputName(path: string, template: string, naming: NamingCase): string {
  const tpl = (template ?? '').trim() || '{stem}';
  let name = tpl
    .replaceAll('{stem}', fileStem(path))
    .replaceAll('{ext}', fileExt(path))
    .replaceAll('{date}', todayDate());
  if (naming === 'lower') name = name.toLowerCase();
  else if (naming === 'slug') name = slugify(name);
  const cleaned = sanitize(name);
  return cleaned || 'output';
}

/** Full output filename (with .md) for previews and the single-file save default. */
export function buildOutputFilename(path: string, template: string, naming: NamingCase): string {
  return `${buildOutputName(path, template, naming)}.md`;
}

/** Human label for an output rule. */
export function ruleLabel(rule: OutputRule): string {
  switch (rule) {
    case 'fixed_folder': return 'A chosen folder';
    case 'mirror_tree':  return 'Mirror source folders';
    default:             return 'Next to each source file';
  }
}
