const { execFileSync, execFile } = require('child_process');

// The drawing bug this suite guards against only reproduces against real Redis:
// without it the server falls back to a shared in-memory object and can't lose
// an update. So the integration tests run a disposable Redis container.
function dockerAvailable() {
  try {
    execFileSync('docker', ['info'], { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

async function startRedis({ port = 6399, name = 'lab-test-redis' } = {}) {
  execFileSync('docker', ['rm', '-f', name], { stdio: 'ignore' });
  execFileSync('docker', [
    'run', '--rm', '-d', '--name', name,
    '-p', `127.0.0.1:${port}:6379`, 'redis:7-alpine'
  ], { stdio: 'ignore' });

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const out = execFileSync('docker', ['exec', name, 'redis-cli', 'ping'], { encoding: 'utf8' });
      if (out.trim() === 'PONG') {
        return {
          url: `redis://127.0.0.1:${port}`,
          stop: () => execFile('docker', ['rm', '-f', name], () => {})
        };
      }
    } catch {
      // container still booting
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('test Redis container did not become ready');
}

module.exports = { dockerAvailable, startRedis };
