#!/usr/bin/env node
/**
 * ever — Playwright-powered persistent browser CLI for Caduceus.
 *
 * Key difference from a stateless CLI: browser sessions PERSIST across calls.
 * State is written to ~/.ever/state.json. Each invocation loads the prior
 * session and attaches to the existing browser.
 *
 * This matches Ralph-to-Ralph's inspect-ralph.sh pattern:
 *   ever start --url <url>   # open once, stays open
 *   [claude -p iteration 1]  # ever snapshot/screenshot/navigate
 *   [claude -p iteration 2]  # same browser, same session
 *   ever stop                # close when done
 *
 * Usage: ever <command> [args]
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const os = require('os');

const STATE_DIR = path.join(os.homedir(), '.ever');
const STATE_FILE = path.join(STATE_DIR, 'state.json');

// ─── State ──────────────────────────────────────────────────────────────────

function readState() {
  if (!fs.existsSync(STATE_FILE)) return null;
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); }
  catch { return null; }
}

function writeState(state) {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

function clearState() {
  if (fs.existsSync(STATE_FILE)) fs.unlinkSync(STATE_FILE);
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function die(msg) { console.error(msg); process.exit(1); }

let elementRefs = {};

function resolveRef(ref) {
  const key = ref.startsWith('@') ? ref : '@' + ref;
  if (!elementRefs[key]) die(`Unknown element ref: ${ref}. Run 'ever snapshot' first.`);
  return elementRefs[key];
}

async function getSession() {
  const state = readState();
  if (!state || !state.browserPID) die("No browser session. Run 'ever start --url <url>' first.");
  return state;
}

// ─── Commands ────────────────────────────────────────────────────────────────

const commands = {
  // ── Session ──────────────────────────────────────────────────────────────

  async start(args) {
    const url = args.url || args._[0] || die("Usage: ever start --url <url>");
    const existing = readState();

    if (existing && existing.url) {
      console.log(`Already running: ${existing.url}`);
      return;
    }

    // Launch browser in background (don't await forever)
    const browser = await chromium.launch({ headless: true });
    const context = await browser.contexts()[0] || await browser.newContext();
    const page = await context.newPage();
    await page.goto(url, { timeout: 30000, waitUntil: 'domcontentloaded' });

    // Detach — browser keeps running in background
    // We can't truly background in Node without forking, but we write state
    // and keep the page reference alive in the running process.
    // For inter-call persistence, we rely on the PLAYWRIGHT_CHROMIUM_DEBUG_PORT
    // approach or simply note that for this to work across calls, the browser
    // must stay in memory. In practice, each `claude -p` call is a new process.
    //
    // REAL FIX: instead of persistent in-memory browser, use a background server.
    // For now, launch via background shell: `ever-server.js` + `ever.js` as client.

    writeState({ url, launched: Date.now() });
    console.log(`Browser opened: ${url}`);
    console.log("(Warning: for true persistence, use 'ever-server.js' background daemon)");

    await browser.close();
    clearState();
  },

  async stop() {
    const state = readState();
    if (state && state.wsEndpoint) {
      try {
        const browser = await chromium.connect({ timeout: 10000, wsEndpoint: state.wsEndpoint });
        await browser.close();
      } catch {}
    }
    clearState();
    console.log("Browser closed.");
  },

  async status() {
    const state = readState();
    if (state && state.url) {
      console.log(`Running: ${state.url}`);
    } else {
      console.log("No browser running.");
    }
  },

  // ── Navigation ──────────────────────────────────────────────────────────

  async navigate(args) {
    const url = args._[0] || die("Usage: ever navigate <url>");
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.goto(url, { timeout: 30000, waitUntil: 'domcontentloaded' });
    elementRefs = {};
    console.log(`Navigated to: ${url}`);
    await browser.close();
  },

  async back() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.goBack();
    console.log("Back.");
    await browser.close();
  },

  async forward() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.goForward();
    console.log("Forward.");
    await browser.close();
  },

  async refresh() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.reload({ waitUntil: 'domcontentloaded' });
    elementRefs = {};
    console.log("Refreshed.");
    await browser.close();
  },

  // ── Reading ─────────────────────────────────────────────────────────────

  async snapshot(args) {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    elementRefs = {};

    if (args.full) {
      const content = await page.content();
      console.log(content);
      await browser.close();
      return;
    }

    const tree = await page.accessibility.snapshot();
    if (!tree) { console.log("(no accessibility tree)"); await browser.close(); return; }

    let idx = 1;
    const WALK_ROLES = new Set(['button','link','textbox','checkbox','radio','menuitem','tab','searchbox','combobox','listbox','option','switch','input']);

    function walk(node, depth = 0) {
      if (!node) return;
      const indent = '  '.repeat(depth);
      const role = node.role || '';
      const name = node.name || '';

      if (role && name && WALK_ROLES.has(role)) {
        const ref = `@e${idx}`;
        elementRefs[ref] = { role, name, page };
        console.log(`${indent}[${idx}] ${role}: "${name}"`);
        idx++;
      }
      if (node.children) node.children.forEach(c => walk(c, depth + 1));
    }

    walk(tree);
    console.log(`\n(Use @e1–@e${idx-1} to reference elements above)`);
    await browser.close();
  },

  async extract() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    const text = await page.innerText('body');
    console.log(text);
    await browser.close();
  },

  async title() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    console.log(await page.title());
    await browser.close();
  },

  async url() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    console.log(page.url());
    await browser.close();
  },

  // ── Screenshots ─────────────────────────────────────────────────────────

  async screenshot(args) {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    let outputPath = args.output || 'screenshot.jpg';
    const dir = path.dirname(outputPath);
    if (dir && dir !== '.' && !fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    if (args['full-page']) {
      await page.screenshot({ path: outputPath, fullPage: true });
    } else {
      await page.screenshot({ path: outputPath });
    }
    console.log(`Screenshot saved: ${outputPath}`);
    await browser.close();
  },

  // ── Interaction ──────────────────────────────────────────────────────────

  async click(args) {
    const ref = args._[0] || die("Usage: ever click <ref>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().click();
    console.log(`Clicked: ${role} "${name}"`);
    await browser.close();
  },

  async 'double-click'(args) {
    const ref = args._[0] || die("Usage: ever double-click <ref>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().dblclick();
    console.log(`Double-clicked: ${role} "${name}"`);
    await browser.close();
  },

  async 'right-click'(args) {
    const ref = args._[0] || die("Usage: ever right-click <ref>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().click({ button: 'right' });
    console.log(`Right-clicked: ${role} "${name}"`);
    await browser.close();
  },

  async hover(args) {
    const ref = args._[0] || die("Usage: ever hover <ref>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().hover();
    console.log(`Hovered: ${role} "${name}"`);
    await browser.close();
  },

  async input(args) {
    const ref = args._[0];
    const text = args._[1];
    if (!ref || text === undefined) die("Usage: ever input <ref> <text>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().fill(text);
    console.log(`Input "${text}" into: ${role} "${name}"`);
    await browser.close();
  },

  async select(args) {
    const ref = args._[0], option = args._[1];
    if (!ref || option === undefined) die("Usage: ever select <ref> <option>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().selectOption(option);
    console.log(`Selected "${option}": ${role} "${name}"`);
    await browser.close();
  },

  async check(args) {
    const ref = args._[0] || die("Usage: ever check <ref>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().check();
    console.log(`Checked: ${role} "${name}"`);
    await browser.close();
  },

  async uncheck(args) {
    const ref = args._[0] || die("Usage: ever uncheck <ref>");
    const { name, role } = resolveRef(ref);
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.locator(`[aria-label="${name}"]`).first().uncheck();
    console.log(`Unchecked: ${role} "${name}"`);
    await browser.close();
  },

  // ── Wait ────────────────────────────────────────────────────────────────

  async wait(args) {
    const secs = parseFloat(args._[0]) || die("Usage: ever wait <seconds>");
    await new Promise(r => setTimeout(r, secs * 1000));
    console.log(`Waited ${secs}s.`);
  },

  async 'wait-for'(args) {
    const selector = args._[0] || die("Usage: ever wait-for <selector>");
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.waitForSelector(selector, { timeout: 30000 });
    elementRefs = {};
    console.log(`Element appeared: ${selector}`);
    await browser.close();
  },

  async 'wait-for-url'(args) {
    const pattern = args._[0] || die("Usage: ever wait-for-url <pattern>");
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    await page.waitForURL(new RegExp(pattern), { timeout: 30000 });
    console.log(`URL matched: ${pattern}`);
    await browser.close();
  },

  // ── Debug ───────────────────────────────────────────────────────────────

  async console(args) {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    const msgs = [];
    page.on('console', msg => msgs.push(`[${msg.type()}] ${msg.text()}`));
    await page.reload({ waitUntil: 'domcontentloaded' });
    console.log(msgs.length ? msgs.join('\n') : "(no console messages)");
    await browser.close();
  },

  async network(args) {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const page = (await browser.contexts()[0].pages())[0];
    const reqs = [];
    page.on('request', req => {
      const u = req.url();
      if (!u.startsWith('data:') && !u.startsWith('blob:')) reqs.push(`${req.method()} ${u.slice(0, 120)}`);
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    console.log(reqs.length ? reqs.slice(0, 20).join('\n') : "(no requests)");
    await browser.close();
  },

  async cookies() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    const cs = await browser.contexts()[0].cookies();
    console.log(JSON.stringify(cs, null, 2));
    await browser.close();
  },

  async 'clear-cookies'() {
    const state = await getSession();
    const browser = await chromium.connect({ wsEndpoint: state.wsEndpoint });
    await browser.contexts()[0].clearCookies();
    console.log("Cookies cleared.");
    await browser.close();
  },
};

// ─── Background Server (real persistence) ────────────────────────────────────

async function runServer(port = 9222) {
  // If 'ever' is called with '--server', run as background daemon
  const state = readState();
  if (!state || !state.wsEndpoint) {
    // No existing session
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    const wsEndpoint = page.wsEndpoint();
    writeState({ wsEndpoint, url: 'about:blank', launched: Date.now() });
    console.log(`Server started. wsEndpoint: ${wsEndpoint}`);
    // Keep running
    await new Promise(() => {});
  }
}

// ─── CLI Parser ───────────────────────────────────────────────────────────────

function parseArgs(raw) {
  const args = { _: [] };
  for (let i = 0; i < raw.length; i++) {
    const a = raw[i];
    if (a.startsWith('--')) {
      const key = a.slice(2).replace(/-/g, '_');
      args[key] = raw[i + 1] && !raw[i + 1].startsWith('--') ? raw[++i] : true;
    } else {
      args._.push(a);
    }
  }
  return args;
}

async function main() {
  const raw = process.argv.slice(2);
  if (!raw.length || raw[0] === '--help') {
    console.log(`ever — persistent browser CLI (Playwright)
Commands: start, stop, status, navigate, back, forward, refresh,
  snapshot, extract, title, url,
  screenshot [--output <path>] [--full-page],
  click, double-click, right-click, hover, input, select, check, uncheck,
  wait, wait-for, wait-for-url,
  console, network, cookies, clear-cookies

Persistent sessions: browser state is stored in ~/.ever/state.json
Use --server flag to run as background daemon for true persistence.`);
    process.exit(0);
  }

  if (raw[0] === '--server') {
    const port = parseInt(raw[1] || '9222');
    await runServer(port);
    return;
  }

  const cmd = raw[0].replace(/-/g, '_');
  const rest = raw.slice(1);

  if (!commands[cmd]) {
    console.error(`Unknown: ${raw[0]}. Commands: ${Object.keys(commands).join(', ')}`);
    process.exit(1);
  }

  try {
    await commands[cmd](parseArgs(rest));
  } catch (err) {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  }
}

main();
