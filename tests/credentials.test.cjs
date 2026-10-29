const test = require('node:test');
const assert = require('node:assert/strict');
const { decryptCredential } = require('../electron/credentials.cjs');

test('saved login restores the plaintext string from Electron async decryption', async () => {
  const encrypted = Buffer.from('test ciphertext');
  const storage = { decryptStringAsync: async buffer => {
    assert.deepEqual(buffer, encrypted);
    return { result: 'test-only-password', shouldReEncrypt: false };
  }};
  assert.equal(await decryptCredential(storage, { secret: encrypted.toString('base64') }), 'test-only-password');
});

test('key rotation metadata is never passed as a password', async () => {
  const storage = { decryptStringAsync: async () => ({ result: 'test-only-password', shouldReEncrypt: true }) };
  assert.equal(await decryptCredential(storage, { secret: 'dGVzdA==' }), 'test-only-password');
});

test('missing credentials do not touch the keychain', async () => {
  assert.equal(await decryptCredential({}, null), '');
  assert.equal(await decryptCredential({}, {}), '');
});

test('malformed decrypted results cannot configure a login', async () => {
  for (const result of [null, {}, { result: 123 }, { result: '' }]) {
    await assert.rejects(decryptCredential({ decryptStringAsync: async () => result }, { secret: 'dGVzdA==' }), /could not be unlocked/);
  }
});
