# SPDX-License-Identifier: LGPL-2.1-or-later
"""What this deployment *serves*: `var/serve/Image`, and the record naming it.

`publish_local()` files a hand-placed kernel as a build; `provision()` fetches
the newest passing production one; `served()` is the one reader of the record
both wrote, and it exists because the table cannot answer "which build is
`var/serve/Image`" - a card says a kernel exists, not that this deployment
serves it.
"""

import json
import os

from .. import atomic, errors, layout, tests
from ..kbuild import Kbuild, _stamp, build_id_of
from .model import CHUNK, SERVED_NAME, Build
from .table import Builds


def publish_local(run):
    """Publish `var/serve/Image` as the build this deployment serves; nothing is run.

    The URL it is recorded under is `--parameter kernel_url=`, else
    `$KCI_KERNEL_URL`, else the file itself; the identity is `--parameter
    tree|branch|commit|describe|defconfig=`, else the `KCI_BUILD_*` environment.
    Returns the exit status.
    """
    image = os.path.abspath(layout.serve("Image"))
    if not os.path.isfile(image):
        raise errors.ArtifactError(f"nothing to publish: {image} is not there")
    url = run.params.get("kernel_url") or os.environ.get("KCI_KERNEL_URL") or f"file://{image}"
    commit = _fact("commit", run)
    kbuild = Kbuild(
        build_id=_published_id(url, commit),
        tree=_fact("tree", run),
        branch=_fact("branch", run),
        arch="riscv64",
        defconfig=_fact("defconfig", run),
        created=_stamp(),
        artifacts={"kernel": url},
        revision={"commit": commit, "describe": _fact("describe", run)},
    )
    table = Builds.load()
    table.merge((kbuild,))
    table.save()
    _remember_served(kbuild, url)
    print(f"published {kbuild.build_id}: {url}  ({layout.index()})")
    return errors.EXIT_PASS


def served() -> dict:
    """The build this deployment serves, as `publish_local()` recorded it; `{}` if none.

    Two readers need this and neither can get it from the table: retention must
    never delete the build `var/serve/Image` is, and the local stack seeds its
    jobs from the build it serves.  The card in `var/state/builds.json` cannot
    answer either question - it says a kernel exists, not that *this* deployment
    serves it, and a card survives a re-provision.  A file that is missing or
    unreadable answers `{}`: "no build published yet" is a state, not an error.
    """
    try:
        with open(layout.state(SERVED_NAME), encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def provision(api, tree="riscv", branch=None) -> "Kbuild":
    """Fetch the newest **passing** production build's kernel and serve it here.

    This is the act `python3 provision.py` performs, and it is the old tree's
    `kcilib/deploy/provision.py` with one reader instead of three: the build is
    chosen from the API (`Kbuilds.getnew(..., passing=True)` - done and passed, the
    window widening until one exists), its kernel is materialized by the same
    `make()` every other fetch uses, `var/serve/Image` is a symlink to it rather
    than a second 27 MB copy (the old `work/serve/Image -> ../env/Image` did the
    same), and `_remember_served()` writes the record the stack's seed reads.

    The *kernel release* is what a seeded stack's `modprobe` matches, so the
    kernel and the modules the record names must come from the same build - both
    are read off this one card, never mixed.

    Returns the card it published.
    """
    from .. import kbuild as kbuild_mod
    card = kbuild_mod.Kbuilds(api).getnew(tree, branch, passing=True)
    build = Build(card).make(("kernel",))
    _link_served(build)
    Builds.load().remember(build)
    _remember_served(card, card.artifact("kernel"))
    return card


def _link_served(build) -> str:
    """Point `var/serve/Image` at `build`'s local kernel; return the link's path.

    A symlink, not a copy: the image the stack serves *is* the build's artifact,
    and a copy is one more 27 MB that can disagree with the bytes next to it.  It
    is written relatively (`../downloads/<id>/Image`) so the workspace survives
    being copied or mounted somewhere else.

    **What was at the path is never deleted silently.**  Our own link goes (it is
    a previous provisioning, and the record of it is rewritten in the same call);
    a *regular file* is either replaced - when its bytes are the kernel we are
    about to serve anyway, so nothing is lost - or moved aside to
    `Image.kept-<stamp>` with a line saying so.  The old tree solved this by
    refusing to touch an existing non-empty image at all (`delivery._ensure_symlink`
    returned early), which kept a hand-placed kernel safe but also meant a
    re-provision served the old bytes while the record named the new build - a lie
    in the one file the stack seeds from.  Moving it aside keeps both promises.
    """
    source = build._local("kernel")
    if not os.path.isfile(source):
        raise errors.ArtifactError(
            f"cannot serve {build.build_id}: {source} is not there")
    link = os.path.abspath(layout.serve("Image"))
    os.makedirs(os.path.dirname(link), exist_ok=True)
    target = os.path.relpath(source, os.path.dirname(link))
    if os.path.islink(link):
        os.unlink(link)
    elif os.path.isfile(link):
        if _same_bytes(link, source):
            print(f"{link} was already {build.build_id}'s kernel; replaced by the link")
            os.unlink(link)
        else:
            kept = f"{link}.kept-{_stamp().replace(':', '')}"
            os.replace(link, kept)
            print(f"! {link} held an image this deployment never recorded "
                  f"({os.path.getsize(kept)} bytes); kept it at {kept}")
    try:
        os.symlink(target, link)
    except OSError as problem:
        raise errors.ArtifactError(f"cannot publish {link}: {problem}") from problem
    return link


def _same_bytes(first, second):
    """Are two files the same bytes?  Read in chunks: an Image is 27 MB."""
    if os.path.getsize(first) != os.path.getsize(second):
        return False
    with open(first, "rb") as left, open(second, "rb") as right:
        while True:
            one, two = left.read(CHUNK), right.read(CHUNK)
            if one != two:
                return False
            if not one:
                return True


def _remember_served(kbuild, url):
    """Write `var/state/served.json` atomically - the act, not just its side effect.

    The old tree recorded the same facts as shell variables in
    `work/env/build.env`, which `run-local-stack.sh` *sourced*; this is that file's
    content as data, written by the same command that publishes the image, so the
    facts and the bytes cannot disagree.  Every key the seed read is here, under
    the name it means rather than the name a shell needed:

        KCI_BUILD_DIR      -> build_dir      (the artifact directory all of them
                                              live under: modules, kselftest, .config)
        KCI_KERNEL_URL     -> kernel_url     KCI_MODULES_URL -> modules
        KCI_ROOTFS_URL     -> rootfs         (the lab's own guest disk, not a build's)
        KCI_BUILD_COMMIT   -> commit         KCI_BUILD_DESCRIBE -> describe
        KCI_BUILD_TREE     -> tree           KCI_BUILD_BRANCH -> branch
        KCI_BUILD_URL      -> tree_url       KCI_BUILD_VERSION/PATCHLEVEL/TAGS -> version
    """
    revision = kbuild.revision or {}
    version = revision.get("version")
    if not isinstance(version, dict):
        # `{"version": N, "patchlevel": N}` or a bare int: `.get()` on the int
        # raised AttributeError and lost the whole file (the old tree's N10).
        version = {"version": version} if isinstance(version, int) else {}
    record = {
        "build_id": kbuild.build_id,
        "node_id": kbuild.node_id,
        "kernel_url": url,
        "build_dir": url.rsplit("/", 1)[0],
        "modules": kbuild.artifact("modules"),
        "kselftest": kbuild.artifact("kselftest_tar_xz") or kbuild.artifact("kselftest"),
        "config": kbuild.artifact("_config"),
        "rootfs": tests.ROOTFS_URL,
        "image": os.path.abspath(layout.serve("Image")),
        "tree": kbuild.tree, "branch": kbuild.branch, "arch": kbuild.arch,
        "defconfig": kbuild.defconfig, "compiler": kbuild.compiler,
        "created": kbuild.created, "state": kbuild.state, "result": kbuild.result,
        "commit": revision.get("commit", ""), "describe": revision.get("describe", ""),
        "tree_url": revision.get("url", ""),
        "version": version.get("version") or "", "patchlevel": version.get("patchlevel") or "",
        "tags": list(revision.get("commit_tags") or []),
        "at": _stamp(),
    }
    path = layout.state(SERVED_NAME)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic.write_json(path, record, indent=1, sort_keys=True)
    except OSError as problem:
        # Loud, and fatal: a published image the deployment cannot name is one
        # retention may prune and the stack cannot seed from.
        raise errors.ArtifactError(
            f"published {kbuild.build_id} but could not record it in {path}: {problem}") from problem


def _fact(name, run):
    """One build fact: `--parameter <name>=`, else `$KCI_BUILD_<NAME>`, else ''."""
    return run.params.get(name) or os.environ.get(f"KCI_BUILD_{name.upper()}", "")


def _published_id(url, commit):
    """The id a local kernel is filed under: the URL's, else the commit's, else a refusal."""
    found = build_id_of({"kernel": url})
    if found:
        return found
    if commit:
        return commit[:12]
    raise errors.ConfigError("a published kernel needs an id: a URL that carries one, or a commit")
