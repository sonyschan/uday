// Signing in.
//
// The site used to have no sign-in at all: the wallet handed the page an
// address, nothing was ever proven to a server, and every action that needed
// proof asked for its own signature. Technically minimal, and incoherent to
// read — the header said "connect" and its opposite said "log out", and a
// paragraph had to explain why something you thought you had logged into kept
// asking you to sign.
//
// So: one signature at the door, and it means what it looks like. The session
// is a signed cookie carrying the address; nothing else about you is stored,
// and it is the ONLY thing this site keeps on a server.
import { recoverPersonalSign, seal, unseal, cookie, readCookie, fail } from './_lib.js';

const FRESH_MS = 10 * 60 * 1000;      // a signature has to be recent
const LIFE_S = 30 * 24 * 3600;        // and the session lasts a month

/// Duplicated verbatim in the page. One character apart and the recovered
/// address is a different, valid-looking wallet — the worst failure here.
export const signInMessage = (addr, ts) =>
  'uday.gift\n\n' +
  'Sign in.\n\n' +
  'wallet: ' + addr.toLowerCase() + '\n' +
  'issued: ' + ts + '\n\n' +
  'This proves the wallet is yours. It costs no gas and moves nothing.';

/// The address a request is signed in as, or null. Every endpoint that acts on
/// someone's behalf goes through this and nothing else.
export function sessionAddr(req, secret) {
  const jar = unseal(readCookie(req, 'uday_s'), secret || 'unset');
  if (!jar || !jar.addr || !jar.exp) return null;
  if (Date.now() / 1000 > jar.exp) return null;
  return String(jar.addr).toLowerCase();
}

export default async function handler(req, res) {
  const SECRET = process.env.X_STATE_SECRET;
  if (!SECRET) return fail(res, 503, 'sign-in is not configured');

  if (req.method === 'DELETE') {
    res.setHeader('Set-Cookie', cookie('uday_s', '', 0, true));
    return res.status(200).end('signed out');
  }

  if (req.method === 'GET') {
    const addr = sessionAddr(req, SECRET);
    res.setHeader('Content-Type', 'application/json');
    return res.status(200).end(JSON.stringify({ addr: addr }));
  }

  if (req.method !== 'POST') return fail(res, 405, 'method not allowed');

  const q = req.query || {};
  const addr = String(q.addr || '').toLowerCase();
  const ts = Number(q.ts || 0);
  if (!/^0x[0-9a-f]{40}$/.test(addr)) return fail(res, 400, 'bad address');
  if (!Number.isFinite(ts) || Math.abs(Date.now() - ts) > FRESH_MS)
    return fail(res, 400, 'that signature is stale — sign in again');

  let signer;
  try { signer = recoverPersonalSign(signInMessage(addr, ts), String(q.sig || '')); }
  catch (e) { return fail(res, 400, 'bad signature'); }
  if (signer.toLowerCase() !== addr) return fail(res, 403, 'signature does not match that wallet');

  const exp = Math.floor(Date.now() / 1000) + LIFE_S;
  res.setHeader('Set-Cookie', cookie('uday_s', seal({ addr, exp }, SECRET), LIFE_S, true));
  res.setHeader('Content-Type', 'application/json');
  return res.status(200).end(JSON.stringify({ addr, exp }));
}
