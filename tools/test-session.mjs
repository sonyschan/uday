import session from '../api/session.js';
import { seal } from '../api/_lib.js';
const ADDR = '0x2b535697a5febdf96012f5a60af530bad52d462d';
const SECRET = 's'.repeat(32);
const mkRes = () => { const r = { code: 0, headers: {}, body: '' };
  r.status = c => { r.code = c; return r; };
  r.setHeader = (k, v) => { r.headers[k.toLowerCase()] = v; return r; };
  r.end = b => { if (b !== undefined) r.body = String(b); return r; }; return r; };
const cookie = 'uday_s=' + seal({ addr: ADDR, exp: 2e9 }, SECRET);
Object.assign(process.env, { X_STATE_SECRET: SECRET, GITHUB_REPO: 'sonyschan/uday' });

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : fail++; console.log((c ? '  ok   ' : '  FAIL ') + n + (c ? '' : '  <- ' + e)); };

// the repo says this wallet is linked
const real = globalThis.fetch;
globalThis.fetch = async () => ({ ok: true, json: async () => ({
  content: Buffer.from(JSON.stringify({ [ADDR]: { handle: 'someone', avatar: '' } })).toString('base64') }) });
let r = mkRes(); await session({ method: 'GET', query: {}, headers: { cookie } }, r);
let j = JSON.parse(r.body);
ok('session GET returns the wallet\'s link', j.addr === ADDR && j.x && j.x.handle === 'someone', r.body);
ok('and is never cached', /no-store/.test(r.headers['cache-control'] || ''), r.headers['cache-control']);

// a wallet with no link gets null, not an error
globalThis.fetch = async () => ({ ok: true, json: async () => ({
  content: Buffer.from(JSON.stringify({ '0xdead': { handle: 'x' } })).toString('base64') }) });
r = mkRes(); await session({ method: 'GET', query: {}, headers: { cookie } }, r);
ok('no link -> x is null', JSON.parse(r.body).x === null, r.body);

// GitHub down must not break signing in
globalThis.fetch = async () => { throw new Error('github is down'); };
r = mkRes(); await session({ method: 'GET', query: {}, headers: { cookie } }, r);
j = JSON.parse(r.body);
ok('github unreachable -> still reports the session', r.code === 200 && j.addr === ADDR && j.x === null, r.body);

// and no session means no lookup at all
r = mkRes(); await session({ method: 'GET', query: {}, headers: {} }, r);
ok('no session -> addr null, no lookup', JSON.parse(r.body).addr === null, r.body);
globalThis.fetch = real;
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
