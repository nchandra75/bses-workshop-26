---
layout: section
routeAlias: motivation
---

# 1 - The problem

Modern systems drown in compute. One small operation, and how far we can push it.

---
layout: two-cols-title
columns: is-8
---

::title::

## Modern systems are buried in arithmetic

::left::

<img src="/figures/LeNet-5_architecture.svg" />

<div class="text-xs opacity-60 mt-2">

By Zhang, A. et al. (WikiMedia Commons 152265656) - https://github.com/d2l-ai/d2l-en, CC BY-SA 4.0

</div>

<v-clicks>

- A single CNN inference: **billions** of multiply-accumulates.
- Image, video, audio, language - all of it is dense linear algebra under the hood.
- The work is *regular and repetitive* - the same tiny operation, a billion times.

</v-clicks>

::right::

<img src="/figures/conv2d.gif" class="h-50" />

<div class="text-xs opacity-60 mt-2">

<a href="https://commons.wikimedia.org/wiki/File:2D_Convolution_Animation.gif">Michael Plotke</a>, <a href="https://creativecommons.org/licenses/by-sa/3.0">CC BY-SA 3.0</a>, via Wikimedia Commons

</div>


<v-click>

<div class="mt-8 text-xl text-center">

Our stand-in for all of it: a **3x3 image convolution.**
Nine multiply-accumulates per pixel - and it is *exactly one conv layer of a CNN.*

</div>

</v-click>

<!--
The hook for both halves of the room: the EE people get a clean compute-bound
kernel; the ML people get the inner loop of every vision model.
-->

---

## Three ways to see a computer

<div class="grid grid-cols-3 gap-4 mt-6">

<div class="p-4 rounded border-2 border-gray-300">

### The white box

<v-click>

What you were taught: a CPU, some memory, a bus. Instructions stepping through, one
after another. Everything visible - and everything **sequential.**

</v-click>

</div>

<div class="p-4 rounded border-2 border-gray-800 bg-gray-800 text-white">

### The black box

<v-click>

How hardware usually shows up: "the accelerator made it 100x faster." You call it,
you trust it, you have **no idea why.** Sealed.

</v-click>

</div>

<div class="p-4 rounded border-2 border-gray-500 bg-gray-400">

### The grey box

<v-click>

Today's job. You don't have to design chips to **peek inside** and reason about why
one version beats another. Translucent, on purpose.

</v-click>

</div>

</div>

---

## How much can a processor actually do?

A back-of-the-envelope, for the board's ARM core:

<v-clicks>

- ~1 GHz, roughly **one instruction per clock** -> ~1e9 useful ops/second.
- One output pixel = 9 multiplies + 8 adds + loads/stores + loop overhead -> **~50 instructions.**
- A 1-megapixel image -> ~5e7 instructions -> **tens of milliseconds** *if every instruction counts.*

</v-clicks>

<v-click>

<div class="mt-6 text-center text-xl">

That "if" is doing all the work.

</div>

</v-click>

---

## The memory wall

<div class="text-xl my-8">

A multiply takes **~1 clock.**
A load that misses cache and goes to DRAM takes **hundreds.**

</div>

<v-clicks>

- The naive convolution re-reads each pixel up to **nine times.**
- It spends most of its life **waiting on memory**, not multiplying.
- Faster arithmetic doesn't help if you're stalled on data.

</v-clicks>

<v-click>

<div class="mt-6 text-center text-xl">

Keep this picture. **Every** rung after the first is a *data-movement* fix.

</div>

</v-click>

---
layout: two-cols-title
---

::title::

## The scoreboard: a roofline

::left::

Two ceilings no design can beat:

- **Compute** - how many MACs/second the hardware can do (flat).
- **Memory** - how fast it can move bytes (sloped: more bytes/pixel -> you hit it sooner).

Every implementation is a **dot** under those ceilings. The gap is performance left
on the table.

<div class="text-xs opacity-60 mt-2">

Williams et al.. Roofline: an insightful visual performance model for multicore architectures. Commun. ACM 52, 4 (April 2009).

</div>

::right::

<Roofline :upto="0" :height="720" />

<div class="mt-4 text-sm opacity-70">

We rebuild this picture at every rung, adding one dot at a time.

</div>

<!--
Keep it simple on the projector: two lines and a moving dot. Don't dwell on the
math; the message is "here's the ceiling, here's us, here's the gap."
-->

---
layout: center
class: text-center
---

## First, the slowest possible answer

Before we optimise anything, we have to **measure** anything.

A pure Python loop - and the discipline of timing it honestly.

<div class="text-sm opacity-70 mt-8">

Notebook: <code>01_python_loops.ipynb</code>

</div>
