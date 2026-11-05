# Tickbench UI spec

## Palette (dark / light)
| Role | Dark | Light |
|---|---|---|
| Background | #0F1214 | #EFECE4 |
| Panel | #171B1E | #FBFAF7 |
| Ink | #E6E2D8 | #1D1B17 |
| Accent (brand, cursor, Run button) | #F2A93B | #B86E00 |
| Strategy equity line | #C98500 | #A86D00 |
| Buy & hold line | #3987E5 | #2A78D6 |
| Profit | #199E70 | #138A5F |
| Loss | #E66767 | #D13F3E |
| Plot overlays (fixed order) | #3987E5, #D95926, #199E70, #C98500, #D55181 | #2A78D6, #EB6834, #1BAF7A, #A86D00, #E87BA4 |

Data colors were validated with the dataviz palette checker (equity vs. benchmark passes every check in both themes). Profit/loss sits in the colorblind warning band, so P&L always also carries +/− signs and ▲/▼ markers.

## Type
- UI: IBM Plex Sans 400/500/600 (bundled, works offline)
- Numbers: JetBrains Mono, tabular figures

## Surfaces and depth
- Elevation layers: base (with subtle film grain), raised rail, panels (shadow-1), cards (shadow-2), floating chrome (shadow-3), modals/toasts (shadow-4)
- Glass (backdrop blur 16px + translucent fill + 1px light edge) only on the floating chart toolbar, modals and toasts. Solid fallback when unsupported. Never behind tables or body text.
- Radii: 4 / 6 / 10 / 14 px

## Motion
One moment only: when a run finishes, the equity curve draws left to right (~750 ms) and the KPI strip counts up and rises in. Hover/press use spring easing. All motion is off under prefers-reduced-motion.

## Layout
Top bar (Workspace / History / Compare, engine status, update pill, theme toggle) · 372px left rail (Strategy, Inputs, Price data, Account/sizing/costs, sticky Run button with progress, Ctrl+Enter) · results area (header chips, 7-tile KPI strip, tabs: Overview, Price chart, Trades, Statistics, What it did).
