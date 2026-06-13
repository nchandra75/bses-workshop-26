---
layout: section
routeAlias: rtl
---

# 3 - Onto the FPGA: hand-written RTL

What's actually inside the chip, our first circuit - and the data-movement wall.

---
layout: two-cols-title
columns: is-4
---

::title::

## What is inside an FPGA?

::left::

<img src="/figures/gemini-fpga.png" class="h-100"/>

<div class="text-xs opacity-60 mt-2">
Img src: Gemini
</div>

::right::

Not a processor. A sheet of:

<div class="ns-c-verytight">

<v-clicks>

- **Logic Blocks**
  - **LUTs** - tiny configurable truth tables; become any logic gate.
  - **Flip-flops** - one-bit registers holding state between clock edges.
- **DSP blocks** - hardened multiply-accumulate units (real multiplier silicon).
- **BRAM** - small on-chip memories.
- **Interconnect** - programmable wiring

</v-clicks>

</div>

<v-click>

<div class="text-xl mt-4">

You don't write a *program* that runs on it. You **describe a circuit**, and the
fabric *becomes* it.

</div>

</v-click>

<v-click>

<div class="mt-6">

Convolution: **nine multipliers** wired into one adder tree, all firing on
the **same clock edge.** 

</div>

</v-click>

---

## The MAC tree: nine multipliers, one edge

<<< @/../rtl/conv3x3_core_unpipelined.sv#mac-tree verilog {all|1|2-9|all}

<v-click>

No loop. **Nine wires into one adder tree.** Each `*` is a hardware multiplier - separate
silicon, all evaluated the same cycle. (`rtl/conv3x3_core_unpipelined.sv`)

</v-click>

---

## The catch: getting data in and out

The datapath is fully parallel. But a fast circuit is useless if you can't feed it.

<v-clicks>

- This first version is driven the simplest way: the CPU writes **each pixel** to a
  hardware register over AXI (**MMIO**), one bus transaction per pixel - and reads each
  result back the same way.
- Every pixel crosses the bus **twice**, under CPU control.

</v-clicks>

---
layout: center
class: text-center
---

## MMIO: how the CPU reaches the accelerator

<img src="/figures/mmio.svg" class="h-[78vh] mx-auto" />

---

## The catch: getting data in and out

The datapath is fully parallel. But a fast circuit is useless if you can't feed it.

- This first version is driven the simplest way: the CPU writes **each pixel** to a
  hardware register over AXI (**MMIO**), one bus transaction per pixel - and reads each
  result back the same way.
- Every pixel crosses the bus **twice**, under CPU control.
- That round-trip costs far more than the nine multiplies it feeds.

<v-click>

<div class="mt-4 text-center text-xl">

Throughput is **poor** - not because compute is slow, but because we're trickling
data by hand. **The bottleneck moved from compute to data movement.**

</div>

</v-click>

<!--
Run 03_rtl_fpga.ipynb on the board: small image, watch the wall-clock. The roofline
dot sits low - data-starved, not compute-starved.
-->


---
layout: two-cols-title
---

::title::

## Side quest: does it meet the clock?

::left::

- 100 MHz $\Rightarrow$ **10 ns** - one tick. 
- **critical path**; too much logic in one hop and it misses the edge.

| design | logic<br>levels | slack<br>@100 MHz | |
|---|---|---|---|
| one-shot | 38 | **&minus;16 ns** | <span class="text-red-600 font-bold">FAILS</span> |
| pipelined | 12 | **+3.3 ns** | <span class="text-green-600 font-bold">MET</span> |


Both must pass the **same** testbench. 

<v-click>

- **pipeline** - insert registers, same logic in four short hops. 
- Trades latency for clock; throughput unchanged.

</v-click>

::right::

<v-click>

<img src="/figures/critical-path-slow.svg" class="w-full" />

</v-click>

<v-click>

<img src="/figures/critical-path-pipelined.svg" class="w-full" />

<div class="mt-2 text-xs opacity-70">

In practice this board ran correct well past 150 MHz before the AXI bus hung - static
timing is worst-case. The bonus notebook ramps the clock live.

</div>

</v-click>

<!--
Kept deliberately short - timing is a side quest now, not the headline. The honest
caveat: no clean correctness cliff on warm silicon.
-->

---
layout: two-cols-title
---

::title::

## Where we are: rung 3

::left::

<Roofline :upto="3" :height="720" />

::right::

- **Compute**: all nine MACs in **one clock** - genuinely parallel hardware.
- But one pixel per MMIO write $\Rightarrow$ **slower than NumPy**

> ####  **Fast compute is wasted if you can't feed it.** Let the accelerator fetch its own data.

---
layout: center
class: text-center
---

## Writing every wire by hand is slow

What if we wrote the convolution in **C++** and let a tool build the circuit -
*and* let the accelerator fetch its own data from DRAM?

<div class="text-sm opacity-70 mt-8">

-> High-Level Synthesis. Notebook: <code>04_hls_naive.ipynb</code>

</div>
