/**
 * Проверка контраста токенов по WCAG 2.1.
 *
 *   node scripts/check-contrast.mjs
 *
 * Читает реальные значения из src/app/globals.css, а не дублирует их здесь, —
 * иначе проверка разъедется с оформлением при первой же правке токена.
 *
 * Пороги WCAG 2.1:
 *   AA  обычный текст  4.5:1
 *   AA  крупный текст  3.0:1
 *   AA  границы/иконки 3.0:1  (критерий 1.4.11 «Non-text Contrast»)
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const cssPath = join(here, "..", "src", "app", "globals.css");
const css = readFileSync(cssPath, "utf8");

/** Вырезать тело блока по его селектору. */
function block(selector) {
  const start = css.indexOf(selector + " {");
  if (start === -1) throw new Error(`Блок ${selector} не найден в globals.css`);
  const open = css.indexOf("{", start);
  const end = css.indexOf("\n}", open);
  return css.slice(open, end);
}

function vars(selector) {
  const found = {};
  for (const match of block(selector).matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    found[match[1]] = match[2];
  }
  return found;
}

const light = vars(":root");
const dark = { ...light, ...vars('[data-theme="dark"]') };

function toRgb(hex) {
  let h = hex.replace("#", "");
  if (h.length === 3) h = [...h].map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function luminance(hex) {
  const [r, g, b] = toRgb(hex).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** @type {{theme:string, fg:string, bg:string, min:number, what:string}[]} */
const checks = [];

for (const [themeName, t] of [
  ["светлая", light],
  ["тёмная", dark],
]) {
  for (const level of ["low", "medium", "high", "critical", "none"]) {
    checks.push({
      theme: themeName,
      fg: `--risk-${level}-text`,
      bg: "--surface",
      min: 4.5,
      what: `подпись уровня «${level}» на карточке`,
      table: t,
    });
    checks.push({
      theme: themeName,
      fg: `--risk-${level}-text`,
      bg: `--risk-${level}-bg`,
      min: 4.5,
      what: `подпись уровня «${level}» на своей плашке`,
      table: t,
    });
    checks.push({
      theme: themeName,
      fg: `--risk-${level}-border`,
      bg: "--surface",
      min: 3.0,
      what: `граница плашки «${level}»`,
      table: t,
    });
  }

  checks.push(
    { theme: themeName, fg: "--text", bg: "--bg", min: 4.5, what: "основной текст", table: t },
    { theme: themeName, fg: "--text", bg: "--surface", min: 4.5, what: "текст на панели", table: t },
    {
      theme: themeName,
      fg: "--text-muted",
      bg: "--surface",
      min: 4.5,
      what: "вторичный текст",
      table: t,
    },
    {
      theme: themeName,
      fg: "--accent-fg",
      bg: "--accent",
      min: 4.5,
      what: "текст на основной кнопке",
      table: t,
    },
    {
      theme: themeName,
      fg: "--accent",
      bg: "--surface",
      min: 4.5,
      what: "ссылка на панели",
      table: t,
    },
    {
      theme: themeName,
      fg: "--sidebar-fg",
      bg: "--sidebar-bg",
      min: 4.5,
      what: "пункт меню",
      table: t,
    },
    {
      theme: themeName,
      fg: "--sidebar-active-fg",
      bg: "--sidebar-active-bg",
      min: 4.5,
      what: "активный пункт меню",
      table: t,
    },
  );
}

let failed = 0;
let currentTheme = "";

for (const check of checks) {
  const fg = check.table[check.fg];
  const bg = check.table[check.bg];
  if (!fg || !bg) {
    console.error(`ПРОПУЩЕНО: нет токена ${!fg ? check.fg : check.bg}`);
    failed += 1;
    continue;
  }
  if (check.theme !== currentTheme) {
    currentTheme = check.theme;
    console.log(`\n=== Тема: ${currentTheme} ===`);
  }
  const value = ratio(fg, bg);
  const ok = value >= check.min;
  if (!ok) failed += 1;
  const mark = ok ? "OK  " : "ПЛОХО";
  console.log(
    `${mark} ${value.toFixed(2).padStart(5)}:1 (нужно ${check.min.toFixed(1)}) — ${check.what}` +
      `  [${check.fg} на ${check.bg}]`,
  );
}

/*
  Отдельная проверка: «высокий» и «критический» обязаны различаться между собой.
  ТЗ фиксирует для них красный и тёмно-красный, то есть один тон, — значит цвет
  сам по себе различить уровни не даёт, и в интерфейсе нужны подпись, иконка и
  штриховка. Здесь лишь фиксируем фактическую разницу, чтобы она не уползла в
  ноль незаметно.
*/
console.log("\n=== Различимость «высокий» ↔ «критический» ===");
for (const [themeName, t] of [
  ["светлая", light],
  ["тёмная", dark],
]) {
  const pair = ratio(t["--risk-high-text"], t["--risk-critical-text"]);
  console.log(
    `${themeName}: ${pair.toFixed(2)}:1 между подписями. ` +
      (pair < 1.5
        ? "Цветом почти не различаются — подпись, иконка и штриховка обязательны."
        : "Различие есть, но подпись и иконка всё равно обязательны."),
  );
}

if (failed > 0) {
  console.error(`\nНе прошло проверок: ${failed}`);
  process.exit(1);
}
console.log("\nВсе проверки контраста пройдены.");
