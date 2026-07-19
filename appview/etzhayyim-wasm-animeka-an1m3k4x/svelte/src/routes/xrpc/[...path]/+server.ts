import type { RequestHandler } from '@sveltejs/kit';

// DNS-only A record: lg-animeka.etzhayyim.com → 108.61.207.153 (nginx Ingress, mitama-udf).
// CF Workers override the host header with the URL hostname, so we use the hostname directly.
const LG_ANIMEKA_BASE = 'http://lg-animeka.etzhayyim.com';
const NSID_PREFIX = 'com.etzhayyim.animeka.';

function noStore(body: unknown, init: ResponseInit = {}): Response {
	const headers = new Headers(typeof init.headers === 'object' ? init.headers : {});
	headers.set('cache-control', 'no-store');
	headers.set('content-type', 'application/json');
	return new Response(JSON.stringify(body), { ...init, headers });
}

export const POST: RequestHandler = async ({ params, request }) => {
	const nsid = params.path ?? '';
	if (!nsid.startsWith(NSID_PREFIX)) {
		return noStore({ error: 'UnknownMethod', nsid }, { status: 404 });
	}

	let body: unknown = {};
	try {
		const text = await request.text();
		body = text ? JSON.parse(text) : {};
	} catch {
		return noStore({ error: 'InvalidJson' }, { status: 400 });
	}

	const upstream = await fetch(`${LG_ANIMEKA_BASE}/xrpc/${nsid}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

	const text = await upstream.text();
	return new Response(text, {
		status: upstream.status,
		headers: {
			'content-type': upstream.headers.get('content-type') ?? 'application/json',
			'cache-control': 'no-store'
		}
	});
};

export const GET: RequestHandler = async ({ params, url }) => {
	const nsid = params.path ?? '';
	if (!nsid.startsWith(NSID_PREFIX)) {
		return noStore({ error: 'UnknownMethod', nsid }, { status: 404 });
	}

	const qs = url.searchParams.toString();
	const upstream = await fetch(`${LG_ANIMEKA_BASE}/xrpc/${nsid}${qs ? '?' + qs : ''}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(Object.fromEntries(url.searchParams))
	});

	const text = await upstream.text();
	return new Response(text, {
		status: upstream.status,
		headers: {
			'content-type': upstream.headers.get('content-type') ?? 'application/json',
			'cache-control': 'no-store'
		}
	});
};
