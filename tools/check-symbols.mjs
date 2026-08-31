#!/usr/bin/env node
// Every function this page CALLS, checked against the ones it DECLARES.
//
//   node tools/check-symbols.mjs app.html land.html
//
// This exists because the same edit has now eaten a function three times.
// Replacing a SLICE of JS between two anchors is a normal way to restructure a
// file, and it silently removes anything that happened to sit between them:
//
//   cnewProbe      lived between cnewCalldata and cnewInit
//   posterModal    lived between the POSTER constants and bestPiece
//   draw           lived between fillDays and the fetch that used it
//
// `node --check` passes every time — the code is still valid JavaScript, it
// just refers to something that is no longer there. Only running it finds
// that, and the landing page's one interaction failed in production because
// nobody ran it.
//
// Deliberately blunt: it reports calls with no visible declaration. Built-ins
// and DOM globals are skipped, so a hit is either a real hole or a name that
// belongs in KNOWN below.
import { readFileSync } from 'node:fs';

const KNOWN = new Set([
  // language + platform
  'if', 'for', 'while', 'switch', 'catch', 'return', 'typeof', 'function', 'await',
  'Promise', 'Array', 'Object', 'String', 'Number', 'Boolean', 'Math', 'JSON', 'Date',
  'Map', 'Set', 'Error', 'RegExp', 'Intl', 'BigInt', 'URL', 'URLSearchParams',
  'parseInt', 'parseFloat', 'isNaN', 'encodeURIComponent', 'decodeURIComponent',
  'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval', 'requestAnimationFrame',
  'fetch', 'alert', 'confirm', 'open', 'addEventListener', 'removeEventListener',
  'Image', 'Blob', 'FileReader', 'TextEncoder', 'TextDecoder', 'AbortController',
  'IntersectionObserver', 'MutationObserver', 'ResizeObserver', 'CustomEvent', 'Event',
  'structuredClone', 'queueMicrotask', 'reportError', 'matchMedia', 'getComputedStyle',
]);

let bad = 0;
for (const file of process.argv.slice(2)) {
  const html = readFileSync(new URL('../' + file, import.meta.url), 'utf8');
  const js = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
    .map(m => m[1]).join('\n');

  // Comments and string literals first. Without this, English prose in a
  // comment ("the personal (host) ...") and CSS inside a template string
  // ("var(--gold)") both read as calls — 44 false positives on app.html, and a
  // check nobody can read is a check nobody runs.
  const blank = src => src.replace(/[^\n]/g, ' ');
  const clean = js
    .replace(/\/\*[\s\S]*?\*\//g, blank)          // block comments
    .replace(/(^|[^:\\])\/\/[^\n]*/g, (m, p) => p + blank(m.slice(p.length)))
    .replace(/'(?:[^'\\\n]|\\.)*'/g, blank)        // 'strings'
    .replace(/"(?:[^"\\\n]|\\.)*"/g, blank)        // "strings"
    .replace(/`(?:[^`\\]|\\.)*`/g, blank)           // `templates`
    // Regex literals last, and by heuristic: a `/` is a regex only where a
    // VALUE may begin. Division cannot follow ( , = : [ ! & | ? { } ; or a
    // return, so what does is a pattern. Without this, /view=personal(&|$)/
    // reads as a call to `personal`.
    .replace(/(^|[(,=:[!&|?{};]|\breturn)(\s*)\/(?![*\/])(?:\\.|\[(?:\\.|[^\]\\])*\]|[^\/\\\n])+\/[gimsuy]*/g,
             (m, pre, ws) => pre + ws + blank(m.slice(pre.length + ws.length)));

  const declared = new Set();
  for (const re of [
    /(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/g,
    /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=/g,
    // const a = 1, b = 2  — the second name is a declaration too
    /,\s*([A-Za-z_$][\w$]*)\s*=/g,
    /(?:function|=>)\s*\(?([A-Za-z_$][\w$]*)/g,      // single-arg params
    /\(([^)]*)\)\s*(?:=>|\{)/g,                       // parameter lists
  ]) {
    for (const m of clean.matchAll(re)) {
      for (const n of m[1].split(/[,\s]+/)) if (n) declared.add(n.replace(/\.\.\./, ''));
    }
  }

  const missing = new Set();
  for (const m of clean.matchAll(/\b([A-Za-z_$][\w$]*)\s*\(/g)) {
    const n = m[1];
    if (KNOWN.has(n) || declared.has(n)) continue;
    // a method call is someone else's business
    const at = m.index;
    if (at > 0 && clean[at - 1] === '.') continue;
    missing.add(n);
  }

  if (missing.size) {
    bad++;
    console.log(`  FAIL ${file}: called but never declared — ${[...missing].join(', ')}`);
  } else {
    console.log(`  ok   ${file}`);
  }
}
process.exit(bad ? 1 : 0);
