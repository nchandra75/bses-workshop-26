---
layout: section
routeAlias: software
---

# 2 - Software: loops, then NumPy

The two software rungs - and how to measure so the numbers don't lie.

---

## Rung 1: the pure Python loop

```python {all|2-3|4-9|10}
for i in range(h):
  for j in range(w):
    acc = 0
    for dy in (-1, 0, 1):
      for dx in (-1, 0, 1):
        yi, xj = i + dy, j + dx
        if 0 <= yi < h and 0 <= xj < w:
          acc += coeff[k] * img[yi, xj]
        k += 1
    out[i, j] = clip(acc >> shift)
```

<v-click>

Correct, and **brutally slow** - the interpreter does each multiply one at a time,
with type-dispatch and loop overhead on every single one. This is the thing you must
*not* do.

</v-click>

---

## Measure honestly, or don't bother

Naive timing lies. Two habits, used **identically** for every rung from here:

<v-clicks>

- **Warm up.** 
  - one-time costs that aren't the computation -
  imports, interpreter warm-up, allocating buffers, cold caches (and later, the FPGA
  allocating DMA buffers). 
  - Throw the first runs away.
- **Average, and show the spread.** 
  - OS scheduler noise
  - Take many; report the **best**, plus the spread so the noise is
  visible, not hidden.

</v-clicks>

<v-click>

<div class="mt-4 text-sm opacity-80">

It lives in <code>fpga_conv/bench.py</code> - one harness, so the method never
changes between rungs.

</div>

</v-click>

<!--
Show the cold-vs-warm gap live in 01_python_loops.ipynb - the per-run plot with the
best line. This is where measurement discipline gets installed.
-->

---
layout: two-cols-title
---

::title::

## Where we are: rung 1 on the board

::left::

<Roofline :upto="1" :height="720" />

::right::

The pure-Python loop measures **0.011 Mpix/s**

> How well does that compare with what the CPU could theoretically do?

---
layout: two-cols-title
---

::title::

## Rung 2: NumPy - the same maths, compiled

::left::

```python
acc = np.zeros_like(img, np.int32)
for k, c in enumerate(coeff):
    if c:
        acc += c * shifted(img, k)
out = clip(acc >> shift)
```

The loop is still there - it just isn't in **Python** any more. 

- Array operations - cleaner code
- Compiled C/Fortran loops
- Single-Instruction Multiple-Data (SIMD) to do several pixels per instruction.

::right::

| | throughput | per pixel |
|---|---|---|
| Python loop | 0.011 Mpix/s | ~87 us |
| NumPy | 1.31 Mpix/s | ~0.77 us |

**~110x** faster on the board (PYNQ-Z2), bit-for-bit identical output.

<v-clicks>

- Many **orders of magnitude** faster than the Python loop.
- For *identical* output (it's our golden reference).

</v-clicks>

<v-click>

<div class="mt-4 text-lg">

Lesson: most of the imagined "CPU vs FPGA" gap is really **good code vs bad code.**
Beat the easy wins first.

</div>

</v-click>

---

## But NumPy has a ceiling

<v-clicks>

- A CPU core does a **bounded** number of arithmetic ops per clock.
- For each output pixel it still **re-reads** the neighbours from memory.
- To go faster: do all nine multiplies **at once, every clock**, and **stop
  re-reading** data.

</v-clicks>

<v-click>

<div class="text-2xl mt-10 text-center">

That is something you **build**, not something you run. -> the FPGA.

</div>

</v-click>

---
layout: two-cols-title
---

::title::

## Where we are: rung 2

::left::

<Roofline :upto="2" :height="720" />

::right::

NumPy: **1.3 Mpix/s** - a ~100x jump for *the same maths*, just compiled instead of
interpreted. The single biggest step on the whole ladder, and not a circuit in sight.

Still pinned to the **memory slope**, far from the ceiling. To climb off it we have to
stop re-reading data - which is what the hardware lets us do.

<!--
Honest aside for the roofline: on a laptop NumPy can sit ABOVE the 100 MHz PL
ceiling. The fair fight is same-system - NumPy on the board's ARM vs the
accelerator in the PL. Make that explicit when you show the roofline.
-->
