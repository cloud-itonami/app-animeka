/**
 * animeka kotoba — barrel.
 *
 * Per ADR-2606011400 (Consensys pattern) MIXED split. The consumer-facing
 * publication catalog on the etzhayyim substrate (AT PDS records; no RW).
 *
 *   work    : defineWork / getWork / listWorks
 *   episode : registerEpisode (draft, FK→work) / publishEpisode (outputCid) /
 *             announceEpisode (socialUri) / getEpisode / listEpisodes
 *   coverage
 *
 * The ComfyUI/USD GPU generation pipeline + LangGraph checkpointer stays etzhayyim
 * infra (consent-capability); it calls publishEpisode/announceEpisode here.
 */

export * from "./types.js";
export {
  defineWork,
  getWork,
  listWorks,
  registerEpisode,
  publishEpisode,
  announceEpisode,
  getEpisode,
  listEpisodes,
  coverage,
} from "./registry.js";
