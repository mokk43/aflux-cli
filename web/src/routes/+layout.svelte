<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import '../app.css';
  import { applyTheme, authToken, isOnline, theme } from '$lib/stores';

  $: applyTheme($theme);

  $: if (browser && !$authToken && $page.url.pathname !== '/') {
    goto('/');
  }

  $: if (browser && $authToken && $page.url.pathname === '/') {
    goto('/scan');
  }

  function toggleTheme(): void {
    theme.set($theme === 'dark' ? 'light' : 'dark');
  }

  if (browser) {
    window.addEventListener('online', () => isOnline.set(true));
    window.addEventListener('offline', () => isOnline.set(false));

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js').catch(() => undefined);
    }
  }
</script>

<svelte:head>
  <title>aflux</title>
</svelte:head>

<div
  class="min-h-screen bg-slate-50 text-slate-950 transition-colors dark:bg-slate-950 dark:text-slate-100"
>
  <header
    class="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur dark:border-slate-800 dark:bg-slate-950/85"
  >
    <div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
      <a href="/scan" class="flex items-center gap-3">
        <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-red-600 text-white">
          A
        </span>
        <span>
          <span class="block text-sm font-semibold tracking-wide">aflux</span>
          <span class="hidden text-xs text-slate-500 dark:text-slate-400 sm:block">
            A-share turnover scanner
          </span>
        </span>
      </a>

      <button
        type="button"
        class="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        on:click={toggleTheme}
      >
        {$theme === 'dark' ? 'Light' : 'Dark'}
      </button>
    </div>
  </header>

  {#if !$isOnline}
    <div class="bg-amber-500 px-4 py-2 text-center text-sm font-medium text-slate-950">
      Offline. Scans are paused until the connection returns.
    </div>
  {/if}

  <slot />
</div>
