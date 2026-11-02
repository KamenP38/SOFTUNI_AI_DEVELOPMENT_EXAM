// Launch only the isolated test server, and always stop the process we own.
const fs = require('node:fs');
const path = require('node:path');
const { spawn, execFileSync } = require('node:child_process');
const net = require('node:net');
const root = path.resolve(__dirname, '..');
process.env.CYPRESS_CACHE_FOLDER = path.join(root, '.artifacts/cypress-cache');
// Electron-based editors can pass this to children; Cypress needs browser mode.
delete process.env.ELECTRON_RUN_AS_NODE;
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const artifact = path.join(root, '.artifacts/cypress');
fs.mkdirSync(artifact, { recursive: true });
async function main() {
  // Never run the audit against a pre-existing process occupying our port.
  await new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', () => reject(new Error('Port 8766 is occupied; refusing to run against another server')));
    probe.listen(8766, '127.0.0.1', () => probe.close(resolve));
  });
  execFileSync(python, ['-m', 'cypress_audit.fixtures', 'migrate'], { cwd: root, stdio: 'inherit', windowsHide: true });
  const log = fs.openSync(path.join(artifact, 'server.log'), 'w');
  const server = spawn(python, ['manage.py', 'runserver', '127.0.0.1:8766', '--noreload', '--settings=cypress_audit.settings'], {
    cwd: root, stdio: ['ignore', log, log], windowsHide: true,
  });
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100 && !ready; attempt += 1) {
      if (server.exitCode !== null) throw new Error('Isolated Django server exited; inspect server.log');
      try {
        const response = await fetch('http://127.0.0.1:8766/staff/login/');
        if (response.headers.get('X-Cypress-Audit') !== 'isolated-synthetic-database') {
          throw new Error('Server identity mismatch; refusing to run');
        }
        ready = response.ok;
      } catch (error) {
        if (error.message.includes('identity mismatch')) throw error;
      }
      if (!ready) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!ready) throw new Error('Isolated Django server did not become ready');
    const args = process.argv.slice(2);
    const options = { project: root, browser: 'electron', config: { baseUrl: 'http://127.0.0.1:8766' } };
    if (args[0]) options.spec = args[0];
    const result = await require('cypress').run(options);
    process.exitCode = result.totalFailed || result.failures ? 1 : 0;
  } finally {
    server.kill();
    fs.closeSync(log);
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
