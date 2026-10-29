// Cloud test of the Plume app in a phone-sized headless Chromium.
// Walks onboarding and the main logging flows, then fills in a few months of sample data
// and screenshots every screen in light and dark mode. Fails on any JavaScript error.
// Usage: node tools/app_test.js app test-out
const { chromium, devices } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");

const root = path.resolve(process.argv[2] || "app");
const out = path.resolve(process.argv[3] || "test-out");
fs.mkdirSync(out, { recursive: true });
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(req.url.split("?")[0]).replace(/\/$/, "/index.html"));
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});

const problems = [], notes = [];
const fail = m => { problems.push(m); console.log("FAIL " + m); };
const ok = m => { notes.push(m); console.log("ok   " + m); };
const DAY = 86400000;

function sampleData(now) {
  // About 10 weeks on Zepbound with two dose increases, steady weight loss and a few symptoms.
  const shots = [], weights = [], effects = [], days = {};
  const sites = ["belly-l", "belly-r", "thigh-l", "thigh-r", "arm-l", "arm-r"];
  const start = now - 70 * DAY;
  for (let w = 0; w < 10; w++) {
    const ts = start + w * 7 * DAY + 19 * 3600000;
    const dose = w < 4 ? "2.5 mg" : w < 8 ? "5 mg" : "7.5 mg";
    shots.push({ id: "s" + w, ts, med: "Zepbound", dose, site: sites[w % 6], note: w === 4 ? "First 5 mg pen" : "" });
    if (w % 2 === 0) effects.push({ id: "e" + w, ts: ts + 1.4 * DAY, type: "nausea", sev: w < 5 ? 1 : 0, note: "" });
    if (w % 3 === 0) effects.push({ id: "f" + w, ts: ts + 2.2 * DAY, type: "fatigue", sev: 0, note: "" });
    if (w % 4 === 1) effects.push({ id: "c" + w, ts: ts + 3.1 * DAY, type: "constipation", sev: 1, note: "more water helped" });
    effects.push({ id: "g" + w, ts: ts + 5 * DAY, type: "great", sev: 0, note: "" });
  }
  for (let d = 70; d >= 0; d -= 3) {
    const t = new Date(now - d * DAY);
    const key = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
    weights.push({ id: "w" + d, date: key, value: Math.round((231 - (70 - d) * 0.24 + Math.sin(d) * 0.8) * 10) / 10 });
    days[key] = { protein: 70 + (d % 5) * 9, water: 5 + (d % 4) };
  }
  return { shots, weights, effects, days };
}

(async () => {
  process.on("unhandledRejection", e => { console.log("Crashed: " + (e && e.stack || e)); process.exit(2); });
  await new Promise(r => server.listen(8124, r));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices["Pixel 7"] });
  // Stand-in for the Android notification plugin, so the test can see exactly what gets scheduled.
  await ctx.addInitScript(() => {
    window.__scheduled = []; window.__scheduleCalls = 0;
    window.Capacitor = { Plugins: { LocalNotifications: {
      checkPermissions: async () => ({ display: "granted" }),
      requestPermissions: async () => ({ display: "granted" }),
      createChannel: async c => { (window.__channels = window.__channels || []).push(c); },
      getPending: async () => ({ notifications: window.__scheduled.map(n => ({ id: n.id })) }),
      cancel: async ({ notifications }) => { const ids = new Set(notifications.map(n => n.id)); window.__scheduled = window.__scheduled.filter(n => !ids.has(n.id)); },
      schedule: async ({ notifications }) => { window.__scheduleCalls++; window.__scheduled.push(...notifications); return { notifications }; },
    } } };
  });
  const page = await ctx.newPage();
  page.on("pageerror", e => fail("JavaScript error: " + e.message));
  page.on("console", m => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fail("Console error: " + m.text()); });
  const shot = async n => { await page.waitForTimeout(450); await page.screenshot({ path: path.join(out, n + ".png") }); };
  const state = () => page.evaluate(() => JSON.parse(localStorage.getItem("plume.v1") || "null"));
  const tap = async sel => { await page.locator(sel).first().click(); await page.waitForTimeout(350); };
  const noOverflow = async where => {
    const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    if (w[0] > w[1] + 1) fail(`${where}: page scrolls sideways (${w[0]}px wide on a ${w[1]}px screen)`);
  };

  await page.goto("http://localhost:8124/index.html");
  await page.waitForTimeout(800);

  // ---------- Onboarding ----------
  await shot("01-welcome");
  if (await page.locator("#nav").isVisible()) fail("Bottom nav bar should be hidden during onboarding");
  else ok("Nav bar hidden during onboarding");
  await tap('[data-action="ob-next"]');
  await tap('[data-action="ob-set"][data-k="med"][data-v="Zepbound"]');
  await tap('[data-action="ob-set"][data-k="dose"][data-v="5 mg"]');
  await shot("02-medication");
  await tap('[data-action="ob-next"]');
  await tap('[data-action="ob-set"][data-k="shotDay"][data-v="1"]');
  await page.fill("#ob-time", "19:00");
  await shot("03-shot-day");
  await tap('[data-action="ob-next"]');
  await page.fill("#ob-weight", "214.6");
  await page.fill("#ob-goal", "175");
  await page.fill("#ob-name", "Alex");
  await shot("04-starting-point");
  await tap('[data-action="ob-finish"]');
  let s = await state();
  if (!s || !s.settings.onboarded) fail("Onboarding did not finish");
  else if (s.settings.dose !== "5 mg" || s.settings.shotDay !== 1 || s.weights.length !== 1 || s.settings.name !== "Alex") fail("Onboarding saved wrong values: " + JSON.stringify(s.settings));
  else ok("Onboarding saves medication, dose, shot day, weight and name");
  await shot("05-today-new");

  // ---------- Reminders ----------
  await page.waitForTimeout(1200);
  let sched = await page.evaluate(() => window.__scheduled);
  const shotRem = sched.find(n => n.id === 1);
  if (!shotRem || !shotRem.schedule.on || shotRem.schedule.on.weekday !== 2) fail("Weekly shot reminder missing or on the wrong day: " + JSON.stringify(shotRem));
  else ok("Shot reminder repeats weekly on Monday 7 PM");
  // Plan for "today at 8 AM" so the result doesn't depend on when the test runs.
  const plan = () => page.evaluate(() => { const n = new Date(); n.setHours(8, 0, 0, 0); return reminderPlan(n).map(x => x.id); });
  let ids = await plan();
  const todayWater = l => l.filter(i => i >= 1000 && i < 1020).length;
  if (todayWater(ids) !== 5) fail("Expected 5 water reminders today (9, 11, 1, 3, 5), got " + todayWater(ids));
  else ok("5 water reminders a day, every 2 hours from 9 AM");
  if (!ids.includes(2000)) fail("Lunch protein reminder missing");
  if (ids.filter(i => i >= 5000 && i < 5100).length !== 1) fail("Expected exactly one weigh-in reminder in the coming week, got " + ids.filter(i => i >= 5000 && i < 5100).length);
  else ok("One weigh-in reminder per week");
  if (ids.filter(i => i >= 4000 && i < 4100).length !== 1) fail("Expected one day-after-shot check-in per week");
  else ok("One day-after-shot check-in per week");
  if (ids.some(i => i >= 3000 && i < 3100)) fail("Evening wrap-up should be off by default");
  await page.evaluate(() => { const t = today(); t.water = S.settings.waterGoal; t.protein = S.settings.proteinGoal; save(); });
  ids = await plan();
  if (todayWater(ids) !== 0 || ids.includes(2000)) fail("Today's water/protein reminders should stop once goals are hit");
  else if (!ids.some(i => i >= 1020 && i < 1040)) fail("Tomorrow's water reminders should still be there");
  else ok("Water and protein reminders stop for the day once goals are hit, and come back tomorrow");
  await page.evaluate(() => { const t = today(); t.water = 0; t.protein = 0; save(); render(); });
  await noOverflow("Today (new user)");

  // ---------- Log a shot ----------
  await tap('.hero [data-action="log-shot"]');
  await shot("06-log-shot");
  await tap('.site-list [data-site="thigh-l"]');
  await tap('[data-action="save-shot"]');
  s = await state();
  if (s.shots.length !== 1 || s.shots[0].site !== "thigh-l" || s.shots[0].dose !== "5 mg") fail("Shot not saved correctly: " + JSON.stringify(s.shots));
  else ok("Logging a shot saves site and dose");
  const heroText = await page.locator(".hero").innerText();
  if (!/Next shot in/.test(heroText)) fail("Hero should count down to the next shot after logging, got: " + heroText.replace(/\n/g, " "));
  else ok("Countdown moves to next week after logging");
  const sugg = await page.evaluate(() => suggestedSite());
  if (sugg === "thigh-l") fail("Site rotation suggested the site that was just used");
  else ok("Site rotation suggests a different site next (" + sugg + ")");

  // ---------- Protein, water, symptom, weight ----------
  await tap('[data-action="protein"][data-v="25"]');
  await tap('[data-action="protein"][data-v="10"]');
  await tap('[data-action="water"][data-v="1"]');
  await tap('[data-action="water"][data-v="1"]');
  await tap('[data-action="water"][data-v="1"]');
  s = await state();
  const k = Object.keys(s.days).pop();
  if (s.days[k].protein !== 35 || s.days[k].water !== 3) fail("Protein/water wrong: " + JSON.stringify(s.days[k]));
  else ok("Protein and water buttons add up");
  await tap('[data-action="protein-custom"]');
  await shot("07-add-protein");
  await tap('#sheet [data-action="protein"][data-v="30"]');
  s = await state();
  if (s.days[Object.keys(s.days).pop()].protein !== 65) fail("Protein quick pick did not add 30 g");
  else ok("Protein food picks work");

  await tap('[data-action="effect"][data-type="nausea"]');
  await tap('#sheet [data-action="pick-sev"][data-v="1"]');
  await shot("08-symptom");
  await tap('[data-action="save-effect"]');
  s = await state();
  if (s.effects.length !== 1 || s.effects[0].sev !== 1) fail("Symptom not saved: " + JSON.stringify(s.effects));
  else ok("Symptom with severity saves");

  await tap('[data-action="log-weight"]');
  await page.fill("#w-val", "213.2");
  await shot("09-weigh-in");
  await tap('[data-action="save-weight"]');
  s = await state();
  if (s.weights.length !== 1 || s.weights[0].value !== 213.2) fail("Same-day weigh-in should replace today's value: " + JSON.stringify(s.weights));
  else ok("Same-day weigh-in replaces the earlier one");

  // Quick-add button in the nav
  await tap('.nav .fab');
  await shot("10-quick-add");
  await page.goBack(); await page.waitForTimeout(400); // Android back button closes the sheet
  if (await page.locator("#sheet.show").count()) fail("Back button did not close the sheet");
  else ok("Back button closes sheets");

  // ---------- Sample data for realistic screens ----------
  await page.evaluate(d => { const st = JSON.parse(localStorage.getItem("plume.v1")); Object.assign(st, d); st.settings.dose = "7.5 mg"; localStorage.setItem("plume.v1", JSON.stringify(st)); }, sampleData(Date.now()));
  await page.reload(); await page.waitForTimeout(800);
  await shot("11-today");
  await noOverflow("Today");

  await tap('.nav [data-tab="history"]');
  await shot("12-history-shots");
  await tap('[data-action="seg"][data-v="weight"]');
  await shot("13-history-weight");
  await tap('[data-action="seg"][data-v="effects"]');
  await shot("14-history-symptoms");
  await tap('.nav [data-tab="progress"]');
  await shot("15-progress-free");
  await noOverflow("Progress");
  await tap('[data-action="range"][data-v="all"]');
  await shot("16-progress-locked");
  await tap('[data-action="report"]');
  await shot("17-pro-offer");
  await tap('#sheet [data-action="buy"]');
  s = await state();
  if (!s.settings.pro) fail("Pro unlock (test build) did not turn Pro on");
  else ok("Pro unlock works in the test build");
  await shot("18-progress-pro");
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await shot("19-progress-pro-bottom");
  const report = await page.evaluate(() => buildReport());
  if (!/Zepbound/.test(report) || !/Weight:/.test(report) || !/Nausea/.test(report)) fail("Doctor summary is missing parts:\n" + report);
  else ok("Doctor summary includes medication, weight and symptoms");
  fs.writeFileSync(path.join(out, "doctor-summary-sample.txt"), report);

  await tap('.nav [data-tab="me"]');
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot("20-settings");
  await page.locator(".rem-row").first().scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -120));
  await shot("20b-reminders");
  await tap('.rem-text[data-action="edit-water"]');
  await tap('[data-action="water-opt"][data-k="waterEvery"][data-v="3"]');
  await shot("20c-water-reminders");
  await tap('[data-action="water-save"]');
  await page.waitForTimeout(300);
  ids = await plan();
  if (todayWater(ids) !== 4) fail("Every 3 hours from 9 AM to 7 PM should give 4 reminders, got " + todayWater(ids));
  else ok("Changing water reminders to every 3 hours works");
  await tap('.toggle[data-k="remindWater"]');
  await page.waitForTimeout(400);
  sched = await page.evaluate(() => window.__scheduled.map(n => n.id));
  if (sched.some(i => i >= 1000 && i < 1200)) fail("Turning water reminders off should cancel them");
  else ok("Turning a reminder off cancels it");
  await tap('.toggle[data-k="remindWater"]');
  const ch = await page.evaluate(() => (window.__channels || []).map(c => c.id + ":" + c.sound));
  if (!ch.includes("plume-reminders:plume_chime.wav") || !ch.includes("plume-water:plume_water.wav")) fail("Notification sound channels not set up: " + JSON.stringify(ch));
  else ok("Notification channels use the Plume chime and water-drop sounds");
  await tap('[data-action="test-notif"]');
  await page.waitForTimeout(300);
  const tests = await page.evaluate(() => window.__scheduled.filter(n => n.id >= 9000).map(n => n.channelId));
  if (tests.length !== 2 || !tests.includes("plume-water")) fail("Test notification button should schedule 2 test reminders, got " + JSON.stringify(tests));
  else ok("'Send a test notification' schedules a chime and a water-drop reminder");
  await shot("20d-test-notification");
  await noOverflow("Settings");
  await tap('[data-action="edit-goals"]');
  await tap('[data-action="goal-unit"][data-v="kg"]');
  await tap('[data-action="goals-save"]');
  s = await state();
  const lastW = s.weights.sort((a, b) => a.date.localeCompare(b.date)).pop().value;
  if (s.settings.unit !== "kg" || lastW > 120) fail("Switching to kg did not convert weights (latest " + lastW + ")");
  else ok("Switching units converts all weigh-ins (latest " + lastW + " kg)");

  // ---------- Dark mode ----------
  await page.emulateMedia({ colorScheme: "dark" });
  await tap('.nav [data-tab="today"]');
  await shot("21-today-dark");
  await tap('.nav [data-tab="progress"]');
  await shot("22-progress-dark");
  await tap('.nav [data-tab="today"]');
  await tap('.hero [data-action="log-shot"]');
  await shot("23-log-shot-dark");

  const report2 = [`Plume app test ${new Date().toISOString()}`, `${problems.length} problem(s)`, "", ...problems.map(p => "FAIL " + p), ...notes.map(n => "ok   " + n)].join("\n");
  fs.writeFileSync(path.join(out, "report.txt"), report2);
  console.log("\n" + report2);
  await browser.close(); server.close();
  process.exit(problems.length ? 1 : 0);
})();
