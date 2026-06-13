import { fileURLToPath } from 'node:url'

// The slides live in slides/ but the code-walkthrough slides can import the
// *real* source files from the repo (../rtl, ../hls, ../python) via `<<<` so
// they never drift from what is simulated / run on the board. Allow the dev
// server to read those parent directories.
//
// Plain object (no `defineConfig` import) so it loads without `vite` as a
// direct dependency under pnpm's hoisting.
const repoRoot = fileURLToPath(new URL('..', import.meta.url))

export default {
  server: {
    fs: {
      allow: [repoRoot],
    },
  },
}
