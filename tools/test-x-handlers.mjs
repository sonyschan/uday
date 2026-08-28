import start from '../api/x/start.js';
import session, { signInMessage } from '../api/session.js';
import callback from '../api/x/callback.js';
import unlink from '../api/x/unlink.js';
import { seal } from '../api/_lib.js';
import { execSync, execFileSync } from 'node:child_process';

let pass = 0, fail = 0;
const ok = (n, c, extra) => { c ? pass++ : fail++; console.log((c ? '  ok   ' : '  FAIL ') + n + (c ? '' : '  <- ' + extra)); };

const KEY = '0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318';
const ADDR = execSync(`cast wallet address --private-key ${KEY}`).toString().trim().toLowerCase();
const OTHER = '0x1111111111111111111111111111111111111111';
const sign = m => execFileSync('cast', ['wallet', 'sign', '--private-key', KEY, m]).toString().trim();

function mkRes() {
  const r = { code: 0, headers: {}, body: '' };
  r.status = c => { r.code = c; return r; };
  r.setHeader = (k, v) => { r.headers[k.toLowerCase()] = v; return r; };
  r.end = b => { if (b !== undefined) r.body = String(b); return r; };
  return r;
}
const ENV = {
  X_OAUTH_CLIENT_ID: 'cid', X_OAUTH_CLIENT_SECRET: 'csec',
  X_STATE_SECRET: 's'.repeat(32), X_OAUTH_REDIRECT: 'https://uday.gift/api/x/callback',
  GITHUB_TOKEN: 'ghtok', GITHUB_REPO: 'sonyschan/uday',
};
const withEnv = async (env, fn) => {
  const old = { ...process.env };
  Object.assign(process.env, env);
  try { return await fn(); } finally { process.env = old; }
};

// ---- session ----
await withEnv({ X_STATE_SECRET: '' }, async () => {
  const r = mkRes(); await session({ method: 'POST', query: {}, headers: {} }, r);
  ok('session: unconfigured -> 503', r.code === 503, r.code);
});
let COOKIE = null;
await withEnv(ENV, async () => {
  const ts = Date.now();
  const sig = sign(signInMessage(ADDR, ts));
  let r = mkRes();
  await session({ method: 'POST', query: { addr: ADDR, sig, ts: ts - 3600000 }, headers: {} }, r);
  ok('session: stale signature -> 400', r.code === 400, r.code);

  r = mkRes();
  await session({ method: 'POST', query: { addr: OTHER, sig, ts }, headers: {} }, r);
  ok('session: signature for a DIFFERENT wallet -> 403', r.code === 403, r.code + ' ' + r.body);

  r = mkRes();
  await session({ method: 'POST', query: { addr: ADDR, sig, ts }, headers: {} }, r);
  ok('session: valid signature -> 200 + cookie', r.code === 200 && /uday_s=/.test(r.headers['set-cookie'] || ''), r.code);
  ok('session cookie is HttpOnly+Secure+Lax and shared',
     /HttpOnly/.test(r.headers['set-cookie']) && /Secure/.test(r.headers['set-cookie']) &&
     /SameSite=Lax/.test(r.headers['set-cookie']) && /Domain=\.uday\.gift/.test(r.headers['set-cookie']),
     r.headers['set-cookie']);
  COOKIE = (r.headers['set-cookie'] || '').split(';')[0];

  r = mkRes(); await session({ method: 'GET', query: {}, headers: { cookie: COOKIE } }, r);
  ok('session: GET reports the signed-in address', JSON.parse(r.body).addr === ADDR, r.body);

  r = mkRes(); await session({ method: 'GET', query: {}, headers: {} }, r);
  ok('session: GET with no cookie reports null', JSON.parse(r.body).addr === null, r.body);

  r = mkRes(); await session({ method: 'DELETE', query: {}, headers: { cookie: COOKIE } }, r);
  ok('session: DELETE clears the cookie', /Max-Age=0/.test(r.headers['set-cookie']), r.headers['set-cookie']);

  // a forged cookie must not become a session
  const forged = 'uday_s=' + seal({ addr: OTHER, exp: 2e9 }, 'not-the-secret');
  r = mkRes(); await session({ method: 'GET', query: {}, headers: { cookie: forged } }, r);
  ok('session: a cookie sealed with the wrong secret is refused', JSON.parse(r.body).addr === null, r.body);

  // an expired one either
  const stale = 'uday_s=' + seal({ addr: ADDR, exp: 1 }, ENV.X_STATE_SECRET);
  r = mkRes(); await session({ method: 'GET', query: {}, headers: { cookie: stale } }, r);
  ok('session: an expired session is refused', JSON.parse(r.body).addr === null, r.body);
});

// ---- start ----
await withEnv({ X_OAUTH_CLIENT_ID: '', X_STATE_SECRET: '' }, async () => {
  const r = mkRes(); await start({ query: {}, headers: {} }, r);
  ok('start: unconfigured -> bounces back, not a text page',
     r.code === 302 && /#x-err=config$/.test(r.headers.location || ''), r.code + ' ' + r.headers.location);
});
await withEnv(ENV, async () => {
  let r = mkRes(); await start({ query: { back: '/c/unipeg' }, headers: {} }, r);
  ok('start: no session -> #x-err=signin',
     r.code === 302 && /#x-err=signin$/.test(r.headers.location || ''), r.code + ' ' + r.headers.location);

  r = mkRes(); await start({ query: { back: 'https://evil.example/x' }, headers: {} }, r);
  ok('start: bounce refuses an absolute `back`', r.headers.location === '/c#x-err=signin', r.headers.location);

  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ result: '0x0' }) });
  r = mkRes(); await start({ query: { back: '/c/unipeg' }, headers: { cookie: COOKIE } }, r);
  ok('start: signed in but holds 0 uDAY -> #x-err=nouday',
     r.code === 302 && /#x-err=nouday$/.test(r.headers.location || ''), r.code + ' ' + r.headers.location);

  globalThis.fetch = async () => ({ ok: true, json: async () => ({ result: '0x' + (5n * 10n ** 18n).toString(16) }) });
  r = mkRes(); await start({ query: { back: '/c/unipeg' }, headers: { cookie: COOKIE } }, r);
  const loc = r.headers.location || '';
  ok('start: signed-in holder -> 302 to x.com authorize',
     r.code === 302 && loc.startsWith('https://x.com/i/oauth2/authorize'), r.code + ' ' + r.body + loc.slice(0, 60));
  const u = new URL(loc || 'https://x/');
  ok('start: PKCE S256 challenge present',
     u.searchParams.get('code_challenge_method') === 'S256' && (u.searchParams.get('code_challenge') || '').length > 20);
  ok('start: scope is read-only, no offline', u.searchParams.get('scope') === 'tweet.read users.read', u.searchParams.get('scope'));
  ok('start: state cookie is HttpOnly+Secure+Lax',
     /HttpOnly/.test(r.headers['set-cookie']) && /Secure/.test(r.headers['set-cookie']) && /SameSite=Lax/.test(r.headers['set-cookie']));
  globalThis.fetch = realFetch;
});

// ---- callback ----
await withEnv(ENV, async () => {
  let r = mkRes(); await callback({ query: { code: 'c', state: 's' }, headers: {} }, r);
  ok('callback: no cookie -> /c#x-err=state', r.code === 302 && r.headers.location === '/c#x-err=state', r.code + ' ' + r.headers.location);

  const jar = { addr: ADDR, verifier: 'v', state: 'realstate', back: '/c/unipeg' };
  const cookieHdr = 'uday_xo=' + seal(jar, ENV.X_STATE_SECRET);
  r = mkRes(); await callback({ query: { code: 'c', state: 'WRONG' }, headers: { cookie: cookieHdr } }, r);
  ok('callback: state mismatch -> back#x-err=state', r.code === 302 && r.headers.location === '/c/unipeg#x-err=state', r.code + ' ' + r.headers.location);

  r = mkRes(); await callback({ query: { error: 'access_denied' }, headers: { cookie: cookieHdr } }, r);
  ok('callback: user cancelled -> back#x-err=cancelled (not the success shape)',
     r.code === 302 && r.headers.location === '/c/unipeg#x-err=cancelled', r.headers.location);

  // happy path, every network call intercepted
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: (init && init.method) || 'GET', init });
    if (String(url).includes('oauth2/token')) return { ok: true, status: 200, json: async () => ({ access_token: 'tok' }) };
    if (String(url).includes('users/me')) return { ok: true, status: 200, json: async () => ({ data: { username: 'h2crypto_eth', name: 'Sony', profile_image_url: 'https://pbs.twimg.com/profile_images/1/a_normal.jpg' } }) };
    if (String(url).includes('/contents/')) {
      if ((init && init.method) === 'PUT') return { ok: true, status: 200, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => ({ sha: 'abc', content: Buffer.from('{}').toString('base64') }) };
    }
    return { ok: false, status: 500, json: async () => ({}) };
  };
  r = mkRes(); await callback({ query: { code: 'c', state: 'realstate' }, headers: { cookie: cookieHdr } }, r);
  ok('callback: happy path -> back with the handle', r.code === 302 && r.headers.location === '/c/unipeg#x=h2crypto_eth', r.code + ' ' + r.headers.location);
  const put = calls.find(c => c.method === 'PUT');
  const written = put ? JSON.parse(Buffer.from(JSON.parse(put.init.body).content, 'base64').toString()) : null;
  ok('callback: committed the binding', !!written && written[ADDR] && written[ADDR].handle === 'h2crypto_eth', JSON.stringify(written));
  ok('callback: stored the _bigger avatar crop', written && written[ADDR].avatar.endsWith('_bigger.jpg'), written && written[ADDR].avatar);
  ok('callback: token exchange tried Basic auth first', calls[0].init.headers.Authorization.startsWith('Basic '));
  ok('callback: cookie is burned', /Max-Age=0/.test(r.headers['set-cookie']));


  // X's token endpoint rejected a correct Basic header on a client_credentials
  // probe and wanted the pair in the body — so the fallback has to work
  let seen = [];
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes('oauth2/token')) {
      seen.push(init.headers.Authorization ? 'basic' : 'body');
      if (init.headers.Authorization) return { ok: false, status: 400, text: async () => 'Missing required parameter [client_secret].' };
      const b = new URLSearchParams(init.body);
      if (b.get('client_secret') !== 'csec' || b.get('client_id') !== 'cid')
        return { ok: false, status: 401, text: async () => 'no creds in body' };
      return { ok: true, status: 200, json: async () => ({ access_token: 'tok' }) };
    }
    if (u.includes('users/me')) return { ok: true, status: 200, json: async () => ({ data: { username: 'h2crypto_eth', name: 'S', profile_image_url: 'https://pbs.twimg.com/profile_images/1/a_normal.jpg' } }) };
    if ((init && init.method) === 'PUT') return { ok: true, status: 200, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ sha: 'a', content: Buffer.from('{}').toString('base64') }) };
  };
  r = mkRes(); await callback({ query: { code: 'c', state: 'realstate' }, headers: { cookie: cookieHdr } }, r);
  ok('callback: Basic rejected -> retries with body credentials',
     r.code === 302 && seen.join(',') === 'basic,body', r.code + ' ' + seen.join(','));
  globalThis.fetch = realFetch;

  // the handle already belongs to another wallet: refuse, do not move it
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes('oauth2/token')) return { ok: true, status: 200, json: async () => ({ access_token: 'tok' }) };
    if (u.includes('users/me')) return { ok: true, status: 200, json: async () => ({ data: { username: 'h2crypto_eth', name: 'S', profile_image_url: 'https://pbs.twimg.com/profile_images/1/a_normal.jpg' } }) };
    if ((init && init.method) === 'PUT') { throw new Error('TEST: it tried to write'); }
    return { ok: true, status: 200, json: async () => ({ sha: 'a',
      content: Buffer.from(JSON.stringify({ '0xsomebodyelse': { handle: 'h2crypto_eth' } })).toString('base64') }) };
  };
  r = mkRes(); await callback({ query: { code: 'c', state: 'realstate' }, headers: { cookie: cookieHdr } }, r);
  ok('callback: a handle held by another wallet -> #x-err=taken, no write',
     r.code === 302 && /#x-err=taken$/.test(r.headers.location || ''), r.code + ' ' + r.headers.location);

  // a hostile /2/users/me response must never reach the file
  globalThis.fetch = async (url, init) => {
    if (String(url).includes('oauth2/token')) return { ok: true, status: 200, json: async () => ({ access_token: 'tok' }) };
    if (String(url).includes('users/me')) return { ok: true, status: 200, json: async () => ({ data: { username: '<img src=x>', name: 'x', profile_image_url: 'javascript:alert(1)' } }) };
    return { ok: true, status: 200, json: async () => ({ sha: 'a', content: Buffer.from('{}').toString('base64') }) };
  };
  r = mkRes(); await callback({ query: { code: 'c', state: 'realstate' }, headers: { cookie: cookieHdr } }, r);
  ok('callback: unusable handle -> back#x-err=profile', r.code === 302 && r.headers.location === '/c/unipeg#x-err=profile', r.code + ' ' + r.headers.location);
  globalThis.fetch = realFetch;
});

// ---- unlink ----
await withEnv(ENV, async () => {
  let r = mkRes(); await unlink({ query: {}, headers: {} }, r);
  ok('unlink: no session -> 401', r.code === 401, r.code);

  const realFetch = globalThis.fetch;
  let body = null;
  globalThis.fetch = async (url, init) => {
    if ((init && init.method) === 'PUT') { body = JSON.parse(init.body); return { ok: true, status: 200, json: async () => ({}) }; }
    return { ok: true, status: 200, json: async () => ({ sha: 'a',
      content: Buffer.from(JSON.stringify({ [ADDR]: { handle: 'x' }, '0xother': { handle: 'y' } })).toString('base64') }) };
  };
  r = mkRes(); await unlink({ query: {}, headers: { cookie: COOKIE } }, r);
  const after = body ? JSON.parse(Buffer.from(body.content, 'base64').toString()) : null;
  ok('unlink: a session removes only that wallet',
     r.code === 200 && after && !after[ADDR] && after['0xother'], JSON.stringify(after));
  globalThis.fetch = realFetch;
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
