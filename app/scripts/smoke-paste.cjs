// Paste-code flow: paste a strategy, Confirm, load data, run.
const path = require("path");
const fs = require("fs");
const { _electron } = require("playwright");
const out = path.resolve(process.argv[2] || "screenshots");
fs.mkdirSync(out, { recursive: true });
const ex = path.join(__dirname, "..", "..", "engine", "examples");
(async () => {
  const app = await _electron.launch({ executablePath: require("electron"), args: [path.join(__dirname, ".."), "--no-sandbox"],
    env: { ...process.env, TICKBENCH_DATA: path.join(out, ".data") } });
  const win = await app.firstWindow();
  await win.setViewportSize({ width: 1480, height: 920 });
  await win.waitForSelector(".example");
  await win.evaluate(() => localStorage.clear());
  await win.click("text=Paste code instead");
  await win.fill("textarea", fs.readFileSync(path.join(ex, "strategies", "sma_cross.mq5"), "utf8"));
  await win.fill("input[aria-label='File name']", "gold ea");
  await win.waitForTimeout(300);
  await win.screenshot({ path: path.join(out, "11-paste.png") });
  await win.click("button:has-text('Confirm')");
  await win.waitForSelector("text=gold_ea.mq5");
  // data via the http-free path: pick the CSV through the engine directly
  await win.evaluate(async (csv) => { window.__csv = csv; }, path.join(ex, "data", "XAUUSD_GC_daily.csv"));
  await app.evaluate(({ dialog }, csv) => { dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [csv] }); },
    path.join(ex, "data", "XAUUSD_GC_daily.csv"));
  await win.click("button:has-text('Choose a CSV file')");
  await win.waitForSelector(".data-strip");
  await win.screenshot({ path: path.join(out, "12-pasted-loaded.png") });
  await win.click(".run-btn");
  await win.waitForSelector(".kpis", { timeout: 60000 });
  await win.waitForTimeout(1200);
  await win.screenshot({ path: path.join(out, "13-pasted-result.png") });
  console.log("paste flow passed");
  await app.close();
})().catch((e) => { console.error(e); process.exit(1); });
