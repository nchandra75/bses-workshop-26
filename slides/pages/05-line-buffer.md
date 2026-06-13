---
layout: section
routeAlias: line-buffer
---

# 5 - Line buffers: read each pixel once

II = 1 in compute. And the bottleneck moves again.

---
layout: two-cols-title
---

::title::

## Line buffers: a stream becomes a window

::left::

<img src="/figures/line-buffer-window.svg" class="h-[50vh]" />

::right::

- Pixels arrive **one per cycle**, raster order.
- A 3x3 window needs **three rows at once.**
- Keep the previous two rows on-chip - each new pixel completes a vertical column.

<v-click>

<div class="mt-4 text-sm opacity-80">

Sliding-window-over-a-stream: how *almost all* FPGA image processing works. We'll
reuse this exact idea in HLS.

The compute loop now hits **II = 1** - one output pixel per clock.
(`hls/conv3x3_fast.cpp`)

> Was also tried in the RTL, but MMIO was the bottleneck there

</div>

</v-click>

---
layout: two-cols-title
---

::title::

## Is it faster?

::left::

**10.1 Mpix/s** - 51 ms / frame. ~7x the naive HLS

> #### but only a fraction of the 62.5 Mpix/s ceiling.


<v-clicks>

- The memory port is **byte-wide.**
- Even reading each pixel once, it pulls in **one byte per clock** - and must write a
  byte out too.
- A datapath that finishes a pixel every clock now **waits on memory.**

</v-clicks>

::right::

<v-click>

<div class="text-xl mt-4">

**Memory-bandwidth bound** (~10 Mpix/s).

</div>

</v-click>

<!--
The key teaching moment: fixing compute revealed a memory-access wall. The bottleneck
always moves. The roofline names which wall you're against.
-->

---
layout: two-cols-title
---

::title::

## Where we are: rung 5

::left::

<Roofline :upto="5" :height="720" />

::right::

The line buffer reads each pixel **once** - 2 bytes/pixel instead of 10 - so the dot
jumps **right** to higher intensity and up to **10 Mpix/s**.

But it's still **below** the ceiling at that intensity: II=1 in compute, yet trickling
single-byte transfers. Same intensity, more throughput available - if we burst.

---
layout: center
class: text-center
---

## Stop trickling bytes

Read and write in **bursts**, and overlap read / compute / write so memory traffic
**hides behind** compute.

<div class="text-sm opacity-70 mt-8">

-> Streaming with DMA. Notebook: <code>06_streaming.ipynb</code>

</div>
