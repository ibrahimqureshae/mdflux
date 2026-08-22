// Supported input formats — single source of truth for the FRONTEND.
// Keep in sync with the backend lists: `capabilities.py` (sidecar routing) and
// `lib.rs` (CORE_EXTS / OCR_EXTS / AUDIO_EXTS). When you add a format, update all three.

/** Core document formats that are always available. */
export const CORE_EXTS = [
  'pdf', 'docx', 'pptx', 'xlsx', 'xls', 'html', 'htm', 'csv', 'json', 'xml', 'epub', 'txt', 'md',
];

/** Image formats — converted via the optional OCR engine. */
export const IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'tiff', 'tif', 'bmp'];

/** Audio formats — converted via the optional transcription engine. */
export const AUDIO_EXTS = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'];

/** Everything the app accepts as input. */
export const SUPPORTED_EXTS = [...CORE_EXTS, ...IMAGE_EXTS, ...AUDIO_EXTS];

export function isImageExt(ext: string): boolean {
  return IMAGE_EXTS.includes(ext.toLowerCase());
}
export function isAudioExt(ext: string): boolean {
  return AUDIO_EXTS.includes(ext.toLowerCase());
}
/** Formats handled by a heavy optional engine (OCR / transcription) — slower, model loads on first use. */
export function isHeavyExt(ext: string): boolean {
  return isImageExt(ext) || isAudioExt(ext);
}

/** File extension without the leading dot, lowercased. Empty if none. */
export function extFromPath(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? '';
  const i = base.lastIndexOf('.');
  if (i <= 0 || i === base.length - 1) return '';
  return base.slice(i + 1).toLowerCase();
}

/** Short drop-zone / badge label for an extension. */
export function formatLabel(ext: string): string {
  const e = ext.replace(/^\./, '').toLowerCase();
  if (!e) return 'Unknown';
  if (isImageExt(e)) return 'Image';
  if (isAudioExt(e)) return 'Audio';
  const labels: Record<string, string> = {
    pdf: 'PDF', docx: 'Word', pptx: 'PowerPoint', xlsx: 'Excel', xls: 'Excel',
    html: 'HTML', htm: 'HTML', csv: 'CSV', json: 'JSON', xml: 'XML',
    epub: 'EPUB', txt: 'Text', md: 'Markdown',
  };
  return labels[e] ?? e.toUpperCase();
}
