const path = require('path');
const { spawn } = require('child_process');

// Boots the real server.js in a child process so tests exercise the whole
// socket -> handler -> Redis path, not a stubbed slice of it.
async function startServer({ port, redisUrl }) {
  const child = spawn(process.execPath, [path.join(__dirname, '..', '..', 'server.js')], {
    env: { ...process.env, PORT: String(port), REDIS_URL: redisUrl, NODE_ENV: 'test' },
    stdio: ['ignore', 'pipe', 'pipe']
  });

  const logs = [];
  child.stdout.on('data', (d) => logs.push(d.toString()));
  child.stderr.on('data', (d) => logs.push(d.toString()));

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (logs.join('').includes(`running on port ${port}`)) {
      return {
        url: `http://127.0.0.1:${port}`,
        logs,
        stop: () => new Promise((resolve) => {
          child.once('exit', resolve);
          child.kill('SIGKILL');
        })
      };
    }
    if (child.exitCode !== null) throw new Error(`server exited early:\n${logs.join('')}`);
    await new Promise((r) => setTimeout(r, 200));
  }
  child.kill('SIGKILL');
  throw new Error(`server did not start:\n${logs.join('')}`);
}

module.exports = { startServer };
