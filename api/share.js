// The page a holder shares: GET /s/<assetId>  (rewritten to /api/share?id=)
//
// X's crawler reads og:/twitter: tags and runs no JavaScript, so the card a
// post shows is decided entirely by the URL in the post. Sharing uday.gift
// shows the site's card; sharing THIS page shows the holder's own piece.
// It is a real page for humans too — the card, large, and a way in — rather
// than a redirect, because crawlers and people disagree about redirects and
// a page that is honest to both needs no user-agent sniffing.
import cache from '../data/art-cache.json' with { type: 'json' };

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export default function handler(req, res) {
  const id = String(req.query.id || '');
  const r = /^\d{1,7}$/.test(id) ? cache[id] : null;
  if (!r || !r.d) { res.statusCode = 404; res.setHeader('Content-Type', 'text/plain'); return res.end('no such dated piece'); }
  const label = MONTHS[+r.d.slice(0, 2) - 1] + ' ' + r.d.slice(3);
  // the image must be absolute and on THIS deployment, so a preview shares its own card
  const host = req.headers['x-forwarded-host'] || req.headers.host || 'uday.gift';
  const base = 'https://' + host;
  const img = base + '/card/' + id + '.png';
  const title = label + ' · uDAY #' + id;
  const desc = 'A day as a collectible, onchain. This piece carries ' + label + '. Some days are just dates. Some become part of your story.';
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=0, s-maxage=86400');
  res.end(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="uDAY">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${esc(base + '/s/' + id)}">
<meta property="og:image" content="${esc(img)}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@udaygift">
<meta name="twitter:title" content="${esc(title)}">
<meta name="twitter:description" content="${esc(desc)}">
<meta name="twitter:image" content="${esc(img)}">
<meta name="theme-color" content="#0b0918">
<link rel="icon" href="https://uday.gift/assets/uday-logo.png">
<style>
html{background:#0b0918;color:#f4f0e6;color-scheme:dark}
body{margin:0;min-height:100svh;display:grid;place-items:center;font-family:"Nunito Sans",system-ui,sans-serif;padding:24px;box-sizing:border-box}
main{max-width:900px;width:100%;text-align:center}
img{width:100%;height:auto;image-rendering:pixelated;border:1px solid #2a2440;border-radius:6px}
p{font-size:15px;color:#b8b0d0;margin:18px 0}
a.btn{display:inline-block;margin:6px;padding:12px 22px;border:1px solid #e8b93f;color:#e8b93f;text-decoration:none;font-size:14px;letter-spacing:.16em;text-transform:uppercase;border-radius:4px}
a.btn--solid{background:#e8b93f;color:#0b0918}
</style></head>
<body><main>
<img src="${esc(img)}" width="1200" height="630" alt="${esc(title)}">
<p>${esc(desc)}</p>
<a class="btn btn--solid" href="https://app.uday.gift/">Open uDAY</a>
<a class="btn" href="https://uday.gift/">What is this?</a>
</main></body></html>`);
}
