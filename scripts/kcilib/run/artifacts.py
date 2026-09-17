#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Artifact transfer shared by the pull-lab worker and the fetch-and-run script.

Two rules this module exists to keep in one place, because both were bugs once:

* a partial transfer is never lost and never trusted blindly.  The bytes land in
  <dest>.part beside a sidecar naming the URL they came from, so a later attempt
  - even a later run of the same command - resumes with a Range request instead
  of downloading a 144MB rootfs from zero again;
* a file is only reused once it has been PROVEN complete.  os.path.exists()
  adopted an Image that an interrupted run had left truncated and handed it to
  tuxrun as a kernel; a .part whose sidecar already records its own size used to
  be resumed from that total, which the server answered with 416 "Requested
  Range Not Satisfiable" until somebody deleted the file by hand.

Nothing here swallows a failure: a transfer that cannot be shown complete raises,
or keeps its partial data on purpose.
"""

import json
import os
import re
import time

import requests

# 4 GiB per download; rootfs tarballs fit easily.
MAX_DOWNLOAD_SIZE = 4 << 30

# A KernelCI artifact URL names the build it belongs to in the first path
# segment after the host: /<job-name>-<build-id>/<file>, where the id is a
# 24-character kcidb node id (kbuild-gcc-14-riscv-6aa3689720239ade90209d50).
# A pull-lab job definition carries no build id of its own - only artifact
# URLs - so this is where the worker's ledger takes "which build did this run
# test" from, instead of inventing a parallel identity.
BUILD_ID_RE = re.compile(r"/([^/?\s]+?)-([0-9a-f]{24})(?:[/?]|$)")

# Read in this order so the answer never depends on dict order: the kernel
# first (the artifact that decides what was booted), then the test and module
# tarballs, then the config.
BUILD_ID_ARTIFACT_KEYS = (
    "kernel", "kselftest_tar_xz", "kselftest", "modules", "_config",
)


def build_id_from_artifacts(artifacts):
    """The kbuild node id a job definition's artifacts came from, or "".

    Returns "" when no artifact URL names a build: a job whose kernel is
    served from a local mirror (the local stack seeds exactly that) has no id
    to take, and a caller must decide what to file the run under rather than
    getting a fabricated one from here.
    """
    for key in BUILD_ID_ARTIFACT_KEYS:
        url = (artifacts or {}).get(key) or ""
        match = BUILD_ID_RE.search(str(url))
        if match:
            return match.group(2)
    return ""
# Per-read gap, not a total budget: artifact hosts (storage.kernelci.org,
# files.kernelci.org) go quiet mid-transfer often enough that the old 300s
# meant "hang for five minutes, then retry".  60s of silence is a stalled
# connection; a slow-but-moving download is unaffected.
DOWNLOAD_TIMEOUT = 60


def _resume_offset(part_path, meta_path, url):
    """Bytes already on disk for *url* from an earlier attempt (0 = start over).

    production storage truncates big transfers routinely (a 144MB rootfs
    arriving as 1.3MB is ordinary), and restarting from zero each time means a
    flaky link never finishes.  The partial file is only trusted when its
    sidecar says it belongs to *url* and does not already exceed the expected
    size - otherwise a stale partial would be prepended to good data."""
    try:
        with open(meta_path) as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return 0
    if not isinstance(meta, dict) or meta.get("url") != url:
        return 0
    try:
        size = os.path.getsize(part_path)
    except OSError:
        return 0
    total = meta.get("total")
    if isinstance(total, int) and size > total:
        return 0
    return size


def _write_resume_meta(meta_path, url, total):
    tmp_path = f"{meta_path}.tmp"
    with open(tmp_path, "w") as handle:
        json.dump({"url": url, "total": total}, handle)
    os.replace(tmp_path, meta_path)


def publish_complete_part(path, url=None, max_size=MAX_DOWNLOAD_SIZE):
    """Publish the .part at *path* when its sidecar proves it complete.

    Returns the number of bytes published, or 0 when *path* is not provably
    complete (still short, or its sidecar missing/corrupt).  `path` is the
    `<dest>.part` file: the finished name and the sidecar are derived from it,
    exactly as download() writes them.

    A crash between the last byte and `os.replace` leaves the full file under
    `<dest>.part` beside a sidecar recording that exact size.  The old code
    resumed from that offset instead of publishing it, so every attempt asked
    for `bytes=<total>-` and the server answered 416 "Requested Range Not
    Satisfiable" three times before raising: that artifact stayed
    undownloadable, and every job needing it reported Infrastructure, until
    somebody deleted the `.part` by hand (#7).

    Only a sidecar that names *url* and a size that is exactly the recorded
    total makes a partial publishable - a short file is a normal resume and a
    long one is not trustworthy at all.  Without *url* there is nothing to
    compare the sidecar against, so a caller that knows the URL passes it."""
    part_path = path
    # The finished name and the sidecar are derived from the .part path exactly
    # as download() builds them, so a caller only ever has to name the file.
    dest = path.removesuffix(".part")
    meta_path = f"{part_path}.json"
    try:
        with open(meta_path) as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return 0
    if not isinstance(meta, dict):
        return 0
    if url is not None and meta.get("url") != url:
        return 0
    total = meta.get("total")
    if not isinstance(total, int) or total <= 0 or total > max_size:
        return 0
    try:
        if os.path.getsize(part_path) != total:
            return 0
        os.replace(part_path, dest)
        if os.path.exists(meta_path):
            os.unlink(meta_path)
    except OSError:
        return 0
    return total


def _discard_partial(part_path, meta_path):
    """Drop a partial transfer whose bytes cannot be trusted (a refused range).

    Appending to it would hand the caller a file that is silently corrupt, so
    the transfer restarts from zero instead of risking that."""
    for path in (part_path, meta_path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _content_range_total(response):
    """Total length from a `Content-Range` header, or None.

    Both the 206 body (`bytes 100-999/1000`) and the 416 error form
    (`bytes */1000`) carry it, so the parser is shared."""
    content_range = response.headers.get("Content-Range")
    if not content_range or "/" not in content_range:
        return None
    try:
        return int(content_range.rsplit("/", 1)[1])
    except ValueError:
        return None


def download(url, dest, max_size=MAX_DOWNLOAD_SIZE):
    """Stream *url* to *dest*, verifying size and resuming partial transfers.

    The bytes land in `<dest>.part` and are only renamed into place once the
    full length has arrived, so *dest* is never a half file.  A truncated or
    stalled attempt keeps its partial data (with a sidecar recording which URL
    it belongs to), and the next attempt - even a later run of the same
    command - asks the server for the remainder with a Range request."""
    print(f"Downloading {url}")
    last_error = None
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part_path = f"{dest}.part"
    meta_path = f"{dest}.part.json"
    # A .part that an earlier run left complete (crash between the last write
    # and the rename) is published here, before any range request is built:
    # resuming from its own total is what produced the permanent 416 (#7).
    completed = publish_complete_part(part_path, url=url, max_size=max_size)
    if completed:
        print(f"           -> {dest} ({completed} bytes, completed by an "
              "earlier attempt)")
        return
    for attempt in range(3):
        try:
            offset = _resume_offset(part_path, meta_path, url)
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            if offset:
                print(f"  resuming at {offset} bytes")
            with requests.get(
                url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                allow_redirects=False, headers=headers
            ) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    raise requests.exceptions.RequestException(
                        f"refusing redirect for {url}"
                    )
                if offset and response.status_code == 200:
                    # Server ignored the Range header: start from scratch
                    # rather than appending to a file it knows nothing about.
                    print("  server ignored the Range request; restarting")
                    offset = 0
                    headers = {}
                elif offset and response.status_code == 416:
                    # The server refuses bytes=<offset>-: the partial file is
                    # not what its sidecar claims, or the artifact changed
                    # under us.  Trust the server's own total - when it says
                    # the offset IS the whole file, the transfer was complete
                    # all along; otherwise the stored bytes are unusable, so
                    # drop them and restart from zero.  This is the state that
                    # used to raise after three 416s and wedge the artifact
                    # for good (#7).
                    refused_total = _content_range_total(response)
                    if refused_total == offset:
                        os.replace(part_path, dest)
                        if os.path.exists(meta_path):
                            os.unlink(meta_path)
                        print(f"           -> {dest} ({offset} bytes, the "
                              "server confirmed the partial file was complete)")
                        return
                    print("  server rejected the resume range (416); "
                          "discarding the partial file and restarting")
                    _discard_partial(part_path, meta_path)
                    continue
                elif offset and response.status_code != 206:
                    raise requests.exceptions.RequestException(
                        f"unexpected status {response.status_code} for a "
                        f"resumed download of {url}"
                    )
                response.raise_for_status()
                total = _content_range_total(response)
                if total is None:
                    length = response.headers.get("Content-Length")
                    try:
                        total = int(length) + offset if length else None
                    except ValueError:
                        total = None
                if total is not None and total > max_size:
                    raise OSError(f"Download too large {url}: {total} > {max_size}")
                size = offset
                try:
                    with open(part_path, "ab" if offset else "wb") as handle:
                        for chunk in response.iter_content(chunk_size=1 << 20):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            size += len(chunk)
                            if size > max_size:
                                raise OSError(
                                    f"Download too large {url}: > {max_size}")
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    # Keep what arrived: the next attempt resumes from here.
                    _write_resume_meta(meta_path, url, total)
                    raise
            _write_resume_meta(meta_path, url, total)
            if total is not None and size != total:
                raise OSError(f"Truncated download {url}: {size}/{total} bytes")
            os.replace(part_path, dest)
            if os.path.exists(meta_path):
                os.unlink(meta_path)
            print(f"           -> {dest} ({size} bytes)")
            return
        except (requests.exceptions.RequestException, OSError) as error:
            last_error = error
            if attempt < 2:
                print(f"  download attempt {attempt + 1}/3 failed: {error}; retrying")
                time.sleep(2 * (attempt + 1))
    raise last_error


def gzip_isize(path):
    """Uncompressed size from a gzip member's 4-byte trailer, or None.

    A complete *download* is not proof of a complete *gunzip*: the kernel is
    decompressed into its final name, so a run killed mid-gunzip leaves a
    truncated Image that still exists and is still non-empty.  The trailer is
    the only size a finished .gz carries, and reading 4 bytes costs nothing."""
    try:
        with open(path, "rb") as handle:
            handle.seek(-4, os.SEEK_END)
            return int.from_bytes(handle.read(4), "little")
    except (OSError, ValueError):
        return None


def looks_complete(dest):
    """True when *dest* can be a complete decompression of dest + ".gz".

    Only consulted for a file with NO manifest record, i.e. the one case where
    a cache hit would otherwise adopt a file on trust (#13)."""
    gz = dest + ".gz"
    if not os.path.exists(gz):
        return True
    isize = gzip_isize(gz)
    if not isize:
        return True
    return os.path.getsize(dest) == isize
