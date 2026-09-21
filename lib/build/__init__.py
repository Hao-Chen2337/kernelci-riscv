# SPDX-License-Identifier: LGPL-2.1-or-later
"""The local half of a build: the bytes we fetch, the guest disk we bake, the table.

`Build` is one build - a `Kbuild` plus `var/downloads/<build-id>/`; `Builds` is
the table of them, one JSON file at `layout.index()`.  The downloader here is the
only one in the tree.

One module per verb, so a reader can find the one to change: `model` is `Build`
and the vocabulary every part of this half shares, `fetch` is the ranged
download, `rootfs` is the guest disk, `publish` is what this deployment serves,
`table` is the local table.  This file is re-exports only - `lib/job.py`,
`lib/re.py`, `lib/poller.py`, `lib/retention.py`, the root entry points and the
page read the package, not its insides.

接口形状（C++，只有声明）：include/kci/local.hpp §7 Build / Builds。
"""

from .fetch import download
from .model import (
    ARTIFACTS,
    ATTEMPTS,
    CHUNK,
    DISK_SIZE,
    MAX_SIZE,
    PROVENANCE_ACTS,
    SERVED_NAME,
    TAR_SUFFIXES,
    TIMEOUT,
    WANT,
    Build,
)
from .publish import provision, publish_local, served
from .rootfs import bake_rootfs, kvm_tests
from .table import Builds

# The whole of the surface `lib/build.py` promised while it was one module: a
# caller written against it - `build.download`, `from ..build import ARTIFACTS` -
# does not have to know that it became a package, or how it is arranged inside.
__all__ = ["ARTIFACTS", "ATTEMPTS", "CHUNK", "DISK_SIZE", "MAX_SIZE", "PROVENANCE_ACTS",
           "SERVED_NAME", "TAR_SUFFIXES", "TIMEOUT", "WANT", "Build", "Builds",
           "bake_rootfs", "download", "kvm_tests", "provision", "publish_local", "served"]
