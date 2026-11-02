const path = require('node:path');
process.env.CYPRESS_CACHE_FOLDER = path.resolve(__dirname, '../.artifacts/cypress-cache');
require('node:child_process').execFileSync(process.execPath, [require.resolve('cypress/bin'), 'install'], { stdio: 'inherit', windowsHide: true });
