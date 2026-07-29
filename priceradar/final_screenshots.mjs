/**
 * final_screenshots.mjs — Take high-quality evidence screenshots with headed browser
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

const SHOTS = 'C:/Users/Nicolas/Documents/PrecificacaoBruninho/priceradar/screenshots';

const browser = await chromium.launch({ headless: false, slowMo: 100 });
const page = await browser.newPage();
await page.setViewportSize({ width: 1400, height: 900 });

// Step 1: Load homepage
await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
await page.waitForTimeout(500);

// Screenshot 1: Fresh homepage
await page.screenshot({ path: `${SHOTS}/S1_homepage_fresh.png`, fullPage: false });
console.log('S1_homepage_fresh.png');

// Screenshot 2: Header close-up
const headerEl = await page.$('header');
await headerEl.screenshot({ path: `${SHOTS}/S2_header_closeup.png` });
console.log('S2_header_closeup.png');

// Step 2: Submit form (defaults already set: Fortaleza CE, 280k-500k)
await page.click('form button[type="submit"]');
await page.waitForTimeout(5000);

// Screenshot 3: After results loaded
await page.screenshot({ path: `${SHOTS}/S3_results_above_fold.png`, fullPage: false });
console.log('S3_results_above_fold.png');

// Screenshot 4: KPI cards close-up
const kpiGrid = await page.$('.grid.grid-cols-2.md\\:grid-cols-5, .grid.md\\:grid-cols-5');
if (kpiGrid) {
  await kpiGrid.screenshot({ path: `${SHOTS}/S4_kpi_cards.png` });
  console.log('S4_kpi_cards.png');
} else {
  console.log('KPI grid not found for close-up');
}

// Screenshot 5: Header with export button
await headerEl.screenshot({ path: `${SHOTS}/S5_header_with_export.png` });
console.log('S5_header_with_export.png');

// Screenshot 6: Scroll to chart
await page.evaluate(() => {
  const chart = document.querySelector('.recharts-wrapper, [class*="recharts"]');
  if (chart) chart.scrollIntoView({ behavior: 'instant' });
});
await page.waitForTimeout(300);
await page.screenshot({ path: `${SHOTS}/S6_chart_section.png`, fullPage: false });
console.log('S6_chart_section.png');

// Screenshot 7: Scroll to result cards
await page.evaluate(() => {
  const grid = document.querySelector('.grid.grid-cols-1.md\\:grid-cols-2');
  if (grid) grid.scrollIntoView({ behavior: 'instant' });
});
await page.waitForTimeout(300);
await page.screenshot({ path: `${SHOTS}/S7_result_cards.png`, fullPage: false });
console.log('S7_result_cards.png');

// Screenshot 8: Full page
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(200);
await page.screenshot({ path: `${SHOTS}/S8_full_page.png`, fullPage: true });
console.log('S8_full_page.png');

// Collect verification data
const verification = await page.evaluate(() => {
  // Class-based checks (reliable with Tailwind v3)
  const header = document.querySelector('header');
  const submitBtn = document.querySelector('form button[type="submit"]');
  const firstKpiCard = document.querySelector('.grid.grid-cols-2 > div:first-child, .grid.md\\:grid-cols-5 > div:first-child');
  const lastKpiCard = document.querySelector('.grid.grid-cols-2 > div:last-child, .grid.md\\:grid-cols-5 > div:last-child');
  const exportBtn = Array.from(document.querySelectorAll('header button')).find(b => b.textContent.includes('Exportar Excel'));
  const h1 = document.querySelector('header h1');
  const inputs = Array.from(document.querySelectorAll('form input'));
  const gradientBars = document.querySelectorAll('div.h-1');
  const rechartsEl = document.querySelector('.recharts-wrapper, .recharts-surface, [class*="recharts"]');
  const refLine = document.querySelector('.recharts-reference-line');
  const bodyText = document.body.innerText;

  return {
    header: {
      hasClass_bg_mrv_green: header?.className.includes('bg-mrv-green'),
      bgOpacity: window.getComputedStyle(header).getPropertyValue('--tw-bg-opacity').trim(),
    },
    h1: h1?.textContent.trim(),
    inputs: {
      count: inputs.length,
      firstHasRoundedBorder: inputs[0] ? window.getComputedStyle(inputs[0]).borderRadius !== '0px' : false,
      firstBg: inputs[0] ? window.getComputedStyle(inputs[0]).backgroundColor : null,
    },
    submitBtn: {
      exists: !!submitBtn,
      text: submitBtn?.textContent.trim(),
      hasClass_bg_mrv_orange: submitBtn?.className.includes('bg-mrv-orange'),
      twBgOpacity: submitBtn ? window.getComputedStyle(submitBtn).getPropertyValue('--tw-bg-opacity').trim() : null,
    },
    firstKpiCard: {
      hasClass_bg_mrv_green: firstKpiCard?.className.includes('bg-mrv-green'),
      text: firstKpiCard?.textContent.trim().slice(0, 30),
    },
    lastKpiCard: {
      hasClass_border_mrv_orange: lastKpiCard?.className.includes('border-mrv-orange'),
      text: lastKpiCard?.textContent.trim().slice(0, 30),
    },
    exportBtn: {
      exists: !!exportBtn,
      text: exportBtn?.textContent.trim(),
      hasClass_bg_mrv_orange: exportBtn?.className.includes('bg-mrv-orange'),
    },
    chart: {
      hasRecharts: !!rechartsEl,
      hasRefLine: !!refLine,
    },
    resultCards: {
      gradientBarCount: gradientBars.length,
    },
    portals: {
      hasVivaReal: bodyText.includes('VivaReal'),
      hasZap: bodyText.includes('Zap'),
      hasOLX: bodyText.includes('OLX'),
    },
    hasVariationPct: bodyText.includes('%'),
    hasRefMRV: bodyText.includes('Ref. MRV'),
  };
});

console.log('\n=== VERIFICATION DATA ===');
console.log(JSON.stringify(verification, null, 2));

await browser.close();
