const { defineConfig } = require('cypress');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const root = __dirname;
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
function fixture(action, payload = null) {
  return JSON.parse(execFileSync(python, ['-m', 'cypress_audit.fixtures', action, JSON.stringify(payload)], {
    cwd: root, encoding: 'utf8', windowsHide: true,
  }).trim());
}

module.exports = defineConfig({
  viewportWidth: 1440,
  viewportHeight: 1000,
  video: false,
  screenshotOnRunFailure: true,
  screenshotsFolder: '.artifacts/cypress/screenshots',
  trashAssetsBeforeRuns: false,
  defaultCommandTimeout: 8000,
  requestTimeout: 15000,
  env: { auditPassword: 'Synthetic-Audit-Only!492' },
  e2e: {
    baseUrl: 'http://127.0.0.1:8766',
    specPattern: 'cypress/e2e/*.cy.js',
    supportFile: 'cypress/support/e2e.js',
    setupNodeEvents(on, config) {
      if (config.baseUrl !== 'http://127.0.0.1:8766') {
        throw new Error('Refusing Cypress audit against any URL except the isolated loopback server');
      }
      on('before:browser:launch', (browser, launchOptions) => {
        if (browser.name === 'electron') {
          // Capture the configured 1440x1000 viewport without outer-window cropping.
          launchOptions.preferences.width = 1920;
          launchOptions.preferences.height = 1200;
          launchOptions.preferences.webPreferences = {
            ...launchOptions.preferences.webPreferences,
            backgroundThrottling: false,
          };
        }
        return launchOptions;
      });
      on('task', {
        'db:reset': () => fixture('reset'),
        'db:snapshot': () => fixture('snapshot'),
        'db:examPresentation': () => fixture('exam_presentation'),
        'auth:session': (role) => fixture('session', role),
        'db:changeQuote': () => fixture('change_quote'),
        'db:occupySlot': () => fixture('occupy_slot'),
        'audit:console': (entry) => {
          fs.appendFileSync(path.join(root, '.artifacts/cypress/console.jsonl'), `${JSON.stringify(entry)}\n`);
          return null;
        },
      });
      on('after:run', (results) => {
        fs.mkdirSync(path.join(root, '.artifacts/cypress'), { recursive: true });
        fs.writeFileSync(path.join(root, '.artifacts/cypress/results.json'), JSON.stringify(results, null, 2));
        const screenshots = (results.runs || []).flatMap((run) =>
          (run.screenshots || []).map((shot) => ({ spec: run.spec.relative, ...shot })));
        fs.writeFileSync(path.join(root, '.artifacts/cypress/screenshots-final.json'), JSON.stringify(screenshots, null, 2));
      });
    },
  },
});
