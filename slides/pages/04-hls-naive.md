---
layout: section
routeAlias: hls-naive
---

# 4 - HLS: C++ into a circuit

The same convolution in C++, the accelerator fetching its own data - and the II wall.

---
layout: two-cols-title
columns: is-9
--- 

::title::

## Regular C code

::left::

<<< @/../hls/conv3x3.cpp#conv-loops cpp {all|1-2|11}

::right::

<v-click>

Recognisable: 

- loop over pixels, 
- loop over the neighbourhood, 
- accumulate. 

`p = in[...]`: **bandwidth-hungry DRAM read** - re-fetched for every
tap. 

</v-click>

---

## The pragmas are where the hardware is

```cpp {all}
#pragma HLS INTERFACE m_axi port=in  bundle=gmem0   // read image straight from DRAM
#pragma HLS INTERFACE m_axi port=out bundle=gmem1   // write result to DRAM

#pragma HLS INTERFACE s_axilite port=return         // control registers Python pokes

#pragma HLS PIPELINE II=1                            // one pixel per clock... we hope
```

<v-clicks>

- `m_axi` - the PL becomes a **bus master**, reading DRAM itself. No more per-pixel
  MMIO from the CPU.
- `s_axilite` - the control registers Python writes to start it.
- `PIPELINE II=1` - the *goal*: one output pixel per clock.

</v-clicks>

---
layout: two-cols-title
---

::title::

## Initiation Interval: the number that matters

::left::

**II** = clocks between successive loop iterations starting.

- II = 1 $\Rightarrow$ a new pixel **every clock.** The goal.
- Naive loop re-reads its 3x3 window from DRAM **every** output pixel - up to nine
  reads - all through **one** memory port.
- The tool can't start the next iteration until those reads finish.

<div class="mt-4 text-center text-xl">

Result: **II = 9.** Nine clocks per pixel.

</div>

::right::

**1.44 Mpix/s** - 359 ms for a 720x720 frame.

~80x the MMIO RTL core.

<v-clicks>

- Faster than MMIO RTL - it fetches in bulk, not one pixel at a time.
- Still far from the ceiling: **9 bytes read + 1 written** per output pixel.
- Low **arithmetic intensity** - few MACs per byte moved.

</v-clicks>

---
layout: two-cols-title
---

::title::

## Where we are: rung 4

::left::

<Roofline :upto="4" :height="720" />

::right::

- Naive HLS now fetches its own data over DMA - **1.4 Mpix/s**, about level with NumPy.
- The dot sits **far left** on the memory slope: the kernel re-reads the 3x3 window from
DRAM for every output pixel, **~10 bytes/pixel**.

It's not compute-bound (II=9 hides under the memory wait). The fix is to stop
re-reading.

---
layout: center
class: text-center
---

## The datapath could go nine times faster

It's memory access holding it back. The fix is the idea the RTL already used:

**don't re-read. Keep the last two rows on-chip.**

<div class="text-sm opacity-70 mt-8">

Notebook: <code>05_line_buffer.ipynb</code>

</div>
