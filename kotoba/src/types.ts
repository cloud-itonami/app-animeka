/**
 * animeka kotoba — publication-catalog record types.
 *
 * Per ADR-2606011400 (Consensys pattern) — MIXED split. animeka's primary
 * function is split:
 *   - PRODUCT (etzhayyim front, this package): the consumer-facing catalog of
 *     anime works + episodes (title, IPFS output CID, publish/announce status,
 *     social announcement URI). Registry on AT PDS records (replaces
 *     vertex_animeka work/episode).
 *   - INFRA (stays etzhayyim, NOT here): the ComfyUI/USD GPU generation pipeline +
 *     LangGraph checkpointer (RW-backed job state in assemble_episode). It is
 *     invoked via consent-capability and writes published results into this
 *     catalog. No RW/GPU/checkpointer code lives in this package.
 *
 * No PII / settlement on the catalog layer. IPFS output CIDs are the permitted
 * etzhayyim substrate. AT-Lexicon: no float (integers only).
 *
 * Identity hierarchy:
 *   did:web:an1m3k4x.etzhayyim.com                         — controller (app DID)
 *   did:web:an1m3k4x.etzhayyim.com:work:{workId}           — an anime work/title
 *   did:web:an1m3k4x.etzhayyim.com:episode:{episodeId}     — an episode
 */

export const ANIMEKA_DID_PREFIX = "did:web:an1m3k4x.etzhayyim.com:" as const;

export const WORK_COLLECTION = "com.etzhayyim.animeka.work";
export const EPISODE_COLLECTION = "com.etzhayyim.animeka.episode";

// ─── Work (anime title / series) ────────────────────────────────────

export interface WorkRecord {
  did: string;
  workId: string;
  title: string;
  synopsis?: string;
  creatorDid: string;
  createdAt: string;
}

export interface WorkView extends WorkRecord {
  workUri: string;
}

export interface DefineWorkInput {
  workId: string;
  title: string;
  creatorDid: string;
  synopsis?: string;
}

export interface DefineWorkOutput {
  status: "defined" | "alreadyExists" | "rejected";
  workUri?: string;
  did?: string;
  workId?: string;
  error?: string;
}

export interface GetWorkInput {
  workId: string;
}
export interface GetWorkOutput {
  work?: WorkView;
  error?: string;
}
export interface ListWorksInput {
  creatorDid?: string;
  limit?: number;
  cursor?: string;
}
export interface ListWorksOutput {
  items: WorkView[];
  cursor?: string;
  total: number;
}

// ─── Episode ────────────────────────────────────────────────────────

/**
 * draft     — catalog entry created, not yet rendered
 * published — render complete, outputCid set
 * announced — social announcement posted (socialUri set)
 */
export type EpisodeStatus = "draft" | "published" | "announced";

export interface EpisodeRecord {
  did: string;
  episodeId: string;
  /** FK → work workId. */
  workId: string;
  /** Episode number within the work (≥1). */
  episodeNo: number;
  title?: string;
  /** IPFS CID of the rendered episode (set on publish). */
  outputCid?: string;
  status: EpisodeStatus;
  /** at:// URI of the Bluesky announcement (set on announce). */
  socialUri?: string;
  createdAt: string;
}

export interface EpisodeView extends EpisodeRecord {
  episodeUri: string;
}

export interface RegisterEpisodeInput {
  episodeId: string;
  workId: string;
  episodeNo: number;
  title?: string;
}

export interface RegisterEpisodeOutput {
  status: "registered" | "alreadyExists" | "rejected" | "workNotFound";
  episodeUri?: string;
  did?: string;
  episodeId?: string;
  error?: string;
}

export interface PublishEpisodeInput {
  episodeId: string;
  /** IPFS CID of the rendered output. */
  outputCid: string;
}

export interface PublishEpisodeOutput {
  status: "published" | "notFound" | "rejected";
  episodeId?: string;
  newStatus?: EpisodeStatus;
  error?: string;
}

export interface AnnounceEpisodeInput {
  episodeId: string;
  socialUri: string;
}

export interface AnnounceEpisodeOutput {
  status: "announced" | "notFound" | "rejected";
  episodeId?: string;
  newStatus?: EpisodeStatus;
  error?: string;
}

export interface GetEpisodeInput {
  episodeId: string;
}
export interface GetEpisodeOutput {
  episode?: EpisodeView;
  error?: string;
}
export interface ListEpisodesInput {
  workId?: string;
  status?: EpisodeStatus;
  limit?: number;
  cursor?: string;
}
export interface ListEpisodesOutput {
  items: EpisodeView[];
  cursor?: string;
  total: number;
}

// ─── Coverage ───────────────────────────────────────────────────────

export interface CoverageInput {
  maxScan?: number;
}
export interface CoverageOutput {
  workCount?: number;
  episodeCount?: number;
  episodesByStatus?: Record<string, number>;
  truncated?: boolean;
  error?: string;
}

// ─── Helpers ────────────────────────────────────────────────────────

export function workDidFor(id: string): string {
  return `${ANIMEKA_DID_PREFIX}work:${id.toLowerCase()}`;
}
export function workRkey(id: string): string {
  return `work-${id.toLowerCase()}`;
}
export function episodeDidFor(id: string): string {
  return `${ANIMEKA_DID_PREFIX}episode:${id.toLowerCase()}`;
}
export function episodeRkey(id: string): string {
  return `episode-${id.toLowerCase()}`;
}

/** Minimal CIDv1 sanity check (base32 'b...' or base58btc 'Qm...'). */
export function looksLikeCid(s: string): boolean {
  return /^b[a-z2-7]{20,}$/.test(s) || /^Qm[1-9A-HJ-NP-Za-km-z]{20,}$/.test(s);
}
