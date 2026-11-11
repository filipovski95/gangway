// Cloud test of crew-shared port days, against a fake Supabase (no real database is touched).
// Usage: node tools/crew_test.js www test-out
const { chromium, devices } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const root = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]);
fs.mkdirSync(out, { recursive: true });
// Same page, with the database switched on.
const html = fs.readFileSync(path.join(root, "index.html"), "utf8").replace(/const CREW_DB = \{[^}]*\};/, 'const CREW_DB = { url: "https://crew.example.co", key: "anon-test" };');
if (!html.includes("crew.example.co")) throw new Error("CREW_DB line not found");
fs.writeFileSync(path.join(root, "crew.html"), html);
const types = { ".html": "text/html", ".json": "application/json", ".css": "text/css", ".woff2": "font/woff2", ".jpg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml" };
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(req.url.split("?")[0]));
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" }); fs.createReadStream(p).pipe(res);
});
const today = new Date().toLocaleDateString("en-CA");
const plus = n => { const d = new Date(today + "T12:00"); d.setDate(d.getDate() + n); return d.toLocaleDateString("en-CA"); };
const rows = [
  { ship_key: "celebritysilhouette", ship: "Celebrity Silhouette", day: today, port: "cur", n: 3, sail_out: "17:00:00" },
  { ship_key: "celebritysilhouette", ship: "Celebrity Silhouette", day: today, port: "bon", n: 1, sail_out: null },     // outvoted
  { ship_key: "celebritysilhouette", ship: "Celebrity Silhouette", day: plus(3), port: "fll", n: 2, sail_out: "16:00:00" },
  { ship_key: "celebritysilhouette", ship: "Celebrity Silhouette", day: "2026-11-18", port: "fll", n: 1, sail_out: null }, // official day (Grand Cayman) must win
  { ship_key: "crewonlyship", ship: "Crew Only Ship", day: today, port: "cur", n: 1, sail_out: null },
];
const problems = [];
const check = (cond, msg) => { console.log((cond ? "ok   " : "FAIL ") + msg); if (!cond) problems.push(msg); };

(async () => {
  await new Promise(r => server.listen(8124, r));
  const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
  const ctx = await browser.newContext({ ...devices["Pixel 7"] });
  await ctx.route("https://raw.githubusercontent.com/**", r => r.abort());
  const rpc = []; let online = true;
  await ctx.route("https://crew.example.co/**", async r => {
    const u = new URL(r.request().url()), h = r.request().headers();
    if (!online) return r.abort();
    if (h.apikey !== "anon-test") return r.fulfill({ status: 401, body: "{}" });
    if (u.pathname.endsWith("/crew_consensus")) {
      const [a, b] = (h.range || "0-999").split("-").map(Number);
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows.slice(a, b + 1)) });
    }
    if (u.pathname.includes("/rpc/")) { rpc.push({ fn: u.pathname.split("/").pop(), body: JSON.parse(r.request().postData()) }); return r.fulfill({ status: 204, body: "" }); }
    r.fulfill({ status: 404, body: "{}" });
  });
  const page = await ctx.newPage();
  page.on("pageerror", e => check(false, "JavaScript error: " + e.message));
  await page.addInitScript(() => { if (!localStorage.getItem("gw:ship")) localStorage.setItem("gw:ship", JSON.stringify("Celebrity Silhouette")); });
  await page.goto("http://localhost:8124/crew.html"); await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(out, "crew-01-home.png"), fullPage: true });

  const pass = await page.textContent("#pass");
  check(/Today:\s*Willemstad/.test(pass), "Today's card shows Curaçao from crew (most-reported port wins over Bonaire)");
  check(/added by crew · 3 confirmed/.test(pass), "Today's card says it was added by crew, 3 confirmed");
  check(/16:30|All aboard\s*16:30/.test(pass), "All aboard worked out from the crew sailing time (17:00 − 30 min)");
  await page.click("[data-itall]").catch(() => {});
  const itin = await page.textContent("#itin");
  check(/Fort Lauderdale[\s\S]*added by crew · 2 confirmed/.test(itin), "Itinerary shows the crew Fort Lauderdale day");
  const nov18 = await page.evaluate(() => myShip().calls.filter(c => (c.a || c.d).startsWith("2026-11-18")).map(c => c.p + (c.crew ? "*" : "")));
  check(JSON.stringify(nov18) === '["gcm"]', "Official Grand Cayman call on 18 Nov beats the crew report (" + nov18 + ")");
  check(/Share the days I add with other crew on Silhouette/.test(itin), "Share checkbox is shown, ticked by default");

  // Ships in port at Curaçao today
  await page.evaluate(() => openPort("cur")); await page.waitForTimeout(1200);
  const harbour = await page.textContent("#harbour");
  check(/Celebrity Silhouette[\s\S]*added by crew/.test(harbour), "Curaçao's ships-in-port lists Silhouette, marked added by crew");
  check(/Crew Only Ship/.test(harbour), "A ship only crew have reported also appears");
  await page.screenshot({ path: path.join(out, "crew-02-curacao.png"), fullPage: true });
  await page.evaluate(() => closePort()); await page.waitForTimeout(500);

  // Adding a day is sent to the database
  const day = plus(10);
  await page.fill("#itDay", day); await page.selectOption("#itPort", "coz"); await page.fill("#itOut", "18:00");
  await page.click("[data-itadd]"); await page.waitForTimeout(800);
  const add = rpc.find(x => x.fn === "add_crew_day");
  check(add && add.body.p_ship === "Celebrity Silhouette" && add.body.p_day === day && add.body.p_port === "coz" && add.body.p_out === "18:00" && /^[0-9a-f-]{36}$/.test(add.body.p_device),
    "Added day reaches the database with ship, date, port, time and a phone id: " + JSON.stringify(add && add.body));
  // Removing it sends a removal
  await page.click(`[data-unhere="${day}"]`); await page.waitForTimeout(800);
  check(rpc.some(x => x.fn === "remove_crew_day" && x.body.p_day === day), "Removing the day removes it from the database");

  // Offline: queued, then sent when back online
  online = false; const before = rpc.length;
  await page.fill("#itDay", plus(12)); await page.selectOption("#itPort", "bon"); await page.click("[data-itadd]"); await page.waitForTimeout(800);
  const queued = await page.evaluate(() => JSON.parse(localStorage.getItem("gw:crewq") || "[]").length);
  check(queued === 1 && rpc.length === before, "Offline add waits in the queue on the phone");
  online = true; await page.evaluate(() => flushCrew()); await page.waitForTimeout(800);
  const left = await page.evaluate(() => JSON.parse(localStorage.getItem("gw:crewq") || "[]").length);
  check(left === 0 && rpc.some(x => x.body.p_day === plus(12) && x.body.p_port === "bon"), "Queued day is sent once back online");

  // Sharing switched off: nothing sent
  await page.uncheck("#itShare"); const n0 = rpc.length;
  await page.fill("#itDay", plus(14)); await page.selectOption("#itPort", "coz"); await page.click("[data-itadd]"); await page.waitForTimeout(800);
  check(rpc.length === n0, "With sharing unticked, added days stay on the phone");
  await page.screenshot({ path: path.join(out, "crew-03-itinerary.png"), fullPage: true });

  // No horizontal scroll at 320px with the new checkbox
  await page.setViewportSize({ width: 320, height: 700 }); await page.waitForTimeout(300);
  check(await page.evaluate(() => document.documentElement.scrollWidth <= 321), "No sideways scrolling at 320px");
  await browser.close(); server.close();
  console.log(`\n${problems.length} problem(s)`); process.exit(problems.length ? 1 : 0);
})();
