<script lang="ts">
  import { githubBlocks } from './diff';
  import type { DiffResult, DiffRow } from './diff';

  let {
    diff,
    filename,
  }: {
    diff: DiffResult;
    filename: string;
  } = $props();

  let opened = $state<Record<string, boolean>>({});
  const blocks = $derived(diff.kind === 'full' ? githubBlocks(diff.rows) : []);
  const hasExpand = $derived(blocks.some(b => b.kind === 'expand'));

  function toggle(id: string) {
    opened = { ...opened, [id]: !opened[id] };
  }
  function expandAll() {
    const next: Record<string, boolean> = {};
    for (const b of blocks) {
      if (b.kind === 'expand') next[b.id] = true;
    }
    opened = next;
  }

  const statBlocks = $derived.by(() => {
    const add = diff.added;
    const del = diff.removed;
    const total = add + del;
    if (total === 0) return { green: 0, red: 0, empty: 5 };
    const green = Math.round((add / total) * 5);
    const red = Math.min(5 - green, Math.round((del / total) * 5) || (del > 0 ? 1 : 0));
    const g = Math.min(5, Math.max(add > 0 ? 1 : 0, green));
    const r = Math.min(5 - g, Math.max(del > 0 ? 1 : 0, red));
    return { green: g, red: r, empty: 5 - g - r };
  });

  const barKinds = $derived([
    ...Array.from({ length: statBlocks.green }, () => 'add' as const),
    ...Array.from({ length: statBlocks.red }, () => 'del' as const),
    ...Array.from({ length: statBlocks.empty }, () => 'empty' as const),
  ]);

  function marker(type: DiffRow['type']): string {
    if (type === 'add') return '+';
    if (type === 'del') return '-';
    return ' ';
  }
</script>

{#if diff.kind === 'summary'}
  <div class="gh-file">
    <div class="file-header">
      <span class="file-path">{filename}</span>
      <span class="diffstat">
        <span class="stat-add">+{diff.added.toLocaleString()}</span>
        <span class="stat-del">-{diff.removed.toLocaleString()}</span>
      </span>
    </div>
    <div class="summary">
      <p>{diff.note}</p>
    </div>
  </div>
{:else}
  <div class="gh-file">
    <div class="file-header">
      <div class="file-info">
        <svg class="file-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <path fill="currentColor" d="M2 1.75C2 .784 2.784 0 3.75 0h6.586c.464 0 .909.184 1.237.513l2.914 2.914c.329.328.513.773.513 1.237v9.586A1.75 1.75 0 0 1 13.25 16h-9.5A1.75 1.75 0 0 1 2 14.25Zm1.75-.25a.25.25 0 0 0-.25.25v12.5c0 .138.112.25.25.25h9.5a.25.25 0 0 0 .25-.25V6h-2.75A1.75 1.75 0 0 1 9 4.25V1.5Zm6.75.062L11.5 4.25h2.062Z"/>
        </svg>
        <span class="file-path">{filename}</span>
      </div>
      <div class="file-actions">
        {#if hasExpand}
          <button class="expand-all" type="button" onclick={expandAll} title="Show every unchanged line">Expand all</button>
        {/if}
        <span class="diffstat" title="{diff.added} additions and {diff.removed} deletions">
          <span class="stat-add">+{diff.added.toLocaleString()}</span>
          <span class="stat-del">-{diff.removed.toLocaleString()}</span>
          <span class="stat-bars" aria-hidden="true">
            {#each barKinds as kind, i (i)}
              <span class="bar bar-{kind}"></span>
            {/each}
          </span>
        </span>
      </div>
    </div>

    <div class="blob-wrapper">
      <table class="diff-table">
        <tbody>
          {#each blocks as block}
            {#if block.kind === 'hunk'}
              <tr class="blob-hunk">
                <td class="blob-num blob-num-hunk"></td>
                <td class="blob-num blob-num-hunk"></td>
                <td class="blob-code blob-code-hunk">{block.header}</td>
              </tr>
            {:else if block.kind === 'expand'}
              {#if opened[block.id]}
                {#each block.rows as row}
                  {@render codeRow(row)}
                {/each}
              {:else}
                <tr class="blob-hunk blob-expand">
                  <td class="blob-num blob-num-hunk" colspan="2">
                    <button class="hunk-btn" type="button" title="Show {block.rows.length} unchanged lines" onclick={() => toggle(block.id)} aria-label="Expand unchanged lines">
                      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8.177.677l2.896 2.896a.25.25 0 0 1-.177.427H8.75v1.25a.75.75 0 0 1-1.5 0V4H5.104a.25.25 0 0 1-.177-.427L7.823.677a.25.25 0 0 1 .354 0ZM7.25 10.75a.75.75 0 0 1 1.5 0V12h2.146a.25.25 0 0 1 .177.427l-2.896 2.896a.25.25 0 0 1-.354 0l-2.896-2.896A.25.25 0 0 1 5.104 12H7.25v-1.25Zm-5-2a.75.75 0 0 0 0-1.5h-.5a.75.75 0 0 0 0 1.5zM4 8.75a.75.75 0 0 1 0-1.5h.5a.75.75 0 0 1 0 1.5zm3-2.75h.5a.75.75 0 0 0 0-1.5H7a.75.75 0 0 0 0 1.5zM8.75 8a.75.75 0 0 1 .75-.75h.5a.75.75 0 0 1 0 1.5h-.5A.75.75 0 0 1 8.75 8zM12 7.25a.75.75 0 0 0 0 1.5h.5a.75.75 0 0 0 0-1.5zM13.25 8a.75.75 0 0 1 .75-.75h.5a.75.75 0 0 1 0 1.5h-.5a.75.75 0 0 1-.75-.75z"/></svg>
                    </button>
                  </td>
                  <td class="blob-code blob-code-hunk">
                    <button class="hunk-code" type="button" onclick={() => toggle(block.id)}>{block.header}</button>
                  </td>
                </tr>
              {/if}
            {:else}
              {#each block.rows as row}
                {@render codeRow(row)}
              {/each}
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}

{#snippet codeRow(row: DiffRow)}
  <tr class="blob-row blob-{row.type}">
    <td class="blob-num blob-num-{row.type}">{row.oldNo ?? ''}</td>
    <td class="blob-num blob-num-{row.type}">{row.newNo ?? ''}</td>
    <td class="blob-code blob-code-{row.type}">
      <span class="blob-code-inner"
        ><span class="blob-code-marker">{marker(row.type)}</span>{#if row.parts}{#each row.parts as part}<span class:x={part.changed}>{part.text}</span>{/each}{:else}{row.text}{/if}</span
      >
    </td>
  </tr>
{/snippet}

<style>
  /* GitHub Primer dark unified-diff. Hardcoded so this tab matches github.com, not the app chrome. */
  .gh-file {
    display: flex;
    flex-direction: column;
    min-height: 100%;
    background: #0d1117;
    color: #e6edf3;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 12px;
    line-height: 20px;
  }

  .file-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 16px;
    background: #161b22;
    border-bottom: 1px solid #30363d;
    flex-shrink: 0;
    position: sticky;
    top: 0;
    z-index: 2;
  }
  .file-info { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .file-icon { color: #8b949e; flex-shrink: 0; }
  .file-path {
    color: #e6edf3;
    font-weight: 600;
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .file-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  .expand-all {
    background: none; border: none; padding: 0;
    color: #58a6ff; font-size: 12px; font-family: inherit; cursor: pointer;
  }
  .expand-all:hover { text-decoration: underline; }
  .diffstat { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; }
  .stat-add { color: #3fb950; }
  .stat-del { color: #f85149; }
  .stat-bars { display: inline-flex; gap: 1px; }
  .bar { width: 8px; height: 8px; border-radius: 1px; }
  .bar-add { background: #3fb950; }
  .bar-del { background: #f85149; }
  .bar-empty { background: #30363d; }

  .summary { padding: 16px; color: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px; }
  .summary p { margin: 0; }

  .blob-wrapper { overflow: auto; flex: 1; min-height: 0; }
  .diff-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
  }

  .blob-num {
    width: 1%;
    min-width: 50px;
    padding: 0 10px;
    color: #6e7681;
    text-align: right;
    vertical-align: top;
    user-select: none;
    white-space: nowrap;
    border-right: 1px solid #30363d;
    background: #0d1117;
  }
  .blob-code {
    padding: 0 10px;
    vertical-align: top;
    white-space: pre;
    tab-size: 4;
    width: 100%;
  }
  .blob-code-inner { display: inline; }
  .blob-code-marker {
    display: inline-block;
    width: 1ch;
    margin-right: 8px;
    user-select: none;
    color: inherit;
  }

  .blob-same .blob-code { color: #e6edf3; }
  .blob-add .blob-num,
  .blob-code-add { background: #12261e; }
  .blob-add .blob-num { color: #3fb950; }
  .blob-code-add { color: #e6edf3; }
  .blob-del .blob-num,
  .blob-code-del { background: #3d1214; }
  .blob-del .blob-num { color: #f85149; }
  .blob-code-del { color: #e6edf3; }

  .blob-code-add .x { background: rgba(46, 160, 67, 0.4); }
  .blob-code-del .x { background: rgba(248, 81, 73, 0.4); }

  .blob-hunk td { background: #111d2e; color: #8b949e; }
  .blob-num-hunk {
    background: #111d2e;
    color: #4493f8;
    border-right-color: #1e3a5f;
  }
  .blob-code-hunk {
    background: #111d2e;
    color: #8b949e;
    white-space: pre;
    font-weight: 400;
  }

  .hunk-btn, .hunk-code {
    background: none; border: none; padding: 0;
    color: inherit; font: inherit; cursor: pointer; width: 100%;
    text-align: inherit;
  }
  .hunk-btn {
    color: #4493f8;
    display: flex;
    align-items: center;
    justify-content: flex-end;
  }
  .hunk-btn svg { display: block; }
  .blob-expand:hover td { background: #1c2b45; }

  .blob-row:hover .blob-num-same { background: #161b22; }
  .blob-row:hover .blob-code-same { background: #161b22; }
</style>
