<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, blobUrl } from '../xrpc';

  type Cut = {
    rkey: string;
    sceneText: string;
    sbCid: string;
    lyCid: string;
    kfCid: string;
    bgCid: string;
    createdAt: string;
  };

  let cuts: Cut[] = $state([]);
  let loading = $state(true);
  let selected: Cut | null = $state(null);
  let mode: 'cuts' | 'tensor' = $state('cuts');

  type RawCut = {
    rkey?: string;
    camera_note?: string;
    dialogueSummary?: string;
    thumbCid?: string;
    flat_cid?: string;
    imageCid?: string;
    bg_cid?: string;
    createdAt?: string;
  };

  async function load() {
    loading = true;
    try {
      const resp = await atQuery<{ items?: RawCut[] }>(
        'com.etzhayyim.animeka.listCuts',
        { limit: 200 }
      );
      cuts = (resp.items ?? [])
        .filter((c) => c.thumbCid)
        .map((c) => ({
          rkey: c.rkey ?? '',
          sceneText: c.camera_note ?? c.dialogueSummary ?? '',
          sbCid: c.thumbCid ?? '',
          lyCid: c.flat_cid ?? '',
          kfCid: c.imageCid ?? '',
          bgCid: c.bg_cid ?? '',
          createdAt: c.createdAt ?? '',
        }))
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    } catch {
      cuts = [];
    }
    loading = false;
  }

  function fmt(iso: string) {
    if (!iso) return '';
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  }

  onMount(load);
</script>

<section class="page">
  <header>
    <h1>Generated Cuts</h1>
    <span class="count">{cuts.length} cuts</span>
    <div class="tabs">
      <button class:active={mode === 'cuts'} onclick={() => mode = 'cuts'}>🖼 Cuts</button>
      <button class:active={mode === 'tensor'} onclick={() => mode = 'tensor'} title="v9 USD cut tensor network — ADR-2605222000">⌬ Tensor Network</button>
    </div>
    <button onclick={load}>↻ Refresh</button>
  </header>

  {#if mode === 'tensor'}
    <div class="tensor-wrap">
      <iframe
        src="/tensor-pipeline.html"
        title="animeka v9 USD cut tensor pipeline"
        loading="lazy"
      ></iframe>
      <p class="muted tensor-note">
        animeka v9 — USD scene → camera keyframe (TU/PAN/TB/TILT/ZOOM) →
        ControlNet × 3 → keyframe render → inbetween interpolation →
        composite cut. 16-node AnimekaUSDScene pack
        (<a href="https://github.com/etzhayyimcojp/etzhayyim-apps-etzhayyimcojp/blob/main/90-docs/adr/2605222000-animeka-usd-cinematic-pipeline.md" target="_blank" rel="noopener">ADR-2605222000</a>).
      </p>
    </div>
  {:else if loading}
    <p class="muted">Loading…</p>
  {:else if cuts.length === 0}
    <p class="muted">No generated cuts yet. The autopilot runs every 15 min.</p>
  {:else}
    <div class="grid">
      {#each cuts as c}
        <article class="card" onclick={() => selected = selected?.rkey === c.rkey ? null : c}>
          <div class="thumb" style:background-image="url({blobUrl(c.sbCid)})"></div>
          <p class="scene">{c.sceneText || '—'}</p>
          <time>{fmt(c.createdAt)}</time>
        </article>
      {/each}
    </div>
  {/if}

  {#if selected}
    <aside class="lightbox" onclick={() => selected = null}>
      <div class="lb-inner" onclick={(e) => e.stopPropagation()}>
        <button class="close" onclick={() => selected = null}>✕</button>
        <p class="lb-scene">{selected.sceneText}</p>
        <div class="frames">
          {#each [
            { cid: selected.sbCid, label: 'Storyboard' },
            { cid: selected.lyCid, label: 'Layout' },
            { cid: selected.kfCid, label: 'Keyframe' },
            { cid: selected.bgCid, label: 'Background' },
          ] as f}
            {#if f.cid}
              <figure>
                <img src={blobUrl(f.cid)} alt={f.label} loading="lazy" />
                <figcaption>{f.label}</figcaption>
              </figure>
            {/if}
          {/each}
        </div>
        <p class="lb-time">{selected.rkey} · {fmt(selected.createdAt)}</p>
      </div>
    </aside>
  {/if}
</section>

<style>
  .page { padding: 24px; max-width: 1400px; }
  header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
  h1 { margin: 0; font-size: 22px; font-weight: 600; }
  .count { color: #6a6e7a; font-size: 13px; }
  button { background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 13px; }
  button:hover { border-color: #5ab0ff; }
  .tabs { display: flex; gap: 6px; margin-left: 8px; }
  .tabs button.active { border-color: #5ab0ff; color: #fff; background: #1d2430; }

  .tensor-wrap { display: flex; flex-direction: column; gap: 8px; }
  .tensor-wrap iframe {
    width: 100%; height: calc(100vh - 200px); min-height: 540px;
    border: 1px solid #22252d; border-radius: 8px; background: #14161b;
  }
  .tensor-note { font-size: 11px; line-height: 1.5; margin: 0; }
  .tensor-note a { color: #5ab0ff; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .card { background: #151823; border: 1px solid #22252d; border-radius: 8px; overflow: hidden; cursor: pointer; }
  .card:hover { border-color: #5ab0ff; }
  .thumb {
    aspect-ratio: 1;
    background: #0c0e14 center/cover no-repeat;
  }
  .scene { margin: 8px 10px 4px; font-size: 12px; color: #c8cad4; line-height: 1.4;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  time { display: block; padding: 0 10px 10px; font-size: 11px; color: #6a6e7a; }

  .lightbox {
    position: fixed; inset: 0; background: rgba(0,0,0,.75); z-index: 100;
    display: flex; align-items: center; justify-content: center;
  }
  .lb-inner {
    background: #151823; border: 1px solid #2a2e3a; border-radius: 12px;
    padding: 24px; max-width: 900px; width: 95vw; position: relative;
    max-height: 90vh; overflow-y: auto;
  }
  .close {
    position: absolute; top: 12px; right: 12px; background: none;
    border: none; color: #a0a4b0; font-size: 18px; cursor: pointer; padding: 4px 8px;
  }
  .lb-scene { font-size: 14px; color: #e6e8ee; margin: 0 0 16px; line-height: 1.6; }
  .frames { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  figure { margin: 0; }
  figure img { width: 100%; border-radius: 6px; display: block; background: #0c0e14; }
  figcaption { text-align: center; font-size: 11px; color: #6a6e7a; margin-top: 4px; }
  .lb-time { margin: 12px 0 0; font-size: 11px; color: #555866; font-family: monospace; }
  .muted { color: #6a6e7a; }
</style>
