# Reference data

Real measurements captured on the PYNQ-Z2, checked in so the roofline and the
notebook scoreboard can be regenerated **without a board** (e.g. when prepping the
deck offline, or if no board is available on the day).

| File | What |
|------|------|
| `board_data_pynqz2_62mhz.json` | full `collect_board_data.py` output - per-rung throughput, bytes/pixel, achieved DRAM bandwidth, clock |
| `scoreboard_pynqz2_62mhz.json` | the same tally in the notebooks' scoreboard format |

Captured 2026-06-12, kernel `edges`, **fclk0 = 62.5 MHz** (the board's boot default;
the design requests 100 MHz but the four-accelerator bitstream is marginally over
timing there - WNS -0.286 ns - so 62.5 is the safe, bit-exact operating point). All
six rungs bit-exact against the golden NumPy reference.

Headline numbers (Mpix/s): pyloop 0.011, software 1.31, rtl 0.017, hls_naive 1.44,
hls_opt 10.1, hls_stream 39.9. Streaming sustains 0.64 pixel/clock and is
memory-bound: it moves 1 byte in + 1 byte out per pixel over two **separate**
byte-wide `m_axi` ports, so its ~80 MB/s is the read+write aggregate (~40 MB/s per
port = 64% of the 62.5 MB/s a byte-wide port delivers at 62.5 MHz).

Regenerate the figure from a baseline:

    python3 ../make_roofline.py reference_data/board_data_pynqz2_62mhz.json

`make_roofline.py` also falls back to `board_data_pynqz2_62mhz.json` automatically
when no fresh `board_data.json` is passed, so the deck always builds against real
numbers rather than a guess.
