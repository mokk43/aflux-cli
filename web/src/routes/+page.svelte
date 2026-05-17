<script lang="ts">
  import { goto } from '$app/navigation';
  import { AfluxApiError, login } from '$lib/api';
  import { setAuthToken } from '$lib/stores';

  let code = '';
  let error = '';
  let loading = false;

  async function submit(): Promise<void> {
    error = '';
    loading = true;
    try {
      const response = await login(code.trim());
      setAuthToken(response.token);
      await goto('/scan');
    } catch (exc) {
      error = exc instanceof AfluxApiError ? exc.message : 'Login failed.';
    } finally {
      loading = false;
    }
  }
</script>

<main class="flex min-h-[calc(100vh-66px)] items-center justify-center px-4 py-12">
  <section
    class="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-8 shadow-xl shadow-slate-200/60 dark:border-slate-800 dark:bg-slate-900 dark:shadow-black/30"
  >
    <div class="mb-8">
      <p class="text-sm font-semibold uppercase tracking-[0.3em] text-red-600 dark:text-red-400">
        Secure access
      </p>
      <h1 class="mt-3 text-3xl font-bold tracking-tight">Enter aflux access code</h1>
      <p class="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-400">
        Use the passcode configured in <code>AFLUX_ACCESS_CODE</code> to open the scanner.
      </p>
    </div>

    <form class="space-y-5" on:submit|preventDefault={submit}>
      <label class="block">
        <span class="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
          Access code
        </span>
        <input
          bind:value={code}
          type="password"
          autocomplete="current-password"
          class="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-base outline-none transition focus:border-red-500 focus:ring-4 focus:ring-red-500/10 dark:border-slate-700 dark:bg-slate-950"
          placeholder="Enter code"
        />
      </label>

      {#if error}
        <div class="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      {/if}

      <button
        type="submit"
        disabled={loading || !code.trim()}
        class="w-full rounded-2xl bg-red-600 px-4 py-3 font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-slate-400"
      >
        {loading ? 'Validating...' : 'Continue'}
      </button>
    </form>
  </section>
</main>
