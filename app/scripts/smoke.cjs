// End-to-end smoke test: launch the real Electron app, run an example, screenshot every view.
// Usage (Linux CI / dev):  xvfb-run -a node scripts/smoke.cjs [outDir]
const path = require("path");
const fs = require("fs");
const { _electron } = require("playwright");

const out = path.resolve(process.argv[2] || path.join(__dirname, "..", "screenshots"));
fs.mkdirSync(out, { recursive: true });

(async () => {
  const app = await _electron.launch({
    executablePath: require("electron"),
    args: [path.join(__dirname, ".."), "--no-sandbox"],
    env: { ...process.env, TICKBENCH_DATA: path.join(out, ".data") },
  });
  const win = await app.firstWindow();
  await win.setViewportSize({ width: 1480, height: 920 });
  const shot = async (name) => {
    await win.waitForTimeout(500);
    await win.screenshot({ path: path.join(out, `${name}.png`) });
    console.log("saved", name);
  };
  const errors = [];
  win.on("pageerror", (e) => errors.push(String(e)));
  win.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  await win.waitForSelector(".example", { timeout: 30000 });
  await shot("01-empty");

  for (const theme of ["dark"]) {
    void theme;
  }
  await win.click("text=SMA cross in Pine Script");
  await win.waitForSelector(".kpis", { timeout: 60000 });
  await win.waitForTimeout(1200);
  await shot("02-overview");

  await win.click("role=tab[name=/Price chart/]");
  await win.waitForTimeout(800);
  await shot("03-price-chart");

  await win.click("role=tab[name=/Trades/]");
  await win.waitForSelector("table.data tbody tr");
  await shot("04-trades");
  await win.click("table.data tbody tr:nth-child(3)");
  await win.waitForTimeout(900);
  await shot("05-trade-on-chart");

  await win.click("role=tab[name=/Statistics/]");
  await shot("06-statistics");
  await win.click("role=tab[name=/What it did/]");
  await shot("07-log");

  // a second language, then compare both runs
  await win.click("role=tab[name=/Overview/]");
  await win.click("text=Workspace");
  await win.evaluate(() => document.querySelector(".main-scroll")?.scrollTo(0, 0));
  const ok = await win.locator("text=Run again").count();
  if (ok) await win.click("text=Run again");
  await win.waitForTimeout(1500);
  await win.click("text=History");
  await win.waitForSelector(".history-item");
  const boxes = win.locator(".history-item input[type=checkbox]");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await shot("08-history");
  await win.click("text=Compare selected");
  await win.waitForTimeout(1500);
  await shot("09-compare");

  await win.click("button[aria-label='Toggle light or dark theme']");
  await win.click("text=History");
  await win.locator(".history-item").first().click();
  await win.waitForSelector(".kpis");
  await win.waitForTimeout(1300);
  await shot("10-overview-light");

  await app.close();
  if (errors.length) {
    console.error("Renderer errors:\n" + errors.join("\n"));
    process.exit(1);
  }
  console.log("smoke test passed");
})().catch((e) => { console.error(e); process.exit(1); });
