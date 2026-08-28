import { readFileSync } from 'node:fs';
import { signInMessage } from '../api/session.js';
import { seal, unseal, okHandle, okAvatar, recoverPersonalSign } from '../api/_lib.js';

let pass = 0, fail = 0;
const ok = (name, cond) => { cond ? pass++ : fail++; console.log((cond ? '  ok   ' : '  FAIL ') + name); };

// A. the page and the server must build the SAME string
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const block = html.match(/async function signIn\(\)\{([\s\S]*?)\n\}/)[1];
// pull just the message out of signIn(), which also does wallet calls
const clientMsg = new Function('addr', 'ts', block
  .replace(/^[\s\S]*?const msg =/, 'const msg =')
  .replace(/;\s*let sig[\s\S]*$/, ';')
  + '\nreturn msg;');
const A = '0xE72D42810212C856636CD9D019E98CFE985535FD', TS = 1756300000000;
// the page lowercases before building the message, so feed it the same
ok('page sign-in message === server sign-in message',
   clientMsg(A.toLowerCase(), TS) === signInMessage(A, TS));
ok('the page lowercases the address before signing', /toLowerCase\(\)/.test(block));
if (clientMsg(A.toLowerCase(), TS) !== signInMessage(A, TS)) {
  console.log('   client:', JSON.stringify(clientMsg(A.toLowerCase(), TS)));
  console.log('   server:', JSON.stringify(signInMessage(A, TS)));
}
ok('message lowercases the address', signInMessage(A, TS).includes(A.toLowerCase()));

// B. sealed state survives a round trip and refuses tampering
const S = 'test-secret-'.repeat(3);
const jar = { addr: A.toLowerCase(), verifier: 'v', state: 's', back: '/c/unipeg' };
const tok = seal(jar, S);
ok('seal/unseal round trip', JSON.stringify(unseal(tok, S)) === JSON.stringify(jar));
ok('a flipped payload byte is rejected',
   unseal(tok.replace(/^./, c => c === 'a' ? 'b' : 'a'), S) === null);
ok('a flipped mac byte is rejected',
   unseal(tok.slice(0, -1) + (tok.slice(-1) === 'A' ? 'B' : 'A'), S) === null);
ok('a different secret is rejected', unseal(tok, S + '!') === null);
ok('garbage is rejected', unseal('nonsense', S) === null && unseal(null, S) === null);

// C. what may reach the published file
ok('handle: normal accepted', okHandle('h2crypto_eth'));
ok('handle: 15 chars accepted', okHandle('a'.repeat(15)));
ok('handle: 16 chars refused', !okHandle('a'.repeat(16)));
ok('handle: empty refused', !okHandle(''));
ok('handle: dash refused', !okHandle('bad-handle'));
ok('handle: markup refused', !okHandle('<img src=x>'));
ok('avatar: twimg accepted', okAvatar('https://pbs.twimg.com/profile_images/1/a_bigger.jpg'));
ok('avatar: other host refused', okAvatar('https://evil.example/a.jpg') === false);
ok('avatar: javascript refused', okAvatar('javascript:alert(1)') === false);
ok('avatar: http twimg refused', okAvatar('http://pbs.twimg.com/a.jpg') === false);

// D. recovery still rejects the shapes an attacker controls
ok('short signature throws', (() => { try { recoverPersonalSign('x', '0x00'); return false; } catch { return true; } })());
ok('non-hex signature throws', (() => { try { recoverPersonalSign('x', '0xzz'); return false; } catch { return true; } })());

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
