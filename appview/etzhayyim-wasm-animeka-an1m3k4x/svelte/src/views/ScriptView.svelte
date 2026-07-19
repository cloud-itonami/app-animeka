<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, blobBg, flatProps } from '../xrpc';
  import { thumbSVG, svgDataUri } from '../lib/procart';

  let { episodeId }: { episodeId?: string } = $props();

  type Cut = {
    rkey?: string;
    cut_num?: string | number;
    duration_frames?: string | number;
    fps?: string | number;
    dialogue_summary?: string;
    scene_id?: string;
    scene_num?: string | number;
    episode_id?: string;
    thumb_cid?: string;
  };
  let cuts: Cut[] = $state([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const params: Record<string, unknown> = { limit: 500 };
      if (episodeId && episodeId !== 'latest') params.episodeId = episodeId;
      const resp = await atQuery<{ items: Cut[] }>('com.etzhayyim.animeka.listCuts', params);
      cuts = resp.items ?? [];
    } catch {
      cuts = [];
    }
    loading = false;
  }

  type Scene = { sceneKey: string; sceneNum: string | number | null; cuts: Cut[] };
  let scenes = $derived.by((): Scene[] => {
    const map = new Map<string, Scene>();
    for (const c of cuts) {
      const get = flatProps(c as unknown as Record<string, unknown>);
      const sceneId = (get('scene_id', 'sceneId') as string | undefined) ?? '';
      const sceneNum = get('scene_num', 'sceneNum') as string | number | null | undefined;
      const key = String(sceneId || sceneNum || '_unsorted');
      const existing = map.get(key);
      if (existing) {
        existing.cuts.push(c);
      } else {
        map.set(key, { sceneKey: key, sceneNum: sceneNum ?? null, cuts: [c] });
      }
    }
    return Array.from(map.values()).sort((a, b) => {
      const an = Number(a.sceneNum ?? Number.MAX_SAFE_INTEGER);
      const bn = Number(b.sceneNum ?? Number.MAX_SAFE_INTEGER);
      return an - bn;
    });
  });

  onMount(load);
</script>

<section class="page">
  <header>
    <h1>Script <span class="muted">· {episodeId ?? 'latest'}</span></h1>
    <p class="muted">Scene → cut tree, derived from <code>listCuts</code> (grouped by scene_id). Drag-to-cut planned.</p>
  </header>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if cuts.length === 0}
    <div class="empty">
      <p>No cuts on this episode.</p>
      <p class="muted">Open the Pipeline board and add cuts, or run <code>generateScript</code> on a cut to start the auto-breakdown.</p>
    </div>
  {:else}
    <div class="split">
      <div class="script">
        <table>
          <thead><tr><th>Scene</th><th>Cut</th><th>Duration</th><th>Dialogue / Action</th></tr></thead>
          <tbody>
            {#each scenes as s}
              {#each s.cuts as c, idx}
                {@const cg = flatProps(c as unknown as Record<string, unknown>)}
                {@const cutNum = cg('cut_num', 'cutNum')}
                {@const dialogue = (cg('dialogue_summary', 'dialogueSummary') as string | undefined) ?? '—'}
                <tr class:scene-start={idx === 0}>
                  {#if idx === 0}
                    <td class="mono" rowspan={s.cuts.length}>S#{s.sceneNum ?? '—'}</td>
                  {/if}
                  <td class="mono">#{cutNum ?? '?'}</td>
                  <td>{c.duration_frames ?? 0}f / {c.fps ?? 24}fps</td>
                  <td class="dialogue">{dialogue}</td>
                </tr>
              {/each}
            {/each}
          </tbody>
        </table>
      </div>
      <div class="board">
        {#each scenes as s}
          <div class="scene">
            <h3>S#{s.sceneNum ?? '—'} <span class="muted">({s.cuts.length} cuts)</span></h3>
            <div class="thumbs">
              {#each s.cuts as c}
                {@const cg = flatProps(c as unknown as Record<string, unknown>)}
                {@const cn = cg('cut_num', 'cutNum')}
                {@const tCid = cg('thumb_cid') as string | undefined}
                <div class="panel">
                  {#if tCid}
                    <div class="thumb" style:background={blobBg(tCid)}></div>
                  {:else}
                    <div class="thumb" style:background={svgDataUri(thumbSVG(String(c.rkey ?? cn ?? 'cut')))}>
                      <span class="cn">#{cn ?? '?'}</span>
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</section>

<style>
  .page { padding: 20px; max-width: 1400px; }
  header h1 { margin: 0 0 4px; font-size: 18px; }
  .muted { color: #6a6e7a; font-weight: 400; font-size: 12px; }
  code { background: #0c0e14; padding: 1px 4px; border-radius: 2px; font-size: 11px; }
  .empty { padding: 32px; background: #15181f; border: 1px dashed #22252d; border-radius: 8px; text-align: center; }
  .split { display: grid; grid-template-columns: 1fr 380px; gap: 16px; }
  .script, .board { background: #15181f; border: 1px solid #22252d; border-radius: 6px; padding: 12px; }
  .board { overflow: auto; max-height: calc(100vh - 160px); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 6px; color: #a0a4b0; border-bottom: 1px solid #22252d; font-weight: 500; }
  td { padding: 8px 6px; border-bottom: 1px solid #1a1d26; vertical-align: top; }
  td.mono { font-family: ui-monospace, monospace; color: #5ab0ff; }
  td.dialogue { color: #e0cc7d; }
  tr.scene-start td { border-top: 1px solid #2a2e3a; }
  .scene { margin-bottom: 18px; }
  .scene h3 { font-size: 12px; text-transform: uppercase; color: #a0a4b0; margin: 0 0 6px; }
  .thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 6px; }
  .panel .thumb {
    aspect-ratio: 16/9; background: #1d2430; border-radius: 4px;
    position: relative; background-size: cover; background-position: center;
  }
  .panel .thumb .cn {
    position: absolute; left: 4px; top: 4px;
    background: rgba(0,0,0,0.55); color: #fff;
    padding: 1px 5px; border-radius: 2px;
    font-family: ui-monospace, monospace; font-size: 10px;
  }
</style>
