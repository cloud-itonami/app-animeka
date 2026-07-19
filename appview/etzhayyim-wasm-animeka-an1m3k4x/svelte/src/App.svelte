<script lang="ts">
  import { onMount } from 'svelte';
  import Dashboard from './views/Dashboard.svelte';
  import PipelineBoard from './views/PipelineBoard.svelte';
  import CutDetail from './views/CutDetail.svelte';
  import CutList from './views/CutList.svelte';
  import Gallery from './views/Gallery.svelte';
  import ScriptView from './views/ScriptView.svelte';
  import ReviewRoom from './views/ReviewRoom.svelte';

  type View = 'dashboard' | 'pipeline' | 'cut' | 'cuts' | 'gallery' | 'script' | 'review';
  let view: View = $state('dashboard');
  let context: Record<string, string> = $state({});

  function parsePath() {
    const { pathname } = window.location;
    // /at/{authority}/com.etzhayyim.animeka.cut/{rkey} → cut detail
    const atMatch = pathname.match(/^\/at\/([^/]+)\/com\.etzhayyim\.apps\.animeka\.([^/]+)\/([^/]+)$/);
    if (atMatch) {
      const [, authority, collection, rkey] = atMatch;
      if (collection === 'cut') {
        view = 'cut';
        context = { authority, rkey };
        return;
      }
    }
    if (pathname.startsWith('/episodes/') && pathname.endsWith('/script')) {
      view = 'script';
      context = { episodeId: pathname.split('/')[2] };
      return;
    }
    if (pathname.startsWith('/episodes/') && pathname.endsWith('/review')) {
      view = 'review';
      context = { episodeId: pathname.split('/')[2] };
      return;
    }
    if (pathname.startsWith('/episodes/')) {
      view = 'pipeline';
      context = { episodeId: pathname.split('/')[2] };
      return;
    }
    if (pathname === '/cuts' || pathname.startsWith('/cuts/')) {
      view = 'cuts';
      context = {};
      return;
    }
    if (pathname === '/gallery' || pathname.startsWith('/gallery/')) {
      view = 'gallery';
      context = {};
      return;
    }
    if (pathname === '/script' || pathname.startsWith('/script/')) {
      view = 'script';
      context = { episodeId: 'latest' };
      return;
    }
    if (pathname === '/review' || pathname.startsWith('/review/')) {
      view = 'review';
      context = { episodeId: 'latest' };
      return;
    }
    if (pathname.startsWith('/works/')) {
      view = 'dashboard';
      context = { workId: pathname.split('/')[2] };
      return;
    }
    view = 'dashboard';
    context = {};
  }

  function go(path: string) {
    window.history.pushState({}, '', path);
    parsePath();
  }

  onMount(() => {
    parsePath();
    window.addEventListener('popstate', parsePath);
  });
</script>

<svelte:head>
  <title>Animeka — Team-based Anime Creation</title>
  <meta name="description" content="Animeka — KAMI Engine X-sheet timeline for the 12-stage anime production pipeline." />
</svelte:head>

<div class="shell">
  <aside class="rail">
    <button class="brand" onclick={() => go('/')}>🎬 Animeka</button>
    <nav>
      <button class:active={view === 'dashboard'} onclick={() => go('/')}>📚 Works</button>
      <button class:active={view === 'pipeline'} onclick={() => go('/episodes/latest')}>▦ Pipeline</button>
      <button class:active={view === 'cut' || view === 'cuts'} onclick={() => go('/cuts')}>✂ Cuts</button>
      <button class:active={view === 'gallery'} onclick={() => go('/gallery')}>🖼 Gallery</button>
      <button class:active={view === 'script'} onclick={() => go('/episodes/latest/script')}>📝 Script</button>
      <button class:active={view === 'review'} onclick={() => go('/episodes/latest/review')}>⏳ Reviews</button>
    </nav>
    <div class="spacer"></div>
    <div class="foot">did:web:animeka.etzhayyim.com</div>
  </aside>
  <main>
    {#if view === 'dashboard'}
      <Dashboard workId={context.workId} {go} />
    {:else if view === 'pipeline'}
      <PipelineBoard episodeId={context.episodeId} {go} />
    {:else if view === 'cut'}
      <CutDetail authority={context.authority} rkey={context.rkey} />
    {:else if view === 'cuts'}
      <CutList {go} />
    {:else if view === 'gallery'}
      <Gallery />
    {:else if view === 'script'}
      <ScriptView episodeId={context.episodeId} />
    {:else if view === 'review'}
      <ReviewRoom episodeId={context.episodeId} />
    {/if}
  </main>
</div>

<style>
  :global(html, body, #app) {
    margin: 0;
    width: 100%;
    height: 100%;
    background: #0c0e14;
    color: #e6e8ee;
    font: 14px/1.4 -apple-system, 'Hiragino Sans', system-ui, sans-serif;
  }
  .shell {
    display: grid;
    grid-template-columns: 220px 1fr;
    height: 100vh;
  }
  .rail {
    background: #111318;
    border-right: 1px solid #22252d;
    display: flex;
    flex-direction: column;
    padding: 12px 0;
  }
  .brand {
    font-size: 16px;
    font-weight: 600;
    background: none;
    border: 0;
    color: #e6e8ee;
    text-align: left;
    padding: 8px 16px;
    cursor: pointer;
  }
  nav {
    display: flex;
    flex-direction: column;
    margin-top: 12px;
  }
  nav button {
    background: none;
    border: 0;
    color: #a0a4b0;
    text-align: left;
    padding: 10px 16px;
    cursor: pointer;
    font-size: 14px;
  }
  nav button:hover { color: #fff; background: #1a1d26; }
  nav button.active { color: #fff; background: #1d2430; border-left: 3px solid #5ab0ff; padding-left: 13px; }
  .spacer { flex: 1; }
  .foot { padding: 12px 16px; font-size: 11px; color: #555866; border-top: 1px solid #22252d; }
  main { overflow: auto; }
</style>
