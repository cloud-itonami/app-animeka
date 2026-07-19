<script lang="ts">
  import { onMount } from 'svelte';
  import { atQuery, atProcedure, flatProps } from '../xrpc';
  import ActorRoster from '../components/ActorRoster.svelte';
  import ChatPanel from '../components/ChatPanel.svelte';
  import { STAGES, STAGE_OWNER, ACTOR_BY_SLUG, type ActorSlug, type StageKey } from '../actors';

  let { episodeId, go }: { episodeId?: string; go: (path: string) => void } = $props();

  type StageStatus = Partial<Record<StageKey, string>>;
  type Cut = {
    rkey?: string;
    cut_num?: number;
    duration_frames?: number;
    fps?: number;
    priority?: string;
    dialogue_summary?: string;
    camera_note?: string;
    stage_status?: string;
    createdAt?: string;
    _parsed?: StageStatus;
    _label?: string;
  };
  type Retake = {
    rkey?: string;
    cutUri?: string;
    stage?: string;
    severity?: string;
    status?: string;
  };

  let cuts: Cut[] = $state([]);
  let retakeMap: Map<string, number> = $state(new Map()); // `${cutRkey}:${stage}` → open count
  let loading = $state(true);
  let activeActor: ActorSlug | null = $state(null);
  let filterRetake = $state(false);

  type ChatMessage = { sender: string; text: string; isUser: boolean; actorSlug?: ActorSlug };
  let messages: ChatMessage[] = $state([]);

  // Stage → approved count (derived from cuts)
  const stageCounts = $derived(() => {
    const m: Partial<Record<StageKey, { approved: number; total: number }>> = {};
    for (const s of STAGES) m[s.key] = { approved: 0, total: cuts.length };
    for (const c of cuts) {
      for (const s of STAGES) {
        if (c._parsed?.[s.key] === 'approved') m[s.key]!.approved++;
      }
    }
    return m;
  });

  const visibleCuts = $derived(
    filterRetake
      ? cuts.filter(c => STAGES.some(s => {
          const key = `${c.rkey}:${s.key}`;
          return retakeMap.get(key) ?? 0 > 0;
        }))
      : cuts
  );

  const totalApproved = $derived(
    cuts.filter(c => c._parsed?.composite === 'approved').length
  );
  const totalRetakes = $derived([...retakeMap.values()].reduce((a, b) => a + b, 0));

  function statusColor(s?: string): string {
    switch (s) {
      case 'approved':    return '#1c4a32';
      case 'in_progress': return '#4a3d1c';
      case 'review':      return '#1c394a';
      case 'retake':      return '#4a1c1c';
      default:            return '#14161d';
    }
  }

  function statusIcon(s?: string): string {
    switch (s) {
      case 'approved':    return '✓';
      case 'in_progress': return '◌';
      case 'review':      return '⊙';
      case 'retake':      return '↺';
      default:            return '';
    }
  }

  function cutLabel(c: Cut, idx: number): string {
    if (c.cut_num != null) return `#${c.cut_num}`;
    // autopilot cuts: use sequential index
    return `#${idx + 1}`;
  }

  function cutSummary(c: Cut): string {
    const get = flatProps(c as unknown as Record<string, unknown>);
    return String(get('camera_note', 'cameraNote') ?? get('dialogue_summary', 'dialogueSummary') ?? '');
  }

  async function load() {
    loading = true;
    try {
      const params: Record<string, unknown> = { limit: 500 };
      if (episodeId && episodeId !== 'latest') params.episodeId = episodeId;
      const [cutsResp, retakesResp] = await Promise.all([
        atQuery<{ items: Cut[] }>('com.etzhayyim.animeka.listCuts', params),
        atQuery<{ items: Retake[] }>('com.etzhayyim.animeka.listRetakes', { status: 'open', limit: 500 }),
      ]);

      cuts = (cutsResp.items ?? [])
        .sort((a, b) => (a.createdAt ?? '').localeCompare(b.createdAt ?? ''))
        .map((c) => {
          let parsed: StageStatus = {};
          if (c.stage_status) {
            try { parsed = JSON.parse(c.stage_status); } catch { /* ignore */ }
          }
          return { ...c, _parsed: parsed };
        });

      // Build retake map: cutRkey:stage → open count
      const rmap = new Map<string, number>();
      for (const r of retakesResp.items ?? []) {
        const rkey = r.cutUri?.split('/').pop() ?? '';
        const key = `${rkey}:${r.stage ?? ''}`;
        rmap.set(key, (rmap.get(key) ?? 0) + 1);
      }
      retakeMap = rmap;
    } catch {
      cuts = [];
    }
    loading = false;
  }

  function onActorSelect(slug: ActorSlug | null) {
    activeActor = slug;
  }

  function stageHighlighted(key: StageKey): boolean {
    if (!activeActor) return false;
    return ACTOR_BY_SLUG[activeActor].stageKeys.includes(key);
  }

  async function onSend(text: string, slug: ActorSlug | null) {
    const targetLabel = slug ? `@${ACTOR_BY_SLUG[slug].displayName}` : '@all';
    messages = [...messages, { sender: 'You', text: `${targetLabel} ${text}`, isUser: true, actorSlug: slug ?? undefined }];
    try {
      const r = await atProcedure<{ reply?: string; sender?: string; actorSlug?: ActorSlug }>(
        'com.etzhayyim.animeka.chat',
        { message: text, actorSlug: slug ?? undefined, episodeId: episodeId ?? 'latest' },
      );
      const replySlug = (r?.actorSlug as ActorSlug | undefined) ?? slug ?? undefined;
      messages = [...messages, {
        sender: r?.sender ?? 'Animeka',
        text: r?.reply ?? '(empty reply)',
        isUser: false,
        actorSlug: replySlug,
      }];
    } catch (err) {
      messages = [...messages, {
        sender: 'system',
        text: `chat RPC failed: ${String((err as Error)?.message ?? err).slice(0, 200)}`,
        isUser: false,
        actorSlug: slug ?? undefined,
      }];
    }
  }

  onMount(load);
</script>

<section class="page">
  <aside class="left">
    <ActorRoster selected={activeActor} onselect={onActorSelect} />
  </aside>

  <div class="center">
    <header>
      <div class="title-row">
        <h1>Pipeline Board <span class="ep muted">· {episodeId ?? 'all cuts'}</span></h1>
        <div class="stats">
          <span class="stat stat-ok">{totalApproved} composited</span>
          <span class="stat stat-rt">{totalRetakes} retakes</span>
          <span class="stat">{cuts.length} cuts total</span>
        </div>
      </div>
      <div class="controls">
        <div class="legend">
          <span><i style:background="#1c4a32"></i> approved</span>
          <span><i style:background="#4a3d1c"></i> in progress</span>
          <span><i style:background="#1c394a"></i> review</span>
          <span><i style:background="#4a1c1c"></i> retake</span>
          <span><i style:background="#14161d"></i> pending</span>
        </div>
        <div class="btns">
          <button class="ctrl" class:active={filterRetake} onclick={() => filterRetake = !filterRetake}>
            ↺ retakes only
          </button>
          <button class="ctrl" onclick={() => go('/review')}>▶ Review Room</button>
          <button class="ctrl" onclick={load}>↻</button>
        </div>
      </div>
    </header>

    {#if loading}
      <p class="muted">Loading…</p>
    {:else}
      <div class="board">
        <!-- Stage header row -->
        <div class="hrow">
          <div class="hcell cutcol">
            <span class="col-title">Cut</span>
            <span class="muted xs">{visibleCuts.length} shown</span>
          </div>
          {#each STAGES as s}
            {@const owner = STAGE_OWNER[s.key]}
            {@const hl = stageHighlighted(s.key)}
            {@const counts = stageCounts()[s.key]}
            <div class="hcell stage-head" class:highlight={hl}>
              <span class="stage-label">{s.label}</span>
              {#if owner}
                <button class="owner" title={`${owner.role} — ${owner.responsibility}`} onclick={() => onActorSelect(owner.slug)}>
                  <span class="dot" style:background={owner.color}>{owner.emoji}</span>
                  <span class="oname">{owner.displayName}</span>
                </button>
              {:else}
                <span class="muted xs">—</span>
              {/if}
              <!-- progress bar -->
              {#if counts && counts.total > 0}
                {@const pct = Math.round((counts.approved / counts.total) * 100)}
                <div class="prog-wrap" title="{counts.approved}/{counts.total} approved">
                  <div class="prog-bar" style:width="{pct}%"></div>
                </div>
                <span class="prog-label muted xs">{counts.approved}/{counts.total}</span>
              {/if}
            </div>
          {/each}
        </div>

        <!-- Cut rows -->
        {#if visibleCuts.length === 0}
          <div class="row">
            <div class="cutcol ghost"><span class="muted">No cuts match filter.</span></div>
            {#each STAGES as _}<div class="cell"></div>{/each}
          </div>
        {:else}
          {#each visibleCuts as cut, idx}
            {@const summary = cutSummary(cut)}
            {@const hasRetake = STAGES.some(s => (retakeMap.get(`${cut.rkey}:${s.key}`) ?? 0) > 0)}
            <div class="row" class:has-retake={hasRetake}>
              <button
                class="cutcol"
                onclick={() => go(`/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.cut/${cut.rkey}`)}
                title={cut.rkey}
              >
                <span class="cut-num">{cutLabel(cut, idx)}</span>
                {#if cut.duration_frames}<span class="muted xs">{cut.duration_frames}f</span>{/if}
                {#if summary}<span class="summary">{summary}</span>{/if}
              </button>
              {#each STAGES as s}
                {@const status = cut._parsed?.[s.key]}
                {@const rtCount = retakeMap.get(`${cut.rkey}:${s.key}`) ?? 0}
                {@const hl = stageHighlighted(s.key)}
                <div
                  class="cell"
                  class:highlight={hl}
                  style:background={statusColor(rtCount > 0 ? 'retake' : status)}
                  title="{s.label}: {rtCount > 0 ? `${rtCount} retake(s)` : (status ?? 'pending')}"
                >
                  {#if rtCount > 0}
                    <span class="rt-badge">{rtCount}</span>
                  {:else if status}
                    <span class="status-icon">{statusIcon(status)}</span>
                  {/if}
                </div>
              {/each}
            </div>
          {/each}
        {/if}
      </div>
    {/if}
  </div>

  <aside class="right">
    <ChatPanel
      {messages}
      {activeActor}
      onsend={onSend}
      onactorclick={onActorSelect}
    />
  </aside>
</section>

<style>
  .page {
    display: grid;
    grid-template-columns: 320px minmax(0, 1fr) 320px;
    height: 100vh;
    overflow: hidden;
  }
  .left, .right { height: 100%; overflow: hidden; display: flex; }
  .center { overflow: auto; padding: 14px 16px; min-width: 0; display: flex; flex-direction: column; gap: 10px; }

  header { flex-shrink: 0; }
  .title-row { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
  h1 { margin: 0; font-size: 17px; font-weight: 600; }
  .ep { font-weight: 400; }
  .muted { color: #6a6e7a; }
  .stats { display: flex; gap: 10px; }
  .stat { font-size: 11px; color: #8a8f9c; background: #1a1d26; padding: 2px 8px; border-radius: 10px; border: 1px solid #22252d; }
  .stat-ok { color: #7de0a8; border-color: #1c4a32; background: #0f2a1e; }
  .stat-rt { color: #ff8a8a; border-color: #4a1c1c; background: #2a0f0f; }

  .controls { display: flex; align-items: center; gap: 12px; justify-content: space-between; flex-wrap: wrap; }
  .legend { display: flex; gap: 8px; font-size: 11px; color: #8a8f9c; flex-wrap: wrap; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }
  .btns { display: flex; gap: 6px; }
  .ctrl {
    background: #1a1d26; border: 1px solid #2a2e3a; color: #c0c4d0;
    padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;
  }
  .ctrl:hover { border-color: #5ab0ff; color: #fff; }
  .ctrl.active { border-color: #ff6060; color: #ff8a8a; background: #2a1010; }

  /* Board */
  .board { display: flex; flex-direction: column; gap: 1px; min-width: 1000px; }
  .hrow, .row { display: grid; grid-template-columns: 200px repeat(12, 1fr); gap: 1px; }

  .hcell {
    background: #111318; padding: 6px 4px; text-align: center;
    color: #a0a4b0; min-height: 72px;
    display: flex; flex-direction: column; justify-content: flex-start; align-items: center; gap: 3px;
    padding-top: 8px;
  }
  .hcell.cutcol { text-align: left; align-items: flex-start; padding: 8px 10px; }
  .col-title { font-size: 11px; text-transform: uppercase; color: #a0a4b0; letter-spacing: .05em; }
  .stage-head.highlight { background: #1a2436; outline: 1px solid #5ab0ff; }
  .stage-label { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: #c0c4d0; }

  .owner {
    display: inline-flex; align-items: center; gap: 3px;
    padding: 2px 5px 2px 2px; background: #181b23; border: 1px solid #2a2e3a;
    border-radius: 10px; color: #d0d4e0; font: inherit; font-size: 10px; cursor: pointer;
  }
  .owner:hover { background: #1d2330; border-color: #3a4254; }
  .dot {
    width: 15px; height: 15px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 8px; color: #0c0e14;
  }
  .oname { white-space: nowrap; max-width: 60px; overflow: hidden; text-overflow: ellipsis; }
  .xs { font-size: 10px; }

  /* Progress bar in header cell */
  .prog-wrap { width: 80%; height: 3px; background: #22252d; border-radius: 2px; overflow: hidden; }
  .prog-bar { height: 100%; background: #2a7a4a; border-radius: 2px; transition: width .3s; }
  .prog-label { }

  /* Cut rows */
  .cutcol {
    background: #15181f; padding: 6px 10px; text-align: left;
    display: flex; flex-direction: column; gap: 2px; border: 0; color: #e6e8ee;
    cursor: pointer; font: inherit; min-height: 36px;
  }
  .cutcol:hover { background: #1d2430; }
  .cutcol.ghost { cursor: default; background: #111318; }
  .cut-num { font-size: 12px; font-weight: 600; line-height: 1; }
  .summary {
    font-size: 10px; color: #7a8090;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px;
  }
  .row.has-retake .cutcol { border-left: 3px solid #ff5a5a; padding-left: 7px; }

  .cell {
    min-height: 36px; display: flex; align-items: center; justify-content: center;
    position: relative; font-size: 11px;
  }
  .cell.highlight { outline: 1px solid #5ab0ff; outline-offset: -1px; }
  .status-icon { font-size: 12px; color: rgba(255,255,255,0.5); }
  .rt-badge {
    background: #d93838; color: #fff; font-size: 10px; font-weight: 700;
    min-width: 16px; height: 16px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center; padding: 0 4px;
  }
</style>
