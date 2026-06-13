---
layout: section
routeAlias: wrap
---

# Wrap-up

One operation, seven implementations, one picture.

---
layout: two-cols-title
clicks: 6
---

::title::

## The ladder

::left::

<v-clicks>

| Rung | What it taught |
|------|----------------|
| **Python loops** | measure honestly; the interpreter is the wall |
| **NumPy** | most "CPU vs FPGA" gaps are good vs bad code |
| **RTL + MMIO** | parallel compute, starved by data movement |
| **HLS naive** | C++ to a circuit; the II / re-read wall |
| **Line buffer** | read once; now memory-bandwidth bound |
| **Streaming DMA** | burst + dataflow; near the hardware limit |

</v-clicks>

::right::

<div class="ns-c-tight">

The recurring lesson: **the bottleneck moves.** Compute, then memory, then bandwidth.

<div class="mt-4">

<Roofline :upto="$clicks" :height="600" />

</div>

</div>

---

## Where to go from here

<div class="text-xl my-8">

The `edges` kernel you ran is a **fixed** 3x3 filter.

A CNN **learns** its kernels - but the hardware operation is **identical.**

<v-clicks>

- **Multiple channels** - real conv layers are CxHxW, not 1xHxW.
- **Learned kernels** - train them instead of hand-picking.
- **Wider datapaths** - several pixels per clock; parallel memory.

</v-clicks>

</div>

<v-click>

<div class="text-2xl mt-8 text-center">

The circuit on the board is **one conv layer.** Stack them and you have the inner loop
of every modern vision model.

</div>

</v-click>


---
layout: two-cols-title
---

::title::

## How to go faster

::left::

<div class="ns-c-tight pr-4">

#### Clues from the roofline plot

- Burst mode data transfer: efficient use of the bus - go **up**
- Do more compute with each transferred byte - go **right**

<v-click>

#### Move the roofline

- Flat roof was only **one pixel per clock** - the datapath we happened to build.
- The Zynq has 220 DSPs; nine of them is a rounding error.

> move **up**: more compute, several pixels per clock, raising the roof itself. 

The memory ceiling has to rise with it, or
the wider datapath just starves. That's a real CNN accelerator.

</v-click>

</div>

::right::

<img src="/figures/raise-the-roof.svg" class="w-full" />

---

## The point of this exercise

<v-clicks>

- You may be a data scientist - but you should know what your computers are capable of
- You may be a computer engineer - but you should know what you want to compute
- You may be an electrical engineer - but you should know what needs to be built

</v-clicks>


<v-click>

<div class="text-xl mt-6 text-center opacity-80">

The box started **black.** You can see into it now. That's the grey box - and it's
yours whether or not you ever write another line of Verilog.

</div>

</v-click>
