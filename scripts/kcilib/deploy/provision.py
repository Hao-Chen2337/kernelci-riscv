# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Publish the kernel this deployment serves, and record which build it is.

`./run.sh provision` is this module and nothing else: it downloads the newest
usable production kbuild's kernel Image into work/env/, publishes it as
work/serve/Image (what the local stack's seed hands to its jobs) and writes
work/env/build.env, which stack --seed reads so the seeded nodes name the same
kbuild (modprobe matches by kernel release).

It prepares no guest rootfs: a run bakes the rootfs it needs from the URL the
job definition carries and keeps the result in the bake cache
(kcilib.run.bake).  Until 2026-09-19 this module also baked a fixed
work/env/rootfs-kvm.ext4 of its own with a manifest of its own; the bake cache
made that redundant, and it was the last reason this command needed bake logic
at all.
"""

import os
import shlex
import sys

from kcilib.core import layout, policy
from kcilib.model import Builds
from kcilib.model.nodes import newest_kbuild_node, revision_of
from kcilib.run import delivery

# What this deployment publishes and records.  Both paths are work/'s, which
# kcilib.core.layout owns; the serve path is the one stack --seed hands to jobs.
DEFAULT_IMAGE = os.path.join(delivery.WORK_ENV, "Image")
DEFAULT_SERVE_IMAGE = os.path.join(delivery.WORK_SERVE, "Image")


def provision_only(args):
    """Prepare work/serve/Image + work/env/build.env; returns the exit status."""
    kernel_url = args.kernel_url or os.environ.get("KCI_KERNEL_URL")
    modules_url = args.modules_url or os.environ.get("KCI_MODULES_URL")
    revision = {}
    if not kernel_url:
        # No pinned build hash: take kernel + modules from the newest passing
        # build.  Both come from the SAME node on purpose: modprobe matches
        # /lib/modules by kernel release, so mixing builds makes every kvm test
        # skip with "Cannot open /dev/kvm".
        node = newest_kbuild_node(args.job, args.api_url)
        if not node.artifact("kernel"):
            sys.exit(f"newest {args.job} node {node.node_id} carries no "
                     f"kernel artifact")
        card = Builds().add(node)
        kernel_url = card.kernel
        modules_url = modules_url or card.modules
        revision = revision_of(node)
        print(f"newest {args.job}: {revision.get('describe', '?')} "
              f"({(revision.get('commit') or '')[:12]}) id={node.node_id}")
    else:
        # A pinned kernel URL has no node to read a revision from: the caller
        # states it, or the seed has nothing to label its nodes with.
        revision = {
            "commit": os.environ.get("KCI_BUILD_COMMIT", ""),
            "describe": os.environ.get("KCI_BUILD_DESCRIBE", ""),
            "tree": os.environ.get("KCI_BUILD_TREE", ""),
            "branch": os.environ.get("KCI_BUILD_BRANCH", ""),
            "url": os.environ.get("KCI_BUILD_URL", ""),
        }
    delivery.check_consistency(kernel_url, modules_url)
    # The rootfs this lab boots its guests from is the lab's own image, not a
    # build artifact: the one URL policy owns.  Recorded in build.env because
    # that file is this deployment's description of what it serves; nothing
    # prunes or bakes it any more - a run bakes its rootfs from this URL on
    # demand and keeps the result in the bake cache.
    rootfs_url = policy.POLICY.rootfs_url
    manifest = delivery.load_manifest()
    delivery.provision_kernel(kernel_url, DEFAULT_IMAGE, DEFAULT_SERVE_IMAGE,
                              manifest)
    delivery.save_manifest(manifest)
    # One source of truth for "which kbuild these artifacts came from" -
    # including the revision: run-local-stack.sh seeds jobs from this file, so the
    # served kernel, the baked modules and the job definition cannot drift apart.
    build_dir = kernel_url.rsplit("/", 1)[0]
    # The path is kcilib.core.layout's (it owns what lives in work/env).
    build_env = os.fspath(layout.deployment_env())
    version = revision.get("version")
    if not isinstance(version, dict):
        # Either {"version": N, "patchlevel": N} or a bare int (N10): .get() on
        # the int raised AttributeError and lost the whole file.
        version = {"version": version} if isinstance(version, int) else {}
    tags = " ".join(revision.get("commit_tags") or [])

    def env_line(key, value):
        """KEY=<shell-quoted value>.

        build.env is *sourced* by run-local-stack.sh, so a raw value breaks the
        deployment: a space-joined tag list ran `v7.0: command not found`, and a
        quote or backslash corrupted the shell state (N2).
        """
        return f"{key}={shlex.quote('' if value is None else str(value))}\n"

    with open(build_env, "w") as handle:
        handle.write("# Written by ./run.sh provision - do not edit by hand.\n")
        handle.write("# The kbuild every work/ artifact below comes from;\n")
        handle.write("# run-local-stack.sh seeds jobs from these URLs and\n")
        handle.write("# labels the nodes it creates with this revision.\n")
        handle.write("# Values are shell-quoted: this file is sourced, not parsed.\n")
        handle.write(env_line("KCI_BUILD_DIR", build_dir))
        handle.write(env_line("KCI_KERNEL_URL", kernel_url))
        if modules_url:
            handle.write(env_line("KCI_MODULES_URL", modules_url))
        handle.write(env_line("KCI_ROOTFS_URL", rootfs_url))
        handle.write(env_line("KCI_BUILD_COMMIT", revision.get("commit") or ""))
        handle.write(env_line("KCI_BUILD_DESCRIBE", revision.get("describe") or ""))
        handle.write(env_line("KCI_BUILD_TREE", revision.get("tree") or ""))
        handle.write(env_line("KCI_BUILD_BRANCH", revision.get("branch") or ""))
        handle.write(env_line("KCI_BUILD_URL", revision.get("url") or ""))
        handle.write(env_line("KCI_BUILD_VERSION", version.get("version") or ""))
        handle.write(env_line("KCI_BUILD_PATCHLEVEL", version.get("patchlevel") or ""))
        handle.write(env_line("KCI_BUILD_TAGS", tags))
    print(f"build pinned at {build_env}: {build_dir}")
    if revision.get("commit"):
        print(f"build revision: {revision.get('describe') or '?'} "
              f"({revision['commit'][:12]})")
    else:
        print("  !! build revision unknown (the kernel URL came from outside "
              "production): the seed will fall back to its pinned placeholder "
              "unless KCI_BUILD_COMMIT/KCI_BUILD_DESCRIBE are set")
    print("provision complete")
    return 0


# The judgement itself is kcilib.run.judge's, reached through the run this entry
# point hands to kci: judge_run() over the console the run archived, so the
# printed verdict, the record and the process status are one verdict.


