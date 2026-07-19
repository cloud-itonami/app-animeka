<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, atProcedure, blobUrl, flatProps } from '../xrpc';
  import { STAGES } from '../actors';
  import type { StageKey } from '../actors';

  let { authority, rkey }: { authority?: string; rkey?: string } = $props();

  // ── Cut data ────────────────────────────────────────────────────────────────
  type CutRow = Record<string, unknown>;
  let cut: CutRow | null = $state(null);
  let retakes: Record<string, unknown>[] = $state([]);
  let loading = $state(true);
  let tab: 'storyboard' | 'animation' | 'comp' = $state('storyboard');

  // ── Derived image CIDs from the cut row ─────────────────────────────────────
  const thumbCid  = $derived(cut ? String(cut.thumb_cid  ?? cut.thumbCid  ?? '') : '');
  const flatCid   = $derived(cut ? String(cut.flat_cid   ?? cut.flatCid   ?? '') : '');
  const imageCid  = $derived(cut ? String(cut.image_cid  ?? cut.imageCid  ?? '') : '');
  const bgCid     = $derived(cut ? String(cut.bg_cid     ?? cut.bgCid     ?? '') : '');
  const outputCid = $derived(cut ? String(cut.output_cid ?? cut.outputCid ?? '') : '');

  const stageStatus = $derived((): Partial<Record<StageKey, string>> => {
    if (!cut?.stage_status) return {};
    try { return JSON.parse(String(cut.stage_status)); } catch { return {}; }
  });

  const sceneText = $derived(() => {
    if (!cut) return '';
    const get = flatProps(cut);
    return String(get('camera_note', 'cameraNote') ?? get('dialogue_summary', 'dialogueSummary') ?? '');
  });

  const createdAt = $derived(() => {
    if (!cut?.createdAt) return '';
    const d = new Date(String(cut.createdAt));
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  });

  // ── Retake form ─────────────────────────────────────────────────────────────
  let retakeComment = $state('');
  let retakeSeverity = $state('minor');
  let submittingRetake = $state(false);

  function tabStage(): string {
    if (tab === 'storyboard') return 'storyboard';
    if (tab === 'animation')  return 'keyAnim';
    return 'composite';
  }

  // ── Pipeline stage definitions (display only) ────────────────────────────────
  const PIPELINE = [
    { id: 'script',      label: '脚本',      stageKey: null       as StageKey | null },
    { id: 'storyboard',  label: '絵コンテ',  stageKey: 'storyboard' as StageKey     },
    { id: 'layout',      label: 'レイアウト', stageKey: 'layout'   as StageKey       },
    { id: 'keyAnim',     label: '原画',      stageKey: 'keyAnim'  as StageKey       },
    { id: 'inbetween',   label: '動画',      stageKey: 'inbetween' as StageKey      },
    { id: 'colorDesign', label: '色指定',    stageKey: 'colorDesign' as StageKey    },
    { id: 'finish',      label: '仕上げ',    stageKey: 'finish'   as StageKey       },
    { id: 'background',  label: '背景',      stageKey: 'background' as StageKey     },
    { id: 'composite',   label: '撮影',      stageKey: 'composite' as StageKey      },
    { id: 'edit',        label: '編集',      stageKey: 'edit'     as StageKey       },
    { id: 'sound',       label: '音響',      stageKey: 'sound'    as StageKey       },
    { id: 'delivery',    label: '納品',      stageKey: 'delivery' as StageKey       },
  ];

  // ── Load ─────────────────────────────────────────────────────────────────────
  async function load() {
    if (!rkey) return;
    loading = true;
    try {
      // Load all cuts and find this one by rkey
      const [cutsResp, retakesResp] = await Promise.all([
        atQuery<{ items: CutRow[] }>('com.etzhayyim.animeka.listCuts', { limit: 500 }),
        atQuery<{ items: Record<string, unknown>[] }>(
          'com.etzhayyim.animeka.listRetakes',
          { cut_id: rkey, limit: 50 }
        ),
      ]);
      cut = (cutsResp.items ?? []).find(c => c.rkey === rkey) ?? null;
      retakes = retakesResp.items ?? [];
    } catch (err) {
      console.error('CutDetail load', err);
      cut = null;
    }
    loading = false;
  }

  async function submitRetake() {
    if (!rkey || !retakeComment.trim()) return;
    submittingRetake = true;
    try {
      await atProcedure('com.etzhayyim.animeka.submitRetake', {
        target_uri: `at://anonymous/com.etzhayyim.animeka.cut/${rkey}`,
        cut_id: rkey,
        stage: tabStage(),
        severity: retakeSeverity,
        comment: retakeComment.trim(),
        timecode_frame: 0,
      });
      retakeComment = '';
      await load();
    } catch (err) { console.error('submitRetake', err); }
    submittingRetake = false;
  }

  async function resolveRetake(r: Record<string, unknown>) {
    if (!r.rkey) return;
    await atProcedure('com.etzhayyim.animeka.resolveRetake', { retakeId: r.rkey, status: 'resolved' });
    await load();
  }

  onMount(load);
</script>

<section class="page">
  <!-- ── Header ── -->
  <header>
    <div class="title-block">
      <h1>Cut <code>{rkey}</code></h1>
      <span class="meta muted">{authority ?? 'an1m3k4x.etzhayyim.com'} · {createdAt()}</span>
    </div>
    <nav class="tabs">
      <button class:active={tab === 'storyboard'} onclick={() => tab = 'storyboard'}>
        Storyboard + Layout
      </button>
      <button class:active={tab === 'animation'} onclick={() => tab = 'animation'}>
        Animation
      </button>
      <button class:active={tab === 'comp'} onclick={() => tab = 'comp'}>
        Color & Comp
      </button>
    </nav>
    <button class="btn-sm" onclick={load}>↻</button>
  </header>

  <!-- ── 12-stage pipeline strip ── -->
  <div class="pipeline">
    {#each PIPELINE as p}
      {@const status = p.stageKey ? stageStatus()[p.stageKey] : undefined}
      <div
        class="pip-cell"
        class:approved={status === 'approved'}
        class:pending={!status}
        title="{p.label}: {status ?? 'pending'}"
      >
        <span class="pip-label">{p.label}</span>
        <span class="pip-icon">{status === 'approved' ? '✓' : '·'}</span>
      </div>
    {/each}
  </div>

  {#if loading}
    <p class="muted" style="padding:20px">Loading…</p>
  {:else if !cut}
    <p class="muted" style="padding:20px">Cut not found: {rkey}</p>
  {:else}
    <div class="split">

      <!-- ── Main canvas ── -->
      <div class="canvas">

        <!-- Tab: Storyboard + Layout -->
        {#if tab === 'storyboard'}
          <div class="two-pane">
            <div class="pane">
              <div class="pane-label">絵コンテ (Storyboard)</div>
              {#if thumbCid}
                <img class="pane-img" src={blobUrl(thumbCid)} alt="storyboard" />
              {:else}
                <div class="pane-empty">未生成</div>
              {/if}
            </div>
            <div class="pane">
              <div class="pane-label">レイアウト (Layout)</div>
              {#if flatCid}
                <img class="pane-img" src={blobUrl(flatCid)} alt="layout" />
              {:else}
                <div class="pane-empty">未生成</div>
              {/if}
            </div>
          </div>
          {#if sceneText()}
            <div class="scene-bar">
              <span class="scene-label">Scene</span>
              <p>{sceneText()}</p>
            </div>
          {/if}

        <!-- Tab: Animation -->
        {:else if tab === 'animation'}
          <div class="anim-view">
            <div class="kf-pane">
              <div class="pane-label">原画 (Keyframe)</div>
              {#if imageCid}
                <img class="pane-img kf-img" src={blobUrl(imageCid)} alt="keyframe" />
              {:else}
                <div class="pane-empty">未生成</div>
              {/if}
            </div>
            <!-- X-sheet / frame strip -->
            <div class="xsheet">
              <div class="xhead">
                <span>F</span><span>絵</span><span>BG</span><span>SE</span><span>Note</span>
              </div>
              {#each Array(12) as _, i}
                {@const isKey = i === 0 || i === 11}
                <div class="xrow" class:key={isKey}>
                  <span class="fn">{i + 1}</span>
                  <span>{isKey ? '◉' : '·'}</span>
                  <span>{i === 0 ? '◉' : ''}</span>
                  <span></span>
                  <span class="xnote">{i === 0 && sceneText() ? sceneText().slice(0, 30) : ''}</span>
                </div>
              {/each}
            </div>
          </div>

        <!-- Tab: Color & Comp -->
        {:else}
          <div class="comp-view">
            {#if bgCid}
              <div class="bg-pane">
                <div class="pane-label">背景 (Background)</div>
                <img class="pane-img" src={blobUrl(bgCid)} alt="background" />
              </div>
            {/if}
            <div class="video-pane">
              <div class="pane-label">撮影合成 (Composite MP4)</div>
              {#if outputCid}
                <!-- svelte-ignore a11y_media_has_caption -->
                <video
                  class="comp-video"
                  src={blobUrl(outputCid)}
                  controls
                  loop
                  playsinline
                ></video>
              {:else}
                <div class="pane-empty">compositor 未実行</div>
              {/if}
            </div>
          </div>
        {/if}

      </div>

      <!-- ── Side panel ── -->
      <aside class="side">

        <!-- Cut metadata -->
        <section class="side-section">
          <h3>Cut info</h3>
          <dl class="meta-dl">
            <dt>rkey</dt><dd><code>{rkey}</code></dd>
            <dt>stages</dt>
            <dd>
              {#each Object.entries(stageStatus()) as [k, v]}
                <span class="stage-tag approved">{k}</span>
              {/each}
              {#if Object.keys(stageStatus()).length === 0}
                <span class="muted">none</span>
              {/if}
            </dd>
            {#if cut.duration_frames}
              <dt>frames</dt><dd>{cut.duration_frames}f @ {cut.fps ?? 12}fps</dd>
            {/if}
          </dl>
        </section>

        <!-- Retake submission -->
        <section class="side-section">
          <h3>Submit retake <span class="muted">({tabStage()})</span></h3>
          <form onsubmit={(e) => { e.preventDefault(); submitRetake(); }}>
            <select bind:value={retakeSeverity}>
              <option value="nit">Nit</option>
              <option value="minor">Minor</option>
              <option value="major">Major</option>
              <option value="blocker">Blocker</option>
            </select>
            <textarea
              bind:value={retakeComment}
              placeholder="Describe the issue…"
              rows="3"
            ></textarea>
            <button type="submit" disabled={submittingRetake || !retakeComment.trim()}>
              {submittingRetake ? 'Submitting…' : 'Submit'}
            </button>
          </form>
        </section>

        <!-- Open retakes -->
        <section class="side-section">
          <h3>Open retakes ({retakes.filter(r => r.status === 'open').length})</h3>
          {#if retakes.length === 0}
            <p class="muted small">No retakes on this cut.</p>
          {:else}
            <ul class="retake-list">
              {#each retakes as r}
                <li class="rt sev-{String(r.severity ?? 'minor')}">
                  <div class="rt-h">
                    <strong>{String(r.stage ?? '')}</strong>
                    <span class="muted">{String(r.severity ?? '')}</span>
                    {#if r.status === 'open'}
                      <button class="resolve-btn" onclick={() => resolveRetake(r)}>✓</button>
                    {:else}
                      <span class="resolved-tag">resolved</span>
                    {/if}
                  </div>
                  <p>{String(r.comment ?? '')}</p>
                </li>
              {/each}
            </ul>
          {/if}
        </section>

      </aside>
    </div>
  {/if}
</section>

<style>
  .page {
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
    padding: 14px 16px; box-sizing: border-box; gap: 8px;
  }

  /* Header */
  header { display: flex; align-items: center; gap: 12px; flex-shrink: 0; flex-wrap: wrap; }
  .title-block { display: flex; flex-direction: column; gap: 2px; }
  h1 { margin: 0; font-size: 16px; font-weight: 600; }
  h1 code { font-family: ui-monospace, monospace; font-size: 13px; color: #a0c8ff; }
  .meta { font-size: 11px; }
  .muted { color: #6a6e7a; }
  .tabs { display: flex; gap: 1px; margin-left: auto; }
  .tabs button {
    background: #15181f; border: 1px solid #22252d; color: #a0a4b0;
    padding: 5px 14px; cursor: pointer; font: inherit; font-size: 12px;
  }
  .tabs button:first-child { border-radius: 4px 0 0 4px; }
  .tabs button:last-child  { border-radius: 0 4px 4px 0; }
  .tabs button.active { background: #1d2430; color: #5ab0ff; border-color: #5ab0ff; }
  .btn-sm {
    background: #1a1d26; border: 1px solid #2a2e3a; color: #c0c4d0;
    padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px;
  }

  /* Pipeline strip */
  .pipeline {
    display: grid; grid-template-columns: repeat(12, 1fr); gap: 2px; flex-shrink: 0;
  }
  .pip-cell {
    background: #111318; border: 1px solid #1c1f28; border-radius: 3px;
    padding: 4px 2px; text-align: center; display: flex; flex-direction: column; gap: 2px;
  }
  .pip-cell.approved { background: #0f2a1e; border-color: #1c4a32; }
  .pip-label { font-size: 9px; color: #6a6e7a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pip-icon { font-size: 11px; color: #3a3e4a; }
  .pip-cell.approved .pip-icon { color: #4de09a; }

  /* Main split */
  .split { display: grid; grid-template-columns: 1fr 300px; gap: 10px; flex: 1; min-height: 0; }

  /* Canvas */
  .canvas { background: #111318; border: 1px solid #22252d; border-radius: 6px; overflow: hidden; display: flex; flex-direction: column; }

  /* Two-pane (storyboard + layout) */
  .two-pane { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; flex: 1; background: #22252d; min-height: 0; }
  .pane { background: #111318; display: flex; flex-direction: column; min-height: 0; }
  .pane-label { font-size: 10px; color: #6a6e7a; padding: 6px 10px; border-bottom: 1px solid #1c1f28; flex-shrink: 0; }
  .pane-img { width: 100%; height: 100%; object-fit: contain; display: block; background: #0c0e14; }
  .pane-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: #3a3e4a; font-size: 12px; font-style: italic; }
  .scene-bar { padding: 8px 12px; border-top: 1px solid #22252d; flex-shrink: 0; }
  .scene-label { font-size: 10px; color: #6a6e7a; text-transform: uppercase; margin-right: 8px; }
  .scene-bar p { display: inline; margin: 0; font-size: 12px; color: #c0c4d0; }

  /* Animation tab */
  .anim-view { display: grid; grid-template-columns: 1fr 220px; gap: 1px; background: #22252d; flex: 1; min-height: 0; }
  .kf-pane { background: #111318; display: flex; flex-direction: column; }
  .kf-img { max-height: calc(100% - 30px); object-fit: contain; }
  .xsheet { background: #0c0e14; overflow-y: auto; font-family: ui-monospace, monospace; font-size: 11px; }
  .xhead { display: grid; grid-template-columns: 24px 28px 28px 28px 1fr; padding: 4px 6px; background: #1d2430; color: #6a6e7a; position: sticky; top: 0; gap: 4px; }
  .xrow { display: grid; grid-template-columns: 24px 28px 28px 28px 1fr; padding: 2px 6px; border-bottom: 1px solid #14161d; color: #6a6e7a; gap: 4px; }
  .xrow.key { background: #1a2436; color: #c0c4d0; }
  .fn { color: #5ab0ff; text-align: right; }
  .xnote { color: #8a8f9c; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* Comp tab */
  .comp-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .bg-pane { flex-shrink: 0; max-height: 30%; overflow: hidden; display: flex; flex-direction: column; border-bottom: 1px solid #22252d; }
  .bg-pane .pane-img { object-fit: cover; height: calc(100% - 26px); }
  .video-pane { flex: 1; display: flex; flex-direction: column; min-height: 0; }
  .comp-video { width: 100%; flex: 1; display: block; background: #000; object-fit: contain; }

  /* Side */
  .side { display: flex; flex-direction: column; gap: 0; overflow-y: auto; min-height: 0; }
  .side-section { padding: 10px 12px; border-bottom: 1px solid #1c1f28; }
  h3 { margin: 0 0 8px; font-size: 11px; text-transform: uppercase; color: #a0a4b0; letter-spacing: .06em; }
  .meta-dl { display: grid; grid-template-columns: max-content 1fr; gap: 3px 10px; font-size: 11px; margin: 0; }
  dt { color: #6a6e7a; }
  dd { margin: 0; color: #c0c4d0; word-break: break-all; }
  .stage-tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; margin-right: 3px; }
  .stage-tag.approved { background: #0f2a1e; color: #4de09a; border: 1px solid #1c4a32; }

  select {
    width: 100%; background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee;
    padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-bottom: 6px;
  }
  textarea {
    width: 100%; background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee;
    padding: 6px 8px; border-radius: 4px; font: inherit; font-size: 12px;
    resize: vertical; box-sizing: border-box;
  }
  form button {
    margin-top: 6px; background: #1f4a3a; border: 1px solid #2a6a50; color: #7de0a8;
    padding: 5px 14px; border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  form button:disabled { opacity: 0.5; cursor: not-allowed; }

  .retake-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 5px; }
  .rt { padding: 6px 8px; border-radius: 4px; background: #0c0e14; border-left: 3px solid #5ab0ff; }
  .rt.sev-major   { border-color: #ff8a3a; }
  .rt.sev-blocker { border-color: #ff5a5a; }
  .rt.sev-nit     { border-color: #5a5e6a; }
  .rt-h { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
  .rt-h strong { font-size: 11px; color: #e6e8ee; }
  .rt-h .muted { font-size: 10px; }
  .resolve-btn { margin-left: auto; background: #1f3a2a; border: 0; color: #7de0a8; padding: 1px 7px; border-radius: 3px; font-size: 10px; cursor: pointer; }
  .resolved-tag { margin-left: auto; font-size: 10px; color: #4a5a4a; }
  .rt p { margin: 0; font-size: 11px; color: #c0c4d0; line-height: 1.4; }
  .small { font-size: 11px; }
</style>
