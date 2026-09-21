# SPDX-License-Identifier: LGPL-2.1-or-later
"""One module per page: the five routes whose body is a page and not a read.

`builds` is `/` (the merged table, its tabs and the correspondence), `jobs` is
`/jobs`, `runs` is `/runs`, `worker` is `/worker` and `analysis` is `/analysis`.
Each holds the `Gui` methods that draw its page and the module-level helpers only
that page calls; anything two pages share lives in the modules above this one
(`widgets`, `cells`, `tables`, `values`, `urls`, `fields`, `sorting`, `driftview`,
`trendview`), which is what keeps a page module from having to import another.

`/local/<build_id>` has no module of its own, and does not want one: it is a build's
own page and not a station, so it is drawn where its rows live - `builds`'s
`_correspondence`.
"""
