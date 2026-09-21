# SPDX-License-Identifier: LGPL-2.1-or-later
"""A frontend prototype of the kernelci-riscv console: the pages, without the back end.

Nothing in this package runs a command, reads a record or opens a socket to the API.
`data.py` holds the rows - copied from what the running console on 8082 printed - and
`pages.py` draws them.  The point of the package is to be looked at and argued with
before any of it is wired to the real readers.

    python3 -m proto.serve            then open http://127.0.0.1:8084

The seam is `data.py`: `proto/serve.py` calls `data.data()` once per request and
hands the dict to the page.  Replacing that call with the real readers is the whole
of the eventual change, which is why no page module may import `data` itself.
"""
