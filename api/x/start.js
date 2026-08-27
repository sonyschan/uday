// Step one of linking an X account to a wallet.
//
// The wallet has to PROVE itself here. Without that, anyone could call this
// endpoint with somebody else's address and hang their own X handle on it —
// the page would then show a stranger's account next to that person's day.
// So: a personal_sign the visitor produced seconds ago, recovered server-side,
// and a uDAY balance, which is the same floor joining a room already charges.
import {
  recoverPersonalSign, seal, cookie, pkceVerifier, pkceChallenge,
  udayWhole, fail, b64url,
} from '../_lib.js';
import { randomBytes } from 'node:crypto';

/// The exact text the wallet signs. Shared verbatim with the page — one
/// character apart and the recovered address is a different, valid-looking
/// wallet, which is the worst possible failure here.
export const linkMessage = (addr, ts) =>
  'uday.gift\n\n' +
  'Link an X account to this wallet.\n\n' +
  'wallet: ' + addr.toLowerCase() + '\n' +
  'issued: ' + ts + '\n\n' +
  'Signing proves the wallet is yours. It costs no gas, moves nothing, and\n' +
  'authorises nothing else.';

const FRESH_MS = 10 * 60 * 1000;

export default async function handler(req, res) {
  const {
    X_OAUTH_CLIENT_ID: CLIENT_ID,
    X_STATE_SECRET: SECRET,
    X_OAUTH_REDIRECT: REDIRECT,
  } = process.env;
  if (!CLIENT_ID || !SECRET) return fail(res, 503, 'X login is not configured');

  const q = req.query || {};
  const addr = String(q.addr || '').toLowerCase();
  const sig = String(q.sig || '');
  const ts = Number(q.ts || 0);
  // only ever a path on this site: a full URL here would make this an open
  // redirect that arrives wearing our domain
  const back = /^\/[A-Za-z0-9\-/_]{0,64}$/.test(String(q.back || '')) ? String(q.back) : '/c';

  if (!/^0x[0-9a-f]{40}$/.test(addr)) return fail(res, 400, 'bad address');
  if (!Number.isFinite(ts) || Math.abs(Date.now() - ts) > FRESH_MS)
    return fail(res, 400, 'that signature is stale — start again');

  let signer;
  try { signer = recoverPersonalSign(linkMessage(addr, ts), sig); }
  catch { return fail(res, 400, 'bad signature'); }
  if (signer.toLowerCase() !== addr) return fail(res, 403, 'signature does not match that wallet');

  // Same floor the community contract enforces for joining. It is not really
  // about spam: a wallet with no uDAY has no day on any calendar, so there is
  // nothing for an X account to stand next to.
  let whole;
  try { whole = await udayWhole(addr); }
  catch { return fail(res, 503, 'could not read the chain — try again'); }
  if (whole < 1n) return fail(res, 403, 'linking X needs at least 1 uDAY');

  const verifier = pkceVerifier();
  const state = b64url(randomBytes(16));
  const redirect = REDIRECT || 'https://uday.gift/api/x/callback';

  // Signed, not encrypted — none of it is secret, it only must not be forged.
  res.setHeader('Set-Cookie', cookie('uday_xo', seal({ addr, verifier, state, back }, SECRET), 900));
  const u = new URL('https://x.com/i/oauth2/authorize');
  u.searchParams.set('response_type', 'code');
  u.searchParams.set('client_id', CLIENT_ID);
  u.searchParams.set('redirect_uri', redirect);
  // users.read needs tweet.read alongside it; nothing here can post, and no
  // offline.access means we never hold a refresh token for anybody
  u.searchParams.set('scope', 'tweet.read users.read');
  u.searchParams.set('state', state);
  u.searchParams.set('code_challenge', pkceChallenge(verifier));
  u.searchParams.set('code_challenge_method', 'S256');
  res.status(302).setHeader('Location', u.toString());
  res.end();
}
