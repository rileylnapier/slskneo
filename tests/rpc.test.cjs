const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const fs = require('node:fs/promises');
const path = require('node:path');
const { rpc } = require('../electron/rpc.cjs');

async function fixture(t, handler) {
  const dir = await fs.mkdtemp('/tmp/soulseek-rpc-');
  const socketPath = path.join(dir, 'socket');
  const sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket);
    socket.on('error', () => {});
    socket.on('close', () => sockets.delete(socket));
    let input = '';
    socket.setEncoding('utf8');
    socket.on('data', chunk => {
      input += chunk;
      const newline = input.indexOf('\n');
      if (newline < 0) return;
      const request = JSON.parse(input.slice(0, newline));
      socket.removeAllListeners('data');
      handler(socket, request);
    });
  });
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    if (server.listening) await new Promise(resolve => server.close(resolve));
    await fs.rm(dir, { recursive: true, force: true });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(socketPath, resolve);
  });
  return socketPath;
}

test('RPC correlates a fragmented result and sends method parameters', async t => {
  const socket = await fixture(t, (connection, request) => {
    assert.equal(request.method, 'results');
    assert.deepEqual(request.params, { search_id: 'abc', limit: 25 });
    connection.write(JSON.stringify({ id: 'another-request', result: 'ignored' }) + '\n');
    const response = JSON.stringify({ id: request.id, result: { results: [{ filename: 'Música.flac' }] } }) + '\n';
    connection.write(response.slice(0, 20));
    setTimeout(() => connection.end(response.slice(20)), 5);
  });
  assert.deepEqual(await rpc(socket, 'results', { search_id: 'abc', limit: 25 }, 1000), {
    results: [{ filename: 'Música.flac' }],
  });
});

test('RPC propagates a backend error instead of resolving success', async t => {
  const socket = await fixture(t, (connection, request) => connection.end(JSON.stringify({
    id: request.id, error: { message: 'Not connected. Connect first.' },
  }) + '\n'));
  await assert.rejects(rpc(socket, 'search', { query: 'test' }, 1000), /Not connected/);
});

test('RPC rejects malformed responses', async t => {
  const socket = await fixture(t, connection => connection.end('{invalid json}\n'));
  await assert.rejects(rpc(socket, 'status', {}, 1000), /Invalid backend response/);
});

test('RPC rejects a connection closing before its response', async t => {
  const socket = await fixture(t, connection => connection.end());
  await assert.rejects(rpc(socket, 'status', {}, 1000), /closed the connection/);
});

test('RPC times out a backend that never responds', async t => {
  const socket = await fixture(t, () => {});
  await assert.rejects(rpc(socket, 'status', {}, 25), /too long/);
});

test('RPC refuses oversized backend data before JSON parsing', async t => {
  const socket = await fixture(t, connection => connection.end('x'.repeat(16 * 1024 * 1024 + 1)));
  await assert.rejects(rpc(socket, 'status', {}, 10000), /size limit/);
});

test('RPC absolute deadline is not extended by unrelated traffic', async t => {
  let timer;
  const socket = await fixture(t, connection => {
    timer = setInterval(() => connection.write('{"id":"other","result":null}\n'), 5);
    connection.on('close', () => clearInterval(timer));
  });
  t.after(() => clearInterval(timer));
  await assert.rejects(rpc(socket, 'status', {}, 40), /too long/);
});

test('RPC reports a missing daemon with an actionable message', async () => {
  await assert.rejects(rpc('/tmp/no-such-soulseek-socket.sock', 'status', {}, 100), /Reopen the desktop app/);
});
