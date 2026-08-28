// Guards the two dictionaries against the failure that shipped once: a
// Chinese string pasted into the English block. Object literals let a
// duplicate key through silently — the later one simply wins — so English
// readers were served Chinese for two strings and nothing anywhere complained.
//
//   node tools/test-i18n.mjs
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  cond ? pass++ : fail++;
  console.log((cond ? '  ok   ' : '  FAIL ') + name + (cond ? '' : '  <- ' + extra));
};

const block = html.match(/const I18N = \{[\s\S]*?\n\};/)[0];
const enStart = block.indexOf('  en: {'), zhStart = block.indexOf('  zh: {');
const parts = { en: block.slice(enStart, zhStart), zh: block.slice(zhStart) };
const KEY = /'([a-z][a-zA-Z0-9._]*)'\s*:\s*'((?:[^'\\]|\\.)*)'/g;

const keys = {}, vals = {};
for (const loc of ['en', 'zh']) {
  keys[loc] = []; vals[loc] = {};
  for (const m of parts[loc].matchAll(KEY)) { keys[loc].push(m[1]); vals[loc][m[1]] = m[2]; }
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

// The page must never go below its text-size floors by shipping an empty string.
const empties = keys.en.filter(k => !vals.en[k].trim() || !(vals.zh[k] || '').trim());
ok('no empty strings in either dictionary', empties.length === 0, empties.join(', '));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
