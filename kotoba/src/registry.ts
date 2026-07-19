/**
 * animeka kotoba — work + episode publication-catalog registries + coverage.
 * AT PDS records (no RW/checkpointer/GPU). An episode references an existing
 * work (FK). Lifecycle: register(draft) → publish(outputCid) → announce(socialUri),
 * mirroring the etzhayyim-infra publish_episode graph which calls into this catalog.
 */

import type { Etzhayyim } from "@etzhayyim/sdk";
import {
  EPISODE_COLLECTION,
  WORK_COLLECTION,
  episodeDidFor,
  episodeRkey,
  looksLikeCid,
  workDidFor,
  workRkey,
  type AnnounceEpisodeInput,
  type AnnounceEpisodeOutput,
  type CoverageInput,
  type CoverageOutput,
  type DefineWorkInput,
  type DefineWorkOutput,
  type EpisodeRecord,
  type EpisodeView,
  type GetEpisodeInput,
  type GetEpisodeOutput,
  type GetWorkInput,
  type GetWorkOutput,
  type ListEpisodesInput,
  type ListEpisodesOutput,
  type ListWorksInput,
  type ListWorksOutput,
  type PublishEpisodeInput,
  type PublishEpisodeOutput,
  type RegisterEpisodeInput,
  type RegisterEpisodeOutput,
  type WorkRecord,
  type WorkView,
} from "./types.js";

const PAGE_LIMIT = 100;
const DEFAULT_MAX_SCAN = 10_000;

async function exists(e: Etzhayyim, collection: string, rkey: string): Promise<boolean> {
  const resp = await e.read({ collection, rkey }).catch(() => ({ records: [] }));
  return Boolean(resp.records[0]?.value);
}

// ─── Work ───────────────────────────────────────────────────────────

export async function defineWork(e: Etzhayyim, input: DefineWorkInput): Promise<DefineWorkOutput> {
  if (!input.workId || !input.title) return { status: "rejected", error: "missingRequiredFields" };
  if (!input.creatorDid || !input.creatorDid.startsWith("did:")) return { status: "rejected", error: "invalidCreatorDid" };
  const rkey = workRkey(input.workId);
  const existing = await e.read<WorkRecord>({ collection: WORK_COLLECTION, rkey }).catch(() => ({ records: [] }));
  if (existing.records[0]?.value) {
    return { status: "alreadyExists", workUri: existing.records[0].uri, did: existing.records[0].value.did, workId: input.workId };
  }
  const did = workDidFor(input.workId);
  const record: WorkRecord = {
    did,
    workId: input.workId,
    title: input.title,
    synopsis: input.synopsis,
    creatorDid: input.creatorDid,
    createdAt: new Date().toISOString(),
  };
  const receipt = await e.write({ collection: WORK_COLLECTION, record: record as unknown as Record<string, unknown>, rkey });
  return { status: "defined", workUri: receipt.uri, did, workId: input.workId };
}

export async function getWork(e: Etzhayyim, input: GetWorkInput): Promise<GetWorkOutput> {
  if (!input.workId) return { error: "invalidWorkId" };
  const resp = await e.read<WorkRecord>({ collection: WORK_COLLECTION, rkey: workRkey(input.workId) }).catch(() => ({ records: [] }));
  const r = resp.records[0];
  if (!r) return { error: "notFound" };
  return { work: { ...r.value, workUri: r.uri } };
}

export async function listWorks(e: Etzhayyim, input: ListWorksInput = {}): Promise<ListWorksOutput> {
  const limit = Math.min(input.limit ?? 50, 200);
  const resp = await e.read<WorkRecord>({ collection: WORK_COLLECTION, cursor: input.cursor, limit });
  const items: WorkView[] = resp.records
    .filter((r) => (input.creatorDid ? r.value.creatorDid === input.creatorDid : true))
    .map((r) => ({ ...r.value, workUri: r.uri }));
  return { items, cursor: resp.cursor, total: items.length };
}

// ─── Episode ────────────────────────────────────────────────────────

export async function registerEpisode(e: Etzhayyim, input: RegisterEpisodeInput): Promise<RegisterEpisodeOutput> {
  if (!input.episodeId || !input.workId) return { status: "rejected", error: "missingRequiredFields" };
  if (!Number.isInteger(input.episodeNo) || input.episodeNo < 1) return { status: "rejected", error: "episodeNoMustBePosInt" };
  if (!(await exists(e, WORK_COLLECTION, workRkey(input.workId)))) {
    return { status: "workNotFound", error: `workNotFound:${input.workId}` };
  }
  const rkey = episodeRkey(input.episodeId);
  const existing = await e.read<EpisodeRecord>({ collection: EPISODE_COLLECTION, rkey }).catch(() => ({ records: [] }));
  if (existing.records[0]?.value) {
    return { status: "alreadyExists", episodeUri: existing.records[0].uri, did: existing.records[0].value.did, episodeId: input.episodeId };
  }
  const did = episodeDidFor(input.episodeId);
  const record: EpisodeRecord = {
    did,
    episodeId: input.episodeId,
    workId: input.workId,
    episodeNo: input.episodeNo,
    title: input.title,
    status: "draft",
    createdAt: new Date().toISOString(),
  };
  const receipt = await e.write({ collection: EPISODE_COLLECTION, record: record as unknown as Record<string, unknown>, rkey });
  return { status: "registered", episodeUri: receipt.uri, did, episodeId: input.episodeId };
}

export async function publishEpisode(e: Etzhayyim, input: PublishEpisodeInput): Promise<PublishEpisodeOutput> {
  if (!input.episodeId) return { status: "rejected", error: "missingEpisodeId" };
  if (!input.outputCid || !looksLikeCid(input.outputCid)) return { status: "rejected", error: "invalidOutputCid" };
  const rkey = episodeRkey(input.episodeId);
  const resp = await e.read<EpisodeRecord>({ collection: EPISODE_COLLECTION, rkey }).catch(() => ({ records: [] }));
  const ep = resp.records[0]?.value;
  if (!ep) return { status: "notFound", error: "episodeNotFound" };
  if (ep.status === "announced") return { status: "rejected", error: "episodeAlreadyAnnounced" };
  await e.write({
    collection: EPISODE_COLLECTION,
    record: { ...ep, outputCid: input.outputCid, status: "published" } as unknown as Record<string, unknown>,
    rkey,
  });
  return { status: "published", episodeId: input.episodeId, newStatus: "published" };
}

export async function announceEpisode(e: Etzhayyim, input: AnnounceEpisodeInput): Promise<AnnounceEpisodeOutput> {
  if (!input.episodeId) return { status: "rejected", error: "missingEpisodeId" };
  if (!input.socialUri || !input.socialUri.startsWith("at://")) return { status: "rejected", error: "invalidSocialUri" };
  const rkey = episodeRkey(input.episodeId);
  const resp = await e.read<EpisodeRecord>({ collection: EPISODE_COLLECTION, rkey }).catch(() => ({ records: [] }));
  const ep = resp.records[0]?.value;
  if (!ep) return { status: "notFound", error: "episodeNotFound" };
  if (ep.status !== "published") return { status: "rejected", error: `episodeNotPublished:${ep.status}` };
  await e.write({
    collection: EPISODE_COLLECTION,
    record: { ...ep, socialUri: input.socialUri, status: "announced" } as unknown as Record<string, unknown>,
    rkey,
  });
  return { status: "announced", episodeId: input.episodeId, newStatus: "announced" };
}

export async function getEpisode(e: Etzhayyim, input: GetEpisodeInput): Promise<GetEpisodeOutput> {
  if (!input.episodeId) return { error: "invalidEpisodeId" };
  const resp = await e.read<EpisodeRecord>({ collection: EPISODE_COLLECTION, rkey: episodeRkey(input.episodeId) }).catch(() => ({ records: [] }));
  const r = resp.records[0];
  if (!r) return { error: "notFound" };
  return { episode: { ...r.value, episodeUri: r.uri } };
}

export async function listEpisodes(e: Etzhayyim, input: ListEpisodesInput = {}): Promise<ListEpisodesOutput> {
  const limit = Math.min(input.limit ?? 50, 200);
  const resp = await e.read<EpisodeRecord>({ collection: EPISODE_COLLECTION, cursor: input.cursor, limit });
  const items: EpisodeView[] = resp.records
    .filter((r) => {
      const v = r.value;
      if (input.workId && v.workId !== input.workId) return false;
      if (input.status && v.status !== input.status) return false;
      return true;
    })
    .map((r) => ({ ...r.value, episodeUri: r.uri }));
  return { items, cursor: resp.cursor, total: items.length };
}

// ─── Coverage ───────────────────────────────────────────────────────

async function countAll<T>(e: Etzhayyim, collection: string, maxScan: number, onRow: (v: T) => void): Promise<number> {
  let cursor: string | undefined;
  let scanned = 0;
  while (scanned < maxScan) {
    const page = await e.read<T>({ collection, cursor, limit: PAGE_LIMIT });
    for (const r of page.records) {
      if (scanned >= maxScan) break;
      onRow(r.value);
      scanned += 1;
    }
    if (scanned >= maxScan || !page.cursor || page.records.length < PAGE_LIMIT) break;
    cursor = page.cursor;
  }
  return scanned;
}

export async function coverage(e: Etzhayyim, input: CoverageInput = {}): Promise<CoverageOutput> {
  const maxScan = Math.min(input.maxScan ?? DEFAULT_MAX_SCAN, DEFAULT_MAX_SCAN);
  const workCount = await countAll<WorkRecord>(e, WORK_COLLECTION, maxScan, () => {});
  const episodesByStatus: Record<string, number> = {};
  const episodeCount = await countAll<EpisodeRecord>(e, EPISODE_COLLECTION, maxScan, (v) => {
    episodesByStatus[v.status] = (episodesByStatus[v.status] ?? 0) + 1;
  });
  return {
    workCount,
    episodeCount,
    episodesByStatus,
    truncated: workCount >= maxScan || episodeCount >= maxScan,
  };
}
