const net = require('node:net');
const { randomUUID } = require('node:crypto');

function rpc(socketPath, method, params = {}, timeout = 120000) {
  return new Promise((resolve, reject) => {
    const id = randomUUID();
    const socket = net.createConnection(socketPath);
    let bytes = 0;
    let buffer = '';
    let settled = false;
    const deadline = setTimeout(() => finish(new Error('The backend took too long to respond. Check its status before retrying.')), timeout);
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      socket.destroy();
      error ? reject(error) : resolve(value);
    };
    socket.setEncoding('utf8');
    socket.setTimeout(timeout, () => finish(new Error('The backend took too long to respond. Check its status before retrying.')));
    socket.on('connect', () => socket.write(JSON.stringify({ id, method, params }) + '\n'));
    socket.on('error', () => finish(new Error('The Soulseek backend is unavailable. Reopen the desktop app.')));
    socket.on('end', () => finish(new Error('The backend closed the connection.')));
    socket.on('data', chunk => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > 16 * 1024 * 1024) return finish(new Error('Backend response exceeded its size limit.'));
      buffer += chunk;
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        try {
          const response = JSON.parse(line);
          if (response.id !== id) continue;
          if (response.error) return finish(new Error(response.error.message || 'Backend request failed.'));
          return finish(null, response.result);
        } catch { return finish(new Error('Invalid backend response.')); }
      }
    });
  });
}

module.exports = { rpc };
