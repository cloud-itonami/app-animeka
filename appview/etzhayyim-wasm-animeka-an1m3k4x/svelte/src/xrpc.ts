/** Minimal XRPC helper — talks to the same-origin /xrpc/* endpoint. */

const XRPC_BASE = '/xrpc';
// Blob fetching goes directly to the PDS — animeka's /xrpc proxy only handles
// com.etzhayyim.animeka.* and would 404 on com.atproto.sync.getBlob.
const PDS_BASE = 'https://atproto.etzhayyim.com';

// Autopilot blobs are uploaded via legacy-trust header (no JWT session),
// so auth.userDid is undefined and PDS stores them under "anonymous".
const BLOB_DID = 'anonymous';

/** Blob URL helper. com.atproto.sync.getBlob requires both did + cid. */
export function blobUrl(cid?: string | null, did: string = BLOB_DID): string {
  if (!cid) return '';
  const params = new URLSearchParams({ did, cid });
  return `${PDS_BASE}/xrpc/com.atproto.sync.getBlob?${params.toString()}`;
}

/** CSS background-image fragment with fallback to a flat block. */
export function blobBg(cid?: string | null, fallback = '#1d2430'): string {
  return cid ? `url(${blobUrl(cid)}) center/cover` : fallback;
}

/**
 * Animeka stores domain fields in two places: typed columns on
 * vertex_animeka (snake_case) and a `props` JSON blob (original camelCase
 * payload from addCut/etc.). The read view exposes both. Most camelCase
 * fields like `dialogueSummary` aren't in the typed-column allow-list, so
 * UI components must look in `props` as a fallback. This helper parses
 * `props` once and returns a getter that prefers typed snake_case if set,
 * falling back to the camelCase key inside props.
 */
export function flatProps(row: Record<string, unknown>): (snake: string, camel?: string) => unknown {
  let parsed: Record<string, unknown> | null = null;
  const propsRaw = row.props;
  if (typeof propsRaw === 'string' && propsRaw.length > 0) {
    try { parsed = JSON.parse(propsRaw) as Record<string, unknown>; } catch { parsed = null; }
  } else if (propsRaw && typeof propsRaw === 'object') {
    parsed = propsRaw as Record<string, unknown>;
  }
  return (snake, camel) => {
    const direct = row[snake];
    if (direct !== undefined && direct !== null && direct !== '') return direct;
    if (!parsed) return undefined;
    const c = camel ?? snake.replace(/_([a-z])/g, (_, ch) => ch.toUpperCase());
    return parsed[c] ?? parsed[snake];
  };
}

export async function atQuery<T = unknown>(
  nsid: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  // PDS XRPC routes com.etzhayyim.animeka.* as POST-only regardless of lexicon type.
  // Using POST + JSON body keeps both query and procedure call sites uniform.
  const resp = await fetch(`${XRPC_BASE}/${nsid}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) throw new Error(`XRPC ${nsid} failed: ${resp.status}`);
  return resp.json() as Promise<T>;
}

export async function atProcedure<T = unknown>(
  nsid: string,
  body: Record<string, unknown> = {},
): Promise<T> {
  const resp = await fetch(`${XRPC_BASE}/${nsid}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`XRPC ${nsid} failed: ${resp.status}`);
  return resp.json() as Promise<T>;
}
