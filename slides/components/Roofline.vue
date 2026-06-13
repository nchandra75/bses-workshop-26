<!--
  <Roofline :upto="N" /> - the recurring workshop roofline, drawn as plain SVG.

  Dot positions are the measured board numbers (x = arithmetic intensity, y =
  throughput); :upto controls how many rungs show, in ladder order, so the same
  picture grows across the deck:

      <Roofline :upto="0" />   ceilings only (the empty scoreboard)
      <Roofline :upto="1" />   + Python loops
      ...
      <Roofline :upto="6" />   + HLS streaming (the full picture)

  Two data sources, on purpose:
    - ../../python/reference_data/board_data_pynqz2_62mhz.json  (measured; the board)
    - ../roofline-layout.json                                   (hand-tweaked labels)
  Re-measure the board -> update the first. Nudge a label -> edit the second.
-->
<script setup>
import board from '../../python/reference_data/board_data_pynqz2_62mhz.json'
import layout from '../roofline-layout.json'
import { computed } from 'vue'

const props = defineProps({
  upto: { type: Number, default: 99 },
  height: { type: Number, default: 940 },
  legend: { type: Boolean, default: true },
})

const MACS = 9
const peak = board.peak_mpix
const bw = board.effective_dram_bw_bytes
const A = layout.axes

// --- geometry --------------------------------------------------------------
const W = 780
const H = props.height
const M = { l: 64, r: 26, t: 50, b: 54 }
const PW = W - M.l - M.r
const PH = H - M.t - M.b

const lg = Math.log10
const sx = (v) => M.l + ((lg(v) - lg(A.xmin)) / (lg(A.xmax) - lg(A.xmin))) * PW
const sy = (v) => M.t + (1 - (lg(v) - lg(A.ymin)) / (lg(A.ymax) - lg(A.ymin))) * PH

// --- ceilings & roofline ---------------------------------------------------
const ridge = (peak * 1e6 * MACS) / bw           // MAC/byte where slope meets roof
const memAt = (x) => (bw * x) / MACS / 1e6        // memory ceiling, Mpix/s
const roofPath = `M ${sx(A.xmin)} ${sy(memAt(A.xmin))} L ${sx(ridge)} ${sy(peak)} L ${sx(A.xmax)} ${sy(peak)}`

const computeLine = { x1: sx(A.xmin), x2: sx(A.xmax), y: sy(peak) }
const memLine = { x1: sx(A.xmin), y1: sy(memAt(A.xmin)), x2: sx(A.xmax), y2: sy(memAt(A.xmax)) }
const ridgeX = sx(ridge)
const memRect = { x: sx(A.xmin), w: sx(ridge) - sx(A.xmin), y: M.t, h: PH }
const compRect = { x: sx(ridge), w: sx(A.xmax) - sx(ridge), y: M.t, h: PH }
const regionY = M.t + 16
const memLabelX = sx(Math.sqrt(A.xmin * ridge))
const compLabelX = sx(Math.sqrt(ridge * A.xmax))

// --- axis ticks (log decades) ----------------------------------------------
function decades(min, max) {
  const out = []
  for (let e = Math.floor(lg(min)); e <= Math.ceil(lg(max)); e++) {
    const v = Math.pow(10, e)
    if (v >= min * 0.999 && v <= max * 1.001) out.push(v)
  }
  return out
}
const fmt = (v) => (v >= 1 ? String(v) : String(v))
const xticks = decades(A.xmin, A.xmax).map((v) => ({ v, x: sx(v) }))
const yticks = decades(A.ymin, A.ymax).map((v) => ({ v, y: sy(v) }))

// --- points (first :upto rungs, in ladder order) ---------------------------
const intensityOf = (r) => (r.bytes_per_pixel ? MACS / r.bytes_per_pixel : 0.9)
const shown = computed(() =>
  board.rungs.slice(0, props.upto).map((r) => {
    const lp = layout.points[r.name] || {}
    const cx = sx(intensityOf(r))
    const cy = sy(r.mpix)
    return {
      name: r.name,
      cx, cy,
      text: lp.text || r.label,
      color: lp.color || '#333',
      lx: cx + (lp.dx ?? 12),
      ly: cy + (lp.dy ?? 0),
      anchor: lp.anchor || 'start',
    }
  })
)

const title = layout.title || `Roofline - PYNQ-Z2`
const R = layout.regions || {}
const legendRows = [
  { dash: '0', label: 'roofline (attainable)', color: '#111', w: 3 },
  { dash: '6 4', label: `compute ceiling (${peak} Mpix/s)`, color: '#888', w: 1.5 },
  { dash: '1 4', label: 'DRAM-bandwidth ceiling', color: '#888', w: 1.5 },
]
const legX = sx(A.xmin) + 14
const legY = M.t + 30
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${H}`" width="100%" class="roofline">
    <!-- regime shading -->
    <rect :x="memRect.x" :y="memRect.y" :width="memRect.w" :height="memRect.h" fill="#3b7dd8" opacity="0.07" />
    <rect :x="compRect.x" :y="compRect.y" :width="compRect.w" :height="compRect.h" fill="#e08a1e" opacity="0.09" />

    <!-- gridlines + ticks -->
    <g class="grid">
      <line v-for="t in xticks" :key="'xg'+t.v" :x1="t.x" :x2="t.x" :y1="M.t" :y2="M.t+PH" />
      <line v-for="t in yticks" :key="'yg'+t.v" :x1="M.l" :x2="M.l+PW" :y1="t.y" :y2="t.y" />
    </g>
    <g class="tick">
      <text v-for="t in xticks" :key="'xt'+t.v" :x="t.x" :y="M.t+PH+18" text-anchor="middle">{{ fmt(t.v) }}</text>
      <text v-for="t in yticks" :key="'yt'+t.v" :x="M.l-8" :y="t.y+4" text-anchor="end">{{ fmt(t.v) }}</text>
    </g>

    <!-- plot frame -->
    <rect :x="M.l" :y="M.t" :width="PW" :height="PH" fill="none" stroke="#333" stroke-width="1" />

    <!-- ceilings + roofline -->
    <line :x1="computeLine.x1" :x2="computeLine.x2" :y1="computeLine.y" :y2="computeLine.y"
          stroke="#888" stroke-width="1.5" stroke-dasharray="6 4" />
    <line :x1="memLine.x1" :y1="memLine.y1" :x2="memLine.x2" :y2="memLine.y2"
          stroke="#888" stroke-width="1.5" stroke-dasharray="1 4" />
    <path :d="roofPath" fill="none" stroke="#111" stroke-width="3" />
    <line :x1="ridgeX" :x2="ridgeX" :y1="M.t" :y2="M.t+PH" stroke="#999" stroke-width="0.8" />

    <!-- regime labels -->
    <text :x="memLabelX" :y="regionY" text-anchor="middle" class="region mem">{{ R.memory }}</text>
    <text :x="compLabelX" :y="regionY" text-anchor="middle" class="region comp">{{ R.compute }}</text>
    <text :x="ridgeX" :y="M.t-4" text-anchor="middle" class="ridge">{{ R.ridge }}</text>

    <!-- dots + labels -->
    <g v-for="p in shown" :key="p.name">
      <line :x1="p.cx" :y1="p.cy" :x2="p.lx" :y2="p.ly" stroke="#bbb" stroke-width="0.8" />
      <circle :cx="p.cx" :cy="p.cy" r="7" :fill="p.color" stroke="#fff" stroke-width="1.5" />
      <text :x="p.lx" :y="p.ly + 4" :text-anchor="p.anchor" class="dot-label" :fill="p.color">{{ p.text }}</text>
    </g>

    <!-- legend -->
    <g v-if="legend" class="legend">
      <g v-for="(r, i) in legendRows" :key="'lg'+i" :transform="`translate(${legX}, ${legY + i*18})`">
        <line x1="0" x2="26" y1="0" y2="0" :stroke="r.color" :stroke-width="r.w" :stroke-dasharray="r.dash" />
        <text x="32" y="4">{{ r.label }}</text>
      </g>
    </g>

    <!-- titles -->
    <text :x="M.l + PW/2" :y="26" text-anchor="middle" class="title">{{ title }}</text>
    <text :x="M.l + PW/2" :y="H-10" text-anchor="middle" class="axis">arithmetic intensity (MACs / byte of DRAM traffic)</text>
    <text :transform="`translate(16, ${M.t + PH/2}) rotate(-90)`" text-anchor="middle" class="axis">throughput (Mpix/s)</text>
  </svg>
</template>

<style scoped>
.roofline { font-family: ui-sans-serif, system-ui, sans-serif; }
.grid line { stroke: #c8c8c8; stroke-width: 0.6; opacity: 0.5; }
.tick text { font-size: 18px; fill: #444; }
.axis { font-size: 19px; fill: #222; }
.title { font-size: 23px; font-weight: 600; fill: #111; }
.region { font-size: 17px; font-weight: 700; }
.region.mem { fill: #23538f; }
.region.comp { fill: #9c5a00; }
.ridge { font-size: 15px; fill: #888; }
.dot-label { font-size: 19px; font-weight: 600; }
.legend text { font-size: 16px; fill: #333; }
</style>
