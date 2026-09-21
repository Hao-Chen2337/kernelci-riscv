# SPDX-License-Identifier: LGPL-2.1-or-later
"""The catalogue, split into parts: one module per group of `# ---` banners.

`lib/i18n/__init__.py` merges these parts **in the order it imports them**, and that
order is the source order of the one file this package was split from, and it is
what `KEYS` is built from, so
reordering the parts reorders every list `--check` prints.  No key lives in two
parts.

The split axis is the banners the catalogue already carried: they name the page a
block of words belongs to, and a part is a run of adjacent blocks.  Splitting by
key prefix would be the other axis, and the wrong one - one page's vocabulary spans
many prefixes (`nav.`, `page.`, `col.`, `count.`), so prefix-splitting tears a
page's words across six modules.

    shell      navigation, the counts strip, `/`, `/remote`
    local      `/local` and `/local/<build_id>`
    work       `/pull`, `/jobs`, `/runs`, `/worker`
    analysis   `/analysis`: drift, the timeline, its columns and its charts
    record     the record's own words: states, buttons, the live panel, refusals
    words      the axes strip, "the API did not answer", and value -> label maps

A new sentence is one edit in one part.
"""
