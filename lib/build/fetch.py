# SPDX-License-Identifier: LGPL-2.1-or-later
"""The ranged HTTP fetch: one artifact, whole or not at all.

`download()` is the only downloader in the tree - the worker, the offline table
and a one-shot run all come through it - and every helper here exists to answer
one of its two questions: *is what is on this disk already the whole artifact?*
(`_complete`, `_remote_size`, `_remote_total`, `_content_range_total`) and *what
did the host actually give us?* (`_status_error`, `_read`, `_copy`).
"""

import os
import shutil
import time

import requests

from .. import errors
from ..kbuild import build_id_of
from .model import ATTEMPTS, CHUNK, MAX_SIZE, TIMEOUT, _Permanent


def _names_this_build(url, build_id):
    """Does `url` carry `build_id`?  The question `Build.merge()` turns on.

    `build_id_of()` reads the id out of an artifact URL and searches the keys a
    kbuild's artifacts use, so one URL is asked as `{"kernel": url}` on purpose:
    every artifact of one build is filed under the same `<name>-<build id>`
    directory, and a URL that names none of them (`/Image`, `file://…/Image`)
    cannot say which build it is.
    """
    return bool(build_id) and build_id_of({"kernel": url}) == build_id


def download(url, dest, expected=None, max_size=MAX_SIZE):
    """Fetch `url` into `dest`, resuming, and publish it only when it is whole.

    A short transfer, a refused range or a redirect is an ArtifactError, never a
    `dest` that half exists; a local path or `file://` URL is copied instead.
    """
    source = _local_source(url)
    if source:
        return _copy(source, dest, expected, max_size)
    if _complete(dest, url, expected, max_size):
        return dest
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part = f"{dest}.part"
    last = None
    for attempt in range(ATTEMPTS):
        try:
            offset = os.path.getsize(part) if os.path.isfile(part) else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            if offset:
                print(f"  resuming {os.path.basename(dest)} at {offset} bytes", flush=True)
            with requests.get(url, stream=True, headers=headers, timeout=TIMEOUT,
                              allow_redirects=False) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    raise _Permanent(f"refusing a redirect for {url}")
                if offset and response.status_code == 416:
                    # The host refuses `bytes=<offset>-`: a total equal to the
                    # offset means the file was whole all along.
                    if _content_range_total(response) == offset:
                        os.replace(part, dest)
                        print(f"  {dest} ({offset} bytes, the host confirms it)", flush=True)
                        return dest
                    _remove(part)
                    offset = 0
                    continue
                if offset and response.status_code == 200:
                    # The Range was ignored: start over rather than keep bytes the
                    # host knows nothing about.
                    offset = 0
                elif offset and response.status_code != 206:
                    raise _status_error(response.status_code, f"resuming {url}")
                if response.status_code not in (200, 206):
                    raise _status_error(response.status_code, url)
                proof = _remote_total(response, offset) or expected
                if proof is not None and proof > max_size:
                    raise _Permanent(f"{url} is {proof} bytes; refusing it")
                size = _read(response, part, offset, max_size)
            if proof is not None and size != proof:
                raise errors.ArtifactError(f"{url} is truncated: {size} of {proof} bytes")
            os.replace(part, dest)
            print(f"  {dest} ({size} bytes)", flush=True)
            return dest
        except _Permanent:
            raise
        except errors.ArtifactError as error:
            # Truncation and 5xx are worth another attempt; a 404 is not.
            last = error
        except (requests.RequestException, OSError) as error:
            # Every transport failure leaves here as one of ours: a caller must
            # not have to know what a requests exception is, and a raw one would
            # reach the entry point as a traceback with exit 1 - the one exit
            # code that means "a test failed".
            last = error
            if attempt < ATTEMPTS - 1:
                print(f"  attempt {attempt + 1}/{ATTEMPTS} failed: {error}", flush=True)
                time.sleep(2 * (attempt + 1))
    # **"The way there is broken" is not "this build cannot be fetched."**  Both used to
    # leave here as `ArtifactError`, so a caller could not tell a 404 on one artifact (a
    # fact about that build: `deadbeef1234` has no `modules` URL at all) from a proxy that
    # cannot connect (a fact about the network, and true of every build).  The transport
    # failure keeps its own type - `InfraError`, the exit-3 "we never got what we came for"
    # of `lib/errors.py` - and a caller that wants to stop pulling when the network is down
    # can finally see which one it is.  `table.py pull` is the first such caller.
    if isinstance(last, requests.RequestException):
        raise errors.InfraError(
            f"{url}: gave up after {ATTEMPTS} attempts: {last}") from last
    raise errors.ArtifactError(
        f"{url}: gave up after {ATTEMPTS} attempts: {last}") from last


def _status_error(code, what):
    """A 4xx is permanent, anything else is worth retrying."""
    message = f"unexpected status {code} for {what}"
    return _Permanent(message) if 400 <= code < 500 else errors.ArtifactError(message)


def _complete(path, url, expected=None, max_size=MAX_SIZE):
    """True when `path` is already the whole artifact: its size is the proven one."""
    if not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    known = expected if expected is not None else _remote_size(url)
    return bool(known) and size == known and size <= max_size


def _remote_size(url):
    """The size the host reports for `url`, or None - one HEAD, no body."""
    try:
        with requests.head(url, timeout=TIMEOUT, allow_redirects=False) as response:
            if response.is_redirect or response.status_code != 200:
                return None
            length = response.headers.get("Content-Length")
    except (requests.RequestException, OSError):
        return None
    return int(length) if length and length.isdigit() else None


def _remote_total(response, offset):
    """The whole artifact's size as this response reports it, or None."""
    total = _content_range_total(response)
    if total is not None:
        return total
    length = response.headers.get("Content-Length")
    return int(length) + offset if length and length.isdigit() else None


def _content_range_total(response):
    """The total in a `Content-Range` header - `bytes 1-9/10` and `bytes */10` both carry it."""
    value = response.headers.get("Content-Range") or ""
    tail = value.rsplit("/", 1)[-1]
    return int(tail) if "/" in value and tail.isdigit() else None


def _read(response, part, offset, max_size):
    """Append the body to the partial file and return the size it now has."""
    size = offset
    with open(part, "ab" if offset else "wb") as handle:
        for chunk in response.iter_content(CHUNK):
            if not chunk:
                continue
            handle.write(chunk)
            size += len(chunk)
            if size > max_size:
                raise errors.ArtifactError(f"more than {max_size} bytes arrived")
        handle.flush()
        os.fsync(handle.fileno())
    return size


def _local_source(url):
    """`url` as a local path when it names one (`file://` or a bare path), else ''."""
    if url.startswith("file://"):
        return url[len("file://"):] or ""
    if "://" in url:
        return ""
    return url if os.path.isfile(url) else ""


def _copy(source, dest, expected=None, max_size=MAX_SIZE):
    """Copy a local artifact into `dest`, proving its size the way a download does."""
    size = os.path.getsize(source)
    if size <= 0 or size > max_size or (expected is not None and expected != size):
        raise errors.ArtifactError(f"{source} is {size} bytes; refusing it")
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part = f"{dest}.part"
    shutil.copyfile(source, part)
    os.replace(part, dest)
    return dest


def _remove(path):
    """Delete `path` if it is there; a leftover temp file is never worth failing a run over."""
    try:
        os.unlink(path)
    except OSError:
        pass
