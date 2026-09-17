"""The resumable transfer: a complete .part, a 416, and a real restart."""
import json
import os
import tempfile

from kcilib.run import artifacts

from .support import _Response, check, no_sleep, stub_requests


def test_download_complete_part_and_416():
    """#7: a complete .part is published, a bogus one is not trusted."""
    with tempfile.TemporaryDirectory() as tmp:
        url = "http://storage/Image"
        dest = os.path.join(tmp, "Image")
        part = f"{dest}.part"
        meta = f"{dest}.part.json"

        # (a) full-size .part + matching sidecar: publish, no HTTP request
        with open(part, "wb") as handle:
            handle.write(b"x" * 1000)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        with stub_requests(artifacts):   # any GET raises AssertionError
            artifacts.download(url, dest, max_size=1 << 20)
        check(os.path.getsize(dest) == 1000, "complete .part was not published")
        check(not os.path.exists(part), ".part left behind after publishing")
        check(not os.path.exists(meta), "sidecar left behind after publishing")

        # (b) a 416 whose Content-Range total equals the offset: the server
        # itself confirms the partial was the whole artifact
        os.unlink(dest)
        with open(part, "wb") as handle:
            handle.write(b"y" * 500)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        ranges = []

        def get_416(_url, **kwargs):
            ranges.append(kwargs.get("headers", {}).get("Range"))
            return _Response(416, headers={"Content-Range": "bytes */500"})

        with no_sleep(), stub_requests(artifacts, get=get_416):
            artifacts.download(url, dest, max_size=1 << 20)
        check(os.path.getsize(dest) == 500, "a 416 = complete was not published")
        check(ranges == ["bytes=500-"], ranges)

        # (c) a mismatched 416 drops the partial, so the transfer restarts
        # from zero instead of wedging the artifact
        os.unlink(dest)
        with open(part, "wb") as handle:
            handle.write(b"z" * 10)
        with open(meta, "w") as handle:
            json.dump({"url": url, "total": 1000}, handle)
        seen = []

        def get_restart(_url, **kwargs):
            seen.append(kwargs.get("headers", {}).get("Range"))
            if len(seen) == 1:
                return _Response(416, headers={"Content-Range": "bytes */1000"})
            return _Response(200, headers={"Content-Length": "1000"},
                             chunks=[b"a" * 1000])

        with no_sleep(), stub_requests(artifacts, get=get_restart):
            artifacts.download(url, dest, max_size=1 << 20)
        check(seen[0] == "bytes=10-", seen)
        check(seen[1] is None, f"the restart still resumed: {seen}")
        check(os.path.getsize(dest) == 1000, "restart did not fetch the file")

        # a sidecar for another URL must never be used to publish
        with open(part, "wb") as handle:
            handle.write(b"w" * 20)
        with open(meta, "w") as handle:
            json.dump({"url": "http://other/Image", "total": 20}, handle)
        check(artifacts.publish_complete_part(
                  part, url=url, max_size=1 << 20) == 0,
              "a sidecar naming another URL must not publish the .part")
    print("test_download_complete_part_and_416 OK")
