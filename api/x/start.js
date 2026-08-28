// Step one of linking an X account to a wallet.
//
// The wallet is already proven: signing in put a signed session cookie on
// .uday.gift, and that is what says which wallet is asking. This endpoint used
// to demand its own personal_sign because there WAS no sign-in — which is how
// linking an X account ended up needing two approvals and a paragraph to
// explain them.
import {
  seal, cookie, pkceVerifier, pkceChallenge, udayWhole, bounce, b64url,
} from '../_lib.js';
import { sessionAddr } from '../session.js';
import { randomBytes } from 'node:crypto';

export default async function handler(req, res) {
  const q = req.query || {};
  // parsed FIRST, because every failure below has to be able to send the
  // visitor back to the room they pressed the button in
  // — only ever a path on this site: a full URL would make this an open
  // redirect that arrives wearing our domain
  const back = /^\/[A-Za-z0-9\-/_]{0,64}$/.test(String(q.back || '')) ? String(q.back) : '/c';

  const {
    X_OAUTH_CLIENT_ID: CLIENT_ID,
    X_STATE_SECRET: SECRET,
    X_OAUTH_REDIRECT: REDIRECT,
  } = process.env;
  if (!CLIENT_ID || !SECRET) return bounce(res, back, 'config', 'missing client id or state secret');

  const addr = sessionAddr(req, SECRET);
  if (!addr) return bounce(res, back, 'signin', 'no session');

  // Same floor the community contract enforces for joining. It is not really
  // about spam: a wallet with no uDAY has no day on any calendar, so there is
  // nothing for an X account to stand next to.
  let whole;
  try { whole = await udayWhole(addr); }
  catch (e) { return bounce(res, back, 'chain', e.message); }
  if (whole < 1n) return bounce(res, back, 'nouday');

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
