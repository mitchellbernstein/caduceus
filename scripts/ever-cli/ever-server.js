#!/usr/bin/env node
/**
 * ever-server — Background daemon for persistent browser sessions.
 *
 * Start: ever-server start --url <url>
 * Stop:  ever-server stop
 * Status: ever-server status
 *
 * The server keeps a Chrome/Chromium browser open and exposes state via
 * ~/.ever/state.json (wsEndpoint + URL). The ever.js CLI connects via CDP
 * (Chrome DevTools Protocol) WebSocket to attach to the same browser.
 *
 * Usage in shell scripts:
 *   ever-server start --url https://example.com
 *   ever snapshot   # connects via wsEndpoint in state.json
 *   ever screenshot --output screenshots/home.jpg
 *   ever navigate https://example.com/pricing
 *   ever-server stop
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const os = require('os');

const STATE_DIR = path.join(os.homedir(), '.ever');
const STATE_FILE = path.join(STATE_DIR, 'state.json');

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

async function start(url) {
  if (readState()) {
    console.log("Server already running.");
    return;
  }
  console.log(`Launching browser at ${url}...`);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(url, { timeout: 30000, waitUntil: 'domcontentloaded' });
  const wsEndpoint = page.wsEndpoint();
  writeState({ wsEndpoint, url, launched: Date.now() });
  console.log(`Server started. wsEndpoint stored. URL: ${url}`);
  console.log("Browser will stay open until 'ever-server stop' is called.");
  // Keep process alive
  await new Promise(() => {});
}

async function stop() {
  const state = readState();
  if (!state) { console.log("No server running."); return; }
  try {
    const browser = await chromium.connect({ timeout: 10000, wsEndpoint: state.wsEndpoint });
    await browser.close();
  } catch (e) { console.log("Browser already gone."); }
  clearState();
  console.log("Server stopped.");
}

async function status() {
  const state = readState();
  if (state) console.log(`Running: ${state.url} (wsEndpoint available)`);
  else console.log("No server running.");
}

const cmd = process.argv[2];
const urlArg = process.argv.find(a => a.startsWith('--url='))?.slice(6)
  || process.argv[process.argv.indexOf('--url') + 1];

if (cmd === 'start') {
  const url = urlArg || die("Usage: ever-server start --url <url>");
  start(url).catch(e => { console.error(e.message); process.exit(1); });
} else if (cmd === 'stop') {
  stop().catch(e => { console.error(e.message); process.exit(1); });
} else if (cmd === 'status') {
  status();
} else {
  console.log("Usage: ever-server start --url <url> | stop | status");
}
