// Supported input formats — single source of truth for the FRONTEND.
// Keep in sync with the backend lists: `capabilities.py` (sidecar routing) and
// `lib.rs` (CORE_EXTS / OCR_EXTS / AUDIO_EXTS). When you add a format, update all three.

/** Core document formats — always available (provisioned at Stage 0). */
export const CORE_EXTS = [
  'pdf', 'docx', 'pptx', 'xlsx', 'xls', 'html', 'htm', 'csv', 'json', 'xml', 'epub',
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
