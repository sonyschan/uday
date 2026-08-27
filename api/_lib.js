// Shared helpers for the /api functions. Files starting with _ are not routes.
//
// These exist for ONE reason: X's OAuth endpoints send no CORS headers at all
// (measured — POST /2/oauth2/token answers 400 and GET /2/users/me answers 403,
// neither with access-control-allow-origin), so the token exchange cannot
// happen in a browser. Everything else on this site is still static.
import { secp256k1 } from '@noble/curves/secp256k1';
import { keccak_256 } from '@noble/hashes/sha3';
import { createHmac, timingSafeEqual, randomBytes, createHash } from 'node:crypto';

export const UDAY = '0x359211bb6b8CAbcE02DCBEc1c55B50f2EC884146';
export const RPC = process.env.ROBINHOOD_RPC_URL ||
                   'https://rpc.mainnet.chain.robinhood.com/rpc';

const enc = new TextEncoder();

export function hexToBytes(h) {
  h = h.startsWith('0x') ? h.slice(2) : h;
  if (h.length % 2) throw new Error('odd hex');
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
  return out;
}
export const bytesToHex = b => [...b].map(x => x.toString(16).padStart(2, '0')).join('');

/// Recovers the signer of an EIP-191 personal_sign. This is the only thing
/// standing between a visitor and attaching their X account to somebody else's
/// wallet, so it is verified in tests against signatures produced by an
/// independent implementation (`cast wallet sign`), never trusted on reading.
export function recoverPersonalSign(message, sigHex) {
  const body = enc.encode(message);
  // the prefix counts BYTES, not characters — a non-ASCII message signed by a
  // wallet and verified by a char-length implementation recovers garbage
  const prefix = enc.encode('\x19Ethereum Signed Message:\n' + body.length);
  const full = new Uint8Array(prefix.length + body.length);
  full.set(prefix, 0);
  full.set(body, prefix.length);
  const digest = keccak_256(full);

  const sig = hexToBytes(sigHex);
  if (sig.length !== 65) throw new Error('bad signature length');
  let v = sig[64];
  if (v >= 27) v -= 27;
  if (v !== 0 && v !== 1) throw new Error('bad recovery id');

  const s = secp256k1.Signature
    .fromCompact(sig.slice(0, 64))
    .addRecoveryBit(v);
  const pub = s.recoverPublicKey(digest).toRawBytes(false).slice(1);  // drop the 0x04 tag
  return '0x' + bytesToHex(keccak_256(pub).slice(-20));
}

/// State that has to survive a round trip through x.com without a database:
/// signed, not encrypted — nothing in it is secret, it only must not be forged.
export function seal(obj, secret) {
  const body = Buffer.from(JSON.stringify(obj)).toString('base64url');
  const mac = createHmac('sha256', secret).update(body).digest('base64url');
  return body + '.' + mac;
}
export function unseal(token, secret) {
  if (typeof token !== 'string' || !token.includes('.')) return null;
  const [body, mac] = token.split('.');
  const want = createHmac('sha256', secret).update(body).digest('base64url');
  const a = Buffer.from(mac || ''), b = Buffer.from(want);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  try { return JSON.parse(Buffer.from(body, 'base64url').toString()); } catch { return null; }
}

export const b64url = b => Buffer.from(b).toString('base64url');
export const pkceVerifier = () => b64url(randomBytes(32));
export const pkceChallenge = v => b64url(createHash('sha256').update(v).digest());

export function cookie(name, value, maxAge) {
  // Lax survives the top-level GET that x.com redirects us back with, and
  // refuses to ride along on anyone else's cross-site request.
  return `${name}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;
}
export function readCookie(req, name) {
  const raw = req.headers.cookie || '';
  const m = raw.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return m ? m[1] : null;
}

/// Whole uDAY held. The same floor the community contract enforces for joining,
/// applied here so the commit-back path cannot be driven by a stranger: linking
/// costs you a token you had to buy, exactly like everything else on this site.
export async function udayWhole(addr) {
  const data = '0x70a08231' + addr.toLowerCase().replace('0x', '').padStart(64, '0');
  const r = await fetch(RPC, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_call',
                           params: [{ to: UDAY, data }, 'latest'] }),
  });
  const j = await r.json();
  if (!j.result || j.result === '0x') return 0n;
  return BigInt(j.result) / (10n ** 18n);
}

/// An X handle as X itself defines one. Anything else never reaches the file.
export const okHandle = h => typeof h === 'string' && /^[A-Za-z0-9_]{1,15}$/.test(h);
/// Avatars are hotlinked from X's own CDN and nowhere else, so a compromised or
/// unexpected value cannot point the page at an arbitrary host.
export const okAvatar = u => typeof u === 'string' &&
  /^https:\/\/pbs\.twimg\.com\/[\w./-]{1,180}$/.test(u);

export function fail(res, code, why) {
  res.status(code).setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.end(why);
}
