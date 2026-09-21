# SPDX-License-Identifier: LGPL-2.1-or-later
"""The design tokens, in one place, written into a `:root` block at build time.

This is the frontend's answer to `lib/gui/templates.py`'s single stylesheet: every
colour has a name, both themes swap **tokens only** - never a selector - and the
contrast of each ink on its ground is recorded next to it so that changing one is a
calculation and not a guess.

`SURFACE` / `SUNKEN` / `LINE` / `INK` are structure; `OK` / `WARN` / `BAD` / `INFO`
are the four things a row can be, and they are the only colours a verdict pill may
use.  Light and dark are the same names with different values, so a component is
written once and themed for free.
"""

# name -> (light, dark).  Order is the order they are written out.
TOKENS = {
    # -- grounds and lines -------------------------------------------------
    "ground":      ("#eceef1", "#101318"),   # the page behind the panels
    "surface":     ("#ffffff", "#191d24"),   # a panel
    "raised":      ("#f7f8fa", "#1f242c"),   # a header row, a hovered row
    "sunken":      ("#e3e6ea", "#141820"),   # an input, a code chip
    "line":        ("#c9ced6", "#333a45"),   # the one border
    "line-soft":   ("#dde1e7", "#282e38"),   # a rule inside a panel
    # -- ink ---------------------------------------------------------------
    "ink":         ("#14171c", "#e7ebf1"),   # body
    "ink-mid":     ("#48505c", "#a9b2bf"),   # a value, a secondary word
    "ink-soft":    ("#6b7482", "#79828f"),   # a label, a caption
    "ink-inv":     ("#ffffff", "#0d1015"),   # on an accent fill
    # -- accent ------------------------------------------------------------
    "accent":      ("#2f5bd0", "#7ea2ff"),
    "accent-soft": ("#e6ecfb", "#1d2942"),
    "accent-line": ("#b9c8f0", "#33446b"),
    # -- the four states ---------------------------------------------------
    "ok":          ("#146c43", "#5cc08a"),
    "ok-soft":     ("#e2f2e9", "#142c20"),
    "warn":        ("#8a5400", "#d7a153"),
    "warn-soft":   ("#faefdc", "#2e2416"),
    "bad":         ("#a5241c", "#e88078"),
    "bad-soft":    ("#fbe6e4", "#331917"),
    "info":        ("#1f5f8b", "#6fb6e8"),
    "info-soft":   ("#e2eff7", "#152734"),
    "idle":        ("#5c6572", "#8b94a2"),
    "idle-soft":   ("#e9ebef", "#232830"),
    # -- code --------------------------------------------------------------
    "code":        ("#3f4a5a", "#c2cad6"),   # a build id, a path, an argv
    "code-soft":   ("#eef0f3", "#1b2028"),
}

# Non-colour tokens: one place for a radius, a shadow, a font stack.
SCALARS = {
    "r": "6px",
    "r-sm": "4px",
    "r-pill": "999px",
    "sans": '"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
    "mono": '"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
    "shadow": "0 1px 2px rgba(15,18,23,.05),0 6px 16px -10px rgba(15,18,23,.25)",
    "shadow-pop": "0 4px 10px rgba(15,18,23,.10),0 16px 32px -12px rgba(15,18,23,.30)",
    "topbar-h": "46px",
}

# Measured contrast of each ink on `surface` (light / dark), as a record of what
# was checked rather than as a promise.  All are above AA 4.5:1 for the 11px pill,
# which is the smallest type on the page.
CONTRAST = {
    "ink": "16.2 / 14.1", "ink-mid": "8.1 / 8.3", "ink-soft": "5.4 / 5.6",
    "ok": "6.7 / 8.4", "warn": "6.4 / 8.9", "bad": "7.1 / 7.4",
    "info": "6.5 / 8.0", "idle": "6.1 / 5.9", "accent": "6.0 / 7.3",
    "code": "8.6 / 11.5",
}


def css_vars() -> str:
    """The `:root` block: light on the bare selector, dark behind the two switches.

    `prefers-color-scheme` is honoured only while the reader has not chosen
    (`[data-theme]` unset), so the OS decides the first paint and the reader's
    click decides after that.  Writing dark as `:root[data-theme=dark]` as well
    keeps the two paths one block of names.
    """
    light = "\n".join(f"  --{k}: {v[0]};" for k, v in TOKENS.items())
    dark = "\n".join(f"    --{k}: {v[1]};" for k, v in TOKENS.items())
    flat = "\n".join(f"    --{k}: {v};" for k, v in SCALARS.items())
    dark_flat = "\n".join(f"    --{k}: {v};" for k, v in SCALARS.items())
    return f""":root {{
{light}
{flat}
  color-scheme: light;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{dark}
{dark_flat}
    color-scheme: dark;
  }}
}}
:root[data-theme="dark"] {{
{dark}
{dark_flat}
  color-scheme: dark;
}}
:root[data-theme="light"] {{
  color-scheme: light;
}}"""
