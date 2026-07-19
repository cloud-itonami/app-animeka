<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, atProcedure, blobUrl } from '../xrpc';

  let { episodeId }: { episodeId?: string } = $props();

  const FPS = 12;
  const CUT_FRAMES = 48; // 4 s × 12 fps default per cut

  type PlaylistCut = {
    rkey: string;
    outputCid: string;
    createdAt: string;
    sceneText: string;
  };

  type Retake = {
    rkey?: string;
    cutUri?: string;
    stage?: string;
    severity?: string;
    status?: string;
    comment?: string;
    timecodeFrame?: number;
  };

  let playlist: PlaylistCut[] = $state([]);
  let retakes: Retake[] = $state([]);
  let loadingPlaylist = $state(true);
  let loadingRetakes = $state(true);

  let cutIndex = $state(0);
  let videoEl: HTMLVideoElement | undefined = $state(undefined);
  let currentFrame = $state(0);

  let showRetakeForm = $state(false);
  let retakeStage = $state('composite');
  let retakeSeverity = $state('minor');
  let retakeComment = $state('');
  let submitting = $state(false);

  const current = $derived(playlist[cutIndex] ?? null);
  const totalFrames = $derived(playlist.length * CUT_FRAMES);
  const episodeFrame = $derived(cutIndex * CUT_FRAMES + currentFrame);

  function fmtTc(frame: number): string {
    const s = Math.floor(frame / FPS);
    const f = frame % FPS;
    const m = Math.floor(s / 60);
    return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}.${String(f).padStart(2, '0')}`;
  }

  function retakeEpFrame(r: Retake): number {
    const rkey = r.cutUri?.split('/').pop() ?? '';
    const idx = playlist.findIndex(c => c.rkey === rkey);
    return (idx >= 0 ? idx : 0) * CUT_FRAMES + Number(r.timecodeFrame ?? 0);
  }

  async function loadPlaylist() {
    loadingPlaylist = true;
    try {
      const resp = await atQuery<{ items?: Record<string, unknown>[] }>(
        'com.etzhayyim.animeka.listCuts',
        { limit: 500 }
      );
      playlist = (resp.items ?? [])
        .filter(c => c.output_cid)
        .map(c => ({
          rkey: String(c.rkey ?? ''),
          outputCid: String(c.output_cid ?? ''),
          createdAt: String(c.createdAt ?? c.created_at ?? ''),
          sceneText: String(c.camera_note ?? c.dialogueSummary ?? ''),
        }))
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    } catch { playlist = []; }
    loadingPlaylist = false;
  }

  async function loadRetakes() {
    loadingRetakes = true;
    try {
      const params: Record<string, unknown> = { status: 'open', limit: 200 };
      if (episodeId && episodeId !== 'latest') params.episodeId = episodeId;
      const resp = await atQuery<{ items: Retake[] }>('com.etzhayyim.animeka.listRetakes', params);
      retakes = resp.items ?? [];
    } catch { retakes = []; }
    loadingRetakes = false;
  }

  function onEnded() {
    if (cutIndex < playlist.length - 1) {
      cutIndex++;
      currentFrame = 0;
    }
  }

  function onTimeUpdate() {
    if (videoEl) currentFrame = Math.floor(videoEl.currentTime * FPS);
  }

  function jumpToCut(idx: number) {
    cutIndex = idx;
    currentFrame = 0;
    if (videoEl) videoEl.currentTime = 0;
  }

  function jumpToRetake(r: Retake) {
    const rkey = r.cutUri?.split('/').pop() ?? '';
    const idx = playlist.findIndex(c => c.rkey === rkey);
    if (idx < 0) return;
    const cf = Number(r.timecodeFrame ?? 0);
    cutIndex = idx;
    currentFrame = cf;
    if (videoEl) videoEl.currentTime = cf / FPS;
  }

  function scrub(e: MouseEvent) {
    if (totalFrames === 0) return;
    const el = e.currentTarget as HTMLElement;
    const ratio = (e.clientX - el.getBoundingClientRect().left) / el.offsetWidth;
    const frame = Math.floor(Math.max(0, Math.min(ratio, 1)) * totalFrames);
    const ci = Math.min(Math.floor(frame / CUT_FRAMES), playlist.length - 1);
    const cf = Math.min(frame - ci * CUT_FRAMES, CUT_FRAMES - 1);
    cutIndex = ci;
    currentFrame = cf;
    if (videoEl) videoEl.currentTime = cf / FPS;
  }

  async function resolve(r: Retake) {
    if (!r.rkey) return;
    await atProcedure('com.etzhayyim.animeka.resolveRetake', { retakeId: r.rkey, status: 'resolved' });
    await loadRetakes();
  }

  async function submitRetake() {
    if (!current || !retakeComment.trim()) return;
    submitting = true;
    try {
      await atProcedure('com.etzhayyim.animeka.submitRetake', {
        target_uri: `at://anonymous/com.etzhayyim.animeka.cut/${current.rkey}`,
        cut_id: current.rkey,
        stage: retakeStage,
        severity: retakeSeverity,
        comment: retakeComment.trim(),
        timecode_frame: currentFrame,
      });
      retakeComment = '';
      showRetakeForm = false;
      await loadRetakes();
    } catch (err) { console.error('submitRetake', err); }
    submitting = false;
  }

  // Auto-play continuation when cut changes mid-playback
  $effect(() => {
    const _cut = current;
    if (videoEl && _cut) {
      videoEl.load();
    }
  });

  onMount(() => { loadPlaylist(); loadRetakes(); });
</script>

<section class="page">
  <header>
    <h1>Review Room <span class="ep">{episodeId ?? 'all cuts'}</span></h1>
    <div class="meta muted">{playlist.length} cuts · {fmtTc(totalFrames)}</div>
    <button class="btn-refresh" onclick={() => { loadPlaylist(); loadRetakes(); }}>↻</button>
  </header>

  {#if loadingPlaylist}
    <p class="muted">Loading playlist…</p>
  {:else if playlist.length === 0}
    <p class="muted">No composited cuts yet — compositor must run first.</p>
  {:else}
    <div class="split">

      <!-- ── Left column: player + timeline ── -->
      <div class="player-col">

        <div class="screen-wrap">
          <!-- svelte-ignore a11y_media_has_caption -->
          <video
            bind:this={videoEl}
            src={current ? blobUrl(current.outputCid) : ''}
            onended={onEnded}
            ontimeupdate={onTimeUpdate}
            controls
            playsinline
            class="screen"
          ></video>
          <div class="hud">
            <span class="hud-cut">#{cutIndex + 1}/{playlist.length} · {current?.rkey ?? ''}</span>
            <span class="hud-tc">{fmtTc(episodeFrame)}</span>
          </div>
        </div>

        {#if current?.sceneText}
          <p class="scene-text">{current.sceneText}</p>
        {/if}

        <!-- Timeline scrubber -->
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="timeline" onclick={scrub} title="Click to scrub">
          <!-- playhead -->
          <div
            class="playhead"
            style:left="{totalFrames > 0 ? (episodeFrame / totalFrames) * 100 : 0}%"
          ></div>
          <!-- cut boundaries -->
          {#each playlist as _, i}
            {#if i > 0}
              <div class="cut-mark" style:left="{(i * CUT_FRAMES / totalFrames) * 100}%"></div>
            {/if}
          {/each}
          <!-- retake markers — episode-relative position -->
          {#each retakes as r}
            {@const pct = totalFrames > 0 ? Math.min(100, (retakeEpFrame(r) / totalFrames) * 100) : 0}
            <span
              class="marker sev-{r.severity ?? 'minor'}"
              style:left="{pct}%"
              title="[{r.severity}] {r.stage}: {r.comment}"
            ></span>
          {/each}
        </div>

        <!-- Cut strip -->
        <div class="cut-strip">
          {#each playlist as c, i}
            <button
              class="cut-btn"
              class:active={i === cutIndex}
              onclick={() => jumpToCut(i)}
              title="#{i + 1} · {c.sceneText}"
            >{i + 1}</button>
          {/each}
        </div>

        <!-- Retake bar -->
        <div class="retake-bar">
          <button class="btn-retake" onclick={() => showRetakeForm = !showRetakeForm}>
            {showRetakeForm ? '✕ Cancel' : '+ Mark Retake'}
          </button>
          {#if showRetakeForm}
            <form
              class="retake-form"
              onsubmit={(e) => { e.preventDefault(); submitRetake(); }}
            >
              <span class="muted form-tc">@ {fmtTc(episodeFrame)} · {current?.rkey ?? ''}</span>
              <div class="form-row">
                <select bind:value={retakeStage}>
                  <option value="storyboard">Storyboard</option>
                  <option value="layout">Layout</option>
                  <option value="keyAnim">Key Anim</option>
                  <option value="inbetween">Inbetween</option>
                  <option value="composite">Composite</option>
                  <option value="sound">Sound</option>
                </select>
                <select bind:value={retakeSeverity}>
                  <option value="nit">Nit</option>
                  <option value="minor">Minor</option>
                  <option value="major">Major</option>
                  <option value="blocker">Blocker</option>
                </select>
              </div>
              <textarea
                bind:value={retakeComment}
                placeholder="Describe the issue…"
                rows="2"
              ></textarea>
              <button type="submit" disabled={submitting || !retakeComment.trim()}>
                {submitting ? 'Submitting…' : 'Submit Retake'}
              </button>
            </form>
          {/if}
        </div>
      </div>

      <!-- ── Right column: retake queue ── -->
      <aside class="queue">
        <h3>Open retakes ({retakes.length})</h3>
        {#if loadingRetakes}
          <p class="muted">Loading…</p>
        {:else if retakes.length === 0}
          <p class="muted">No open retakes 🎉</p>
        {:else}
          <ul>
            {#each retakes as r}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
              <li class="sev-{r.severity ?? 'minor'}" onclick={() => jumpToRetake(r)}>
                <div class="rh">
                  <strong>{r.stage}</strong>
                  <span class="badge sev-{r.severity ?? 'minor'}">{r.severity ?? 'minor'}</span>
                  <span class="muted tc">{fmtTc(retakeEpFrame(r))}</span>
                  <button
                    class="resolve-btn"
                    onclick={(e) => { e.stopPropagation(); resolve(r); }}
                    title="Mark resolved"
                  >✓</button>
                </div>
                <p>{r.comment}</p>
              </li>
            {/each}
          </ul>
        {/if}
      </aside>

    </div>
  {/if}
</section>

<style>
  .page { padding: 16px 20px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }
  header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-shrink: 0; }
  h1 { margin: 0; font-size: 17px; font-weight: 600; }
  .ep { color: #6a6e7a; font-weight: 400; }
  .meta { font-size: 12px; }
  .muted { color: #6a6e7a; }
  .btn-refresh { background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; margin-left: auto; }
  .btn-refresh:hover { border-color: #5ab0ff; }

  .split { display: grid; grid-template-columns: 1fr 340px; gap: 14px; flex: 1; min-height: 0; }

  /* ── Player column ── */
  .player-col { display: flex; flex-direction: column; gap: 8px; min-height: 0; }

  .screen-wrap { position: relative; background: #000; border-radius: 6px; overflow: hidden; flex-shrink: 0; }
  .screen { display: block; width: 100%; max-height: 42vh; object-fit: contain; background: #000; }
  .hud {
    position: absolute; bottom: 0; left: 0; right: 0;
    display: flex; justify-content: space-between; align-items: center;
    padding: 6px 10px;
    background: linear-gradient(transparent, rgba(0,0,0,0.7));
    pointer-events: none;
  }
  .hud-cut { font-family: ui-monospace, monospace; font-size: 11px; color: #a0c8ff; }
  .hud-tc  { font-family: ui-monospace, monospace; font-size: 13px; color: #fff; letter-spacing: .04em; }

  .scene-text { margin: 0; font-size: 12px; color: #c0c4d0; line-height: 1.5; flex-shrink: 0; }

  /* Timeline */
  .timeline {
    background: #0c0e14; border: 1px solid #22252d; border-radius: 5px;
    height: 32px; position: relative; cursor: crosshair; flex-shrink: 0; overflow: hidden;
  }
  .playhead {
    position: absolute; top: 0; bottom: 0; width: 2px;
    background: #5ab0ff; transform: translateX(-50%); pointer-events: none;
  }
  .cut-mark {
    position: absolute; top: 4px; bottom: 4px; width: 1px;
    background: #2a3040; transform: translateX(-50%); pointer-events: none;
  }
  .marker {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 6px; height: 20px; border-radius: 2px; background: #5ab0ff;
    pointer-events: none;
  }
  .marker.sev-major   { background: #ff8a3a; }
  .marker.sev-blocker { background: #ff5a5a; }
  .marker.sev-nit     { background: #5a5e6a; }

  /* Cut strip */
  .cut-strip {
    display: flex; gap: 3px; flex-wrap: wrap; flex-shrink: 0;
  }
  .cut-btn {
    background: #1a1d26; border: 1px solid #22252d; color: #6a6e7a;
    padding: 2px 6px; border-radius: 3px; font-size: 11px; cursor: pointer; min-width: 28px;
  }
  .cut-btn:hover { border-color: #5ab0ff; color: #e6e8ee; }
  .cut-btn.active { border-color: #5ab0ff; color: #5ab0ff; background: #0d1a2e; }

  /* Retake bar */
  .retake-bar { flex-shrink: 0; }
  .btn-retake {
    background: #2a1a14; border: 1px solid #5a2a1a; color: #ff8a4a;
    padding: 5px 14px; border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .btn-retake:hover { border-color: #ff6a2a; }
  .retake-form {
    margin-top: 8px; display: flex; flex-direction: column; gap: 6px;
    background: #0c0e14; border: 1px solid #22252d; border-radius: 6px; padding: 10px;
  }
  .form-tc { font-family: ui-monospace, monospace; font-size: 11px; }
  .form-row { display: flex; gap: 6px; }
  select {
    flex: 1; background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee;
    padding: 4px 8px; border-radius: 4px; font-size: 12px;
  }
  textarea {
    background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee;
    padding: 6px 8px; border-radius: 4px; font-size: 12px; resize: vertical;
    font-family: inherit;
  }
  .retake-form button[type="submit"] {
    background: #1f4a3a; border: 1px solid #2a6a50; color: #7de0a8;
    padding: 5px 14px; border-radius: 4px; cursor: pointer; font-size: 12px;
    align-self: flex-end;
  }
  .retake-form button[type="submit"]:disabled { opacity: 0.5; cursor: not-allowed; }

  /* ── Retake queue ── */
  .queue {
    background: #15181f; border: 1px solid #22252d; border-radius: 6px;
    padding: 12px; overflow-y: auto; min-height: 0;
  }
  h3 { margin: 0 0 10px; font-size: 11px; text-transform: uppercase; color: #a0a4b0; letter-spacing: .06em; }
  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
  li {
    padding: 8px 10px; border-radius: 4px; background: #0c0e14;
    border-left: 3px solid #5ab0ff; cursor: pointer;
  }
  li:hover { border-color: #7ad0ff; }
  li.sev-major   { border-color: #ff8a3a; }
  li.sev-blocker { border-color: #ff5a5a; }
  li.sev-nit     { border-color: #5a5e6a; }
  .rh { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
  .rh strong { font-size: 12px; color: #e6e8ee; }
  .badge { font-size: 10px; padding: 1px 5px; border-radius: 3px; background: #1a2030; color: #7a8090; }
  .badge.sev-major   { background: #2a1a0a; color: #ff8a3a; }
  .badge.sev-blocker { background: #2a0a0a; color: #ff5a5a; }
  .badge.sev-nit     { background: #1a1c24; color: #5a5e6a; }
  .tc { font-family: ui-monospace, monospace; font-size: 11px; }
  .resolve-btn {
    margin-left: auto; background: #1f3a2a; border: 0; color: #7de0a8;
    padding: 2px 8px; border-radius: 3px; font-size: 11px; cursor: pointer;
  }
  .resolve-btn:hover { background: #2a5a3a; }
  li p { margin: 0; font-size: 12px; color: #c0c4d0; line-height: 1.4; }
</style>
