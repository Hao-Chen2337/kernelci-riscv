# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The one KernelCI API client. Every script that reads nodes goes through here.

Why this module exists: the same three functions had been written out five
times, roughly verbatim, in scripts that all talk to the same API -

    scripts/fetch-and-run-latest.py   api_get / pick_newest
    scripts/tools/config_drift.py           api_get / fetch_all_nodes / list_nodes
    scripts/tools/regression_tracker.py     api_get / fetch_all_nodes / list_nodes
    scripts/kcilib/run/poll.py            fetch_nodes / retrieve_job_definition
    scripts/kcilib/table/buildref.py        fetch_nodes

- each with its own idea of the /latest prefix, its own pagination loop (or no
pagination at all), and its own retry story.  An API change then has to be made
in five places, and the four that were forgotten fail silently: a missing page
looks exactly like "the build does not exist".

What is deliberately NOT here: kernelci-core's own client.  It is the right
client for the *services* that already depend on kernelci-core (the callback,
the scheduler), but these scripts are standalone on purpose - ./run.sh fetch is
documented as needing "no stack, no node, no token", and requiring a cloned
kernelci-core with a kernelci.toml would take that away.  What we do owe the
upstream client is its CONVENTIONS: the /latest prefix, {items,total,offset}
pagination, and JSON-or-error.
"""

import time

import requests

# The public API, and the default a deployment overrides with KCI_API_URL.
PRODUCTION_API = "https://api.kernelci.org"
LOCAL_API = "http://127.0.0.1:8001"
REQUEST_TIMEOUT = 60
# /nodes pages at this size when the caller does not say.  200 is what the
# scripts that already paged used, and what the API serves happily.
PAGE_LIMIT = 200


class APIError(RuntimeError):
    """The API answered, but not with something usable."""


class KernelCI:
    """A read-mostly client for one KernelCI API.

    Only what these scripts actually need: fetch nodes (one page or all),
    one node, an event page, and a job definition.  Writes (creating nodes)
    are done by the scripts that own that decision, through :meth:`post`,
    so an accidental write is never one method call away from a read.
    """

    def __init__(self, base_url=None, token=None, timeout=REQUEST_TIMEOUT,
                 retries=3):
        self.base_url = (base_url or LOCAL_API).rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()

    @property
    def latest(self):
        """The /latest base: KernelCI serves everything under it, and the dev
        API accepts both forms, so the canonical one is always used."""
        if self.base_url.endswith("/latest"):
            return self.base_url
        return f"{self.base_url}/latest"

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get(self, path, params=None, retries=None):
        """GET one path and return the parsed JSON object.

        Retries a connection error (the local API drops idle ones) and raises
        requests' own exceptions otherwise, so callers that already catch
        requests.exceptions.RequestException - kcilib.run.poll does - keep working.
        """
        url = path if path.startswith("http") else f"{self.latest}{path}"
        attempts = self.retries if retries is None else retries
        last = None
        for attempt in range(max(1, attempts)):
            try:
                response = self.session.get(url, params=params,
                                            headers=self.headers(),
                                            timeout=self.timeout,
                                            allow_redirects=False)
                self._refuse_redirect(response, url)
                response.raise_for_status()
                return self._json(response, url)
            except requests.exceptions.ConnectionError as error:
                last = error
                if attempt + 1 < attempts:
                    time.sleep(attempt + 1)
        raise last

    def post(self, path, payload, token=None):
        """POST a JSON body (node creation, for the scripts that own it)."""
        url = path if path.startswith("http") else f"{self.latest}{path}"
        headers = {"Authorization": f"Bearer {token}"} if token else self.headers()
        response = self.session.post(url, json=payload, headers=headers,
                                     timeout=self.timeout,
                                     allow_redirects=False)
        self._refuse_redirect(response, url)
        response.raise_for_status()
        return self._json(response, url)

    @staticmethod
    def _refuse_redirect(response, url):
        """A 3xx is never the answer: it means something else is answering.

        Only job_definition() used to check this, so a proxy that replied "302 +
        a perfectly valid JSON body" was accepted as data by every other reader -
        and 302+HTML merely looked like a JSON error, which hid the difference.
        Asking not to follow redirects (allow_redirects=False) is not the same as
        noticing one arrived.
        """
        if response.is_redirect or response.is_permanent_redirect:
            raise APIError(
                f"refusing redirect for {url} (HTTP {response.status_code}); "
                "the API is not where this URL says it is")

    @staticmethod
    def _json(response, url):
        try:
            return response.json()
        except ValueError as error:
            # A proxy's HTML error page is not JSON.  This used to escape as a
            # bare ValueError and kill callers that only expect API errors.
            raise APIError(f"{url} did not return JSON: {error}") from error

    # ---- the reads these scripts actually make -------------------------

    def nodes(self, **filters):
        """One page of /nodes.  *limit* defaults to PAGE_LIMIT."""
        params = {key: value for key, value in filters.items()
                  if value is not None}
        params.setdefault("limit", PAGE_LIMIT)
        page = self.get("/nodes", params)
        if not isinstance(page, dict):
            raise APIError(f"/nodes returned {type(page).__name__}, not an object")
        return page.get("items") or []

    def all_nodes(self, **filters):
        """Every matching node, walking pages.

        /nodes returns results in creation order and truncates each response to
        the page limit, so a single request silently misses the newest nodes of
        a busy job - a missing page is indistinguishable from "no such build".
        The response carries {items,total,offset}, which is what makes walking
        it possible without guessing.
        """
        params = {key: value for key, value in filters.items()
                  if value is not None}
        params.setdefault("limit", PAGE_LIMIT)
        items, offset = [], 0
        while True:
            page = self.get("/nodes", dict(params, offset=offset))
            if not isinstance(page, dict):
                raise APIError("/nodes did not return an object")
            batch = page.get("items") or []
            items.extend(batch)
            offset += len(batch)
            total = page.get("total")
            if not batch:
                return items
            if total is not None and offset >= total:
                return items
            if total is None and len(batch) < params["limit"]:
                return items

    def node(self, node_id):
        """One node by id."""
        node = self.get(f"/node/{node_id}")
        if not isinstance(node, dict):
            raise APIError(f"/node/{node_id} did not return an object")
        return node

    def events(self, **filters):
        """One page of /events (the pull-lab queue)."""
        params = {key: value for key, value in filters.items()
                  if value is not None}
        page = self.get("/events", params)
        if not isinstance(page, dict):
            raise APIError("/events did not return an object")
        return page.get("items") or []

    def job_definition(self, url):
        """Fetch a pull-lab job definition from its (external) URL.

        Refuses a redirect: the definition URL is handed out by the scheduler
        and a redirect means something in between is answering instead.
        """
        response = self.session.get(url, timeout=self.timeout,
                                    allow_redirects=False)
        if response.is_redirect or response.is_permanent_redirect:
            raise APIError(f"refusing redirect for {url}")
        response.raise_for_status()
        job = self._json(response, url)
        if not isinstance(job, dict):
            raise APIError(f"job definition at {url} is not an object")
        return job


def client(api_url=None, token=None, **kwargs):
    """The client for *api_url* (or $KCI_API_URL, or the local default)."""
    import os
    base = api_url or os.environ.get("KCI_API_URL") or LOCAL_API
    return KernelCI(base, token=token, **kwargs)
