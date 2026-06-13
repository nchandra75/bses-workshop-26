---
layout: section
routeAlias: streaming
---

# 6 - Streaming with DMA: near the roof

Change *how* it talks to memory, not *what* it computes.

---
layout: two-cols-title
---

::title::

## Burst, and overlap

::left::

Same line-buffer compute. New memory behaviour:

<v-clicks>

- **Burst** the transfers - ask DRAM for many bytes at once. DRAM is fast in bulk,
  slow per byte; bursting amortises the access latency.
- **Dataflow** - split into three stages (read -> compute -> write) on FIFOs, running
  **concurrently.** While one row computes, the next is read and the previous is
  written.

</v-clicks>

::right::

<v-click>

<div class="mt-4">

Memory traffic now **hides behind** compute. A Vitis `DATAFLOW` pipeline; csynth
reports all three loops at II = 1 with inferred bursts. (`hls/conv3x3_stream.cpp`)

</div>

</v-click>

<v-click>

<div class="mt-6 text-center text-xl">

**~40 Mpix/s** on the board - read *and* write.

</div>

</v-click>

---
layout: two-cols-title
---

::title::

## The whole climb

::left::

<Roofline :upto="6" :height="760" />

::right::

<div class="ns-c-tight">

The streaming dot sits up near the **ridge point** - where the memory and compute
ceilings meet. We're no longer obviously wasting either resource.

To go further: **widen** the datapath (several pixels/clock) or use a **wider/parallel**
memory interface. Real, but a different design.

**The whole climb:** 0.011 -> 39.9 Mpix/s. About **3500x** on the same nine-MAC
operation - most of it won by moving data better, not computing faster.

</div>

---

## What it cost on the chip

The three HLS kernels, from their Vitis csynth reports (`xc7z020`, 100 MHz target):

| kernel | inner-loop II | board | DSP (total) | BRAM18K | LUT |
|---|---|---|---|---|---|
| naive | 9 | 1.4 Mpix/s | 7 | 6 | 6.2k |
| line-buffer | 1 | 10 Mpix/s | 8 | 8 | 4.9k |
| streaming | 1 | 40 Mpix/s | 12 | 14 | 5.8k |

<div class="mt-4">

A handful of the chip's 220 DSPs and 280 BRAMs - none over ~6%. And most of those
DSPs aren't the MACs: in the naive kernel only **1** DSP does pixel x coeff (the 8x8
products go to LUTs); the other 6 are 32-bit **address** multiplies. The win came from
**II** (9 -> 1) and memory behaviour, not from spending more silicon.

</div>

---

## What the climb taught us

<v-clicks>

- **Beat the easy wins first.** Python loop -> NumPy was the biggest single jump, and
  it was just better software.
- **Hardware wins on parallelism** - nine MACs every clock - but only if you can
  **feed** it.
- **Every rung after the first was a data-movement fix:** MMIO -> bulk DMA -> read-once
  line buffer -> bursting dataflow.
- **The bottleneck moves.** Fix compute, memory becomes the wall; fix memory access,
  bandwidth does. The **roofline** tells you which wall you're against.

</v-clicks>

<!--
This is the spine of the whole session. If the room remembers one slide, this is it.
-->
