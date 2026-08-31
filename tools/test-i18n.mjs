// Guards the two dictionaries against the failure that shipped once: a
// Chinese string pasted into the English block. Object literals let a
// duplicate key through silently — the later one simply wins — so English
// readers were served Chinese for two strings and nothing anywhere complained.
//
//   node tools/test-i18n.mjs
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../app.html', import.meta.url), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  cond ? pass++ : fail++;
  console.log((cond ? '  ok   ' : '  FAIL ') + name + (cond ? '' : '  <- ' + extra));
};

const block = html.match(/const I18N = \{[\s\S]*?\n\};/)[0];
const enStart = block.indexOf('  en: {'), zhStart = block.indexOf('  zh: {');
const parts = { en: block.slice(enStart, zhStart), zh: block.slice(zhStart) };
// Both quote styles. A double-quoted entry used to be invisible to every
// assertion below — the key looked missing while the page rendered it fine,
// so the suite reported the wrong failure and would have waved through a real
// one (a Chinese string in the English block) written the same way.
const KEY = /'([a-z][a-zA-Z0-9._]*)'\s*:\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g;

const keys = {}, vals = {};
for (const loc of ['en', 'zh']) {
  keys[loc] = []; vals[loc] = {};
  for (const m of parts[loc].matchAll(KEY)) {
    keys[loc].push(m[1]); vals[loc][m[1]] = m[2] !== undefined ? m[2] : m[3];
  }
  const dupes = keys[loc].filter((k, i) => keys[loc].indexOf(k) !== i);
  ok(`${loc}: no duplicate keys`, dupes.length === 0, [...new Set(dupes)].join(', '));
}

const missingZh = keys.en.filter(k => !(k in vals.zh));
const missingEn = keys.zh.filter(k => !(k in vals.en));
ok('every en key has a zh counterpart', missingZh.length === 0, missingZh.join(', '));
ok('every zh key has an en counterpart', missingEn.length === 0, missingEn.join(', '));

// A CJK character in the English dictionary is the exact shape of the bug.
const cjk = /[㐀-鿿＀-￯]/;
const strayCjk = keys.en.filter(k => cjk.test(vals.en[k]));
ok('no CJK in the English dictionary', strayCjk.length === 0, strayCjk.join(', '));
// ...and the mirror: a zh value that is pure ASCII is usually an untranslated paste
const asciiZh = keys.zh.filter(k => /^[\x20-\x7e{}]{25,}$/.test(vals.zh[k]));
ok('no long ASCII-only strings in the Chinese dictionary', asciiZh.length === 0, asciiZh.join(', '));

// Every key the page actually asks for has to exist, or t() prints the key.
const asked = new Set();
for (const m of html.matchAll(/\bt\(\s*'([a-z][a-zA-Z0-9._]*)'/g)) asked.add(m[1]);
for (const m of html.matchAll(/data-i18n="([a-z][a-zA-Z0-9._]*)"/g)) asked.add(m[1]);
// A trailing dot means the call was t('x.err.' + code) — a PREFIX, not a key.
// Those are covered by the page's own allow-lists, so only whole literals are
// asserted; but a prefix that matches nothing at all is still a mistake.
const unknown = [...asked].filter(k => !k.endsWith('.') && !(k in vals.en));
const deadPrefixes = [...asked].filter(k => k.endsWith('.') &&
  !keys.en.some(x => x.startsWith(k)));
ok('every runtime key prefix matches something', deadPrefixes.length === 0, deadPrefixes.join(', '));
ok('every key the page asks for exists', unknown.length === 0, unknown.join(', '));

// The markup carries an English fallback for every translated node — what a
// no-JS visitor reads, and what shows for a frame before applyLang runs. It
// rots silently: SIGN IN shipped while the markup still said CONNECT.
//
// Checked, never auto-fixed. A regex sweep over the whole file once ate a
// script line that was BUILDING markup — the page carries strings containing
// data-i18n="..." inside JS, so only the region before the main script counts.
const markupEnd = html.lastIndexOf('<script>');
const markup = html.slice(0, markupEnd);
const stale = [];
for (const m of markup.matchAll(/data-i18n="([a-z][a-zA-Z0-9._]+)"[^>]*>([^<>]*)</g)) {
  const [, key, txt] = m;
  // the dictionary is read as SOURCE, so \u2014 has to be decoded before the
  // markup's literal em dash can match it
  const want = (vals.en[key] || '').replace(/\\u([0-9a-fA-F]{4})/g,
    (_, h) => String.fromCharCode(parseInt(h, 16))).replace(/\\'/g, "'");
  if (txt.trim() && want && txt !== want) stale.push(key + ': ' + txt.slice(0, 30));
}
ok('markup fallbacks match the English dictionary', stale.length === 0, [...new Set(stale)].join(', '));

// A string with {placeholders} must never be rendered without them — t()
// leaves the braces on the page, which is how "{addr}" reached a visitor.
// Every such key has to be called WITH a vars object somewhere.
const placeholderKeys = keys.en.filter(k => /\{[a-z]+\}/.test(vals.en[k]));
const calledBare = placeholderKeys.filter(k => {
  const re = new RegExp("t\\(\\s*'" + k.replace(/\./g, '\\.') + "'\\s*\\)", 'g');
  return re.test(html);
});
ok('no {placeholder} string is called without vars', calledBare.length === 0, calledBare.join(', '));

// The page must never go below its text-size floors by shipping an empty string.
const empties = keys.en.filter(k => !vals.en[k].trim() || !(vals.zh[k] || '').trim());
ok('no empty strings in either dictionary', empties.length === 0, empties.join(', '));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
