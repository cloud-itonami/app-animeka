<script lang="ts">
  /**
   * ChatPanel — right-side chat (mangaka-style). `@mentions` route the message
   * at a specific actor DID so the UI shows which actor is answering.
   */
  import { ACTORS, ACTOR_BY_SLUG, type ActorSlug } from '../actors';

  interface Message {
    sender: string;
    text: string;
    isUser: boolean;
    actorSlug?: ActorSlug;
  }

  interface Props {
    messages: Message[];
    activeActor: ActorSlug | null;
    onsend: (text: string, actorSlug: ActorSlug | null) => void;
    onactorclick: (slug: ActorSlug | null) => void;
  }
  let { messages, activeActor, onsend, onactorclick }: Props = $props();

  let inputText = $state('');
  let messagesEnd: HTMLDivElement | undefined = $state();

  function send() {
    const t = inputText.trim();
    if (!t) return;
    onsend(t, activeActor);
    inputText = '';
  }
  function keydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  }

  $effect(() => {
    if (messages.length && messagesEnd) messagesEnd.scrollIntoView({ behavior: 'smooth' });
  });
</script>

<div class="chat">
  <div class="head">
    <strong>Animeka AI</strong>
    <span class="muted">
      {#if activeActor}@{ACTOR_BY_SLUG[activeActor].displayName}{:else}broadcast → all 12{/if}
    </span>
  </div>

  <div class="members">
    {#each ACTORS as a}
      <button
        class="chip"
        class:active={activeActor === a.slug}
        title={`${a.role} — ${a.responsibility}`}
        onclick={() => onactorclick(activeActor === a.slug ? null : a.slug)}
      >
        <span class="dot" style:background={a.color}>{a.emoji}</span>
        <span class="name">{a.displayName}</span>
      </button>
    {/each}
  </div>

  <div class="messages">
    {#if messages.length === 0}
      <div class="hint">
        Pick an actor chip and ask — e.g. <em>@Storyboarder</em> "3 案ください".
        <br />未選択時は全 actor へブロードキャスト。
      </div>
    {/if}
    {#each messages as m}
      {@const actor = m.actorSlug ? ACTOR_BY_SLUG[m.actorSlug] : null}
      <div class="msg" class:user={m.isUser}>
        <div class="meta">
          {#if actor}<span class="tag" style:background={actor.color}>{actor.emoji} {actor.displayName}</span>{/if}
          <span class="sender">{m.sender}</span>
        </div>
        <div class="text">{m.text}</div>
      </div>
    {/each}
    <div bind:this={messagesEnd}></div>
  </div>

  <div class="input">
    <textarea
      rows="2"
      placeholder={activeActor ? `Ask @${ACTOR_BY_SLUG[activeActor].displayName}…` : 'Broadcast to all 12 actors…'}
      bind:value={inputText}
      onkeydown={keydown}
    ></textarea>
    <button class="send" onclick={send}>Send</button>
  </div>
</div>

<style>
  .chat {
    width: 320px;
    flex-shrink: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #111318;
    border-left: 1px solid #22252d;
    color: #e6e8ee;
  }
  .head {
    padding: 10px 12px; border-bottom: 1px solid #22252d;
    display: flex; align-items: baseline; gap: 8px;
  }
  .muted { color: #6a6e7a; font-size: 11px; }
  .members {
    display: flex; flex-wrap: wrap; gap: 4px;
    padding: 8px; border-bottom: 1px solid #22252d;
  }
  .chip {
    display: flex; align-items: center; gap: 4px;
    padding: 2px 8px 2px 2px; border: 1px solid #2a2e3a; border-radius: 12px;
    background: #181b23; color: #d0d4e0; font: inherit; font-size: 10px; cursor: pointer;
  }
  .chip:hover { background: #1d2330; }
  .chip.active { border-color: #5ab0ff; background: #1d2430; color: #fff; }
  .dot {
    width: 18px; height: 18px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 10px; color: #0c0e14;
  }
  .name { white-space: nowrap; }
  .messages {
    flex: 1; overflow-y: auto; padding: 10px;
    display: flex; flex-direction: column; gap: 6px;
  }
  .hint { color: #6a6e7a; font-size: 11px; line-height: 1.5; }
  .hint em { color: #a0a4b0; font-style: normal; background: #1e2230; padding: 1px 4px; border-radius: 3px; }
  .msg {
    padding: 6px 8px; border-radius: 6px; background: #181b23;
    border: 1px solid #22252d;
  }
  .msg.user { align-self: flex-end; background: #1d2430; border-color: #2d3a50; max-width: 92%; }
  .meta { display: flex; gap: 6px; align-items: center; margin-bottom: 2px; }
  .tag {
    font-size: 10px; padding: 1px 6px; border-radius: 3px; color: #0c0e14;
  }
  .sender { font-size: 10px; color: #8a8f9c; }
  .text { font-size: 12px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
  .input {
    display: flex; gap: 6px; padding: 8px; border-top: 1px solid #22252d;
  }
  textarea {
    flex: 1; resize: none; border: 1px solid #2a2e3a; border-radius: 4px;
    background: #181b23; color: #e6e8ee; padding: 6px 8px; font: inherit; font-size: 12px;
  }
  textarea::placeholder { color: #5a5e6a; }
  .send {
    padding: 0 14px; border: 0; border-radius: 4px;
    background: #5ab0ff; color: #0c0e14; font-weight: 700; font-size: 12px; cursor: pointer;
  }
  .send:hover { background: #7bc0ff; }
</style>
