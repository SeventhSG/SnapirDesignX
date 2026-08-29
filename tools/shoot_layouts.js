/**
 * Render the built interface at real device sizes and save screenshots.
 *
 * There is no Android device here, so this is how the mobile layout gets looked
 * at rather than assumed. It drives the actual built bundle against the actual
 * backend, in Chromium, at the viewport sizes a phone and a tablet report.
 *
 *   node tools/shoot_layouts.js <baseUrl> <outDir>
 */
const puppeteer = require("puppeteer-core");
const path = require("node:path");
const fs = require("node:fs");

const BASE = process.argv[2] || "http://127.0.0.1:8765";
const OUT = process.argv[3] || path.join(__dirname, "..", "shots");

const CHROME = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
].find((p) => fs.existsSync(p));

const SIZES = [
  { name: "phone-portrait", width: 412, height: 915, dsf: 2.6 },
  { name: "phone-landscape", width: 915, height: 412, dsf: 2.6 },
  { name: "tablet-portrait", width: 800, height: 1180, dsf: 2 },
  { name: "desktop", width: 1440, height: 900, dsf: 1 },
];

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Click the first element matching a selector, optionally by its text. */
async function click(page, sel, text) {
  return page.evaluate(
    (s, t) => {
      const els = [...document.querySelectorAll(s)];
      const el = t ? els.find((e) => (e.innerText || "").includes(t)) : els[0];
      if (!el) return "no match " + s;
      el.click();
      return "ok";
    },
    sel,
    text || ""
  );
}

(async () => {
  if (!CHROME) throw new Error("No Chrome or Edge found");
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1"],
  });

  for (const s of SIZES) {
    const page = await browser.newPage();
    await page.setViewport({
      width: s.width,
      height: s.height,
      deviceScaleFactor: 1,
      isMobile: s.dsf > 1,
      hasTouch: s.dsf > 1,
    });
    await page.goto(BASE + "/", { waitUntil: "networkidle2", timeout: 30000 });
    // The splash is held for a full five seconds by design; wait it out.
    await page.waitForSelector(".home, .empty", { timeout: 20000 });
    await wait(700);

    const shot = async (n) => {
      const f = path.join(OUT, `${s.name}-${n}.png`);
      await page.screenshot({ path: f });
      console.log("  " + path.basename(f));
    };

    console.log(`${s.name} ${s.width}x${s.height}`);
    await shot("1-home");

    console.log("  card: " + (await click(page, ".card")));
    await wait(1200);
    await shot("2-rooms");

    // The first row is a flat heading with no handler; pick a real room.
  console.log("  room: " + (await page.evaluate(() => {
    const row = [...document.querySelectorAll(".tbl tbody tr")]
      .find((r) => r.querySelector(".t-ok"));
    if (!row) return "no ready room";
    row.click();
    return "ok";
  })));
    await wait(4000);
    await shot("3-work");

    // Sketch mode moves the rail and adds the outline bar; both are overlays
    // that have to survive a narrow viewport.
    console.log("  sketch: " + (await click(page, ".vp .seg button", "Sketch")));
    await wait(1400);
    await shot("4-sketch");

    // The settings screen is the other two-column layout worth checking.
    console.log("  settings: " + (await click(page, ".titlebar .right .btn", "")));
    await wait(900);
    await shot("5-settings");

    await page.close();
  }

  await browser.close();
  console.log("done -> " + OUT);
})().catch((e) => {
  console.error("FAILED", e);
  process.exit(1);
});
