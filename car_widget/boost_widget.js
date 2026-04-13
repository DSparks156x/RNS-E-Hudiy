// =======================================================================
// HUDIY THEME INTEGRATION
// Reads window.hudiy.colorScheme (injected by Qt WebEngine) and maps
// Material You tokens to CSS custom properties.  Falls back to the dark
// defaults baked into the HTML :root block when running outside Hudiy.
// =======================================================================
function applyHudiyColors(scheme) {
  if (!scheme || typeof scheme !== 'object') return;
  const root = document.documentElement;
  // camelCase token → --kebab-case CSS variable
  for (const [key, value] of Object.entries(scheme)) {
    if (typeof value !== 'string') continue;
    const cssVar = '--' + key.replace(/([A-Z])/g, '-$1').toLowerCase();
    root.style.setProperty(cssVar, value);
  }
  // Set data-theme attribute for light/dark detection
  root.setAttribute('data-theme', scheme.darkThemeEnabled === false ? 'light' : 'dark');
}

// Initial load: grab colors if Hudiy is already attached
if (window.hudiy && window.hudiy.colorScheme) {
  applyHudiyColors(window.hudiy.colorScheme);
}
// DEBUG: force dark mode
document.documentElement.setAttribute('data-theme', 'dark');

// Hook live theme changes + late attachment
(function hookHudiy() {
  if (!window.hudiy) return;
  const h = window.hudiy;

  const origColorChanged = h.onColorSchemeChanged;
  h.onColorSchemeChanged = function () {
    applyHudiyColors(h.colorScheme);
    buildTheme(boostTheme);
    if (origColorChanged) origColorChanged();
  };

  const origAttached = h.onAttached;
  h.onAttached = function () {
    applyHudiyColors(h.colorScheme);
    if (origAttached) origAttached();
  };
})();

// Helper: read a CSS variable's current computed value
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// =======================================================================
// THEME — persisted to localStorage, selectable from the gauge style picker.
//   'oem'     : Audi S3 OEM cluster style (hardcoded white/bluish-gray/red)
//   'haltech' : white bar arc gauge with thick square ends
//   'hudiy'   : Material You — colors from Hudiy CSS variables
// =======================================================================
let boostTheme = localStorage.getItem('boost_theme') || 'hudiy';

// =======================================================================
// GAUGE GEOMETRY — dynamic based on selected channel
// =======================================================================
const CX = 100, CY = 100;
const ANGLE_START = -120;         // min position (degrees from top, clockwise)
const ANGLE_END   =  120;         // max position
const ANGLE_SPAN  = ANGLE_END - ANGLE_START; // 240

// Dynamic range — set by computeGaugeRange() when channel changes
let gaugeMin = -10, gaugeMax = 20, gaugeRedValue = 15;

// Boost channels get special PSI display treatment
const BOOST_CHANNELS = new Set(['boost_abs', 'boost_spec', 'boost_actual']);

function computeGaugeRange() {
  if (BOOST_CHANNELS.has(gaugeChannel)) {
    // Boost: always show in PSI range (converted from mbar at display time)
    gaugeMin = -10; gaugeMax = 20; gaugeRedValue = 15;
  } else {
    const ch = CHANNELS[gaugeChannel];
    if (!ch) { gaugeMin = 0; gaugeMax = 100; gaugeRedValue = 80; return; }
    gaugeMin = ch.min;
    gaugeMax = ch.max;
    gaugeRedValue = gaugeMin + (gaugeMax - gaugeMin) * 0.85;
  }
}

function valueToAngle(v) {
  const clamped = Math.max(gaugeMin, Math.min(gaugeMax, v));
  return ANGLE_START + ((clamped - gaugeMin) / (gaugeMax - gaugeMin)) * ANGLE_SPAN;
}
function arcPoint(thetaDeg, r) {
  const rad = thetaDeg * Math.PI / 180;
  return { x: CX + r * Math.sin(rad), y: CY - r * Math.cos(rad) };
}
function arcPath(startDeg, endDeg, r) {
  if (Math.abs(endDeg - startDeg) < 0.01) return '';
  const s = arcPoint(startDeg, r);
  const e = arcPoint(endDeg, r);
  const sweep = endDeg - startDeg;
  const largeArc = Math.abs(sweep) > 180 ? 1 : 0;
  const sweepFlag = sweep > 0 ? 1 : 0;
  return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${largeArc} ${sweepFlag} ${e.x.toFixed(2)} ${e.y.toFixed(2)}`;
}

// Compute nice tick step for a given range
function niceStep(range, targetTicks) {
  const rough = range / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / mag;
  let step;
  if (norm < 1.5) step = 1;
  else if (norm < 3) step = 2;
  else if (norm < 7) step = 5;
  else step = 10;
  return step * mag;
}

// ---- SVG element helpers ----
const SVG_NS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
function svgText(attrs, text) {
  const e = svgEl('text', attrs);
  e.textContent = text;
  return e;
}

// Turbo glyph — rendered as an <image> element referencing turbo.png
const XLINK_NS = 'http://www.w3.org/1999/xlink';
function buildTurboIcon(cx, cy, size) {
  const img = svgEl('image', {
    x: (cx - size / 2).toFixed(2),
    y: (cy - size / 2).toFixed(2),
    width: size,
    height: size,
    preserveAspectRatio: 'xMidYMid meet'
  });
  img.setAttribute('href', 'turbo.png');
  img.setAttributeNS(XLINK_NS, 'xlink:href', 'turbo.png');
  return img;
}

const svg = document.getElementById('gauge');

// Per-theme state set by the builder functions
let gaugeValEl     = null;
let gaugeValFracEl = null;
let gaugeUnitEl    = null;
let gaugeLabelEl   = null;
let setGaugeProgress = () => {};

function setGaugeValue(valStr) {
  if (!gaugeValEl) return;
  if (gaugeValFracEl && valStr.startsWith('-')) {
    const digits = valStr.slice(1);
    gaugeValEl.textContent = digits;
    const numHalf = gaugeValEl.getComputedTextLength() / 2;
    gaugeValFracEl.setAttribute('x', 100 - numHalf - 1);
    gaugeValFracEl.setAttribute('text-anchor', 'end');
    gaugeValFracEl.textContent = '-';
  } else {
    if (gaugeValFracEl) gaugeValFracEl.textContent = '';
    gaugeValEl.textContent = valStr;
  }
}

// Format tick label — no decimals for integers, 1 decimal otherwise
function formatTickLabel(v) {
  return (v === Math.floor(v)) ? String(v) : v.toFixed(1);
}

// ---- Shared tick + label generation for all themes ----
function buildTicks(ticksG, labelsG, opts) {
  const { innerR, majorOuterR, minorOuterR, majorWidth, minorWidth,
          normalColor, redColor, labelYOffset } = opts;
  const range = gaugeMax - gaugeMin;
  const majorStep = niceStep(range, 6);
  const minorStep = majorStep / 5;

  // Snap red start to nearest major tick at or above gaugeRedValue
  const redStart = Math.ceil(gaugeRedValue / majorStep) * majorStep;

  const fontSize = opts.fontSize || 18;
  const GAP = 4; // px between label edge and tick inner edge

  // Collect all tick elements for peak hold
  const majorTicks = [];

  for (let v = gaugeMin; v <= gaugeMax + minorStep * 0.01; v += minorStep) {
    // Snap to avoid floating-point drift
    const snapped = Math.round(v * 1000) / 1000;
    if (snapped > gaugeMax) break;
    const a = valueToAngle(snapped);
    const isMajor = Math.abs(snapped % majorStep) < majorStep * 0.01 ||
                    Math.abs(snapped % majorStep - majorStep) < majorStep * 0.01;
    const outerR = isMajor ? majorOuterR : minorOuterR;
    const width = isMajor ? majorWidth : minorWidth;
    const inRed = snapped >= redStart - majorStep * 0.01;
    const tickInner = (inRed && opts.redInset) ? innerR + 2 : innerR;
    const p1 = arcPoint(a, tickInner);
    const p2 = arcPoint(a, outerR);
    const tickEl = svgEl('line', {
      x1: p1.x.toFixed(2), y1: p1.y.toFixed(2),
      x2: p2.x.toFixed(2), y2: p2.y.toFixed(2),
      stroke: inRed ? redColor : normalColor,
      'stroke-width': width
    });
    ticksG.appendChild(tickEl);
    majorTicks.push({ value: snapped, el: tickEl, origColor: inRed ? redColor : normalColor });
    if (isMajor) {
      if (labelsG) {
        const label = formatTickLabel(snapped);
        // Estimate text width accounting for narrow chars (-, 1, .)
        const charW = [...label].reduce((sum, ch) =>
          sum + ('-.,'.includes(ch) ? 0.25 : '1'.includes(ch) ? 0.35 : 0.5), 0);
        const halfW = charW * fontSize * 0.5;
        const halfH = fontSize * 0.4;
        const aRad = a * Math.PI / 180;
        // Radial extent of text box at this angle
        const radialExtent = halfW * Math.abs(Math.sin(aRad)) + halfH * Math.abs(Math.cos(aRad));
        const lr = innerR - GAP - radialExtent;
        const lp = arcPoint(a, lr);
        labelsG.appendChild(svgText({
          x: lp.x.toFixed(2),
          y: (lp.y + labelYOffset).toFixed(2),
          fill: inRed ? redColor : normalColor,
          'text-anchor': 'middle'
        }, label));
      }
    }
  }
  return majorTicks;
}

// ---- Theme: Haltech (white bar, square ends, thick digital readout) ----
function buildHaltechTheme() {
  const ARC_R = 80;

  svg.appendChild(svgEl('circle', { cx: 100, cy: 100, r: 98, fill: '#1a1a1a', stroke: '#444', 'stroke-width': 2 }));
  svg.appendChild(svgEl('circle', { cx: 100, cy: 100, r: 92, fill: '#0a0a0a' }));

  const ticksG = svgEl('g', { stroke: '#fff', 'stroke-linecap': 'round' });
  const labelsG = svgEl('g', { fill: '#fff', 'font-family': '-apple-system, system-ui, sans-serif', 'font-size': 10, 'font-weight': 600 });
  buildTicks(ticksG, labelsG, {
    innerR: 88, majorOuterR: 98, minorOuterR: 94,
    majorWidth: 2, minorWidth: 1,
    normalColor: '#fff', redColor: '#fff',
    labelR: 62, labelYOffset: 4
  });
  svg.appendChild(ticksG);
  svg.appendChild(labelsG);

  svg.appendChild(svgEl('path', {
    d: arcPath(ANGLE_START, ANGLE_END, ARC_R),
    fill: 'none', stroke: '#2a2a2a', 'stroke-width': 14, 'stroke-linecap': 'butt'
  }));

  const progressEl = svgEl('path', {
    d: '', fill: 'none', stroke: '#fff', 'stroke-width': 14, 'stroke-linecap': 'butt'
  });
  svg.appendChild(progressEl);

  gaugeLabelEl = svgText({
    x: 100, y: 90, 'text-anchor': 'middle', fill: '#fff',
    'font-family': '-apple-system, system-ui, sans-serif',
    'font-size': 14, 'font-weight': 700, 'letter-spacing': 2
  }, '');
  svg.appendChild(gaugeLabelEl);

  svg.appendChild(svgEl('rect', {
    x: 60, y: 108, width: 80, height: 38, rx: 3, ry: 3,
    fill: '#000', stroke: '#e01e1e', 'stroke-width': 2
  }));
  gaugeValEl = svgText({
    x: 100, y: 135, 'text-anchor': 'middle', fill: '#fff',
    'font-family': 'Menlo, Monaco, monospace', 'font-size': 22, 'font-weight': 700
  }, '--');
  svg.appendChild(gaugeValEl);

  gaugeUnitEl = svgText({
    x: 100, y: 164, 'text-anchor': 'middle', fill: '#e01e1e',
    'font-family': '-apple-system, system-ui, sans-serif',
    'font-size': 14, 'font-weight': 700, 'letter-spacing': 2
  }, '');
  svg.appendChild(gaugeUnitEl);

  setGaugeProgress = (val) => {
    const currentAngle = valueToAngle(val);
    const zeroAngle = valueToAngle(Math.max(0, gaugeMin));
    const d = (val >= 0 && gaugeMin < 0)
      ? arcPath(zeroAngle, currentAngle, ARC_R)
      : arcPath(ANGLE_START, currentAngle, ARC_R);
    progressEl.setAttribute('d', d);
  };
  setGaugeProgress(Math.max(0, gaugeMin));
}

// ---- Theme: OEM (Audi S3 cluster — adapts to Hudiy light/dark) ----
function buildOemTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

  // Palette adapts to light/dark
  const faceFill       = isDark ? '#242d36' : '#2d3843';
  const tickColor      = '#fff';
  const redColor       = '#e01e1e';
  const needleBase     = '#000';
  const hubFill        = '#000';
  const readoutFill    = '#0b0f13';
  const readoutStroke  = '#1a2028';
  const valFill        = '#fff';
  const unitFill       = '#8aa0b4';
  const shadowColor    = isDark ? 'rgba(0,0,0,0.6)' : 'rgba(0,0,0,0.15)';
  const glowStd        = isDark ? 0.8 : 0;
  const redGlowStd     = isDark ? 1.2 : 0.4;

  const defs = svgEl('defs');
  const grad = svgEl('linearGradient', { id: 'silverBezel', x1: '0%', y1: '0%', x2: '0%', y2: '100%' });
  if (isDark) {
    grad.appendChild(svgEl('stop', { offset: '0%',   'stop-color': '#a0a0a0' }));
    grad.appendChild(svgEl('stop', { offset: '35%',  'stop-color': '#454545' }));
    grad.appendChild(svgEl('stop', { offset: '55%',  'stop-color': '#505050' }));
    grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': '#959595' }));
  } else {
    // Light mode: original bright silver bezel
    grad.appendChild(svgEl('stop', { offset: '0%',   'stop-color': '#e6e6e6' }));
    grad.appendChild(svgEl('stop', { offset: '35%',  'stop-color': '#6a6a6a' }));
    grad.appendChild(svgEl('stop', { offset: '55%',  'stop-color': '#7a7a7a' }));
    grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': '#dcdcdc' }));
  }
  defs.appendChild(grad);
  // Needle shadow (drop shadow only — glow is a separate shape behind the needle)
  const needleShadow = svgEl('filter', { id: 'needleShadow', x: '-50%', y: '-50%', width: '200%', height: '200%' });
  needleShadow.appendChild(svgEl('feDropShadow', {
    dx: 0, dy: 0.5, 'stdDeviation': 1.2,
    'flood-color': shadowColor
  }));
  defs.appendChild(needleShadow);
  // Needle backlight glow filter (blurs a white shape behind needle in dark mode)
  if (isDark) {
    const needleGlowF = svgEl('filter', { id: 'needleGlow', x: '-50%', y: '-50%', width: '200%', height: '200%' });
    needleGlowF.appendChild(svgEl('feGaussianBlur', { in: 'SourceGraphic', 'stdDeviation': 1.5 }));
    defs.appendChild(needleGlowF);
  }
  // Glow for tick/label elements (backlight in dark, none in light)
  const tickGlow = svgEl('filter', { id: 'tickGlow', x: '-20%', y: '-20%', width: '140%', height: '140%' });
  tickGlow.appendChild(svgEl('feGaussianBlur', { in: 'SourceGraphic', 'stdDeviation': glowStd, result: 'blur' }));
  const merge = svgEl('feMerge');
  merge.appendChild(svgEl('feMergeNode', { in: 'blur' }));
  merge.appendChild(svgEl('feMergeNode', { in: 'SourceGraphic' }));
  tickGlow.appendChild(merge);
  defs.appendChild(tickGlow);
  // Red glow for redline elements
  const redGlow = svgEl('filter', { id: 'redGlow', x: '-20%', y: '-20%', width: '140%', height: '140%' });
  redGlow.appendChild(svgEl('feGaussianBlur', { in: 'SourceGraphic', 'stdDeviation': redGlowStd, result: 'blur' }));
  const redMerge = svgEl('feMerge');
  redMerge.appendChild(svgEl('feMergeNode', { in: 'blur' }));
  redMerge.appendChild(svgEl('feMergeNode', { in: 'SourceGraphic' }));
  redGlow.appendChild(redMerge);
  defs.appendChild(redGlow);
  // Glossy gradient for hub red ring
  const hubGloss = svgEl('linearGradient', { id: 'hubRedGloss', x1: '0%', y1: '0%', x2: '0%', y2: '100%' });
  hubGloss.appendChild(svgEl('stop', { offset: '0%',   'stop-color': '#c82020' }));
  hubGloss.appendChild(svgEl('stop', { offset: '35%',  'stop-color': '#a01818' }));
  hubGloss.appendChild(svgEl('stop', { offset: '55%',  'stop-color': '#801212' }));
  hubGloss.appendChild(svgEl('stop', { offset: '80%',  'stop-color': '#a01818' }));
  hubGloss.appendChild(svgEl('stop', { offset: '100%', 'stop-color': '#c82020' }));
  defs.appendChild(hubGloss);
  // Acrylic needle gradient — glossy highlight along the length
  const needleGrad = svgEl('linearGradient', { id: 'needleAcrylic', x1: '0%', y1: '0%', x2: '100%', y2: '0%' });
  needleGrad.appendChild(svgEl('stop', { offset: '0%',   'stop-color': 'rgba(255,255,255,0.6)' }));
  needleGrad.appendChild(svgEl('stop', { offset: '30%',  'stop-color': 'rgba(255,255,255,0.85)' }));
  needleGrad.appendChild(svgEl('stop', { offset: '50%',  'stop-color': 'rgba(255,255,255,0.9)' }));
  needleGrad.appendChild(svgEl('stop', { offset: '70%',  'stop-color': 'rgba(255,255,255,0.75)' }));
  needleGrad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': 'rgba(255,255,255,0.5)' }));
  defs.appendChild(needleGrad);
  // Specular highlight overlay for acrylic effect
  const needleSpec = svgEl('linearGradient', { id: 'needleSpecular', x1: '0%', y1: '0%', x2: '100%', y2: '0%' });
  needleSpec.appendChild(svgEl('stop', { offset: '0%',   'stop-color': 'rgba(255,255,255,0)' }));
  needleSpec.appendChild(svgEl('stop', { offset: '35%',  'stop-color': 'rgba(255,255,255,0.35)' }));
  needleSpec.appendChild(svgEl('stop', { offset: '45%',  'stop-color': 'rgba(255,255,255,0.5)' }));
  needleSpec.appendChild(svgEl('stop', { offset: '55%',  'stop-color': 'rgba(255,255,255,0.1)' }));
  needleSpec.appendChild(svgEl('stop', { offset: '100%', 'stop-color': 'rgba(255,255,255,0)' }));
  defs.appendChild(needleSpec);
  svg.appendChild(defs);

  svg.appendChild(svgEl('circle', { cx: 100, cy: 100, r: 96, fill: faceFill }));

  svg.appendChild(svgEl('circle', {
    cx: 100, cy: 100, r: 98,
    fill: 'none', stroke: 'url(#silverBezel)', 'stroke-width': 4
  }));

  const TICK_INNER = 78;
  const MAJOR_TICK_WIDTH = 3.5;
  const ticksG = svgEl('g', { 'stroke-linecap': 'butt', filter: 'url(#tickGlow)' });
  const labelsG = svgEl('g', {
    filter: 'url(#tickGlow)',
    'font-family': 'Roboto, -apple-system, system-ui, sans-serif',
    'font-size': 18, 'font-weight': 700, 'text-anchor': 'middle',
    'font-style': 'italic'
  });
  const oemMajorTicks = buildTicks(ticksG, labelsG, {
    innerR: TICK_INNER, majorOuterR: 92, minorOuterR: 88,
    majorWidth: MAJOR_TICK_WIDTH, minorWidth: 1.8,
    normalColor: tickColor, redColor: redColor,
    labelR: 62, labelYOffset: 6, redInset: true
  });
  svg.appendChild(ticksG);
  svg.appendChild(labelsG);

  // Red arc spans from first red major tick to last red major tick
  const oemMajorStep = niceStep(gaugeMax - gaugeMin, 6);
  let firstRedMajor = null, lastRedMajor = null;
  for (let v = gaugeMin; v <= gaugeMax + oemMajorStep * 0.01; v += oemMajorStep) {
    const s = Math.round(v * 1000) / 1000;
    if (s > gaugeMax) break;
    if (s >= gaugeRedValue) {
      if (firstRedMajor === null) firstRedMajor = s;
      lastRedMajor = s;
    }
  }
  if (firstRedMajor !== null && lastRedMajor !== null) {
    svg.appendChild(svgEl('path', {
      d: arcPath(valueToAngle(firstRedMajor), valueToAngle(lastRedMajor), TICK_INNER + MAJOR_TICK_WIDTH / 2),
      fill: 'none', stroke: redColor, 'stroke-width': MAJOR_TICK_WIDTH, 'stroke-linecap': 'square',
      filter: 'url(#redGlow)'
    }));
  }

  if (BOOST_CHANNELS.has(gaugeChannel)) {
    const icon = buildTurboIcon(50, 158, 28);
    if (isDark) icon.setAttribute('opacity', 0.7);
    svg.appendChild(icon);
  }

  gaugeLabelEl = null;

  svg.appendChild(svgEl('rect', {
    x: 70, y: 130, width: 60, height: 36, rx: 2, ry: 2,
    fill: readoutFill, stroke: readoutStroke, 'stroke-width': 1
  }));
  // Sign element — fixed position to the left
  gaugeValFracEl = svgText({
    x: 74, y: 149, fill: valFill,
    'text-anchor': 'start',
    'font-family': "'DS-Digital', monospace",
    'font-size': 24, 'font-weight': 700
  }, '');
  svg.appendChild(gaugeValFracEl);
  // Number element — always centered
  gaugeValEl = svgText({
    x: 100, y: 151, fill: valFill,
    'text-anchor': 'middle',
    'font-family': "'DS-Digital', monospace",
    'font-size': 24, 'font-weight': 700
  }, '--');
  svg.appendChild(gaugeValEl);

  gaugeUnitEl = svgText({
    x: 100, y: 162, 'text-anchor': 'middle', fill: unitFill,
    'font-family': '-apple-system, system-ui, sans-serif',
    'font-size': 9, 'font-weight': 700, 'letter-spacing': 1
  }, '');
  svg.appendChild(gaugeUnitEl);

  svg.appendChild(svgEl('circle', {
    cx: 100, cy: 100, r: 19.5,
    fill: hubFill, stroke: 'url(#hubRedGloss)', 'stroke-width': 2.5
  }));

  const needleG = svgEl('g');
  needleG.style.transformOrigin = '100px 100px';
  needleG.style.transition = 'transform 150ms ease-out';
  needleG.style.transform = `rotate(${ANGLE_START}deg)`;
  // Clip for bottom 1/3 of needle (base region only)
  const clipBase = svgEl('clipPath', { id: 'needleBaseClip' });
  clipBase.appendChild(svgEl('rect', { x: 80, y: 66, width: 40, height: 40 }));
  const defs2 = svgEl('defs');
  defs2.appendChild(clipBase);
  needleG.appendChild(defs2);
  // Dark border — clipped to bottom 1/3, no glow filter
  const needlePath = `M100,12
        L102,12.5
        L103.5,87 Q103.5,89 102.5,89
        L97.5,89 Q96.5,89 96.5,87
        L98,12.5 Z`;
  needleG.appendChild(svgEl('path', {
    d: needlePath,
    fill: 'none', stroke: needleBase, 'stroke-width': 4,
    'clip-path': 'url(#needleBaseClip)'
  }));
  // Backlit glow behind needle (dark mode only) — separate blurred white shape
  if (isDark) {
    needleG.appendChild(svgEl('path', {
      d: needlePath,
      fill: '#fff', opacity: 0.8,
      filter: 'url(#needleGlow)'
    }));
  }
  // Acrylic needle + specular with drop shadow
  const needleInner = svgEl('g', { filter: 'url(#needleShadow)' });
  needleInner.appendChild(svgEl('path', {
    d: needlePath,
    fill: 'url(#needleAcrylic)'
  }));
  needleInner.appendChild(svgEl('path', {
    d: needlePath,
    fill: 'url(#needleSpecular)',
    opacity: isDark ? 0.6 : 0.3
  }));
  needleG.appendChild(needleInner);

  svg.appendChild(needleG);

  let peakVal = gaugeMin;
  let peakTimer = null;
  let peakHolding = false;
  let peakTick = null; // currently highlighted tick
  const PEAK_HOLD_MS = 3000;

  function findNearestMajorTick(val) {
    let best = null, bestDist = Infinity;
    for (const t of oemMajorTicks) {
      const d = Math.abs(t.value - val);
      if (d < bestDist) { bestDist = d; best = t; }
    }
    return best;
  }

  function clearPeakTick() {
    if (peakTick) {
      peakTick.el.setAttribute('stroke', peakTick.origColor);
      peakTick = null;
    }
  }

  setGaugeProgress = (val) => {
    const angle = valueToAngle(val);
    needleG.style.transform = `rotate(${angle.toFixed(2)}deg)`;

    if (val > peakVal) {
      peakVal = val;
      clearTimeout(peakTimer);
      peakHolding = false;
      // Update which tick is highlighted
      const tick = findNearestMajorTick(peakVal);
      if (tick !== peakTick) {
        clearPeakTick();
        if (tick) {
          tick.el.setAttribute('stroke', tick.origColor === redColor ? tickColor : redColor);
          peakTick = tick;
        }
      }
    } else if (!peakHolding) {
      peakHolding = true;
      peakTimer = setTimeout(() => {
        clearPeakTick();
        peakVal = val; // reset to current value, not gaugeMin
        peakHolding = false;
      }, PEAK_HOLD_MS);
    }
  };
  setGaugeProgress(Math.max(0, gaugeMin));
}

// ---- Theme: Hudiy (Material You — circular arc bar with rounded ends) ----
function buildHudiyTheme() {
  const colPrimary          = cssVar('--primary') || '#aac7ff';
  const colOnSurface        = cssVar('--on-surface') || '#e2e2e9';
  const colOnSurfaceVar     = cssVar('--on-surface-variant') || '#c4c6d0';
  const colOutlineVariant   = cssVar('--outline-variant') || '#44474e';
  const colError            = cssVar('--error') || '#ffb4ab';

  const ARC_R = 82;
  const ARC_W = 18;
  // Shift everything down to visually center the open arc
  const hudiyG = svgEl('g', { transform: 'translate(0, 12)' });

  // Track arc (background)
  hudiyG.appendChild(svgEl('path', {
    d: arcPath(ANGLE_START, ANGLE_END, ARC_R),
    fill: 'none', stroke: colOutlineVariant, 'stroke-width': ARC_W,
    'stroke-linecap': 'round'
  }));

  // Red zone arc
  const redAngleStart = valueToAngle(gaugeRedValue);
  hudiyG.appendChild(svgEl('path', {
    d: arcPath(redAngleStart, ANGLE_END, ARC_R),
    fill: 'none', stroke: colError, 'stroke-width': ARC_W,
    'stroke-linecap': 'round', opacity: 0.3
  }));

  // Value arc (filled portion)
  const valueArc = svgEl('path', {
    d: arcPath(ANGLE_START, ANGLE_START, ARC_R),
    fill: 'none', stroke: colPrimary, 'stroke-width': ARC_W,
    'stroke-linecap': 'round'
  });
  hudiyG.appendChild(valueArc);

  // Min / Max labels
  hudiyG.appendChild(svgText({
    x: arcPoint(ANGLE_START, ARC_R - ARC_W).x,
    y: arcPoint(ANGLE_START, ARC_R - ARC_W).y + 14,
    fill: colOnSurfaceVar, 'text-anchor': 'middle',
    'font-family': 'Roboto, sans-serif', 'font-size': 10, 'font-weight': 500
  }, formatTickLabel(gaugeMin)));
  hudiyG.appendChild(svgText({
    x: arcPoint(ANGLE_END, ARC_R - ARC_W).x,
    y: arcPoint(ANGLE_END, ARC_R - ARC_W).y + 14,
    fill: colOnSurfaceVar, 'text-anchor': 'middle',
    'font-family': 'Roboto, sans-serif', 'font-size': 10, 'font-weight': 500
  }, formatTickLabel(gaugeMax)));

  // Label text
  gaugeLabelEl = svgText({
    x: 100, y: 160, 'text-anchor': 'middle', fill: colOnSurfaceVar,
    'font-family': 'Roboto, sans-serif',
    'font-size': 11, 'font-weight': 500, 'letter-spacing': 1
  }, '');
  hudiyG.appendChild(gaugeLabelEl);

  // Sign element — positioned dynamically to left of number
  gaugeValFracEl = svgText({
    x: 74, y: 105, fill: colOnSurface,
    'text-anchor': 'end',
    'font-family': 'Roboto, sans-serif',
    'font-size': 36, 'font-weight': 700
  }, '');
  hudiyG.appendChild(gaugeValFracEl);
  // Large centered value
  gaugeValEl = svgText({
    x: 100, y: 105, fill: colOnSurface,
    'text-anchor': 'middle',
    'font-family': 'Roboto, sans-serif',
    'font-size': 36, 'font-weight': 700
  }, '--');
  hudiyG.appendChild(gaugeValEl);

  // Unit label
  gaugeUnitEl = svgText({
    x: 100, y: 122, 'text-anchor': 'middle', fill: colOnSurfaceVar,
    'font-family': 'Roboto, sans-serif',
    'font-size': 12, 'font-weight': 500, 'letter-spacing': 1
  }, '');
  hudiyG.appendChild(gaugeUnitEl);

  // Peak hold dot on the arc
  const peakDot = svgEl('circle', {
    r: ARC_W / 2, fill: colError, opacity: 0
  });
  hudiyG.appendChild(peakDot);

  svg.appendChild(hudiyG);

  let peakVal = gaugeMin;
  let peakTimer = null;
  let peakHolding = false;
  const PEAK_HOLD_MS = 3000;

  function updatePeakDot(val) {
    const a = valueToAngle(val);
    const p = arcPoint(a, ARC_R);
    peakDot.setAttribute('cx', p.x.toFixed(2));
    peakDot.setAttribute('cy', p.y.toFixed(2));
    peakDot.setAttribute('opacity', 1);
    peakDot.setAttribute('fill', val >= gaugeRedValue ? colOnSurface : colError);
  }

  setGaugeProgress = (val) => {
    const clamped = Math.max(gaugeMin, Math.min(gaugeMax, val));
    const angle = valueToAngle(clamped);
    const endAngle = Math.max(ANGLE_START + 1, angle);
    valueArc.setAttribute('d', arcPath(ANGLE_START, endAngle, ARC_R));
    valueArc.setAttribute('stroke', clamped >= gaugeRedValue ? colError : colPrimary);

    if (clamped > peakVal) {
      peakVal = clamped;
      updatePeakDot(peakVal);
      clearTimeout(peakTimer);
      peakHolding = false;
    } else if (!peakHolding && peakDot.getAttribute('opacity') !== '0') {
      peakHolding = true;
      peakTimer = setTimeout(() => {
        peakVal = clamped;
        peakDot.setAttribute('opacity', 0);
        peakHolding = false;
      }, PEAK_HOLD_MS);
    }
  };
  setGaugeProgress(Math.max(0, gaugeMin));
}

// ---- Theme dispatch ----
function buildTheme(name) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  gaugeValEl = gaugeValFracEl = gaugeUnitEl = gaugeLabelEl = null;
  computeGaugeRange();
  if (name === 'haltech') buildHaltechTheme();
  else if (name === 'hudiy') buildHudiyTheme();
  else buildOemTheme();
  applyGaugeLabels();
  const barsEl = document.getElementById('bars');
  barsEl.setAttribute('data-bar-theme', name);
}

// ---- Reload button ----
document.getElementById('reload').addEventListener('click', (e) => {
  e.stopPropagation();
  location.reload();
});

// ====================================================================
// CHANNEL REGISTRY — every wirable diagnostic channel
// Each entry: { module, group, index, label, unit, min, max, decimals }
// ====================================================================
const CHANNELS = {
  // ── Module 0x00: CAN-sourced synthetic groups ──
  // Group 0 — Temperatures
  oil_temp:       { module: 0x00, group: 0, index: 0, label: 'OIL',          unit: '°',  min: 0,   max: 150,  isTemp: true },
  coolant_temp:   { module: 0x00, group: 0, index: 2, label: 'COOLANT',      unit: '°',  min: 0,   max: 130,  isTemp: true },
  iat:            { module: 0x00, group: 0, index: 3, label: 'IAT',          unit: '°',  min: 0,   max: 120,  isTemp: true },

  // Group 1 — RPM / Boost / Load
  rpm:            { module: 0x00, group: 1, index: 0, label: 'RPM',          unit: '',   min: 0,   max: 7000 },
  boost_abs:      { module: 0x00, group: 1, index: 1, label: 'BOOST',        unit: 'mbar', min: 0, max: 3000 },
  engine_load:    { module: 0x00, group: 1, index: 2, label: 'LOAD',         unit: '%',  min: 0,   max: 100 },

  // Group 2 — Battery / Fuel / Speed
  battery:        { module: 0x00, group: 2, index: 0, label: 'BATTERY',      unit: 'V',  min: 11,  max: 15,   decimals: 1 },
  fuel_level:     { module: 0x00, group: 2, index: 1, label: 'FUEL',         unit: '%',  min: 0,   max: 100 },
  speed:          { module: 0x00, group: 2, index: 2, label: 'SPEED',        unit: '',   min: 0,   max: 160 },

  // ── Module 0x01 (ECU) — TP2/KWP2000 groups ──
  // Group 3 — Engine
  ecu_rpm:        { module: 0x01, group: 3, index: 0, label: 'ECU RPM',      unit: '',   min: 0,   max: 7000 },
  maf:            { module: 0x01, group: 3, index: 1, label: 'MAF',          unit: 'g/s', min: 0,  max: 250,  decimals: 1 },
  timing:         { module: 0x01, group: 3, index: 2, label: 'TIMING',       unit: '°',  min: -10, max: 30,   decimals: 1 },

  // Group 20 — Knock sensors
  knock_cyl1:     { module: 0x01, group: 20, index: 0, label: 'KNOCK 1',     unit: '°',  min: -10, max: 5,    decimals: 1 },
  knock_cyl2:     { module: 0x01, group: 20, index: 1, label: 'KNOCK 2',     unit: '°',  min: -10, max: 5,    decimals: 1 },
  knock_cyl3:     { module: 0x01, group: 20, index: 2, label: 'KNOCK 3',     unit: '°',  min: -10, max: 5,    decimals: 1 },
  knock_cyl4:     { module: 0x01, group: 20, index: 3, label: 'KNOCK 4',     unit: '°',  min: -10, max: 5,    decimals: 1 },

  // Group 102 — Coolant / IAT / Injection (from ECU)
  ecu_coolant:    { module: 0x01, group: 102, index: 0, label: 'ECU CLT',    unit: '°',  min: 0,   max: 130,  isTemp: true },
  ecu_iat:        { module: 0x01, group: 102, index: 1, label: 'ECU IAT',    unit: '°',  min: 0,   max: 120,  isTemp: true },
  injection:      { module: 0x01, group: 102, index: 2, label: 'INJ TIME',   unit: 'ms', min: 0,   max: 20,   decimals: 2 },

  // Group 106 — Fuel Pressure
  fuel_pres_spec: { module: 0x01, group: 106, index: 0, label: 'FP SPEC',    unit: 'bar', min: 0,  max: 150,  decimals: 1 },
  fuel_pres_act:  { module: 0x01, group: 106, index: 1, label: 'FP ACT',     unit: 'bar', min: 0,  max: 150,  decimals: 1 },
  fuel_pres_valve:{ module: 0x01, group: 106, index: 2, label: 'FP VALVE',   unit: '%',  min: 0,   max: 100,  decimals: 1 },

  // Group 115 — Boost (from ECU)
  boost_spec:     { module: 0x01, group: 115, index: 0, label: 'BST SPEC',   unit: 'mbar', min: 0, max: 3000 },
  boost_actual:   { module: 0x01, group: 115, index: 1, label: 'BST ACT',    unit: 'mbar', min: 0, max: 3000 },

  // ── Module 0x02 (Transmission) ──
  // Group 11 — Clutch pack 1
  clutch1_0:      { module: 0x02, group: 11, index: 0, label: 'CLUTCH1-A',   unit: '',   min: 0,   max: 100 },
  clutch1_1:      { module: 0x02, group: 11, index: 1, label: 'CLUTCH1-B',   unit: '',   min: 0,   max: 100 },
  clutch1_2:      { module: 0x02, group: 11, index: 2, label: 'CLUTCH1-C',   unit: '',   min: 0,   max: 100 },
  clutch1_3:      { module: 0x02, group: 11, index: 3, label: 'CLUTCH1-D',   unit: '',   min: 0,   max: 100 },

  // Group 12 — Clutch pack 2
  clutch2_0:      { module: 0x02, group: 12, index: 0, label: 'CLUTCH2-A',   unit: '',   min: 0,   max: 100 },
  clutch2_1:      { module: 0x02, group: 12, index: 1, label: 'CLUTCH2-B',   unit: '',   min: 0,   max: 100 },
  clutch2_2:      { module: 0x02, group: 12, index: 2, label: 'CLUTCH2-C',   unit: '',   min: 0,   max: 100 },
  clutch2_3:      { module: 0x02, group: 12, index: 3, label: 'CLUTCH2-D',   unit: '',   min: 0,   max: 100 },

  // Group 16 — Gear selector
  gear_selector:  { module: 0x02, group: 16, index: 0, label: 'GEAR',        unit: '',   min: 0,   max: 6 },

  // Group 19 — Transmission temps
  trans_temp1:    { module: 0x02, group: 19, index: 0, label: 'TRANS T1',    unit: '°',  min: 0,   max: 150,  isTemp: true },
  trans_temp2:    { module: 0x02, group: 19, index: 1, label: 'TRANS T2',    unit: '°',  min: 0,   max: 150,  isTemp: true },
  trans_temp3:    { module: 0x02, group: 19, index: 2, label: 'TRANS T3',    unit: '°',  min: 0,   max: 150,  isTemp: true },

  // ── Module 0x0A (Haldex / AWD) ──
  // Group 1 — AWD temps/voltage
  awd_temp:       { module: 0x0A, group: 1, index: 0, label: 'AWD TEMP',     unit: '°',  min: 0,   max: 150,  isTemp: true },
  awd_voltage:    { module: 0x0A, group: 1, index: 1, label: 'AWD VOLT',     unit: 'V',  min: 0,   max: 15,   decimals: 1 },

  // Group 3 — AWD pressure/torque/valve
  awd_pressure:   { module: 0x0A, group: 3, index: 0, label: 'AWD PRES',     unit: 'bar', min: 0,  max: 50,   decimals: 1 },
  awd_torque:     { module: 0x0A, group: 3, index: 1, label: 'AWD TRQ',      unit: 'Nm', min: 0,   max: 500 },
  awd_valve:      { module: 0x0A, group: 3, index: 2, label: 'AWD VALVE',    unit: '%',  min: 0,   max: 100 },

  // Group 5 — AWD modes
  awd_mode0:      { module: 0x0A, group: 5, index: 0, label: 'AWD M0',       unit: '',   min: 0,   max: 100 },
  awd_mode1:      { module: 0x0A, group: 5, index: 1, label: 'AWD M1',       unit: '',   min: 0,   max: 100 },
  awd_mode2:      { module: 0x0A, group: 5, index: 2, label: 'AWD M2',       unit: '',   min: 0,   max: 100 },
  awd_mode3:      { module: 0x0A, group: 5, index: 3, label: 'AWD M3',       unit: '',   min: 0,   max: 100 },
};

// ====================================================================
// BAR CONFIGURATION — which channels fill the 4 bar slots (order = position)
// Persisted to localStorage so user picks survive reloads.
// ====================================================================
const BAR_SLOTS = 4;
const DEFAULT_BAR_CONFIG = ['iat', 'coolant_temp', 'oil_temp', 'battery'];

function loadBarConfig() {
  try {
    const s = localStorage.getItem('boost_bar_config');
    if (s) {
      const arr = JSON.parse(s);
      if (Array.isArray(arr) && arr.length && arr.every(k => CHANNELS[k])) return arr.slice(0, BAR_SLOTS);
    }
  } catch (_) {}
  return DEFAULT_BAR_CONFIG.slice();
}
let barConfig = loadBarConfig();

function saveBarConfig() {
  localStorage.setItem('boost_bar_config', JSON.stringify(barConfig));
}

// ====================================================================
// GAUGE CHANNEL CONFIG — which channel feeds the round gauge
// Persisted to localStorage.
// ====================================================================
let gaugeChannel = localStorage.getItem('gauge_channel') || 'boost_abs';
if (!CHANNELS[gaugeChannel]) gaugeChannel = 'boost_abs';

function saveGaugeChannel() {
  localStorage.setItem('gauge_channel', gaugeChannel);
}

// ---- Bar gauge DOM refs ----
const BAR_PEAK_HOLD_MS = 3000;
const barEls = ['#bar-iat','#bar-clt','#bar-oil','#bar-4'].map(id => ({
  val: document.querySelector(id + ' .value'),
  fill: document.querySelector(id + ' .fill'),
  label: document.querySelector(id + ' .label'),
  peak: document.querySelector(id + ' .peak'),
  peakVal: -Infinity,
  peakTimer: null,
  peakHolding: false,
}));

let boostUnit = 'imperial';
let boostMode = 'relative';

// Apply labels + reset values from channel config
function applyBarLabels() {
  barEls.forEach((el, i) => {
    const ch = CHANNELS[barConfig[i]];
    if (ch && el) {
      let unit = ch.unit || '';
      if (ch.isTemp) unit = (boostUnit === 'imperial') ? '°F' : '°C';
      el.label.textContent = ch.label;
      el.val.textContent = unit ? `--${unit}` : '--';
      el.fill.style.width = '0%';
    } else if (el) {
      el.label.textContent = '--';
      el.val.textContent = '--';
      el.fill.style.width = '0%';
    }
  });
}
applyBarLabels();

// Apply label + unit to the round gauge based on selected channel
function applyGaugeLabels() {
  const ch = CHANNELS[gaugeChannel];
  if (!ch) return;
  if (BOOST_CHANNELS.has(gaugeChannel)) {
    if (gaugeLabelEl) gaugeLabelEl.textContent = ch.label;
    if (gaugeUnitEl) gaugeUnitEl.textContent = (boostUnit === 'imperial') ? 'PSI' : 'MBAR';
  } else {
    if (gaugeLabelEl) gaugeLabelEl.textContent = ch.label;
    if (gaugeUnitEl) gaugeUnitEl.textContent = ch.isTemp ? (boostUnit === 'imperial' ? '°F' : '°C') : ch.unit;
  }
}

// Latest values keyed by "module:group:index"
const channelValues = {};

function channelKey(module, group, index) {
  return `${module}:${group}:${index}`;
}

function formatChannelValue(ch, raw) {
  const dec = ch.decimals || 0;
  let display = raw;
  let suffix = ch.unit;
  if (ch.isTemp) {
    display = (boostUnit === 'imperial') ? raw * 9 / 5 + 32 : raw;
    suffix = (boostUnit === 'imperial') ? '°F' : '°C';
  }
  return { text: display.toFixed(dec), suffix };
}

function updateBarPeak(el, pct) {
  if (!el.peak) {
    // Create peak element dynamically if not found in DOM
    const track = el.fill ? el.fill.parentElement : null;
    if (!track) return;
    const p = document.createElement('div');
    p.style.cssText = 'position:absolute;top:0;bottom:0;width:3px;background:#e01e1e;z-index:2;display:none;';
    track.appendChild(p);
    el.peak = p;
  }
  if (pct > el.peakVal) {
    el.peakVal = pct;
    el.peak.style.left = pct + '%';
    el.peak.style.display = 'block';
    clearTimeout(el.peakTimer);
    el.peakHolding = false;
  } else if (!el.peakHolding && el.peak.style.display !== 'none') {
    el.peakHolding = true;
    el.peakTimer = setTimeout(() => {
      el.peakVal = -Infinity;
      el.peak.style.display = 'none';
      el.peakHolding = false;
    }, BAR_PEAK_HOLD_MS);
  }
}

function updateBarFromChannel(barIdx) {
  const chKey = barConfig[barIdx];
  const ch = CHANNELS[chKey];
  const el = barEls[barIdx];
  if (!ch || !el) return;
  const raw = channelValues[channelKey(ch.module, ch.group, ch.index)];
  if (raw === undefined) return;
  const { text, suffix } = formatChannelValue(ch, raw);
  el.val.textContent = `${text}${suffix}`;
  const pct = Math.max(0, Math.min(100, ((raw - ch.min) / (ch.max - ch.min)) * 100));
  el.fill.style.width = pct + '%';
  updateBarPeak(el, pct);
}

// ---- Data via hudiy_dataview Socket.IO ----
const MBAR_TO_PSI = 0.0145038;
let atmosphere = 1013.25;

// Initial build (computeGaugeRange is called inside buildTheme)
buildTheme(boostTheme);

fetch('config.json').then(r => r.json()).then(cfg => {
  const u = (cfg.display && cfg.display.units) || {};
  if (u.boost)      boostUnit = u.boost;
  if (u.boost_mode) boostMode = u.boost_mode;
  applyGaugeLabels();
  console.log('[boost] config loaded:', boostUnit, boostMode);
}).catch(err => console.warn('[boost] config.json load failed, using defaults', err));

// Update the round gauge with a new value (handles boost channels specially)
function updateGauge(raw) {
  if (BOOST_CHANNELS.has(gaugeChannel)) {
    // Boost channel: convert mbar to PSI and handle relative/absolute
    const relMbar = raw - atmosphere;
    const psiRel  = relMbar * MBAR_TO_PSI;
    setGaugeProgress(psiRel);
    const displayMbar = boostMode === 'relative' ? relMbar : raw;
    if (boostUnit === 'imperial') {
      const psi = displayMbar * MBAR_TO_PSI;
      setGaugeValue(Math.round(psi).toString());
    } else {
      setGaugeValue(Math.round(displayMbar).toString());
    }
  } else {
    // Generic channel: display raw value with formatting
    const ch = CHANNELS[gaugeChannel];
    if (!ch) return;
    const dec = 0;
    let display = raw;
    if (ch.isTemp && boostUnit === 'imperial') {
      display = raw * 9 / 5 + 32;
    }
    setGaugeValue(display.toFixed(dec));
    setGaugeProgress(raw);
  }
}

function handleDiagnostic(msg) {
  if (!msg || typeof msg !== 'object') return;
  const mod = Number(msg.module), grp = Number(msg.group), data = msg.data || [];

  // Atmosphere reference (always needed for boost channels)
  if (mod === 0x01 && grp === 113 && data.length >= 4) {
    const a = parseFloat(data[3].value);
    if (!isNaN(a)) atmosphere = a;
  }

  // Store every value from this group into channelValues
  data.forEach((item, idx) => {
    const val = parseFloat(item.value);
    if (!isNaN(val)) {
      channelValues[channelKey(mod, grp, idx)] = val;
    }
  });

  // Update round gauge if this group contains the gauge channel
  const gaugeCh = CHANNELS[gaugeChannel];
  if (gaugeCh && gaugeCh.module === mod && gaugeCh.group === grp) {
    const raw = channelValues[channelKey(mod, grp, gaugeCh.index)];
    if (raw !== undefined) updateGauge(raw);
  }

  // Update any bar gauges that are wired to channels in this group
  barConfig.forEach((chKey, barIdx) => {
    const ch = CHANNELS[chKey];
    if (ch && ch.module === mod && ch.group === grp) {
      updateBarFromChannel(barIdx);
    }
  });
}

// ---- Socket.IO subscriptions (auto-computed from barConfig + gaugeChannel + boost essentials) ----
function buildSubscriptions() {
  const subs = new Map();
  // Always subscribe to atmosphere for boost channels
  subs.set('1:113', { module: 0x01, group: 113, priority: 'low' });
  // Gauge channel subscription
  const gaugeCh = CHANNELS[gaugeChannel];
  if (gaugeCh) {
    const key = `${gaugeCh.module}:${gaugeCh.group}`;
    subs.set(key, { module: gaugeCh.module, group: gaugeCh.group, priority: 'normal' });
  }
  // Bar channel subscriptions
  barConfig.forEach(chKey => {
    const ch = CHANNELS[chKey];
    if (!ch) return;
    const key = `${ch.module}:${ch.group}`;
    if (!subs.has(key)) {
      subs.set(key, { module: ch.module, group: ch.group, priority: 'normal' });
    }
  });
  return Array.from(subs.values());
}

let activeSubs = buildSubscriptions();
let sock = null;

function subscribeAll() {
  if (!sock || !sock.connected) return;
  activeSubs.forEach(s => {
    sock.emit('toggle_group', { module: s.module, group: s.group, action: 'add', priority: s.priority });
  });
  console.log('[boost] subscribed to', activeSubs.length, 'groups');
}

function unsubscribeAll() {
  if (!sock || !sock.connected) return;
  activeSubs.forEach(s => {
    sock.emit('toggle_group', { module: s.module, group: s.group, action: 'remove' });
  });
}

// Called when barConfig or gaugeChannel changes — unsub old, resub new
function resubscribe() {
  unsubscribeAll();
  activeSubs = buildSubscriptions();
  subscribeAll();
}

if (typeof io === 'undefined') {
  setGaugeValue('no io');
  console.error('[boost] socket.io.js did not load');
} else {
  try {
    sock = io('http://localhost:5003', { transports: ['websocket', 'polling'] });
    sock.on('connect', () => {
      setGaugeValue('--');
      subscribeAll();
    });
    sock.on('connect_error', (err) => {
      setGaugeValue('err');
      console.error('[boost] connect_error', err);
    });
    sock.on('disconnect', () => { console.warn('[boost] disconnected'); });
    sock.on('diagnostic_update', handleDiagnostic);
    sock.on('diagnostic_batch', (batch) => {
      if (Array.isArray(batch)) batch.forEach(handleDiagnostic);
    });
    window.addEventListener('beforeunload', () => unsubscribeAll());
  } catch (e) {
    setGaugeValue('err');
    console.error('[boost] setup error', e);
  }
}

// ====================================================================
// CHANNEL GROUPS — shared by both pickers for display ordering
// ====================================================================
const CHANNEL_GROUPS = [
  { title: 'CAN — Temps',         keys: ['oil_temp', 'coolant_temp', 'iat'] },
  { title: 'CAN — Engine',        keys: ['rpm', 'boost_abs', 'engine_load'] },
  { title: 'CAN — Vehicle',       keys: ['battery', 'fuel_level', 'speed'] },
  { title: 'ECU — Engine',        keys: ['ecu_rpm', 'maf', 'timing'] },
  { title: 'ECU — Knock',         keys: ['knock_cyl1', 'knock_cyl2', 'knock_cyl3', 'knock_cyl4'] },
  { title: 'ECU — Temps / Inj',   keys: ['ecu_coolant', 'ecu_iat', 'injection'] },
  { title: 'ECU — Fuel Pressure', keys: ['fuel_pres_spec', 'fuel_pres_act', 'fuel_pres_valve'] },
  { title: 'ECU — Boost',         keys: ['boost_spec', 'boost_actual'] },
  { title: 'Trans — Clutch 1',    keys: ['clutch1_0', 'clutch1_1', 'clutch1_2', 'clutch1_3'] },
  { title: 'Trans — Clutch 2',    keys: ['clutch2_0', 'clutch2_1', 'clutch2_2', 'clutch2_3'] },
  { title: 'Trans — General',     keys: ['gear_selector', 'trans_temp1', 'trans_temp2', 'trans_temp3'] },
  { title: 'AWD / Haldex',        keys: ['awd_temp', 'awd_voltage', 'awd_pressure', 'awd_torque', 'awd_valve', 'awd_mode0', 'awd_mode1', 'awd_mode2', 'awd_mode3'] },
];

// ====================================================================
// BAR PICKER — tap bar gauges to open, select up to 4 channels + theme
// ====================================================================
const pickerOverlay = document.getElementById('picker-overlay');
const pickerList   = document.getElementById('picker-list');
const pickerDone   = document.getElementById('picker-done');

let pickerSelection = []; // ordered array of selected channel keys
let pendingBarTheme = boostTheme;

function buildPickerList(preserveSelection) {
  pickerList.innerHTML = '';
  if (!preserveSelection) {
    pickerSelection = barConfig.slice();
    pendingBarTheme = boostTheme;
  }

  const COLUMNS = [
    { heading: 'CAN',        indices: [0, 1, 2] },
    { heading: 'ECU',        indices: [3, 4, 5, 6, 7] },
    { heading: 'Trans / AWD', indices: [8, 9, 10, 11] },
  ];
  COLUMNS.forEach(col => {
    const colDiv = document.createElement('div');
    colDiv.className = 'picker-col';

    const colHead = document.createElement('div');
    colHead.className = 'picker-col-heading';
    colHead.textContent = col.heading;
    colDiv.appendChild(colHead);

    col.indices.forEach(gi => {
      const grp = CHANNEL_GROUPS[gi];
      if (!grp) return;
      const lbl = document.createElement('div');
      lbl.className = 'picker-group-label';
      lbl.textContent = grp.title.replace(/^(CAN|ECU|Trans)\s*[—–-]\s*/, '');
      colDiv.appendChild(lbl);

      grp.keys.forEach(chKey => {
        const ch = CHANNELS[chKey];
        if (!ch) return;
        const item = document.createElement('div');
        item.className = 'picker-item';
        item.dataset.key = chKey;

        const check = document.createElement('div');
        check.className = 'pi-check';

        const label = document.createElement('span');
        label.className = 'pi-label';
        label.textContent = ch.label;

        item.appendChild(check);
        item.appendChild(label);

        item.addEventListener('click', () => toggleChannel(chKey));
        colDiv.appendChild(item);
      });
    });
    pickerList.appendChild(colDiv);
  });
  refreshPickerState();
  refreshBarThemeState();
}

function refreshPickerState() {
  pickerList.querySelectorAll('.picker-item').forEach(item => {
    const key = item.dataset.key;
    const idx = pickerSelection.indexOf(key);
    const check = item.querySelector('.pi-check');
    if (idx >= 0) {
      item.classList.add('selected');
      check.textContent = String(idx + 1);
    } else {
      item.classList.remove('selected');
      check.textContent = '';
    }
  });
}

function refreshBarThemeState() {
  document.querySelectorAll('#bar-theme-chips .theme-chip').forEach(chip => {
    if (chip.dataset.theme === pendingBarTheme) {
      chip.classList.add('selected');
    } else {
      chip.classList.remove('selected');
    }
  });
}

function toggleChannel(chKey) {
  const idx = pickerSelection.indexOf(chKey);
  if (idx >= 0) {
    pickerSelection.splice(idx, 1);
  } else if (pickerSelection.length < BAR_SLOTS) {
    pickerSelection.push(chKey);
  }
  refreshPickerState();
}

function moveChannel(chKey, dir) {
  const idx = pickerSelection.indexOf(chKey);
  if (idx < 0) return;
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= pickerSelection.length) return;
  pickerSelection.splice(idx, 1);
  pickerSelection.splice(newIdx, 0, chKey);
  refreshPickerState();
}

function openPicker() {
  buildPickerList();
  pickerOverlay.classList.add('open');
}

function closePicker() {
  pickerOverlay.classList.remove('open');
  // Apply new bar config
  barConfig = pickerSelection.slice();
  saveBarConfig();
  applyBarLabels();
  barConfig.forEach((_, i) => updateBarFromChannel(i));
  // Apply theme if changed
  if (pendingBarTheme !== boostTheme) {
    boostTheme = pendingBarTheme;
    localStorage.setItem('boost_theme', boostTheme);
    buildTheme(boostTheme);
  }
  resubscribe();
}

pickerDone.addEventListener('click', closePicker);

document.getElementById('picker-clear').addEventListener('click', () => {
  pickerSelection = [];
  refreshPickerState();
});

// Bar theme chip clicks
document.querySelectorAll('#bar-theme-chips .theme-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    pendingBarTheme = chip.dataset.theme;
    refreshBarThemeState();
  });
});

// ====================================================================
// GAUGE PICKER — tap round gauge to open, select 1 channel + theme
// ====================================================================
const gaugePickerOverlay = document.getElementById('gauge-picker-overlay');
const gaugePickerList   = document.getElementById('gauge-picker-list');
const gaugePickerDone   = document.getElementById('gauge-picker-done');

let pendingGaugeChannel = gaugeChannel;
let pendingGaugeTheme   = boostTheme;

function buildGaugePickerList() {
  gaugePickerList.innerHTML = '';
  pendingGaugeChannel = gaugeChannel;
  pendingGaugeTheme   = boostTheme;

  const COLUMNS = [
    { heading: 'CAN',        indices: [0, 1, 2] },
    { heading: 'ECU',        indices: [3, 4, 5, 6, 7] },
    { heading: 'Trans / AWD', indices: [8, 9, 10, 11] },
  ];
  COLUMNS.forEach(col => {
    const colDiv = document.createElement('div');
    colDiv.className = 'picker-col';

    const colHead = document.createElement('div');
    colHead.className = 'picker-col-heading';
    colHead.textContent = col.heading;
    colDiv.appendChild(colHead);

    col.indices.forEach(gi => {
      const grp = CHANNEL_GROUPS[gi];
      if (!grp) return;
      const lbl = document.createElement('div');
      lbl.className = 'picker-group-label';
      lbl.textContent = grp.title.replace(/^(CAN|ECU|Trans)\s*[—–-]\s*/, '');
      colDiv.appendChild(lbl);

      grp.keys.forEach(chKey => {
        const ch = CHANNELS[chKey];
        if (!ch) return;
        const item = document.createElement('div');
        item.className = 'picker-item';
        item.dataset.key = chKey;

        const check = document.createElement('div');
        check.className = 'pi-check';

        const label = document.createElement('span');
        label.className = 'pi-label';
        label.textContent = ch.label;

        item.appendChild(check);
        item.appendChild(label);

        item.addEventListener('click', () => {
          pendingGaugeChannel = chKey;
          refreshGaugePickerState();
        });
        colDiv.appendChild(item);
      });
    });
    gaugePickerList.appendChild(colDiv);
  });
  refreshGaugePickerState();
  refreshGaugeThemeState();
}

function refreshGaugePickerState() {
  gaugePickerList.querySelectorAll('.picker-item').forEach(item => {
    const check = item.querySelector('.pi-check');
    if (item.dataset.key === pendingGaugeChannel) {
      item.classList.add('selected');
      check.textContent = '✓';
    } else {
      item.classList.remove('selected');
      check.textContent = '';
    }
  });
}

function refreshGaugeThemeState() {
  document.querySelectorAll('#gauge-theme-chips .theme-chip').forEach(chip => {
    if (chip.dataset.theme === pendingGaugeTheme) {
      chip.classList.add('selected');
    } else {
      chip.classList.remove('selected');
    }
  });
}

function openGaugePicker() {
  buildGaugePickerList();
  gaugePickerOverlay.classList.add('open');
}

function closeGaugePicker() {
  gaugePickerOverlay.classList.remove('open');
  let needRebuild = false;
  // Apply channel change
  if (pendingGaugeChannel !== gaugeChannel) {
    gaugeChannel = pendingGaugeChannel;
    saveGaugeChannel();
    needRebuild = true;
  }
  // Apply theme change
  if (pendingGaugeTheme !== boostTheme) {
    boostTheme = pendingGaugeTheme;
    localStorage.setItem('boost_theme', boostTheme);
    needRebuild = true;
  }
  if (needRebuild) {
    buildTheme(boostTheme);
  }
  resubscribe();
}

gaugePickerDone.addEventListener('click', closeGaugePicker);

// Gauge theme chip clicks
document.querySelectorAll('#gauge-theme-chips .theme-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    pendingGaugeTheme = chip.dataset.theme;
    refreshGaugeThemeState();
  });
});

// ====================================================================
// TAP HANDLERS — bars open bar picker, round gauge opens gauge picker
// ====================================================================
document.getElementById('bars').addEventListener('click', openPicker);
document.getElementById('boost').addEventListener('click', openGaugePicker);



