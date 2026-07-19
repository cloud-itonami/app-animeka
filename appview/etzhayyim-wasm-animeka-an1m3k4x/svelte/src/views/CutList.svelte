<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, blobBg, flatProps } from '../xrpc';
  import { thumbSVG, svgDataUri } from '../lib/procart';

  let { go }: { go: (path: string) => void } = $props();

  type Cut = {
    rkey?: string;
    cut_num?: string | number;
    duration_frames?: string | number;
    fps?: string | number;
    priority?: string;
    dialogue_summary?: string;
    stage_status?: string;
    episode_id?: string;
    scene_id?: string;
    thumb_cid?: string;
  };
  let cuts: Cut[] = $state([]);
  let loading = $state(true);
  let total = $state(0);

  function progressPct(stageStatusJson?: string): number {
    if (!stageStatusJson) return 0;
    try {
      const s = JSON.parse(stageStatusJson) as Record<string, string>;
      const keys = Object.keys(s);
      if (keys.length === 0) return 0;
      const done = keys.filter((k) => s[k] === 'approved' || s[k] === 'done').length;
      return Math.round((done / 12) * 100);
    } catch {
      return 0;
    }
  }

  async function load() {
    loading = true;
    try {
      const resp = await atQuery<{ items: Cut[]; total?: number }>(
        'com.etzhayyim.animeka.listCuts',
        { limit: 200 },
      );
      cuts = resp.items ?? [];
      total = resp.total ?? cuts.length;
    } catch {
      cuts = [];
      total = 0;
    }
    loading = false;
  }

  onMount(load);
</script>

<section class="page">
  <header>
    <h1>Cuts <span class="muted">· {total} total</span></h1>
    <p class="muted">All cuts across every episode. Click a cut to open the storyboard / animation / color editor.</p>
  </header>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if cuts.length === 0}
    <div class="empty">
      <p>No cuts yet.</p>
      <p class="muted">Create a work, add an episode, then break the script into scenes and cuts to populate this view.</p>
    </div>
  {:else}
    <div class="grid">
      {#each cuts as c}
        {@const pct = progressPct(c.stage_status)}
        {@const get = flatProps(c as unknown as Record<string, unknown>)}
        {@const thumb = get('thumb_cid') as string | undefined}
        {@const dialogue = get('dialogue_summary', 'dialogueSummary') as string | undefined}
        {@const cutNum = get('cut_num', 'cutNum')}
        {@const sceneNum = get('scene_num', 'sceneNum')}
        <button class="card" class:retake={c.priority === 'retake'} onclick={() => c.rkey && go(`/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.cut/${c.rkey}`)}>
          {#if thumb}
            <div class="thumb" style:background={blobBg(thumb)}></div>
          {:else}
            <div class="thumb" style:background={svgDataUri(thumbSVG(String(c.rkey ?? cutNum ?? 'cut')))}>
              <span class="cut-badge">#{cutNum ?? '?'}</span>
            </div>
          {/if}
          <div class="meta">
            <strong>#{cutNum ?? '?'}{sceneNum ? ` · S${sceneNum}` : ''}</strong>
            <span class="muted">{c.duration_frames ?? 0}f / {c.fps ?? 24}fps</span>
          </div>
          {#if dialogue}
            <p class="dialogue">{dialogue}</p>
          {/if}
          <div class="bar"><div class="fill" style:width={`${pct}%`}></div></div>
          <div class="row">
            <span class="muted xs">{pct}% complete</span>
            {#if c.priority === 'retake'}<span class="badge retake-badge">retake</span>{/if}
          </div>
        </button>
      {/each}
    </div>
  {/if}
</section>

<style>
  .page { padding: 24px; max-width: 1400px; }
  header { margin-bottom: 16px; }
  h1 { margin: 0 0 4px; font-size: 22px; font-weight: 600; }
  .muted { color: #6a6e7a; font-weight: 400; font-size: 12px; }
  .empty { padding: 40px; background: #15181f; border: 1px dashed #22252d; border-radius: 8px; text-align: center; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
  .card {
    background: #151823; border: 1px solid #22252d; border-radius: 8px;
    padding: 0; cursor: pointer; text-align: left; color: inherit; font: inherit;
    overflow: hidden; transition: border-color 0.1s;
  }
  .card:hover { border-color: #5ab0ff; }
  .card.retake { border-left: 3px solid #ff5a5a; }
  .thumb {
    aspect-ratio: 16/9; background-size: cover; background-position: center;
    display: flex; align-items: center; justify-content: center;
  }

  .cut-badge {
    position: absolute; left: 6px; top: 6px;
    background: rgba(0,0,0,0.55); color: #fff;
    padding: 2px 6px; border-radius: 3px;
    font-family: ui-monospace, monospace; font-size: 10px;
    backdrop-filter: blur(2px);
  }
  .thumb { position: relative; }
  .meta { display: flex; justify-content: space-between; align-items: baseline; padding: 8px 12px 4px; }
  .meta strong { font-size: 14px; }
  .dialogue {
    margin: 0; padding: 0 12px; font-size: 12px; color: #c0c4d0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .bar { height: 4px; background: #22252d; margin: 8px 12px 4px; border-radius: 2px; overflow: hidden; }
  .fill { height: 100%; background: linear-gradient(90deg, #5ab0ff, #3dc14a); }
  .row { display: flex; justify-content: space-between; align-items: center; padding: 0 12px 10px; }
  .xs { font-size: 10px; }
  .badge.retake-badge { background: #5d1f1f; color: #ff8a8a; padding: 2px 6px; border-radius: 3px; font-size: 10px; text-transform: uppercase; }
</style>
