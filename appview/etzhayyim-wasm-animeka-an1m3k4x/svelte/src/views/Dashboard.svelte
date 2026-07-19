<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, atProcedure, blobBg } from '../xrpc';
  import { coverSVG, svgDataUri } from '../lib/procart';
  import { STAGES } from '../actors';
  import type { StageKey } from '../actors';

  let { workId: initWorkId, go }: { workId?: string; go?: (path: string) => void } = $props();

  // ── Data types ───────────────────────────────────────────────────────────────
  type Work = { rkey: string; title: string; status?: string; episodeCount?: number; coverCid?: string };
  type Episode = { rkey: string; episodeNum?: number; titleJP?: string; workRef?: string; createdAt?: string };
  type CutRow = Record<string, unknown>;
  type StageStatus = Partial<Record<StageKey, string>>;

  let works: Work[] = $state([]);
  let episodes: Episode[] = $state([]);
  let cuts: CutRow[] = $state([]);
  let openRetakeCount = $state(0);
  let loading = $state(true);

  let selectedWorkRkey = $state(initWorkId ?? '');
  let newTitle = $state('');
  let creating = $state(false);

  // ── Derived aggregations ─────────────────────────────────────────────────────
  // Parse stage_status JSON once per cut
  const parsedCuts = $derived(
    cuts.map(c => {
      let st: StageStatus = {};
      if (c.stage_status) { try { st = JSON.parse(String(c.stage_status)); } catch { /* ignore */ } }
      return { ...c, _st: st };
    })
  );

  // Group cuts by episode_id (null = autopilot / unassigned)
  const cutsByEpisode = $derived(() => {
    const m = new Map<string, typeof parsedCuts>();
    for (const c of parsedCuts) {
      const eid = String(c.episode_id ?? c.episodeId ?? '');
      if (!m.has(eid)) m.set(eid, []);
      m.get(eid)!.push(c);
    }
    return m;
  });

  const autoCuts = $derived(cutsByEpisode().get('') ?? []);
  const compositedCount = $derived(parsedCuts.filter(c => c._st.composite === 'approved').length);

  // Per-stage approval counts across ALL cuts
  const globalStageCounts = $derived(() => {
    const m: Partial<Record<StageKey, number>> = {};
    for (const s of STAGES) {
      m[s.key] = parsedCuts.filter(c => c._st[s.key] === 'approved').length;
    }
    return m;
  });

  // Episodes belonging to selected work
  const filteredEpisodes = $derived(
    selectedWorkRkey
      ? episodes.filter(e => {
          const ref = String(e.workRef ?? '');
          return ref === selectedWorkRkey || ref.endsWith(`/${selectedWorkRkey}`);
        })
      : episodes
  );

  // ── Load ─────────────────────────────────────────────────────────────────────
  const TEST_TITLE_RE = /^(BK\s*\d+|FR\s*\d+|FE\s*\d+|PK\s+Fix\s+\d+|Tail\s+\d+|Solo\s+Post\s+\d+|Final\s+\d+|Drop\s+\w+(\s+\w+)?\s*\d*|Demo\s+Series.*|ADR-\d.*|.*Diag\d.*|.*Test\s+\w+\s+\d+|.*Pilot\s+Test.*)$/i;

  async function load() {
    loading = true;
    try {
      const [worksResp, cutsResp, episodesResp, retakesResp] = await Promise.all([
        atQuery<{ works?: Record<string, unknown>[]; items?: Record<string, unknown>[] }>(
          'com.etzhayyim.animeka.listWorks', { limit: 200 }
        ),
        atQuery<{ items?: CutRow[] }>('com.etzhayyim.animeka.listCuts', { limit: 500 }),
        atQuery<{ items?: Record<string, unknown>[] }>('com.etzhayyim.animeka.listEpisodes', { limit: 200 })
          .catch(() => ({ items: [] })),
        atQuery<{ items?: unknown[] }>('com.etzhayyim.animeka.listRetakes', { status: 'open', limit: 1 })
          .catch(() => ({ items: [] })),
      ]);

      const rawWorks = worksResp.works ?? worksResp.items ?? [];
      works = rawWorks
        .map(r => {
          let raw: Record<string, unknown> = {};
          if (typeof r.raw === 'string') { try { raw = JSON.parse(r.raw); } catch { raw = {}; } }
          return {
            rkey:         String(r.rkey ?? ''),
            title:        String(r.title ?? raw.title ?? 'Untitled'),
            status:       String(r.status ?? raw.status ?? ''),
            episodeCount: Number(r.episodeCount ?? raw.episodeCount ?? 0),
            coverCid:     String(r.coverCid ?? raw.coverCid ?? ''),
          };
        })
        .filter(w => !TEST_TITLE_RE.test(w.title.trim()));

      cuts = cutsResp.items ?? [];

      episodes = (episodesResp.items ?? []).map(e => ({
        rkey:       String(e.rkey ?? ''),
        episodeNum: Number(e.episode_num ?? e.episodeNum ?? 0) || undefined,
        titleJP:    String(e.title_jp ?? e.titleJP ?? e.title ?? ''),
        workRef:    String(e.work_ref ?? e.workRef ?? ''),
        createdAt:  String(e.createdAt ?? ''),
      }));

      openRetakeCount = (retakesResp.items ?? []).length > 0 ? -1 : 0; // -1 = has retakes
      // Fetch actual count
      atQuery<{ total?: number; items?: unknown[] }>('com.etzhayyim.animeka.listRetakes', { status: 'open', limit: 500 })
        .then(r => { openRetakeCount = (r.items ?? []).length; })
        .catch(() => { openRetakeCount = 0; });

    } catch (err) {
      console.error('Dashboard load', err);
    }
    loading = false;
  }

  async function createWork() {
    if (!newTitle.trim()) return;
    creating = true;
    try {
      await atProcedure('com.etzhayyim.animeka.createWork', { title: newTitle.trim() });
      newTitle = '';
      await load();
    } catch (err) { console.error(err); }
    creating = false;
  }

  function stageCell(eid: string, key: StageKey): { approved: number; total: number } {
    const cs = cutsByEpisode().get(eid) ?? [];
    return {
      approved: cs.filter(c => c._st[key] === 'approved').length,
      total: cs.length,
    };
  }

  function cellColor(approved: number, total: number): string {
    if (total === 0) return '#111318';
    const pct = approved / total;
    if (pct === 0)   return '#14161d';
    if (pct < 0.33)  return '#1a2c1a';
    if (pct < 0.66)  return '#1c4028';
    if (pct < 1)     return '#1f5030';
    return '#1c5c38';
  }

  function cellText(approved: number, total: number): string {
    if (total === 0) return '';
    if (approved === 0) return '';
    if (approved === total) return '✓';
    return `${approved}`;
  }

  onMount(load);

  // ── Publish Episode ──────────────────────────────────────────────────────────
  let publishing = $state(false);
  let publishDone = $state(false);
  let episodeCid = $state('');
  let publishCutCount = $state(0);
  let publishError = $state('');
  let publishMaxCuts = $state(20);

  async function publishEpisode() {
    publishing = true; publishDone = false; publishError = ''; episodeCid = '';
    try {
      const r = await atProcedure<{ episode_cid?: string; episodeCid?: string; cut_count?: number; cutCount?: number; error?: string }>(
        'com.etzhayyim.animeka.publishEpisode', { maxCuts: publishMaxCuts }
      );
      if (r.error) { publishError = r.error; }
      else {
        episodeCid = r.episode_cid ?? r.episodeCid ?? '';
        publishCutCount = r.cut_count ?? r.cutCount ?? 0;
        publishDone = true;
      }
    } catch (e: unknown) { publishError = String(e); }
    publishing = false;
  }

  // ── Score + Kaizen ───────────────────────────────────────────────────────────
  let scoring = $state(false);
  let scoreResult: { scores: unknown[]; summary: Record<string,unknown> } | null = $state(null);
  let scoreError = $state('');
  let scoreCutCount = $state(5);

  let kaizenRunning = $state(false);
  let kaizenResult: { improved_count: number; directives_used: string[]; kaizen_results: unknown[] } | null = $state(null);
  let kaizenError = $state('');
  let kaizenThreshold = $state(65);

  async function runScore() {
    scoring = true; scoreResult = null; scoreError = '';
    try {
      const r = await atProcedure<{ scores?: unknown[]; summary?: Record<string,unknown>; error?: string }>(
        'com.etzhayyim.animeka.scoreCuts', { maxCuts: scoreCutCount }
      );
      if (r.error) scoreError = r.error;
      else scoreResult = { scores: r.scores ?? [], summary: r.summary ?? {} };
    } catch (e: unknown) { scoreError = String(e); }
    scoring = false;
  }

  async function runKaizen() {
    kaizenRunning = true; kaizenResult = null; kaizenError = '';
    try {
      const r = await atProcedure<{ improved_count?: number; directives_used?: string[]; kaizen_results?: unknown[]; error?: string }>(
        'com.etzhayyim.animeka.kaizenCompositor', { maxCuts: scoreCutCount, threshold: kaizenThreshold }
      );
      if (r.error) kaizenError = r.error;
      else kaizenResult = { improved_count: r.improved_count ?? 0, directives_used: r.directives_used ?? [], kaizen_results: r.kaizen_results ?? [] };
    } catch (e: unknown) { kaizenError = String(e); }
    kaizenRunning = false;
  }

  // ── Generate Audio ───────────────────────────────────────────────────────────
  let audioRunning = $state(false);
  let audioResult: { successful: number; mood_distribution: Record<string,number>; tts_cuts: number } | null = $state(null);
  let audioError = $state('');
  let audioCutCount = $state(5);

  async function runGenerateAudio() {
    audioRunning = true; audioResult = null; audioError = '';
    try {
      const r = await atProcedure<{ summary?: { successful?: number; mood_distribution?: Record<string,number>; tts_cuts?: number }; error?: string }>(
        'com.etzhayyim.animeka.generateAudio', { maxCuts: audioCutCount }
      );
      if (r.error) audioError = r.error;
      else {
        const s = r.summary ?? {};
        audioResult = { successful: s.successful ?? 0, mood_distribution: s.mood_distribution ?? {}, tts_cuts: s.tts_cuts ?? 0 };
      }
    } catch (e: unknown) { audioError = String(e); }
    audioRunning = false;
  }
</script>

<div class="page">

  <!-- ── Stats bar ── -->
  <div class="stats-bar">
    <div class="stat-card">
      <span class="stat-num">{cuts.length}</span>
      <span class="stat-label">total cuts</span>
    </div>
    <div class="stat-card green">
      <span class="stat-num">{compositedCount}</span>
      <span class="stat-label">composited</span>
    </div>
    <div class="stat-card">
      <span class="stat-num">{works.length}</span>
      <span class="stat-label">works</span>
    </div>
    <div class="stat-card">
      <span class="stat-num">{episodes.length}</span>
      <span class="stat-label">episodes</span>
    </div>
    {#if openRetakeCount > 0}
      <div class="stat-card red">
        <span class="stat-num">{openRetakeCount}</span>
        <span class="stat-label">open retakes</span>
      </div>
    {/if}
    <!-- Global stage completion bar -->
    <div class="stage-summary">
      {#each STAGES as s}
        {@const n = globalStageCounts()[s.key] ?? 0}
        {@const pct = cuts.length > 0 ? Math.round((n / cuts.length) * 100) : 0}
        <div class="stage-col" title="{s.label}: {n}/{cuts.length}">
          <div class="stage-bar-wrap">
            <div class="stage-bar" style:height="{pct}%"></div>
          </div>
          <span class="stage-bar-label">{s.label}</span>
        </div>
      {/each}
    </div>
    <button class="btn-refresh" onclick={load}>↻</button>
  </div>

  <div class="body">

    <!-- ── Works sidebar ── -->
    <aside class="works-sidebar">
      <div class="sidebar-head">
        <span class="sidebar-title">Works</span>
      </div>

      <form class="create-form" onsubmit={(e) => { e.preventDefault(); createWork(); }}>
        <input bind:value={newTitle} placeholder="New series title…" disabled={creating} />
        <button type="submit" disabled={creating || !newTitle.trim()}>+</button>
      </form>

      {#if loading}
        <p class="muted sm">Loading…</p>
      {:else}
        <!-- "All" option -->
        <button
          class="work-item"
          class:active={!selectedWorkRkey}
          onclick={() => selectedWorkRkey = ''}
        >
          <span class="work-avatar all-avatar">All</span>
          <div class="work-body">
            <strong>All works</strong>
            <span class="muted sm">{episodes.length} ep · {cuts.length} cuts</span>
          </div>
        </button>

        {#each works as w}
          <button
            class="work-item"
            class:active={selectedWorkRkey === w.rkey}
            onclick={() => selectedWorkRkey = selectedWorkRkey === w.rkey ? '' : w.rkey}
          >
            <div
              class="work-avatar"
              style:background={w.coverCid
                ? blobBg(w.coverCid)
                : svgDataUri(coverSVG(w.rkey, w.title))}
            ></div>
            <div class="work-body">
              <strong>{w.title}</strong>
              <span class="muted sm">{w.status || '—'} · {w.episodeCount ?? 0} ep</span>
            </div>
          </button>
        {/each}
      {/if}
    </aside>

    <!-- ── Main: episode Gantt + autopilot section ── -->
    <main class="main">

      <!-- Episode Gantt -->
      {#if !loading}
        <section class="gantt-section">
          <h2>
            Episode Gantt
            {#if selectedWorkRkey}
              <span class="muted sm">· {filteredEpisodes.length} episodes</span>
            {:else}
              <span class="muted sm">· all {episodes.length} episodes</span>
            {/if}
          </h2>

          {#if filteredEpisodes.length === 0}
            <p class="muted sm">No episodes found. Create an episode from the pipeline board or script view.</p>
          {:else}
            <div class="gantt">
              <!-- Header row -->
              <div class="gantt-row gantt-head">
                <div class="gantt-ep-cell">Episode</div>
                {#each STAGES as s}
                  <div class="gantt-cell head-cell" title={s.label}>{s.label}</div>
                {/each}
                <div class="gantt-actions"></div>
              </div>
              <!-- Episode rows -->
              {#each filteredEpisodes as ep}
                {@const eid = ep.rkey}
                {@const epCuts = cutsByEpisode().get(eid) ?? []}
                <div class="gantt-row">
                  <div class="gantt-ep-cell">
                    <span class="ep-num">EP{ep.episodeNum ?? '?'}</span>
                    <span class="ep-title">{ep.titleJP || ep.rkey}</span>
                    <span class="ep-count muted sm">{epCuts.length} cuts</span>
                  </div>
                  {#each STAGES as s}
                    {@const { approved, total } = stageCell(eid, s.key)}
                    <div
                      class="gantt-cell data-cell"
                      style:background={cellColor(approved, total)}
                      title="{s.label}: {approved}/{total}"
                    >
                      <span class="cell-txt">{cellText(approved, total)}</span>
                    </div>
                  {/each}
                  <div class="gantt-actions">
                    <button
                      class="act-btn"
                      title="Pipeline Board"
                      onclick={() => go?.(`/episodes/${ep.rkey}`)}
                    >▦</button>
                    <button
                      class="act-btn"
                      title="Review Room"
                      onclick={() => go?.(`/episodes/${ep.rkey}/review`)}
                    >▶</button>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </section>

        <!-- Autopilot cuts summary row -->
        {#if autoCuts.length > 0}
          <section class="gantt-section">
            <h2>
              Autopilot Cuts
              <span class="muted sm">· {autoCuts.length} cuts · no episode binding</span>
              <div class="ep-actions inline">
                <button class="act-btn" title="Pipeline Board" onclick={() => go?.('/episodes/latest')}>▦ Board</button>
                <button class="act-btn" title="Review Room" onclick={() => go?.('/review')}>▶ Review</button>
              </div>
            </h2>
            <div class="gantt">
              <div class="gantt-row gantt-head">
                <div class="gantt-ep-cell">Group</div>
                {#each STAGES as s}
                  <div class="gantt-cell head-cell" title={s.label}>{s.label}</div>
                {/each}
                <div class="gantt-actions"></div>
              </div>
              <div class="gantt-row">
                <div class="gantt-ep-cell">
                  <span class="ep-num auto-tag">AUTO</span>
                  <span class="ep-title">Autopilot</span>
                  <span class="ep-count muted sm">{autoCuts.length} cuts</span>
                </div>
                {#each STAGES as s}
                  {@const approved = autoCuts.filter(c => c._st[s.key] === 'approved').length}
                  {@const total = autoCuts.length}
                  <div
                    class="gantt-cell data-cell"
                    style:background={cellColor(approved, total)}
                    title="{s.label}: {approved}/{total}"
                  >
                    <span class="cell-txt">{cellText(approved, total)}</span>
                  </div>
                {/each}
                <div class="gantt-actions"></div>
              </div>
            </div>

            <!-- Thumbnail strip of recent composited cuts -->
            <div class="thumb-strip">
              {#each autoCuts.filter(c => c._st.composite === 'approved').slice(-16) as c}
                <button
                  class="thumb-btn"
                  onclick={() => go?.(`/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.cut/${c.rkey}`)}
                  title={String(c.rkey ?? '')}
                >
                  {#if c.thumb_cid}
                    <img
                      class="thumb-img"
                      src={`https://atproto.etzhayyim.com/xrpc/com.atproto.sync.getBlob?did=anonymous&cid=${c.thumb_cid}`}
                      alt={String(c.rkey ?? '')}
                      loading="lazy"
                    />
                  {:else}
                    <div class="thumb-placeholder">▶</div>
                  {/if}
                </button>
              {/each}
            </div>
          </section>
        {/if}
      {/if}

      <!-- Publish + Score/Kaizen panel -->
      {#if !loading && autoCuts.length > 0}
        <section class="kaizen-section">
          <h2>Publish &amp; Kaizen</h2>

          <!-- Row 1: Publish Episode -->
          <div class="kaizen-row">
            <div class="kaizen-label">Episode reel</div>
            <label class="kaizen-sublabel">
              Max cuts: <input type="number" class="kaizen-num" min="1" max="50" bind:value={publishMaxCuts} />
            </label>
            <button class="kaizen-btn pub-btn" onclick={publishEpisode} disabled={publishing}>
              {publishing ? '…' : 'Publish'}
            </button>
            {#if publishError}
              <span class="kaizen-err">{publishError}</span>
            {:else if publishDone}
              <span class="kaizen-ok">
                EP ready · {publishCutCount} cuts ·
                <a href="https://atproto.etzhayyim.com/xrpc/com.atproto.sync.getBlob?did=anonymous&cid={episodeCid}" target="_blank" class="kaizen-link">MP4</a>
              </span>
              <video class="ep-video" src="https://atproto.etzhayyim.com/xrpc/com.atproto.sync.getBlob?did=anonymous&cid={episodeCid}" controls></video>
            {/if}
          </div>

          <!-- Row 2: Score cuts -->
          <div class="kaizen-row">
            <div class="kaizen-label">Vision score</div>
            <label class="kaizen-sublabel">
              Cuts: <input type="number" class="kaizen-num" min="1" max="20" bind:value={scoreCutCount} />
            </label>
            <button class="kaizen-btn score-btn" onclick={runScore} disabled={scoring}>
              {scoring ? '…' : 'Score'}
            </button>
            {#if scoreError}
              <span class="kaizen-err">{scoreError}</span>
            {:else if scoreResult}
              {@const s = scoreResult.summary as { composite_mean?: number; composite_min?: number; weak_cuts?: string[]; top_issues?: string[]; dim_means?: Record<string,number>; kaizen_directives?: string[] }}
              <span class="kaizen-ok">
                mean {s.composite_mean}/100 · min {s.composite_min} · weak {(s.weak_cuts ?? []).length}
              </span>
              {#if (s.top_issues ?? []).length}
                <div class="kaizen-issues">
                  {#each s.top_issues ?? [] as issue}
                    <span class="issue-tag">{issue}</span>
                  {/each}
                </div>
              {/if}
              {#if (s.kaizen_directives ?? []).length}
                <div class="kaizen-directives">
                  {#each s.kaizen_directives ?? [] as d}
                    <div class="directive-row">{d}</div>
                  {/each}
                </div>
              {/if}
            {/if}
          </div>

          <!-- Row 3: Kaizen compositor -->
          <div class="kaizen-row">
            <div class="kaizen-label">Kaizen loop</div>
            <label class="kaizen-sublabel">
              Threshold: <input type="number" class="kaizen-num" min="0" max="100" bind:value={kaizenThreshold} />
            </label>
            <button class="kaizen-btn kaizen-btn-run" onclick={runKaizen} disabled={kaizenRunning}>
              {kaizenRunning ? '…' : 'Re-composite'}
            </button>
            {#if kaizenError}
              <span class="kaizen-err">{kaizenError}</span>
            {:else if kaizenResult}
              <span class="kaizen-ok">
                Improved {kaizenResult.improved_count} cuts
                {#if kaizenResult.directives_used.length}
                  · {kaizenResult.directives_used.join(' · ')}
                {/if}
              </span>
            {/if}
          </div>

          <!-- Row 4: Generate Audio -->
          <div class="kaizen-row">
            <div class="kaizen-label">Audio BGM</div>
            <label class="kaizen-sublabel">
              Cuts: <input type="number" class="kaizen-num" min="1" max="20" bind:value={audioCutCount} />
            </label>
            <button class="kaizen-btn audio-btn" onclick={runGenerateAudio} disabled={audioRunning}>
              {audioRunning ? '…' : 'Generate'}
            </button>
            {#if audioError}
              <span class="kaizen-err">{audioError}</span>
            {:else if audioResult}
              <span class="kaizen-ok">
                {audioResult.successful} cuts · TTS {audioResult.tts_cuts}
                {#if Object.keys(audioResult.mood_distribution).length}
                  · {Object.entries(audioResult.mood_distribution).map(([k,v]) => `${k}×${v}`).join(' ')}
                {/if}
              </span>
            {/if}
          </div>
        </section>
      {/if}

    </main>
  </div>
</div>

<style>
  .page {
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
    background: #0c0e14;
  }

  /* ── Stats bar ── */
  .stats-bar {
    display: flex; align-items: flex-end; gap: 10px; padding: 10px 16px;
    border-bottom: 1px solid #1c1f28; flex-shrink: 0; background: #111318;
    flex-wrap: wrap;
  }
  .stat-card {
    display: flex; flex-direction: column; align-items: center; gap: 1px;
    padding: 4px 10px; background: #15181f; border: 1px solid #22252d;
    border-radius: 6px; min-width: 56px;
  }
  .stat-card.green { border-color: #1c4a32; background: #0f2a1e; }
  .stat-card.red   { border-color: #4a1c1c; background: #2a0f0f; }
  .stat-num { font-size: 20px; font-weight: 700; color: #e6e8ee; line-height: 1; }
  .stat-card.green .stat-num { color: #4de09a; }
  .stat-card.red   .stat-num { color: #ff8a8a; }
  .stat-label { font-size: 9px; color: #6a6e7a; text-transform: uppercase; letter-spacing: .04em; }
  .btn-refresh {
    background: #1a1d26; border: 1px solid #2a2e3a; color: #c0c4d0;
    padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px;
    margin-left: auto; align-self: center;
  }

  /* Stage bar chart in stats */
  .stage-summary {
    display: flex; align-items: flex-end; gap: 3px; height: 40px;
    padding: 0 4px; border-left: 1px solid #22252d; margin-left: 4px;
  }
  .stage-col { display: flex; flex-direction: column; align-items: center; gap: 2px; }
  .stage-bar-wrap {
    width: 14px; height: 28px; background: #1a1d26; border-radius: 2px;
    display: flex; align-items: flex-end; overflow: hidden;
  }
  .stage-bar { width: 100%; background: #2a7a4a; border-radius: 2px; transition: height .4s; }
  .stage-bar-label { font-size: 8px; color: #5a5e6a; white-space: nowrap; }

  /* ── Body ── */
  .body { display: grid; grid-template-columns: 240px 1fr; flex: 1; min-height: 0; }

  /* ── Works sidebar ── */
  .works-sidebar {
    background: #111318; border-right: 1px solid #1c1f28;
    display: flex; flex-direction: column; overflow: hidden;
  }
  .sidebar-head { padding: 10px 12px; border-bottom: 1px solid #1c1f28; }
  .sidebar-title { font-size: 11px; font-weight: 600; text-transform: uppercase; color: #a0a4b0; letter-spacing: .06em; }
  .create-form { display: flex; gap: 4px; padding: 8px; border-bottom: 1px solid #1c1f28; flex-shrink: 0; }
  .create-form input {
    flex: 1; background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee;
    padding: 4px 8px; border-radius: 4px; font: inherit; font-size: 11px; min-width: 0;
  }
  .create-form button {
    background: #5ab0ff; border: 0; color: #0c0e14; padding: 4px 10px;
    border-radius: 4px; cursor: pointer; font-weight: 700; font-size: 13px;
  }
  .create-form button:disabled { opacity: 0.4; cursor: not-allowed; }

  .work-item {
    display: flex; align-items: center; gap: 8px; padding: 8px 10px;
    border: 0; background: none; color: #e6e8ee; cursor: pointer;
    text-align: left; font: inherit; border-bottom: 1px solid #14161d; width: 100%;
  }
  .work-item:hover { background: #15181f; }
  .work-item.active { background: #1d2430; border-left: 3px solid #5ab0ff; padding-left: 7px; }
  .work-avatar {
    width: 36px; height: 48px; border-radius: 3px; flex-shrink: 0;
    background-size: cover; background-position: center; background-color: #1a1d26;
  }
  .all-avatar {
    display: flex; align-items: center; justify-content: center;
    font-size: 9px; font-weight: 700; color: #5ab0ff; background: #1d2430;
    border: 1px solid #2d3a50; height: 36px;
  }
  .work-body { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .work-body strong { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; max-width: 160px; }
  .muted { color: #6a6e7a; }
  .sm { font-size: 11px; }

  /* ── Main content ── */
  .main { overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 20px; }
  h2 { margin: 0 0 10px; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }

  /* ── Gantt table ── */
  .gantt { display: flex; flex-direction: column; gap: 1px; min-width: 900px; }
  .gantt-row { display: grid; grid-template-columns: 200px repeat(12, 1fr) 60px; gap: 1px; }
  .gantt-head .gantt-cell { background: #111318; }
  .gantt-ep-cell {
    background: #15181f; padding: 6px 10px; display: flex; flex-direction: column; gap: 2px;
  }
  .ep-num {
    font-size: 10px; font-weight: 700; color: #5ab0ff;
    font-family: ui-monospace, monospace;
  }
  .ep-num.auto-tag { color: #ffa040; }
  .ep-title { font-size: 11px; color: #e6e8ee; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ep-count { }
  .gantt-cell {
    min-height: 36px; display: flex; align-items: center; justify-content: center;
    font-size: 10px; color: #6a6e7a;
  }
  .head-cell {
    background: #111318; font-size: 9px; color: #6a6e7a; text-transform: uppercase;
    writing-mode: vertical-rl; height: 60px; align-items: center; justify-content: flex-end;
    padding-bottom: 4px; letter-spacing: .04em;
  }
  .data-cell { transition: background .2s; }
  .cell-txt { font-size: 11px; color: rgba(255,255,255,0.7); }
  .gantt-actions {
    display: flex; align-items: center; justify-content: center; gap: 3px;
    background: #111318; padding: 2px;
  }
  .gantt-head .gantt-actions { background: #111318; }
  .act-btn {
    background: #1a1d26; border: 1px solid #2a2e3a; color: #a0a4b0;
    padding: 2px 5px; border-radius: 3px; cursor: pointer; font-size: 10px;
  }
  .act-btn:hover { border-color: #5ab0ff; color: #5ab0ff; }

  .inline { display: inline-flex; margin-left: 8px; }
  .ep-actions { display: flex; gap: 4px; }

  /* ── Thumbnail strip ── */
  .thumb-strip {
    display: flex; gap: 4px; flex-wrap: wrap; margin-top: 8px;
  }
  .thumb-btn {
    background: none; border: 1px solid #22252d; padding: 0; cursor: pointer;
    border-radius: 3px; overflow: hidden; width: 80px; height: 45px;
  }
  .thumb-btn:hover { border-color: #5ab0ff; }
  .thumb-img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .thumb-placeholder {
    width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
    color: #5ab0ff; font-size: 16px; background: #15181f;
  }

  .gantt-section { flex-shrink: 0; overflow-x: auto; }

  /* ── Kaizen section ── */
  .kaizen-section {
    background: #111318; border: 1px solid #1c1f28; border-radius: 8px;
    padding: 14px 16px; display: flex; flex-direction: column; gap: 12px;
  }
  .kaizen-row {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .kaizen-label {
    font-size: 11px; font-weight: 600; color: #a0a4b0; text-transform: uppercase;
    letter-spacing: .04em; width: 100px; flex-shrink: 0;
  }
  .kaizen-sublabel { font-size: 11px; color: #6a6e7a; display: flex; align-items: center; gap: 4px; }
  .kaizen-num {
    width: 44px; background: #1a1d26; border: 1px solid #2a2e3a; color: #e6e8ee;
    padding: 2px 5px; border-radius: 3px; font: inherit; font-size: 11px; text-align: center;
  }
  .kaizen-btn {
    padding: 3px 12px; border-radius: 4px; border: 0; cursor: pointer;
    font: inherit; font-size: 11px; font-weight: 600;
  }
  .pub-btn   { background: #5ab0ff; color: #0c0e14; }
  .score-btn { background: #8b5cf6; color: #fff; }
  .kaizen-btn-run { background: #f59e0b; color: #0c0e14; }
  .audio-btn { background: #10b981; color: #0c0e14; }
  .kaizen-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .kaizen-err { font-size: 11px; color: #ff8a8a; }
  .kaizen-ok  { font-size: 11px; color: #4de09a; }
  .kaizen-link { color: #5ab0ff; text-decoration: none; }
  .ep-video {
    width: 100%; max-width: 480px; border-radius: 4px; margin-top: 6px;
    background: #000; display: block;
  }
  .kaizen-issues {
    display: flex; flex-wrap: wrap; gap: 4px; width: 100%; margin-top: 4px;
  }
  .issue-tag {
    font-size: 10px; background: #2a1c3a; border: 1px solid #4a2c6a;
    color: #c0a0e0; padding: 1px 6px; border-radius: 10px;
  }
  .kaizen-directives {
    width: 100%; margin-top: 4px; display: flex; flex-direction: column; gap: 3px;
  }
  .directive-row {
    font-size: 11px; color: #b0c4d8; background: #151c28; border-left: 2px solid #3a6080;
    padding: 3px 8px; border-radius: 0 3px 3px 0;
  }
</style>
