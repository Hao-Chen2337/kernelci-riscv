#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Artifact transfer shared by the pull-lab worker and the fetch-and-run script.

Two rules, both of which were bugs once: a partial transfer lands in
<dest>.part beside a sidecar naming its URL, so a later attempt resumes with a
Range request instead of starting a 144MB rootfs over; and a file is reused only
once PROVEN complete - os.path.exists() once adopted a truncated Image as a
kernel, and a .part already at its own recorded total drew 416 forever.
Nothing here swallows a failure.  Rationale: code-notes/W2c-kcilib.md.
"""

import json
import os
import re
import time

import requests

# 4 GiB per download; rootfs tarballs fit easily.
MAX_DOWNLOAD_SIZE = 4 << 30

# A KernelCI artifact URL names its build: /<job-name>-<build-id>/<file>, the id
# a 24-character kcidb node id.  A job definition carries no build id of its own,
# so this is where the ledger's "which build did this run test" comes from.
BUILD_ID_RE = re.compile(r"/([^/?\s]+?)-([0-9a-f]{24})(?:[/?]|$)")

# Fixed order, so the answer never depends on dict order: the kernel first (the
# artifact that decides what was booted), then the test and module tarballs.
BUILD_ID_ARTIFACT_KEYS = (
    "kernel", "kselftest_tar_xz", "kselftest", "modules", "_config",
)


def build_id_from_artifacts(artifacts):
    """The kbuild node id a job definition's artifacts came from, or "".

    "" when no artifact URL names a build (a locally mirrored kernel), so the
    caller decides what to file the run under instead of getting a made-up id.
    """
    for key in BUILD_ID_ARTIFACT_KEYS:
        url = (artifacts or {}).get(key) or ""
        match = BUILD_ID_RE.search(str(url))
        if match:
            return match.group(2)
    return ""
# Per-read gap, not a total budget: artifact hosts go quiet mid-transfer, so the
# old 300s meant "hang five minutes, then retry".  A slow-but-moving download is
# unaffected.
DOWNLOAD_TIMEOUT = 60


def _resume_offset(part_path, meta_path, url):
    """Bytes already on disk for *url* from an earlier attempt (0 = start over).

    Storage truncates big transfers routinely, so restarting from zero each time
    means a flaky link never finishes.  The partial is trusted only when its
    sidecar names *url* and it does not exceed the expected size - otherwise a
    stale partial would be prepended to good data."""
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

    Returns the bytes published, or 0 when *path* is not provably complete
    (short, or its sidecar missing/corrupt).  Only a sidecar that names *url*
    and a size exactly equal to the recorded total makes a partial publishable:
    a short file is a normal resume and a long one is not trustworthy.

    A crash between the last byte and os.replace leaves the full file under
    .part, and resuming from its own total asked for `bytes=<total>-` and drew
    416 "Requested Range Not Satisfiable" until the .part was deleted by hand."""
    part_path = path
    # Derived exactly as download() builds them, so a caller only names the file.
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

    Appending to it would hand the caller a silently corrupt file, so the
    transfer restarts from zero instead."""
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

    The bytes land in `<dest>.part` and are renamed into place only once the
    full length arrived, so *dest* is never a half file.  An interrupted attempt
    keeps its partial data plus a URL sidecar, and the next attempt - even a
    later run of the same command - asks for the remainder with a Range."""
    print(f"Downloading {url}")
    last_error = None
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part_path = f"{dest}.part"
    meta_path = f"{dest}.part.json"
    # Published BEFORE any range request is built: resuming from a .part's own
    # total is what produced the permanent 416.
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
                    # Range ignored: restart rather than append to a file the
                    # server knows nothing about.
                    print("  server ignored the Range request; restarting")
                    offset = 0
                    headers = {}
                elif offset and response.status_code == 416:
                    # The server refuses bytes=<offset>-: the total equals the
                    # offset means the file was complete all along; otherwise the
                    # bytes are unusable, so drop them and restart.
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

    A complete download is not proof of a complete gunzip: the kernel is
    decompressed into its final name, so a run killed mid-gunzip leaves a
    truncated Image that still exists and is still non-empty."""
    try:
        with open(path, "rb") as handle:
            handle.seek(-4, os.SEEK_END)
            return int.from_bytes(handle.read(4), "little")
    except (OSError, ValueError):
        return None


def looks_complete(dest):
    """True when *dest* can be a complete decompression of dest + ".gz".

    Only consulted for a file with no manifest record - the one case where a
    cache hit would otherwise adopt a file on trust."""
    gz = dest + ".gz"
    if not os.path.exists(gz):
        return True
    isize = gzip_isize(gz)
    if not isize:
        return True
    return os.path.getsize(dest) == isize
