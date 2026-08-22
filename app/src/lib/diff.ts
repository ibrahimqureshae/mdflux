// Line diff for the Changes tab.
// Dependency-free LCS. Guards against pathological sizes so a 500-page PDF stays
// responsive: above the cap it returns a cheap multiset summary instead of a full diff.
// Numbered rows + hunks are shaped like GitHub's unified file diff.

export type TextPart = { text: string; changed: boolean };

export type DiffRow = {
  type: 'same' | 'add' | 'del';
  text: string;
  oldNo: number | null;
  newNo: number | null;
  parts?: TextPart[];
};

export type DiffResult =
  | { kind: 'full'; rows: DiffRow[]; added: number; removed: number }
  | { kind: 'summary'; added: number; removed: number; note: string };

export type GitHubBlock =
  | { kind: 'hunk'; header: string }
  | { kind: 'expand'; id: string; header: string; rows: DiffRow[] }
  | { kind: 'lines'; rows: DiffRow[] };

const DEFAULT_CAP = 2000;
const CONTEXT = 3;
const WORD_CAP = 400;

export function lineDiff(a: string, b: string, cap = DEFAULT_CAP): DiffResult {
  const aLines = a.split('\n');
  const bLines = b.split('\n');

  if (aLines.length > cap || bLines.length > cap) {
    return summaryDiff(aLines, bLines);
  }

  const n = aLines.length;
  const m = bLines.length;

  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    const row = dp[i];
    const next = dp[i + 1];
    for (let j = m - 1; j >= 0; j--) {
      row[j] = aLines[i] === bLines[j]
        ? next[j + 1] + 1
        : Math.max(next[j], row[j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let added = 0;
  let removed = 0;
  let i = 0;
  let j = 0;
  let oldNo = 0;
  let newNo = 0;
  while (i < n && j < m) {
    if (aLines[i] === bLines[j]) {
      oldNo++; newNo++;
      rows.push({ type: 'same', text: aLines[i], oldNo, newNo });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      oldNo++;
      rows.push({ type: 'del', text: aLines[i], oldNo, newNo: null });
      removed++; i++;
    } else {
      newNo++;
      rows.push({ type: 'add', text: bLines[j], oldNo: null, newNo });
      added++; j++;
    }
  }
  while (i < n) {
    oldNo++;
    rows.push({ type: 'del', text: aLines[i], oldNo, newNo: null });
    removed++; i++;
  }
  while (j < m) {
    newNo++;
    rows.push({ type: 'add', text: bLines[j], oldNo: null, newNo });
    added++; j++;
  }

  return { kind: 'full', rows: attachIntraLine(rows), added, removed };
}

/** Collapse long unchanged runs the way GitHub's file diff does, with @@ hunk headers. */
export function githubBlocks(rows: DiffRow[]): GitHubBlock[] {
  if (rows.length === 0) return [];
  const changeIdx: number[] = [];
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].type !== 'same') changeIdx.push(i);
  }
  if (changeIdx.length === 0) {
    return [{ kind: 'lines', rows }];
  }

  const ranges: [number, number][] = [];
  for (const idx of changeIdx) {
    const start = Math.max(0, idx - CONTEXT);
    const end = Math.min(rows.length, idx + 1 + CONTEXT);
    const last = ranges[ranges.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else ranges.push([start, end]);
  }

  const blocks: GitHubBlock[] = [];
  let cursor = 0;
  let n = 0;
  for (const [start, end] of ranges) {
    const vis = rows.slice(start, end);
    const header = hunkHeader(vis);
    if (cursor < start) {
      blocks.push({
        kind: 'expand',
        id: `e${n++}`,
        header,
        rows: rows.slice(cursor, start),
      });
    } else {
      blocks.push({ kind: 'hunk', header });
    }
    blocks.push({ kind: 'lines', rows: vis });
    cursor = end;
  }
  if (cursor < rows.length) {
    const skipped = rows.slice(cursor);
    blocks.push({
      kind: 'expand',
      id: `e${n++}`,
      header: hunkHeader(skipped),
      rows: skipped,
    });
  }
  return blocks;
}

function hunkHeader(slice: DiffRow[]): string {
  const oldStart = slice.find(r => r.oldNo != null)?.oldNo ?? 1;
  const newStart = slice.find(r => r.newNo != null)?.newNo ?? 1;
  const oldLen = slice.filter(r => r.type !== 'add').length;
  const newLen = slice.filter(r => r.type !== 'del').length;
  return `@@ -${oldStart},${oldLen} +${newStart},${newLen} @@`;
}

function attachIntraLine(rows: DiffRow[]): DiffRow[] {
  const out = rows.slice();
  let i = 0;
  while (i < out.length) {
    if (out[i].type !== 'del') { i++; continue; }
    let j = i;
    while (j < out.length && out[j].type === 'del') j++;
    let k = j;
    while (k < out.length && out[k].type === 'add') k++;
    const n = Math.min(j - i, k - j);
    for (let t = 0; t < n; t++) {
      const w = wordParts(out[i + t].text, out[j + t].text);
      out[i + t] = { ...out[i + t], parts: w.del };
      out[j + t] = { ...out[j + t], parts: w.add };
    }
    i = k;
  }
  return out;
}

function wordParts(a: string, b: string): { del: TextPart[]; add: TextPart[] } {
  const split = (s: string) => s.split(/(\s+)/).filter(t => t.length > 0);
  const aw = split(a);
  const bw = split(b);
  if (aw.length > WORD_CAP || bw.length > WORD_CAP) {
    return {
      del: [{ text: a, changed: true }],
      add: [{ text: b, changed: true }],
    };
  }
  const n = aw.length;
  const m = bw.length;
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    const row = dp[i];
    const next = dp[i + 1];
    for (let j = m - 1; j >= 0; j--) {
      row[j] = aw[i] === bw[j] ? next[j + 1] + 1 : Math.max(next[j], row[j + 1]);
    }
  }
  const del: TextPart[] = [];
  const add: TextPart[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (aw[i] === bw[j]) {
      del.push({ text: aw[i], changed: false });
      add.push({ text: bw[j], changed: false });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      del.push({ text: aw[i], changed: true });
      i++;
    } else {
      add.push({ text: bw[j], changed: true });
      j++;
    }
  }
  while (i < n) { del.push({ text: aw[i], changed: true }); i++; }
  while (j < m) { add.push({ text: bw[j], changed: true }); j++; }
  return { del: mergeParts(del), add: mergeParts(add) };
}

function mergeParts(parts: TextPart[]): TextPart[] {
  const out: TextPart[] = [];
  for (const p of parts) {
    const last = out[out.length - 1];
    if (last && last.changed === p.changed) last.text += p.text;
    else out.push({ ...p });
  }
  return out;
}

function summaryDiff(aLines: string[], bLines: string[]): DiffResult {
  const count = (lines: string[]) => {
    const map = new Map<string, number>();
    for (const l of lines) map.set(l, (map.get(l) ?? 0) + 1);
    return map;
  };
  const ca = count(aLines);
  const cb = count(bLines);
  let added = 0;
  let removed = 0;
  for (const [line, nb] of cb) {
    const na = ca.get(line) ?? 0;
    if (nb > na) added += nb - na;
  }
  for (const [line, na] of ca) {
    const nb = cb.get(line) ?? 0;
    if (na > nb) removed += na - nb;
  }
  return {
    kind: 'summary',
    added,
    removed,
    note: 'Document is large — showing a change summary instead of a full line diff.',
  };
}
