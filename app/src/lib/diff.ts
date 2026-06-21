// Stage 5 — lightweight line diff for the single-file before/after preview.
// Dependency-free LCS. Guards against pathological sizes so a 500-page PDF stays
// responsive: above the cap it returns a cheap multiset summary instead of a full diff.

export type DiffRow = { type: 'same' | 'add' | 'del'; text: string };

export type DiffResult =
  | { kind: 'full'; rows: DiffRow[]; added: number; removed: number }
  | { kind: 'summary'; added: number; removed: number; note: string };

const DEFAULT_CAP = 2000;

export function lineDiff(a: string, b: string, cap = DEFAULT_CAP): DiffResult {
  const aLines = a.split('\n');
  const bLines = b.split('\n');

  if (aLines.length > cap || bLines.length > cap) {
    return summaryDiff(aLines, bLines);
  }

  const n = aLines.length;
  const m = bLines.length;

  // LCS length table.
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

  // Backtrack into rows.
  const rows: DiffRow[] = [];
  let added = 0;
  let removed = 0;
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (aLines[i] === bLines[j]) {
      rows.push({ type: 'same', text: aLines[i] });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: 'del', text: aLines[i] });
      removed++; i++;
    } else {
      rows.push({ type: 'add', text: bLines[j] });
      added++; j++;
    }
  }
  while (i < n) { rows.push({ type: 'del', text: aLines[i] }); removed++; i++; }
  while (j < m) { rows.push({ type: 'add', text: bLines[j] }); added++; j++; }

  return { kind: 'full', rows, added, removed };
}

// Cheap approximation for very large inputs — multiset difference of lines.
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
