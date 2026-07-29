import { chromium } from 'playwright';
import path from 'path';
import { fileURLToPath } from 'url';

const SCREENSHOTS_DIR = 'C:\\Users\\Nicolas\\Documents\\PrecificacaoBruninho\\priceradar\\screenshots';
const BASE_URL = 'http://localhost:5173';

function logCheck(ok, msg) {
  const symbol = ok ? '✓' : '✗';
  console.log(`  ${symbol} ${msg}`);
  return ok;
}

async function getComputedColor(page, selector, property = 'background-color') {
  return page.evaluate(
    ({ sel, prop }) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      return window.getComputedStyle(el)[prop];
    },
    { sel: selector, prop: property }
  );
}

function rgbToHex(rgb) {
  if (!rgb) return null;
  const m = rgb.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!m) return rgb;
  return '#' + [m[1], m[2], m[3]]
    .map(v => parseInt(v).toString(16).padStart(2, '0'))
    .join('').toUpperCase();
}

async function run() {
  const browser = await chromium.launch({ headless: false, slowMo: 50 });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1400, height: 900 });

  const results = [];

  // ─── STEP 1: Load the page ─────────────────────────────────────────────────
  console.log('\n[1] Loading http://localhost:5173 ...');
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\01_homepage.png`, fullPage: true });
  console.log('    Screenshot saved: 01_homepage.png');

  // Check header background color
  const headerBg = await getComputedColor(page, 'header, nav, [class*="header"], [class*="Header"]');
  const headerHex = rgbToHex(headerBg);
  console.log(`    Header bg color raw: ${headerBg} → hex: ${headerHex}`);

  // Also check any element with dark green tone
  const darkGreenEl = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('*'));
    for (const el of all) {
      const bg = window.getComputedStyle(el).backgroundColor;
      const m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (m) {
        const r = +m[1], g = +m[2], b = +m[3];
        // #0B5A42 = rgb(11, 90, 66)
        if (Math.abs(r - 11) < 20 && Math.abs(g - 90) < 20 && Math.abs(b - 66) < 20) {
          return { tag: el.tagName, class: el.className, bg };
        }
      }
    }
    return null;
  });
  results.push(logCheck(!!darkGreenEl, `Dark green (#0B5A42) header found: ${JSON.stringify(darkGreenEl)}`));

  // Check "PriceRadar" title in header
  const titleText = await page.evaluate(() => {
    const h1 = document.querySelector('h1, [class*="title"], [class*="brand"], [class*="logo"]');
    return h1 ? h1.textContent.trim() : document.title;
  });
  console.log(`    Page title/h1: "${titleText}"`);
  const hasPriceRadar = await page.evaluate(() => document.body.innerText.includes('PriceRadar'));
  results.push(logCheck(hasPriceRadar, `"PriceRadar" text present on page`));

  // ─── STEP 2: Check search form ──────────────────────────────────────────────
  console.log('\n[2] Checking search form ...');

  // Check for white input fields
  const inputBg = await getComputedColor(page, 'input[type="text"], input[type="number"], input:not([type])');
  console.log(`    Input bg color: ${inputBg} → ${rgbToHex(inputBg)}`);
  const inputsWhite = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input'));
    return inputs.some(el => {
      const bg = window.getComputedStyle(el).backgroundColor;
      return bg === 'rgb(255, 255, 255)' || bg === 'rgba(255, 255, 255, 1)' || bg === 'white';
    });
  });
  results.push(logCheck(inputsWhite, 'Input fields have white background'));

  // Check for rounded borders on inputs
  const inputRadius = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input'));
    for (const el of inputs) {
      const r = window.getComputedStyle(el).borderRadius;
      if (r && r !== '0px') return r;
    }
    return null;
  });
  results.push(logCheck(!!inputRadius, `Input fields have rounded borders: ${inputRadius}`));

  // Check for orange button "Buscar concorrentes"
  const buscarBtn = await page.locator('button', { hasText: 'Buscar concorrentes' }).first();
  const buscarExists = await buscarBtn.count() > 0;
  results.push(logCheck(buscarExists, '"Buscar concorrentes" button exists'));

  if (buscarExists) {
    const btnBg = await buscarBtn.evaluate(el => window.getComputedStyle(el).backgroundColor);
    console.log(`    Button bg: ${btnBg} → ${rgbToHex(btnBg)}`);
    const isOrange = await buscarBtn.evaluate(el => {
      const bg = window.getComputedStyle(el).backgroundColor;
      const m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (!m) return false;
      const r = +m[1], g = +m[2], b = +m[3];
      // Orange: high R, medium G, low B
      return r > 180 && g > 80 && g < 160 && b < 80;
    });
    results.push(logCheck(isOrange, `"Buscar concorrentes" button is orange (${rgbToHex(btnBg)})`));
  }

  // ─── STEP 3: Fill and submit the form ──────────────────────────────────────
  console.log('\n[3] Filling and submitting form ...');

  // Find cidade input
  const cidadeInput = page.locator('input[placeholder*="cidade"], input[placeholder*="Cidade"], input[name*="cidade"], input[id*="cidade"]').first();
  const cidadeCount = await cidadeInput.count();
  if (cidadeCount > 0) {
    await cidadeInput.fill('Fortaleza, CE');
    console.log('    Filled cidade: Fortaleza, CE');
  } else {
    // Try first text input
    const firstInput = page.locator('input').first();
    await firstInput.fill('Fortaleza, CE');
    console.log('    Filled first input with: Fortaleza, CE');
  }

  // Find preço mínimo
  const minInput = page.locator('input[placeholder*="min"], input[placeholder*="Min"], input[name*="min"], input[id*="min"]').first();
  const minCount = await minInput.count();
  if (minCount > 0) {
    await minInput.fill('280000');
    console.log('    Filled preço mínimo: 280000');
  }

  // Find preço máximo
  const maxInput = page.locator('input[placeholder*="max"], input[placeholder*="Max"], input[name*="max"], input[id*="max"]').first();
  const maxCount = await maxInput.count();
  if (maxCount > 0) {
    await maxInput.fill('500000');
    console.log('    Filled preço máximo: 500000');
  }

  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\02_form_filled.png`, fullPage: true });
  console.log('    Screenshot saved: 02_form_filled.png');

  // Click the search button
  await buscarBtn.click();
  console.log('    Clicked "Buscar concorrentes"');

  // Wait for results
  console.log('    Waiting for results to load...');
  await page.waitForTimeout(3000);

  // Wait for any loading indicator to disappear
  try {
    await page.waitForFunction(
      () => !document.body.innerText.includes('Carregando') && !document.body.innerText.includes('Loading'),
      { timeout: 15000 }
    );
  } catch (e) {
    console.log('    (timeout waiting for loading to finish, proceeding anyway)');
  }

  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\03_results_loaded.png`, fullPage: true });
  console.log('    Screenshot saved: 03_results_loaded.png');

  // ─── STEP 4: Verify results ─────────────────────────────────────────────────
  console.log('\n[4] Verifying results ...');

  const bodyText = await page.evaluate(() => document.body.innerText);

  // 4a. KPI cards: check for 5 cards
  const kpiCount = await page.evaluate(() => {
    // look for card-like elements with numeric content
    const candidates = Array.from(document.querySelectorAll('[class*="card"], [class*="Card"], [class*="kpi"], [class*="KPI"], [class*="stat"], [class*="Stat"]'));
    return candidates.length;
  });
  console.log(`    KPI/card elements found: ${kpiCount}`);

  // Check first card has green background
  const firstCardGreen = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('[class*="card"], [class*="Card"], [class*="kpi"], [class*="stat"]'));
    if (cards.length === 0) return null;
    const first = cards[0];
    const bg = window.getComputedStyle(first).backgroundColor;
    const m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!m) return { bg, isGreen: false };
    const r = +m[1], g = +m[2], b = +m[3];
    // Green: g dominant
    const isGreen = g > r && g > b && g > 50;
    return { bg, isGreen };
  });
  console.log(`    First card bg: ${JSON.stringify(firstCardGreen)}`);

  // Check last card has orange left border (Ref. MRV)
  const hasRefMRV = bodyText.includes('Ref. MRV') || bodyText.includes('MRV');
  results.push(logCheck(hasRefMRV, '"Ref. MRV" or "MRV" text present in results'));

  const lastCardOrangeBorder = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('[class*="card"], [class*="Card"], [class*="kpi"], [class*="stat"]'));
    if (cards.length === 0) return null;
    const last = cards[cards.length - 1];
    const borderColor = window.getComputedStyle(last).borderLeftColor;
    const m = borderColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!m) return { borderColor, isOrange: false };
    const r = +m[1], g = +m[2], b = +m[3];
    const isOrange = r > 180 && g > 80 && g < 160 && b < 80;
    return { borderColor, isOrange };
  });
  console.log(`    Last card border-left: ${JSON.stringify(lastCardOrangeBorder)}`);
  results.push(logCheck(lastCardOrangeBorder?.isOrange, `Last KPI card has orange left border`));

  // 4b. Bar chart
  const hasChart = await page.evaluate(() => {
    return !!(document.querySelector('canvas, svg[class*="chart"], [class*="recharts"], [class*="chart"], [class*="Chart"]'));
  });
  results.push(logCheck(hasChart, 'Bar chart (canvas/svg/recharts) present'));

  // 4c. Result cards with green top bar
  const resultCardsInfo = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('[class*="result"], [class*="Result"], [class*="listing"], [class*="Listing"], [class*="property"], [class*="Property"], [class*="imovel"], [class*="Imovel"]'));
    return {
      count: cards.length,
      firstBorderTop: cards[0] ? window.getComputedStyle(cards[0]).borderTop : null,
      firstBorderTopColor: cards[0] ? window.getComputedStyle(cards[0]).borderTopColor : null
    };
  });
  console.log(`    Result cards found: ${resultCardsInfo.count}`);

  // Check for portal badges (vivareal, zapimoveis, olx)
  const hasVivaReal = bodyText.toLowerCase().includes('vivareal') || bodyText.toLowerCase().includes('viva real');
  const hasZap = bodyText.toLowerCase().includes('zapimoveis') || bodyText.toLowerCase().includes('zap');
  const hasOlx = bodyText.toLowerCase().includes('olx');
  results.push(logCheck(hasVivaReal || hasZap || hasOlx, `Portal badges: vivareal=${hasVivaReal}, zap=${hasZap}, olx=${hasOlx}`));

  // Check for variation badge
  const hasVariation = bodyText.includes('%') || bodyText.includes('variação') || bodyText.includes('Variação');
  results.push(logCheck(hasVariation, 'Variation/percentage values present in results'));

  // 4d. "Exportar Excel" button
  const exportBtn = page.locator('button', { hasText: /exportar excel/i }).first();
  const exportExists = await exportBtn.count() > 0;
  results.push(logCheck(exportExists, '"Exportar Excel" button present'));

  if (exportExists) {
    const exportBg = await exportBtn.evaluate(el => window.getComputedStyle(el).backgroundColor);
    const exportHex = rgbToHex(exportBg);
    const isOrange = await exportBtn.evaluate(el => {
      const bg = window.getComputedStyle(el).backgroundColor;
      const m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (!m) return false;
      const r = +m[1], g = +m[2], b = +m[3];
      return r > 180 && g > 80 && g < 160 && b < 80;
    });
    results.push(logCheck(isOrange, `"Exportar Excel" button is orange (${exportHex})`));
  }

  // ─── STEP 5: Final full-page screenshot ─────────────────────────────────────
  console.log('\n[5] Taking final screenshot ...');
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\04_final_results.png`, fullPage: true });
  console.log('    Screenshot saved: 04_final_results.png');

  // Also scroll to make sure everything visible and take viewport screenshot
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${SCREENSHOTS_DIR}\\05_final_viewport.png`, fullPage: false });
  console.log('    Screenshot saved: 05_final_viewport.png');

  // ─── Summary ────────────────────────────────────────────────────────────────
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  const passed = results.filter(Boolean).length;
  const total = results.length;
  console.log(`  RESULTS: ${passed}/${total} checks passed`);
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  await browser.close();

  if (passed < total) {
    process.exit(1);
  }
}

run().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
