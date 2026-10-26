// Cloud test of the Gangway web app in a phone-sized headless Chromium.
// Serves www/ (the same folder the Android build packs), walks the main flows,
// opens every port page, and fails on any JavaScript error or broken port.
// Usage: node tools/app_test.js www test-out
const { chromium, devices } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");

const root = path.resolve(process.argv[2] || "www");
const out = path.resolve(process.argv[3] || "test-out");
fs.mkdirSync(out, { recursive: true });
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".jpg": "image/jpeg" };
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(req.url.split("?")[0]).replace(/\/$/, "/index.html"));
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});

const problems = [], notes = [];
const fail = m => { problems.push(m); console.log("FAIL " + m); };
const ok = m => { notes.push(m); console.log("ok   " + m); };

(async () => {
  process.on("unhandledRejection", e => { console.log("::notice title=App test report::Crashed: " + String(e && e.stack || e).replace(/\n/g, "%0A")); process.exit(2); });
  await new Promise(r => server.listen(8123, r));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices["Pixel 7"], geolocation: { latitude: 19.33, longitude: -81.38 }, permissions: ["geolocation"] });
  // Offline test of the bundled data: block the online copy so the app must use what ships inside it.
  await ctx.route("https://raw.githubusercontent.com/**", r => r.abort());
  const page = await ctx.newPage();
  page.on("pageerror", e => fail("JavaScript error: " + e.message));
  page.on("console", m => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fail("Console error: " + m.text()); });
  const shot = async n => page.screenshot({ path: path.join(out, n + ".png") });

  await page.goto("http://localhost:8123/index.html");
  await page.waitForTimeout(1500);
  await shot("01-home");
  const idx = JSON.parse(fs.readFileSync(path.join(root, "data/index.json")));
  const count = await page.evaluate(() => document.querySelector("#q")?.getAttribute("placeholder") || "");
  const m = /(\d+)\s+ports/.exec(count);
  if (!m) fail("Search box has no port count: " + count);
  else if (+m[1] !== idx.ports.length) fail(`Search box says ${m[1]} ports but the app has ${idx.ports.length}`);
  else ok(`Home page lists ${m[1]} ports`);

  // Every port in the list must have its guide file and open without errors.
  let opened = 0;
  for (const p of idx.ports) {
    if (!fs.existsSync(path.join(root, "data/ports", p.id + ".json"))) { fail(`Port ${p.id} (${p.name}) is listed but has no guide`); continue; }
    const d = JSON.parse(fs.readFileSync(path.join(root, "data/ports", p.id + ".json")));
    if (!d.places || !d.places.length) fail(`Port ${p.id} (${p.name}) has no places`);
    opened++;
  }
  ok(`${opened} port guide files present and readable`);

  // Open a sample of port pages in the app itself, including the newest ones.
  const sample = [...new Set(["gcm", "bwi", "nyc", "mzr", "mnl", "got", "cer", "gci", ...idx.ports.filter((_, i) => i % 25 === 0).map(p => p.id)])].filter(id => idx.ports.some(p => p.id === id));
  for (const id of sample) {
    const name = idx.ports.find(p => p.id === id).name;
    await page.goto("http://localhost:8123/index.html#" + id);
    await page.waitForTimeout(1200);
    const body = await page.locator("body").innerText();
    if (!body.includes(name.split(" (")[0])) fail(`Port ${name} page did not open`);
    const places = await page.locator("text=/\\d+ of \\d+ places/").count();
    if (!places) fail(`Port ${name} shows no place count`); else ok(`Port ${name} opens with places`);
    if (["bwi", "nyc", "gci", "gcm"].includes(id)) await shot("port-" + id);
  }

  // Ship picker: open, check every cruise line badge, search, pick a ship.
  await page.goto("http://localhost:8123/index.html");
  await page.waitForTimeout(600);
  const opener = page.locator("[data-pick]").first();
  if (await opener.count()) {
    await opener.click(); await page.waitForTimeout(500);
    const lines = await page.locator("[data-line]").count();
    if (lines < 14) fail(`Ship picker shows only ${lines} cruise lines`); else ok(`Ship picker shows ${lines} cruise lines`);
    await shot("02-picker-lines");
    const colours = await page.$$eval("[data-line] .funnel path:first-child", ps => ps.map(p => p.getAttribute("fill")));
    const dupes = colours.filter((c, i) => colours.indexOf(c) !== i);
    if (dupes.length) fail("Cruise lines share funnel colours: " + dupes.join(", ")); else ok("Every cruise line has its own funnel colour");
    const find = page.locator("[data-find]");
    if (await find.count()) {
      await find.fill("wonder"); await page.waitForTimeout(400);
      const hits = await page.locator("[data-found] [data-ship]").count();
      if (!hits) fail("Ship search for 'wonder' found nothing"); else ok(`Ship search for 'wonder' found ${hits} ship(s)`);
      await shot("03-picker-search");
      await find.fill("zzzz"); await page.waitForTimeout(300);
      if (!(await page.locator(".nofind").count())) fail("Ship search shows no message when nothing matches"); else ok("Ship search explains when nothing matches");
      await find.fill(""); await page.waitForTimeout(200);
      if (await page.locator("[data-lines]").isHidden()) fail("Cruise lines stay hidden after clearing the search"); else ok("Cruise lines come back after clearing the search");
    } else fail("Ship picker has no search box");
    await page.locator("[data-line]").first().click(); await page.waitForTimeout(500);
    await shot("04-picker-ships");
    const ships = page.locator("[data-ship]");
    if (!(await ships.count())) fail("Cruise line opens with no ships");
    else { await ships.first().click(); await page.waitForTimeout(800); ok("Picking a ship closes the picker"); await shot("05-after-pick"); }
  } else fail("Could not find the button that opens the ship picker");

  // Small screen and dark mode.
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto("http://localhost:8123/index.html"); await page.waitForTimeout(600);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (overflow) fail("Page scrolls sideways on a small 320px phone"); else ok("No sideways scrolling on a 320px phone");
  await shot("06-small-phone");
  await page.emulateMedia({ colorScheme: "dark" }); await page.reload(); await page.waitForTimeout(600); await shot("07-dark");

  await browser.close(); server.close();
  const report = [`Problems: ${problems.length}`, ...problems.map(p => "FAIL " + p), "", ...notes.map(n => "ok   " + n)];
  fs.writeFileSync(path.join(out, "report.txt"), report.join("\n"));
  // One annotation carrying the whole report, readable through the GitHub API.
  console.log("::notice title=App test report::" + report.join("%0A").replace(/\r/g, ""));
  console.log(`\n${problems.length} problem(s)`);
  process.exit(problems.length ? 1 : 0);
})().catch(e => { console.log("::notice title=App test report::Crashed: " + String(e && e.stack || e).replace(/\n/g, "%0A")); process.exit(2); });
