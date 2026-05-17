<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { onDestroy, onMount } from 'svelte';
  import { AfluxApiError, fetchBoards, scan as runScan } from '$lib/api';
  import {
    DEFAULT_SCAN_PARAMS,
    apiError,
    autoRefreshEnabled,
    isOnline,
    lastUpdatedAt,
    loading,
    refreshIntervalSeconds,
    scanParams,
    scanResponse,
    sortState,
    updateScanResponse
  } from '$lib/stores';
  import {
    cnMarketClass,
    compareResults,
    formatPercent,
    formatPrice,
    formatTurnover,
    marketCountdown,
    phaseClass,
    phaseLabel,
    relativeAge,
    scanTimeLabel,
    staleClass
  } from '$lib/format';
  import type { BoardId, BoardInfo, ScanParams, ScanResult, SortKey } from '$lib/types';

  const fallbackBoards: BoardInfo[] = [
    { id: 'star', label: 'STAR' },
    { id: 'chinext', label: 'CHINEXT' },
    { id: 'sme', label: 'SME' },
    { id: 'main', label: 'MAIN' },
    { id: 'bse', label: 'BSE' }
  ];

  const sortOptions: { key: SortKey; label: string }[] = [
    { key: 'volume_ratio_pct', label: 'Volume ratio' },
    { key: 'price_change_pct', label: 'Price change' },
    { key: 'turnover', label: 'Turnover' },
    { key: 'prev_turnover', label: 'Prev turnover' },
    { key: 'price', label: 'Price' },
    { key: 'code', label: 'Code' },
    { key: 'name', label: 'Name' },
    { key: 'board', label: 'Board' }
  ];
  const tableColumns: { key: SortKey; label: string; align?: 'left' | 'right' }[] = [
    { key: 'code', label: 'Code' },
    { key: 'name', label: 'Name' },
    { key: 'price', label: 'Price', align: 'right' },
    { key: 'price_change_pct', label: 'Change %', align: 'right' },
    { key: 'volume_ratio_pct', label: 'Volume ratio %', align: 'right' },
    { key: 'turnover', label: 'Turnover', align: 'right' },
    { key: 'prev_turnover', label: 'Prev turnover', align: 'right' },
    { key: 'board', label: 'Board' }
  ];

  let boards = fallbackBoards;
  let filtersOpen = false;
  let now = new Date();
  let nextRefreshAt: Date | null = null;
  let rateLimitRetryAt: Date | null = null;
  let touchStartY = 0;
  let pullDistance = 0;
  let mounted = false;
  let tickTimer: number | null = null;

  $: sortedResults = sortResults($scanResponse?.results ?? []);
  $: currentPhase = $scanResponse?.market_phase ?? 'off_market';
  $: canAutoRefresh = $isOnline && currentPhase !== 'off_market';
  $: refreshCountdown =
    nextRefreshAt && $autoRefreshEnabled && canAutoRefresh
      ? Math.max(0, Math.ceil((nextRefreshAt.getTime() - now.getTime()) / 1000))
      : 0;
  $: rateLimitCountdown = rateLimitRetryAt
    ? Math.max(0, Math.ceil((rateLimitRetryAt.getTime() - now.getTime()) / 1000))
    : 0;
  $: if (browser) {
    document.title = $scanResponse
      ? `aflux (${$scanResponse.count}) - ${phaseLabel($scanResponse.market_phase)}`
      : 'aflux';
  }

  onMount(() => {
    mounted = true;
    scanParams.set(paramsFromUrl() ?? $scanParams);
    syncUrl($scanParams);

    fetchBoards()
      .then((items) => {
        boards = items.length ? items : fallbackBoards;
      })
      .catch(() => {
        boards = fallbackBoards;
      });

    const unsubscribeParams = scanParams.subscribe((params) => {
      if (mounted) syncUrl(params);
    });

    tickTimer = window.setInterval(() => {
      now = new Date();
      if (rateLimitRetryAt && now >= rateLimitRetryAt) {
        rateLimitRetryAt = null;
        void performScan();
      }
      maybeAutoRefresh();
    }, 1000);

    return () => {
      unsubscribeParams();
    };
  });

  onDestroy(() => {
    mounted = false;
    if (tickTimer) window.clearInterval(tickTimer);
  });

  function paramsFromUrl(): ScanParams | null {
    if (!browser) return null;
    const query = new URLSearchParams(window.location.search);
    if (![...query.keys()].length) return null;
    const boardsParam = query.get('b');
    const selectedBoards = boardsParam
      ? boardsParam
          .split(',')
          .filter((item): item is BoardId => fallbackBoards.some((board) => board.id === item))
      : DEFAULT_SCAN_PARAMS.boards;
    return {
      volume_ratio: Number(query.get('v') ?? DEFAULT_SCAN_PARAMS.volume_ratio),
      price_change: Number(query.get('p') ?? DEFAULT_SCAN_PARAMS.price_change),
      boards: selectedBoards.length ? selectedBoards : DEFAULT_SCAN_PARAMS.boards,
      include_st: query.get('st') === '1',
      no_cache: query.get('nc') === '1'
    };
  }

  function syncUrl(params: ScanParams): void {
    if (!browser || window.location.pathname !== '/scan') return;
    const query = new URLSearchParams({
      v: String(params.volume_ratio),
      p: String(params.price_change),
      b: params.boards.join(',')
    });
    if (params.include_st) query.set('st', '1');
    if (params.no_cache) query.set('nc', '1');
    const target = `/scan?${query.toString()}`;
    if (`${window.location.pathname}${window.location.search}` !== target) {
      goto(target, { replaceState: true, noScroll: true, keepFocus: true });
    }
  }

  function setParam<K extends keyof ScanParams>(key: K, value: ScanParams[K]): void {
    scanParams.update((params) => ({ ...params, [key]: value }));
  }

  function numberValue(event: Event): number {
    return Number((event.currentTarget as HTMLInputElement).value);
  }

  function checkedValue(event: Event): boolean {
    return (event.currentTarget as HTMLInputElement).checked;
  }

  function selectValue(event: Event): string {
    return (event.currentTarget as HTMLSelectElement).value;
  }

  function sortKeyValue(event: Event): SortKey {
    return selectValue(event) as SortKey;
  }

  function toggleBoard(board: BoardId, checked: boolean): void {
    scanParams.update((params) => {
      const selected = checked
        ? Array.from(new Set([...params.boards, board]))
        : params.boards.filter((item) => item !== board);
      return { ...params, boards: selected.length ? selected : DEFAULT_SCAN_PARAMS.boards };
    });
  }

  async function performScan(): Promise<void> {
    if (!$isOnline || $loading) return;
    loading.set(true);
    apiError.set(null);
    try {
      const response = await runScan($scanParams);
      updateScanResponse(response);
      nextRefreshAt = new Date(Date.now() + $refreshIntervalSeconds * 1000);
    } catch (exc) {
      if (exc instanceof AfluxApiError && exc.status === 429) {
        rateLimitRetryAt = new Date(Date.now() + 30_000);
        apiError.set('Rate limited. Retrying automatically.');
      } else {
        apiError.set(exc instanceof Error ? exc.message : 'Scan failed.');
      }
    } finally {
      loading.set(false);
    }
  }

  function maybeAutoRefresh(): void {
    if (!$autoRefreshEnabled || !canAutoRefresh || document.hidden || $loading) {
      nextRefreshAt = null;
      return;
    }
    if (!nextRefreshAt) {
      nextRefreshAt = new Date(Date.now() + $refreshIntervalSeconds * 1000);
      return;
    }
    if (Date.now() >= nextRefreshAt.getTime()) {
      void performScan();
    }
  }

  function sortResults(results: ScanResult[]): ScanResult[] {
    const state = $sortState;
    if (state.direction === 'none') return results;
    return [...results].sort((a, b) => {
      const result = compareResults(a, b, state.key);
      return state.direction === 'asc' ? result : -result;
    });
  }

  function cycleSort(key: SortKey): void {
    sortState.update((state) => {
      if (state.key !== key) return { key, direction: 'desc' };
      if (state.direction === 'desc') return { key, direction: 'asc' };
      if (state.direction === 'asc') return { key, direction: 'none' };
      return { key, direction: 'desc' };
    });
  }

  function sortDirectionLabel(): string {
    if ($sortState.direction === 'asc') return 'Asc';
    if ($sortState.direction === 'desc') return 'Desc';
    return 'None';
  }

  function exportResults(format: 'csv' | 'json'): void {
    if (!$scanResponse) return;
    const filename = `aflux-${new Date().toISOString().slice(0, 19).replaceAll(':', '')}.${format}`;
    const content =
      format === 'json'
        ? JSON.stringify($scanResponse, null, 2)
        : toCsv($scanResponse.results);
    const blob = new Blob([content, '\n'], {
      type: format === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8'
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  function toCsv(results: ScanResult[]): string {
    const headers = [
      'code',
      'name',
      'price',
      'price_change_pct',
      'volume_ratio_pct',
      'turnover',
      'prev_turnover',
      'board'
    ];
    const rows = results.map((item) =>
      headers
        .map((field) => csvCell(String(item[field as keyof ScanResult] ?? '')))
        .join(',')
    );
    return [headers.join(','), ...rows].join('\n');
  }

  function csvCell(value: string): string {
    return /[",\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
  }

  function handleTouchStart(event: TouchEvent): void {
    if (window.scrollY === 0) touchStartY = event.touches[0]?.clientY ?? 0;
  }

  function handleTouchMove(event: TouchEvent): void {
    if (!touchStartY || window.scrollY > 0) return;
    pullDistance = Math.max(0, (event.touches[0]?.clientY ?? 0) - touchStartY);
  }

  function handleTouchEnd(): void {
    if (pullDistance > 80) void performScan();
    touchStartY = 0;
    pullDistance = 0;
  }
</script>

<main
  class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8"
  on:touchstart={handleTouchStart}
  on:touchmove={handleTouchMove}
  on:touchend={handleTouchEnd}
>
  {#if pullDistance > 0}
    <div class="fixed left-1/2 top-20 z-40 -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-sm text-white shadow-lg dark:bg-white dark:text-slate-950">
      {pullDistance > 80 ? 'Release to scan' : 'Pull to refresh'}
    </div>
  {/if}

  <section class="mb-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
    <div>
      <p class="text-sm font-semibold uppercase tracking-[0.25em] text-red-600 dark:text-red-400">
        Dashboard
      </p>
      <h1 class="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">A-share scan</h1>
      <p class="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
        Configure abnormal turnover and momentum thresholds, then scan current market candidates.
      </p>
    </div>

    <div class="flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-semibold transition hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800 lg:hidden"
        on:click={() => (filtersOpen = !filtersOpen)}
      >
        {filtersOpen ? 'Hide filters' : 'Show filters'}
      </button>
      <button
        type="button"
        disabled={$loading || !$isOnline}
        class="rounded-2xl bg-red-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-slate-400"
        on:click={performScan}
      >
        {$loading ? 'Scanning...' : 'Scan'}
      </button>
    </div>
  </section>

  {#if $apiError}
    <div class="mb-4 flex flex-col gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-500/10 dark:text-red-300 sm:flex-row sm:items-center sm:justify-between">
      <span>
        {$apiError}
        {#if rateLimitCountdown > 0}
          Retrying in {rateLimitCountdown}s.
        {/if}
      </span>
      <button
        type="button"
        class="rounded-xl bg-red-600 px-3 py-1.5 font-semibold text-white"
        on:click={performScan}
      >
        Retry
      </button>
    </div>
  {/if}

  <div class="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
    <aside class:hidden={!filtersOpen} class="lg:block">
      <form
        class="space-y-5 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        on:submit|preventDefault={performScan}
      >
        <label class="block">
          <span class="mb-2 block text-sm font-medium">Volume ratio %</span>
          <input
            type="number"
            min="0"
            step="1"
            value={$scanParams.volume_ratio}
            class="w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950"
            on:input={(event) => setParam('volume_ratio', numberValue(event))}
          />
        </label>

        <label class="block">
          <span class="mb-2 block text-sm font-medium">Price change %</span>
          <input
            type="number"
            step="0.1"
            value={$scanParams.price_change}
            class="w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950"
            on:input={(event) => setParam('price_change', numberValue(event))}
          />
        </label>

        <fieldset>
          <legend class="mb-2 text-sm font-medium">Boards</legend>
          <div class="grid grid-cols-2 gap-2">
            {#each boards as board}
              <label
                class="flex items-center gap-2 rounded-2xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-800"
              >
                <input
                  type="checkbox"
                  checked={$scanParams.boards.includes(board.id)}
                  on:change={(event) => toggleBoard(board.id, checkedValue(event))}
                />
                <span>{board.label}</span>
              </label>
            {/each}
          </div>
        </fieldset>

        <label class="flex items-center justify-between gap-3 rounded-2xl bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
          <span>Include ST stocks</span>
          <input
            type="checkbox"
            checked={$scanParams.include_st}
            on:change={(event) => setParam('include_st', checkedValue(event))}
          />
        </label>

        <label class="flex items-center justify-between gap-3 rounded-2xl bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
          <span>Bypass cache</span>
          <input
            type="checkbox"
            checked={$scanParams.no_cache}
            on:change={(event) => setParam('no_cache', checkedValue(event))}
          />
        </label>

        <div class="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
          <label class="flex items-center justify-between gap-3 text-sm">
            <span>Auto refresh</span>
            <input
              type="checkbox"
              disabled={!canAutoRefresh}
              checked={$autoRefreshEnabled}
              on:change={(event) => autoRefreshEnabled.set(checkedValue(event))}
            />
          </label>
          <select
            value={$refreshIntervalSeconds}
            class="w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            on:change={(event) => refreshIntervalSeconds.set(Number(selectValue(event)))}
          >
            <option value="15">Every 15s</option>
            <option value="30">Every 30s</option>
            <option value="60">Every 60s</option>
            <option value="120">Every 120s</option>
          </select>
          {#if $autoRefreshEnabled && canAutoRefresh}
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Next refresh in {refreshCountdown}s
            </p>
          {:else if currentPhase === 'off_market'}
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Auto-refresh is paused off market.
            </p>
          {/if}
        </div>
      </form>
    </aside>

    <section class="space-y-4">
      <div
        class="grid gap-3 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:grid-cols-4"
      >
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Phase</p>
          <span class={`mt-1 inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${phaseClass(currentPhase)}`}>
            {phaseLabel(currentPhase)}
          </span>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Results</p>
          <p class="mt-1 text-2xl font-bold">{$scanResponse?.count ?? 0}</p>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Updated</p>
          {#if $lastUpdatedAt}
            <p class={`mt-1 text-sm font-semibold ${staleClass($lastUpdatedAt, now)}`}>
              {relativeAge($lastUpdatedAt, now)}
            </p>
          {:else}
            <p class="mt-1 text-sm text-slate-500">Not scanned</p>
          {/if}
        </div>
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Market clock</p>
          <p class="mt-1 text-sm font-semibold">{marketCountdown(now)}</p>
        </div>
      </div>

      {#if $scanResponse}
        <div class="flex flex-col gap-3 rounded-3xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
          <div class="text-sm text-slate-600 dark:text-slate-400">
            Scan time: {scanTimeLabel($scanResponse.scan_time)}
          </div>
          <div class="flex flex-wrap gap-2">
            <select
              class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 md:hidden"
              value={$sortState.key}
              on:change={(event) => cycleSort(sortKeyValue(event))}
            >
              {#each sortOptions as option}
                <option value={option.key}>{option.label}</option>
              {/each}
            </select>
            <button
              class="rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 md:hidden"
              on:click={() => cycleSort($sortState.key)}
            >
              Sort: {sortDirectionLabel()}
            </button>
            <button class="rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700" on:click={() => exportResults('csv')}>
              Export CSV
            </button>
            <button class="rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700" on:click={() => exportResults('json')}>
              Export JSON
            </button>
          </div>
        </div>
      {/if}

      <div
        class="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        {#if $loading}
          <div class="space-y-3 p-4">
            {#each Array(6) as _}
              <div class="h-14 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800"></div>
            {/each}
          </div>
        {:else if !sortedResults.length}
          <div class="p-10 text-center">
            <p class="text-lg font-semibold">No scan results yet</p>
            <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
              Adjust filters and press Scan to fetch market data.
            </p>
          </div>
        {:else}
          <div class="hidden overflow-x-auto md:block">
            <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead class="bg-slate-100 dark:bg-slate-950">
                <tr>
                  {#each tableColumns as option}
                    <th class={`px-4 py-3 font-semibold ${option.align === 'right' ? 'text-right' : 'text-left'}`}>
                      <button class="inline-flex items-center gap-1" on:click={() => cycleSort(option.key)}>
                        {option.label}
                        {#if $sortState.key === option.key && $sortState.direction !== 'none'}
                          <span>{$sortState.direction === 'asc' ? '↑' : '↓'}</span>
                        {/if}
                      </button>
                    </th>
                  {/each}
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                {#each sortedResults as item}
                  <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/60">
                    <td class="px-4 py-3 font-mono text-cyan-700 dark:text-cyan-300">{item.code}</td>
                    <td class="px-4 py-3 font-medium">{item.name}</td>
                    <td class="px-4 py-3 text-right">{formatPrice(item.price)}</td>
                    <td class={`px-4 py-3 text-right font-semibold ${cnMarketClass(item.price_change_pct)}`}>
                      {formatPercent(item.price_change_pct)}
                    </td>
                    <td class={`px-4 py-3 text-right font-semibold ${cnMarketClass(item.volume_ratio_pct)}`}>
                      {formatPercent(item.volume_ratio_pct)}
                    </td>
                    <td class="px-4 py-3 text-right">{formatTurnover(item.turnover)}</td>
                    <td class="px-4 py-3 text-right">{formatTurnover(item.prev_turnover)}</td>
                    <td class="px-4 py-3 uppercase">{item.board ?? '-'}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>

          <div class="divide-y divide-slate-200 dark:divide-slate-800 md:hidden">
            {#each sortedResults as item}
              <article class="space-y-3 p-4">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <p class="font-mono text-sm text-cyan-700 dark:text-cyan-300">{item.code}</p>
                    <h2 class="text-lg font-semibold">{item.name}</h2>
                  </div>
                  <span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs uppercase dark:bg-slate-800">
                    {item.board ?? '-'}
                  </span>
                </div>
                <div class="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p class="text-slate-500">Price</p>
                    <p class="font-semibold">{formatPrice(item.price)}</p>
                  </div>
                  <div>
                    <p class="text-slate-500">Change</p>
                    <p class={`font-semibold ${cnMarketClass(item.price_change_pct)}`}>
                      {formatPercent(item.price_change_pct)}
                    </p>
                  </div>
                  <div>
                    <p class="text-slate-500">Volume ratio</p>
                    <p class={`font-semibold ${cnMarketClass(item.volume_ratio_pct)}`}>
                      {formatPercent(item.volume_ratio_pct)}
                    </p>
                  </div>
                  <div>
                    <p class="text-slate-500">Turnover</p>
                    <p class="font-semibold">{formatTurnover(item.turnover)}</p>
                  </div>
                </div>
              </article>
            {/each}
          </div>
        {/if}
      </div>
    </section>
  </div>
</main>
