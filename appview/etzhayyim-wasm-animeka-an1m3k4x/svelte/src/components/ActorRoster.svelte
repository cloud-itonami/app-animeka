<script lang="ts">
  /**
   * ActorRoster — 12-actor list with capability + responsibility + owned stages.
   * Click an actor chip to highlight the stages they own on the Pipeline Board.
   */
  import { ACTORS, STAGES, type ActorSlug, type StageKey } from '../actors';

  interface Props {
    selected?: ActorSlug | null;
    onselect?: (slug: ActorSlug | null) => void;
  }
  let { selected = null, onselect }: Props = $props();

  function labelForStage(key: StageKey): string {
    return STAGES.find((s) => s.key === key)?.label ?? key;
  }

  function toggle(slug: ActorSlug) {
    onselect?.(selected === slug ? null : slug);
  }
</script>

<aside class="roster">
  <div class="head">
    <span class="title">Actors</span>
    <span class="muted">12 DID roles · click = focus stage</span>
  </div>
  <ul>
    {#each ACTORS as a}
      {@const active = selected === a.slug}
      <li>
        <button class="card" class:active onclick={() => toggle(a.slug)}>
          <span class="avatar" style:background={a.color}>{a.emoji}</span>
          <div class="body">
            <div class="h">
              <strong>{a.displayName}</strong>
              <span class="role">{a.role}</span>
            </div>
            <div class="resp">{a.responsibility}</div>
            <div class="caps">
              {#each a.capability as c}
                <span class="cap">{c}</span>
              {/each}
            </div>
            <div class="stages">
              {#if a.stageKeys.length === 0}
                <span class="stage overseer" title="全工程レビュー">oversight</span>
              {:else}
                {#each a.stageKeys as k}
                  <span class="stage" style:--c={a.color}>{labelForStage(k)}</span>
                {/each}
              {/if}
            </div>
          </div>
        </button>
      </li>
    {/each}
  </ul>
</aside>

<style>
  .roster {
    width: 320px;
    flex-shrink: 0;
    border-right: 1px solid #22252d;
    background: #111318;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .head {
    padding: 10px 12px;
    border-bottom: 1px solid #22252d;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .title { font-weight: 700; font-size: 13px; }
  .muted { color: #6a6e7a; font-size: 11px; }
  ul { list-style: none; padding: 8px; margin: 0; overflow-y: auto; }
  li { margin-bottom: 6px; }
  .card {
    width: 100%;
    display: grid;
    grid-template-columns: 36px 1fr;
    gap: 8px;
    padding: 8px;
    border: 1px solid #22252d;
    border-radius: 6px;
    background: #15181f;
    color: #e6e8ee;
    text-align: left;
    cursor: pointer;
    font: inherit;
  }
  .card:hover { border-color: #3a4254; background: #1a1d26; }
  .card.active { border-color: #5ab0ff; background: #1d2430; }
  .avatar {
    width: 36px; height: 36px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px;
    color: #0c0e14;
  }
  .body { min-width: 0; }
  .h { display: flex; gap: 6px; align-items: baseline; margin-bottom: 2px; }
  .h strong { font-size: 12px; }
  .role { font-size: 10px; color: #a0a4b0; }
  .resp { font-size: 11px; color: #c0c4d0; line-height: 1.35; margin-bottom: 4px; }
  .caps { display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 4px; }
  .cap {
    font-size: 9px; color: #a0a4b0; background: #1e2230;
    border: 1px solid #2b3040; padding: 1px 5px; border-radius: 8px;
  }
  .stages { display: flex; flex-wrap: wrap; gap: 3px; }
  .stage {
    font-size: 10px; padding: 1px 6px; border-radius: 3px;
    background: color-mix(in srgb, var(--c) 25%, #15181f);
    color: #fff;
    border: 1px solid color-mix(in srgb, var(--c) 40%, #15181f);
  }
  .stage.overseer {
    background: #2a2e3a; color: #a0a4b0; border-color: #3a4254;
  }
</style>
