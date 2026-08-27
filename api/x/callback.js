// Step two: X hands back a code, we trade it for a token, read who it belongs
// to, and write the binding into the repo.
//
// The repo IS the database. Every link is a commit with a timestamp and a
// diff, which keeps the promise the rest of this project makes — anything
// dynamic either ships as a commit or is not built. It also means no private
// store exists that a stranger cannot see.
import { unseal, readCookie, cookie, okHandle, okAvatar, fail } from '../_lib.js';

const FILE = 'data/x-links.json';

async function gh(path, init) {
  const r = await fetch('https://api.github.com/repos/' + process.env.GITHUB_REPO + path, {
    ...init,
    headers: {
      Authorization: 'Bearer ' + process.env.GITHUB_TOKEN,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'uday-x-link',
      ...(init && init.headers),
    },
  });
  return r;
}

/// Read-modify-write against a file an hourly bot also touches, so a losing
/// write retries rather than clobbering. Three attempts is plenty at this
/// volume; failing loudly beats a silent overwrite of somebody else's link.
async function commitLink(addr, entry) {
  for (let attempt = 0; attempt < 3; attempt++) {
    let sha = null, links = {};
    const cur = await gh('/contents/' + FILE);
    if (cur.status === 200) {
      const j = await cur.json();
      sha = j.sha;
      try { links = JSON.parse(Buffer.from(j.content, 'base64').toString()) || {}; } catch { links = {}; }
    } else if (cur.status !== 404) {
      throw new Error('github read ' + cur.status);
    }

    // One X account cannot stand on two wallets: the newer claim wins and the
    // older is dropped, or the same handle would appear twice on one calendar
    // with only one of them real.
    for (const k of Object.keys(links)) {
      if (k !== addr && links[k] && links[k].handle &&
          links[k].handle.toLowerCase() === entry.handle.toLowerCase()) delete links[k];
    }
    links[addr] = entry;

    const ordered = {};
    for (const k of Object.keys(links).sort()) ordered[k] = links[k];
    const body = JSON.stringify(ordered, null, 1) + '\n';

    const put = await gh('/contents/' + FILE, {
      method: 'PUT',
      body: JSON.stringify({
        message: 'x-links: @' + entry.handle + ' -> ' + addr.slice(0, 10),
        content: Buffer.from(body).toString('base64'),
        ...(sha ? { sha } : {}),
      }),
    });
    if (put.ok) return true;
    if (put.status !== 409 && put.status !== 422) throw new Error('github write ' + put.status);
  }
  throw new Error('github write kept conflicting');
}

export default async function handler(req, res) {
  const {
    X_OAUTH_CLIENT_ID: CLIENT_ID,
    X_OAUTH_CLIENT_SECRET: CLIENT_SECRET,
    X_STATE_SECRET: SECRET,
    X_OAUTH_REDIRECT: REDIRECT,
    GITHUB_TOKEN, GITHUB_REPO,
  } = process.env;
  if (!CLIENT_ID || !CLIENT_SECRET || !SECRET || !GITHUB_TOKEN || !GITHUB_REPO)
    return fail(res, 503, 'X login is not configured');

  const q = req.query || {};
  const jar = unseal(readCookie(req, 'uday_xo'), SECRET);
  // burn the cookie whatever happens next — a state that survives one attempt
  // is a state that can be replayed
  res.setHeader('Set-Cookie', cookie('uday_xo', '', 0));

  if (!jar) return fail(res, 400, 'this link expired — start again from the room');
  if (q.error) return res.status(302).setHeader('Location', jar.back + '#x=cancelled').end();
  if (!q.code || String(q.state || '') !== jar.state)
    return fail(res, 400, 'state mismatch');

  const form = new URLSearchParams({
    grant_type: 'authorization_code',
    code: String(q.code),
    redirect_uri: REDIRECT || 'https://uday.gift/api/x/callback',
    code_verifier: jar.verifier,
  });
  // X documents Basic auth for a confidential client here, and that is tried
  // first. But its token endpoint is genuinely picky about how credentials are
  // presented — a client_credentials probe rejected a correct Basic header with
  // "Missing required parameter [client_secret]" and only accepted the pair in
  // the body — so a rejection falls through to the body form rather than
  // stranding everyone behind a 502 nobody can debug from a browser.
  const basic = Buffer.from(CLIENT_ID + ':' + CLIENT_SECRET).toString('base64');
  const post = extra => fetch('https://api.x.com/2/oauth2/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...extra.headers },
    body: extra.body,
  });
  let tok = await post({ headers: { Authorization: 'Basic ' + basic }, body: form });
  if (tok.status === 400 || tok.status === 401) {
    const withCreds = new URLSearchParams(form);
    withCreds.set('client_id', CLIENT_ID);
    withCreds.set('client_secret', CLIENT_SECRET);
    tok = await post({ headers: {}, body: withCreds });
  }
  if (!tok.ok) {
    const why = await tok.text().catch(() => '');
    return fail(res, 502, 'X refused the token exchange (' + tok.status + ') ' + why.slice(0, 200));
  }
  const { access_token } = await tok.json();
  if (!access_token) return fail(res, 502, 'X returned no token');

  const me = await fetch('https://api.x.com/2/users/me?user.fields=profile_image_url,name', {
    headers: { Authorization: 'Bearer ' + access_token },
  });
  if (!me.ok) return fail(res, 502, 'could not read that X account (' + me.status + ')');
  const d = (await me.json()).data || {};

  if (!okHandle(d.username)) return fail(res, 502, 'X returned an unusable handle');
  // _normal is X's 48px crop; the page draws these small and pixel-sharp
  const avatar = typeof d.profile_image_url === 'string'
    ? d.profile_image_url.replace('_normal.', '_bigger.') : '';
  const entry = {
    handle: d.username,
    // a display name is arbitrary text from a stranger and the page renders it
    // with textContent, but there is no reason to carry more than fits
    name: typeof d.name === 'string' ? d.name.slice(0, 50) : '',
    avatar: okAvatar(avatar) ? avatar : '',
    at: Math.floor(Date.now() / 1000),
  };

  try { await commitLink(jar.addr, entry); }
  catch (e) { return fail(res, 502, 'linked with X but could not record it: ' + e.message); }

  // The commit needs a deploy before the file is public, so the page is told
  // the handle directly and shows it at once rather than looking broken.
  res.status(302).setHeader('Location', jar.back + '#x=' + entry.handle).end();
}
