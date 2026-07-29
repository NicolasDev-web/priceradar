import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

const SHOTS = 'C:/Users/Nicolas/Documents/PrecificacaoBruninho/priceradar/screenshots';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.setViewportSize({ width: 1400, height: 900 });
await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });

// Click search button
await page.click('form button[type="submit"]');
await page.waitForTimeout(4000);

const result = await page.evaluate(() => {
  const header = document.querySelector('header');
  const cs = window.getComputedStyle(header);
  const bgOpacity = cs.getPropertyValue('--tw-bg-opacity').trim();
  const bgColor = cs.getPropertyValue('background-color');

  // Check the submit button
  const submitBtn = document.querySelector('form button[type="submit"]');
  const submitCs = submitBtn ? window.getComputedStyle(submitBtn) : null;

  // Check export button
  const allBtns = Array.from(document.querySelectorAll('header button'));
  const btnData = allBtns.map(b => ({
    text: b.textContent.trim(),
    bg: window.getComputedStyle(b).backgroundColor,
    classList: b.className.substring(0, 80),
    twBgOpacity: window.getComputedStyle(b).getPropertyValue('--tw-bg-opacity').trim(),
  }));

  // Check KPI first card
  const kpiGrid = document.querySelector('.grid.grid-cols-2');
  const firstKpi = kpiGrid ? kpiGrid.firstElementChild : null;
  const firstKpiBg = firstKpi ? window.getComputedStyle(firstKpi).backgroundColor : null;
  const firstKpiClass = firstKpi ? firstKpi.className.substring(0, 80) : null;
  const firstKpiTwOp = firstKpi ? window.getComputedStyle(firstKpi).getPropertyValue('--tw-bg-opacity') : null;

  return {
    header: { twBgOpacity: bgOpacity, bgColor, classList: header.className },
    submitBtn: submitBtn ? {
      bg: submitCs.backgroundColor,
      twBgOp: submitCs.getPropertyValue('--tw-bg-opacity').trim(),
      cls: submitBtn.className.substring(0, 100),
    } : null,
    headerButtons: btnData,
    firstKpi: { bg: firstKpiBg, cls: firstKpiClass, twOp: firstKpiTwOp },
  };
});
console.log(JSON.stringify(result, null, 2));

// Save header screenshot
const headerBuf = await page.screenshot({ clip: { x: 0, y: 0, width: 1400, height: 65 } });
writeFileSync(`${SHOTS}/07_header_closeup.png`, headerBuf);

// Save first KPI card area
const kpiBuf = await page.screenshot({ clip: { x: 80, y: 240, width: 250, height: 150 } });
writeFileSync(`${SHOTS}/08_kpi_first.png`, kpiBuf);

console.log('screenshots saved');
await browser.close();
