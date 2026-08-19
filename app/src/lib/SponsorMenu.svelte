<script lang="ts">
  import { onMount } from 'svelte';
  import { openUrl } from '@tauri-apps/plugin-opener';

  const LINKS = [
    { label: 'GitHub Sponsors', href: 'https://github.com/sponsors/ibrahimqureshae' },
    { label: 'Buy Me a Coffee', href: 'https://www.buymeacoffee.com/mibrahim99' },
    { label: 'PayPal', href: 'https://www.paypal.me/mibrahimqr' },
  ] as const;

  let open = $state(false);
  let rootEl: HTMLDivElement | null = $state(null);

  onMount(() => {
    function onDocClick(e: MouseEvent) {
      if (open && rootEl && !rootEl.contains(e.target as Node)) open = false;
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') open = false;
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  });

  async function go(href: string) {
    open = false;
    try {
      await openUrl(href);
    } catch {
      // opener plugin rejects unknown hosts; ignore so the menu still closes
    }
  }
</script>

<div class="sponsor" bind:this={rootEl}>
  <button
    class="sponsor-btn"
    class:open
    onclick={() => (open = !open)}
    aria-haspopup="menu"
    aria-expanded={open}
    aria-label="Sponsor MDFlux"
    title="Sponsor"
  >
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
      <path
        d="M7.5 13S2 9.4 2 5.8C2 3.9 3.5 2.5 5.2 2.5c1.1 0 1.9.6 2.3 1.4.4-.8 1.2-1.4 2.3-1.4 1.7 0 3.2 1.4 3.2 3.3C13 9.4 7.5 13 7.5 13z"
        stroke="currentColor"
        stroke-width="1.2"
        stroke-linejoin="round"
      />
    </svg>
  </button>

  {#if open}
    <div class="menu" role="menu" aria-label="Sponsor links">
      <p class="menu-title">Support MDFlux</p>
      {#each LINKS as link}
        <button class="menu-item" role="menuitem" onclick={() => go(link.href)}>
          {link.label}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .sponsor { position: relative; }
  .sponsor-btn {
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
  .sponsor-btn:hover,
  .sponsor-btn.open { color: var(--text-primary); background: var(--surface-3); border-color: #565660; }
  .sponsor-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }

  .menu {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    min-width: 200px;
    background: var(--surface-1);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    padding: var(--sp-2);
    z-index: 40;
  }
  .menu-title {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted);
    padding: 6px 10px 4px;
  }
  .menu-item {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    color: var(--text-primary);
    font-family: var(--font-ui);
    font-size: 13px;
    font-weight: 500;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .menu-item:hover { background: var(--surface-2); }
  .menu-item:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); }
</style>
