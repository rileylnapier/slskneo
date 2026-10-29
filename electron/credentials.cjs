// Electron's async decrypt API returns metadata alongside the plaintext.
// Only the result string may be passed to the backend's credential field.
async function decryptCredential(safeStorage, record) {
  if (!record?.secret) return '';
  const decrypted = await safeStorage.decryptStringAsync(Buffer.from(record.secret, 'base64'));
  if (typeof decrypted?.result !== 'string' || !decrypted.result) {
    throw new Error('Saved credentials could not be unlocked.');
  }
  return decrypted.result;
}

module.exports = { decryptCredential };
