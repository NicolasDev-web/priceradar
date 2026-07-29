/**
 * verify_mrv2.mjs — Targeted MRV visual design verification for PriceRadar
 * Uses actual class/HTML structure from source code.
 */
import { chromium } from 'playwright';

const SCREENSHOTS_DIR = 'C:\\Users\\Nicolas\\Documents\\PrecificacaoBruninho\\priceradar\\screenshots';
const BASE_URL = 'http://localhost:5173';

// MRV brand colors from tailwind.config.ts
const MRV_GREEN = { r: 11, g: 90, b: 66 };   // #0B5A42
const MRV_ORANGE = { r: 243, g: 146, b: 0 };  // #F39200

function colorDistance(actual, target) {
  const m = actual.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return 9999;
  return Math.abs(+m[1] - target.r) + Math.abs(+m[2] - target.g) + Math.abs(+m[3] - target.b);
}

function rgbToHex(rgb) {
  if (!rgb) return 'null';
  const m = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!m) return rgb;
  return '#' + [m[1], m[2], m[3]].map(v => parseInt(v).toString(16).padStart(2, '0')).join('').toUpperCase();
}

const pass = [];
const fail = [];

function check(ok, label, detail = '') {
  const sym = ok ? '✓' : '✗';
  const line = `  ${sym} ${label}${detail ? ' — ' + detail : ''}`;
  console.log(line);
  (ok ? pass : fail).push(label);
  return ok;
}

async function run() {
  const browser = await chromium.launch({ headless: false, slowMo: 80 });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1400, height: 900 });

  // ══════════════════════════════════════════════════════════════════
  // STEP 1 — Load homepage
  // ══════════════════════════════════════════════════════════════════
  console.log('\n═══ [1] Homepage ═══');
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

  // Header: <header class="bg-mrv-green ...">
  const headerBg = await page.$eval('header', el => window.getComputedStyle(el).backgroundColor);
  const headerDist = colorDistance(headerBg, MRV_GREEN);
  check(headerDist < 30, 'Header is dark green (#0B5A42)', `computed: ${headerBg} → ${rgbToHex(headerBg)}, dist=${headerDist}`);

  // PriceRadar title: <h1 class="font-bold text-lg ...">PriceRadar</h1>
  const h1Text = await page.$eval('header h1', el => el.textContent.trim()).catch(() => '');
  check(h1Text === 'PriceRadar', 'Header h1 = "PriceRadar"', `got: "${h1Text}"`);

  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\01_homepage.png`, fullPage: false });
  console.log('  [screenshot] 01_homepage.png');

  // ══════════════════════════════════════════════════════════════════
  // STEP 2 — Search form
  // ══════════════════════════════════════════════════════════════════
  console.log('\n═══ [2] Search form ═══');

  // White input fields with rounded-[8px]
  const inputBg = await page.$eval('form input[type="text"]', el => window.getComputedStyle(el).backgroundColor);
  check(colorDistance(inputBg, { r: 255, g: 255, b: 255 }) < 5, 'Input fields are white', `computed: ${inputBg}`);

  const inputRadius = await page.$eval('form input[type="text"]', el => window.getComputedStyle(el).borderRadius);
  check(inputRadius && inputRadius !== '0px', 'Input fields have rounded borders', `border-radius: ${inputRadius}`);

  // "Buscar concorrentes" button — bg-mrv-orange
  const btn = await page.$('form button[type="submit"]');
  check(!!btn, '"Buscar concorrentes" button exists in form');

  const btnText = btn ? await btn.textContent() : '';
  check(btnText.trim().includes('Buscar concorrentes'), 'Button text = "Buscar concorrentes"', `got: "${btnText.trim()}"`);

  const btnBg = btn ? await btn.evaluate(el => window.getComputedStyle(el).backgroundColor) : '';
  const btnDist = colorDistance(btnBg, MRV_ORANGE);
  check(btnDist < 40, 'Button is orange (#F39200)', `computed: ${btnBg} → ${rgbToHex(btnBg)}, dist=${btnDist}`);

  // ══════════════════════════════════════════════════════════════════
  // STEP 3 — Fill & submit
  // ══════════════════════════════════════════════════════════════════
  console.log('\n═══ [3] Submit form ═══');

  // The form already has default values set in React state:
  //   cidade = 'Fortaleza, CE', precoMin = '280.000', precoMax = '500.000'
  // Just click submit
  console.log('  Clicking "Buscar concorrentes"...');
  await btn.click();

  // Wait for loading to start & finish
  await page.waitForTimeout(500);

  // Wait until KpiBar appears (grid with 5 cards)
  try {
    await page.waitForSelector('.grid.grid-cols-2.md\\:grid-cols-5', { timeout: 20000 });
    console.log('  KPI grid appeared');
  } catch {
    // try alternative
    try {
      await page.waitForFunction(
        () => document.querySelectorAll('[class*="rounded-card"]').length >= 5,
        { timeout: 20000 }
      );
      console.log('  KPI cards appeared (fallback selector)');
    } catch {
      console.log('  (timeout waiting for KPI cards — proceeding)');
    }
  }

  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\02_results_top.png`, fullPage: false });
  console.log('  [screenshot] 02_results_top.png');

  // ══════════════════════════════════════════════════════════════════
  // STEP 4 — Verify results
  // ══════════════════════════════════════════════════════════════════
  console.log('\n═══ [4] Results verification ═══');

  // 4a. KPI cards: first one = bg-mrv-green, last one = border-l-4 border-mrv-orange
  // KpiBar renders a grid with 5 divs. First: bg-mrv-green. Last: border-l-4 border-mrv-orange.

  // Find the KPI grid: <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
  const kpiCards = await page.$$eval(
    '.grid.grid-cols-2 > div, .grid.md\\:grid-cols-5 > div',
    els => els.map(el => ({
      bg: window.getComputedStyle(el).backgroundColor,
      borderLeft: window.getComputedStyle(el).borderLeftColor,
      borderLeftWidth: window.getComputedStyle(el).borderLeftWidth,
      text: el.textContent.trim().slice(0, 40),
    }))
  ).catch(() => []);

  console.log(`  KPI cards found: ${kpiCards.length}`);
  kpiCards.forEach((c, i) => {
    const bgHex = rgbToHex(c.bg);
    const blHex = rgbToHex(c.borderLeft);
    console.log(`    [${i}] bg=${bgHex} border-left=${blHex} w=${c.borderLeftWidth} text="${c.text.slice(0,30)}"`);
  });

  // First card: bg-mrv-green
  const firstCard = kpiCards[0];
  const firstGreenDist = firstCard ? colorDistance(firstCard.bg, MRV_GREEN) : 9999;
  check(firstGreenDist < 30, 'First KPI card has green background (#0B5A42)', `bg=${firstCard?.bg}, dist=${firstGreenDist}`);

  // There should be 5 KPI cards
  check(kpiCards.length === 5, '5 KPI cards present', `found: ${kpiCards.length}`);

  // Last card ("Ref. MRV"): border-l-4 border-mrv-orange
  const lastCard = kpiCards[kpiCards.length - 1];
  const lastOrangeDist = lastCard ? colorDistance(lastCard.borderLeft, MRV_ORANGE) : 9999;
  const lastHasOrangeBorder = lastOrangeDist < 40 && lastCard?.borderLeftWidth !== '0px';
  check(lastHasOrangeBorder, 'Last KPI card ("Ref. MRV") has orange left border', `border-left=${lastCard?.borderLeft} w=${lastCard?.borderLeftWidth}, dist=${lastOrangeDist}`);

  // Check "Ref. MRV" text visible
  const hasRefMRV = await page.evaluate(() => document.body.innerText.includes('Ref. MRV'));
  check(hasRefMRV, '"Ref. MRV" text visible in page');

  // 4b. Bar chart (PriceChart uses recharts, renders SVG)
  // <div class="bg-white rounded-card shadow-card p-6 mb-6"> containing a recharts svg
  const hasChart = await page.evaluate(() => {
    // Recharts renders a div.recharts-wrapper or SVG
    return !!(
      document.querySelector('.recharts-wrapper') ||
      document.querySelector('.recharts-surface') ||
      document.querySelector('svg.recharts-surface') ||
      document.querySelector('[class*="recharts"]')
    );
  });
  check(hasChart, 'Bar chart (Recharts) present');

  // Reference line in chart
  const hasRefLine = await page.evaluate(() => {
    return !!(document.querySelector('.recharts-reference-line') || document.querySelector('[class*="reference-line"]'));
  });
  check(hasRefLine, 'Reference line present in chart');

  // 4c. Result cards: each has div.h-1.bg-mrv-gradient-subtle at top
  // ResultCard: <div class="bg-white rounded-card ..."><div class="h-1 bg-mrv-gradient-subtle" />...
  const gradientBars = await page.$$('div.h-1');
  const gradientBarCount = gradientBars.length;
  check(gradientBarCount > 0, `Result cards have thin top bar (div.h-1 count: ${gradientBarCount})`);

  // Portal badges (spans with portal labels)
  const bodyText = await page.evaluate(() => document.body.innerText);
  const hasVivaReal = bodyText.includes('VivaReal');
  const hasZap = bodyText.includes('Zap');
  const hasOLX = bodyText.includes('OLX');
  check(hasVivaReal || hasZap || hasOLX, `Portal badges visible: VivaReal=${hasVivaReal}, Zap=${hasZap}, OLX=${hasOLX}`);

  // Variation badges (percentage)
  const hasVariation = bodyText.includes('%');
  check(hasVariation, 'Variation % badges present in result cards');

  // 4d. "Exportar Excel" button in header — only appears after results load
  const exportBtn = await page.$('header button');
  const exportText = exportBtn ? await exportBtn.textContent() : '';
  check(exportText.includes('Exportar Excel'), '"Exportar Excel" button present in header', `text: "${exportText.trim()}"`);

  if (exportBtn) {
    const exportBg = await exportBtn.evaluate(el => window.getComputedStyle(el).backgroundColor);
    const exportDist = colorDistance(exportBg, MRV_ORANGE);
    check(exportDist < 40, '"Exportar Excel" button is orange', `computed: ${exportBg} → ${rgbToHex(exportBg)}, dist=${exportDist}`);
  }

  // ══════════════════════════════════════════════════════════════════
  // STEP 5 — Final screenshots
  // ══════════════════════════════════════════════════════════════════
  console.log('\n═══ [5] Final screenshots ═══');

  // Scroll top for viewport screenshot
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\03_final_viewport.png`, fullPage: false });
  console.log('  [screenshot] 03_final_viewport.png (viewport)');

  // Full page
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\04_final_fullpage.png`, fullPage: true });
  console.log('  [screenshot] 04_final_fullpage.png (full page)');

  // Scroll to result cards section
  await page.evaluate(() => {
    const grid = document.querySelector('.grid.grid-cols-1.md\\:grid-cols-2');
    if (grid) grid.scrollIntoView({ behavior: 'instant' });
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\05_result_cards.png`, fullPage: false });
  console.log('  [screenshot] 05_result_cards.png (result cards section)');

  // ══════════════════════════════════════════════════════════════════
  // Summary
  // ══════════════════════════════════════════════════════════════════
  console.log('\n' + '═'.repeat(55));
  console.log(`  PASSED: ${pass.length}/${pass.length + fail.length}`);
  if (fail.length > 0) {
    console.log(`  FAILED checks:`);
    fail.forEach(f => console.log(`    ✗ ${f}`));
  } else {
    console.log('  ALL CHECKS PASSED');
  }
  console.log('═'.repeat(55) + '\n');

  await browser.close();
  if (fail.length > 0) process.exit(1);
}

run().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
