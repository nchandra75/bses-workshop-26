---
layout: section
--- 

# Prelude:

### Where has all the compute gone?

---

<img src="/figures/gemini-cat-researcher.png">

<div class="text-xs opacity-60 mt-2">
Img src: Gemini using massive amounts of compute to draw cats
</div>

---

# Compute in the Present Day

> ## AI / ML / Signal Processing / Communication

- Large amounts of arithmetic
- Large amounts of data

### Specialized computing equipment is often needed

What role do the hardware blackboxes play?

---
layout: two-cols-title
---

::title::

# The plan: one operation, climbing a ladder

::left::

<div class="ns-c-tight">

We take **one** 3x3 convolution and make it faster, rung by rung. Each step fixes
the bottleneck the last one exposed:

<v-clicks>

1. **Python loops** - the baseline. And how to *measure* honestly.
2. **NumPy** - the same maths in compiled C. The biggest single jump.
3. **RTL on the FPGA** - nine multipliers at once, but starved by MMIO.
4. **HLS, naive** - C++ to a circuit; easier abstraction.
5. **Line buffers** - read each pixel once; now memory-bound.
6. **Streaming + DMA** - burst the data; near the hardware's limit.

</v-clicks>

</div>

::right::

<v-click>

<div class="ns-c-tight">

**The one operation:** a 3x3 image convolution - nine multiply-accumulates per
pixel. Compute-heavy, data-light: *exactly one conv layer of a CNN.*

**The recurring question:** how far are we from the limit?

We keep one picture - a **roofline** with two ceilings (how fast the hardware can
compute, how fast it can move data) - and drop each rung on it. The gap is the
performance still on the table.

<div class="mt-4 text-sm opacity-70">

Every rung is bit-exact against one golden NumPy reference.

</div>

</div>

</v-click>
