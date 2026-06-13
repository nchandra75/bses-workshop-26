# Workshop slides

[Slidev](https://sli.dev/) deck for the FPGA convolution workshop, using the
`neversink` theme (same setup as `ee5332/slides`).

**Run every command from this `slides/` directory** - that is where `package.json`
lives. Running `pnpm` from the repo root fails with "no package.json". `pnpm` is
mise-managed; if it is not on your PATH it is at
`~/.local/share/mise/installs/pnpm/latest/pnpm`.

```bash
cd slides         # always
pnpm install
pnpm dev          # live reload at http://localhost:3030 (press r to restart, o to open)
pnpm build        # static site -> dist/
pnpm export       # PDF
```

## Structure

- `slides.md` - entry point: front matter + `src:` includes, one per act.
- `pages/` - one file per act (`01-motivation` ... `05-wrap`) plus `toc`.
- `figures/` - diagrams (Zynq block, line buffer, critical path, waveforms, notebook shots).
- `styles/` - projector-friendly tweaks.
- `vite.config.ts` - whitelists the repo root so slides can `<<<`-import real `../rtl` etc.

## Slide conventions

- **New slide:** a `---` divider on its own line. Per-slide front matter (layout
  etc.) goes in a `---`-fenced block immediately after the divider.
- **Layouts in use:** `section` (act title page), `two-cols-title` (use the
  `::title:: / ::left:: / ::right::` slots), and the default single column.
- **Reveal/click steps:** wrap a list in `<v-clicks>` ... `</v-clicks>`, or a
  single block in `<v-click>` ... `</v-click>`. Blank lines around the tags.
- **Presenter notes:** an HTML comment `<!-- ... -->` at the end of a slide. These
  are the per-beat timings and live-demo cues - keep them.
- **Styling:** UnoCSS / Tailwind utility classes in `class="..."` on `<div>`/`<img>`
  (e.g. `text-center`, `mt-6`, `max-w-4xl`, `text-red-600`). No custom CSS needed
  for one-offs.
- **Live code from real files:** `<<< ../../rtl/conv3x3_core.sv sv {118-126}` pulls a
  real span so it can never drift (see "Code walkthroughs" below). Prefer this over
  pasting code that can rot.

## Figures (read this before adding one)

Diagrams are hand-written SVG in `figures/`. Two rules that are easy to get wrong:

1. **Reference them with an absolute `/figures/...` path, never a relative one.**
   Slidev serves `figures/` at the site root, so:

   ```html
   <img src="/figures/critical-path-slow.svg" class="w-full max-w-4xl mx-auto" />
   ```

   `../figures/...` does *not* resolve reliably and shows a broken-image icon.

2. **An `.svg` is XML, so only the five predefined XML entities are legal inside
   it:** `&amp; &lt; &gt; &quot; &apos;`. Named HTML entities -
   `&mdash; &minus; &middot; &nbsp; &rarr; &asymp;` and friends - are **undefined
   in XML** and make the browser refuse to render the file (broken-image icon,
   even though the dev server returns it `200`). Use a numeric character reference
   or plain ASCII instead:

   | want | use in SVG |
   |------|------------|
   | em dash | `&#8212;` or ` - ` |
   | minus  | `-` |
   | middle dot separator | `&#183;` |
   | approx | `~` or `&#8776;` |
   | arrow  | `&#8594;` or `-&gt;` |

   (Inside the slide **markdown** body - HTML context, not the SVG file - named
   entities like `&rarr;` are fine. The rule is only for the `.svg` files.)

   **Always validate before committing:** `xmllint --noout figures/whatever.svg`
   (silent = good). The CI-free safety net for this whole class of bug.

   Match the house palette so figures look of-a-piece: slate borders `#cbd5e1`,
   blue logic `#3b82f6`/`#dbeafe`, green pass `#22c55e`/`#dcfce7`, amber registers
   `#eab308`/`#fef9c3`, red fail `#ef4444`/`#fee2e2`, font `Inter`.

## Code walkthroughs

The slides show **trimmed** code excerpts with click-through highlighting
(`{all|1-3|5-9}`) - enough to make the point on a projector. The *full* file
walkthrough happens live in the editor / Vivado / Jupyter, which is where the
real teaching energy is (see `docs/workshop-plan.md`).

To instead pull a **real source file** into a slide so it can never drift, use
Slidev's import syntax (paths are relative to the page file):

```
<<< ../../rtl/conv3x3_core.sv sv {118-126}
```

`vite.config.ts` already whitelists the repo root for these parent-directory
imports. Add `// #region name` / `// #endregion name` markers in the source and
import `...conv3x3_core.sv#name` to pull just that span.

## Placeholders to fill

- `figures/zynq-block.svg` - the PS | AXI | PL diagram (reused across the RTL rung and the wrap).
- `figures/line-buffer.svg` - sliding window over a stream.
- Waveform + notebook screenshots.
- HLS synthesis numbers (II / DSP / BRAM / LUT / FF), naive vs line-buffer.

`figures/critical-path-slow.svg` and `critical-path-pipelined.svg` (the
timing/pipelining slides in the RTL rung) are done - use them as the worked example
of the figure conventions above.
