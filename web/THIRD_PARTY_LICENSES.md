# Third-party licenses (web UI)

Every package the web UI depends on is under an open-source license. Direct dependencies are
listed below with the version installed from `package-lock.json`. The full production dependency
tree (`npm ls --omit=dev --all`) was checked: 214 MIT, 22 ISC, 9 Apache-2.0, 6 BSD-3-Clause,
3 BSD-2-Clause, 1 0BSD and 1 MIT-or-CC0 package, plus the two items noted under "Build-time
notes".

## Runtime dependencies

| Package | Version | License | Used for |
| --- | --- | --- | --- |
| next | 15.5.29 | MIT | App Router framework, server rendering |
| react, react-dom | 19.1.0 | MIT | UI rendering |
| radix-ui | 1.8.1 | MIT | Accessible primitives (tooltip, tabs, sheet) |
| shadcn | 4.23.0 | MIT | Component recipes and base Tailwind styles |
| class-variance-authority | 0.7.1 | Apache-2.0 | Component variants |
| cn | 0.5.2 | MIT | Class name merging |
| tw-animate-css | 1.4.0 | MIT | CSS enter/exit animations |
| motion (with framer-motion, motion-dom, motion-utils) | 14.14.0 | MIT | Page fade, navigation and tab indicators, verdict reveal |
| lucide-react | 1.77.0 | ISC | Icons (single stroke style throughout) |
| next-themes | 0.4.6 | MIT | Light and dark theme |
| d3-force | 3.0.1 | ISC | Deterministic campaign map layout |
| d3-zoom, d3-selection, d3-transition | 3.0.1 / 3.0.1 / 3.0.2 | ISC | Zoom and pan of the campaign map |
| d3-dispatch, d3-timer, d3-quadtree, d3-interpolate, d3-color, d3-drag | 3.x | ISC | Transitive d3 modules |
| d3-ease | 3.0.2 | BSD-3-Clause | Transitive d3 module |
| server-only | 0.0.1 | MIT | Keeps the API client on the server |

## Fonts

| Font | License | Notes |
| --- | --- | --- |
| Geist, Geist Mono (Vercel) | SIL Open Font License 1.1 | Downloaded at build time by `next/font` and self-hosted with the app |

## Development dependencies

| Package | License |
| --- | --- |
| typescript | Apache-2.0 |
| tailwindcss, @tailwindcss/postcss | MIT |
| eslint, eslint-config-next, @eslint/eslintrc | MIT |
| @types/react, @types/react-dom, @types/node, @types/d3-force, @types/d3-zoom, @types/d3-selection, @types/d3-transition | MIT |

## Build-time notes

- `caniuse-lite` (CC-BY-4.0, browser support data) is read by the build toolchain only; it is not
  shipped to the browser.
- `sharp` / `@img/sharp-libvips-*` (Apache-2.0 / LGPL-3.0-or-later) is an optional dependency of
  Next.js for `next/image` optimisation. The UI does not use `next/image`, image optimisation is
  disabled (`images.unoptimized` in `next.config.ts`), so libvips is never loaded or distributed
  with the UI. It can be left out with `npm install --omit=optional` on platforms where the SWC
  binary is provided separately.

## Removed

`three`, `three-spritetext`, `react-force-graph-2d` and `react-force-graph-3d` (MIT) were removed
together with the 3D view.

## Own assets

The logo, favicon, app icon and Open Graph image were drawn for this project and are covered by
the repository license.
