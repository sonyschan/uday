// Taking the link back off.
//
// This exists because the link is public and permanent-looking: it puts a
// wallet's whole history one click from a name and a face. A door in without
// a door out would make linking a decision nobody should be asked to make
// once. Same proof as linking — only the wallet can undo the wallet.
import { recoverPersonalSign, fail } from '../_lib.js';
import { linkMessage } from './start.js';

const FILE = 'data/x-links.json';
const FRESH_MS = 10 * 60 * 1000;

async function gh(path, init) {
  return fetch('https://api.github.com/repos/' + process.env.GITHUB_REPO + path, {
    ...init,
    headers: {
      Authorization: 'Bearer ' + process.env.GITHUB_TOKEN,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'uday-x-link',
      ...(init && init.headers),
    },
  });
}

export default async function handler(req, res) {
  const { GITHUB_TOKEN, GITHUB_REPO } = process.env;
  if (!GITHUB_TOKEN || !GITHUB_REPO) return fail(res, 503, 'X login is not configured');

  const q = req.query || {};
  const addr = String(q.addr || '').toLowerCase();
  const ts = Number(q.ts || 0);
  if (!/^0x[0-9a-f]{40}$/.test(addr)) return fail(res, 400, 'bad address');
  if (!Number.isFinite(ts) || Math.abs(Date.now() - ts) > FRESH_MS)
    return fail(res, 400, 'that signature is stale — try again');

  let signer;
  try { signer = recoverPersonalSign(linkMessage(addr, ts), String(q.sig || '')); }
  catch { return fail(res, 400, 'bad signature'); }
  if (signer.toLowerCase() !== addr) return fail(res, 403, 'signature does not match that wallet');

  for (let attempt = 0; attempt < 3; attempt++) {
    const cur = await gh('/contents/' + FILE);
    if (cur.status === 404) return res.status(200).end('already gone');
    if (!cur.ok) return fail(res, 502, 'github read ' + cur.status);
    const j = await cur.json();
    let links = {};
    try { links = JSON.parse(Buffer.from(j.content, 'base64').toString()) || {}; } catch { links = {}; }
    if (!links[addr]) return res.status(200).end('already gone');
    delete links[addr];

    const ordered = {};
    for (const k of Object.keys(links).sort()) ordered[k] = links[k];
    const put = await gh('/contents/' + FILE, {
      method: 'PUT',
      body: JSON.stringify({
        message: 'x-links: unlink ' + addr.slice(0, 10),
        content: Buffer.from(JSON.stringify(ordered, null, 1) + '\n').toString('base64'),
        sha: j.sha,
      }),
    });
    if (put.ok) return res.status(200).end('unlinked');
    if (put.status !== 409 && put.status !== 422) return fail(res, 502, 'github write ' + put.status);
  }
  return fail(res, 502, 'github write kept conflicting');
}
