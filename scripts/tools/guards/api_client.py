"""The one API client: /latest, paging, non-JSON bodies, redirects, retries."""
import json

import requests as _real_requests

from .support import _api_client, _Response, check, no_sleep


def test_api_latest_prefix():
    """kcilib/api.py: one /latest base, whatever form the caller passes.

    The /latest prefix is what the hand-written clients disagreed about, so both
    accepted forms must address the SAME endpoint - not merely both "work".
    """
    from kcilib.api import KernelCI

    check(KernelCI("http://x:8001").latest == "http://x:8001/latest",
          "a bare base must be extended with /latest")
    check(KernelCI("http://x:8001/latest").latest == "http://x:8001/latest",
          "a base that already ends in /latest must not gain a second one")
    check(KernelCI("http://x:8001/").latest == "http://x:8001/latest",
          "a trailing slash must not produce //latest")
    check(KernelCI("http://x:8001/latest/").latest == "http://x:8001/latest",
          "a trailing slash after /latest must be trimmed, not doubled")

    urls, params = [], []

    def page(url, kwargs):
        urls.append(url)
        params.append(kwargs.get("params") or {})
        return _Response(200, json_body={"items": [], "total": 0})

    for base in ("http://x:8001", "http://x:8001/latest"):
        check(_api_client(page, base).all_nodes(limit=7) == [],
              f"the empty page was not returned for base {base}")
    check(urls == ["http://x:8001/latest/nodes"] * 2,
          f"both base forms must hit the same URL: {urls}")
    check(all(entry.get("limit") == 7 and entry.get("offset") == 0
              for entry in params), params)

    # An absolute URL is used as given: a job definition URL is external.
    forwarded = []

    def absolute(url, _kwargs):
        forwarded.append(url)
        return _Response(200, json_body={"artifacts": {}, "tests": []})

    _api_client(absolute).job_definition("http://elsewhere/job.yaml")
    check(forwarded == ["http://elsewhere/job.yaml"],
          f"an absolute URL must be passed through: {forwarded}")
    print("test_api_latest_prefix OK")


def test_api_all_nodes_pages():
    """kcilib/api.py: all_nodes() walks {items,total,offset}, and stops.

    A missing page used to look exactly like "no such build".  Three endings
    are checked: the total is reached, a short page when there is no total, and
    an empty page when the total is stale.
    """
    import kcilib.api as kcapi

    limit = kcapi.PAGE_LIMIT
    first = [{"id": f"{i:024x}"} for i in range(limit)]
    rest = [{"id": f"{i:024x}"} for i in range(limit, limit + 50)]

    def paging(batches, total=None, offsets=None):
        """Answer in the given batches; the offset asked for is recorded."""
        def handler(_url, kwargs):
            asked = (kwargs.get("params") or {}).get("offset")
            offsets.append(asked)
            if len(offsets) > 8:
                # A walk that never ends must fail here, not hang the suite.
                check(False, "all_nodes() did not terminate: "
                             f"{len(offsets)} requests, offsets {offsets}")
            index = len(offsets) - 1
            body = {"items": batches[index] if index < len(batches) else [],
                    "offset": asked}
            if total is not None:
                body["total"] = total
            return _Response(200, json_body=body)
        return handler

    # (a) the total is reported: two pages, and the walk ends at the total.
    offsets = []
    nodes = _api_client(
        paging([first, rest], total=limit + 50, offsets=offsets)).all_nodes()
    check(len(nodes) == limit + 50,
          f"expected {limit + 50} nodes, got {len(nodes)}")
    check(offsets == [0, limit],
          f"the second page must be asked for at offset {limit}: {offsets}")
    check(nodes[0]["id"] == first[0]["id"]
          and nodes[-1]["id"] == rest[-1]["id"],
          "the pages must be concatenated in creation order")

    # (b) no total at all: a page shorter than the limit is the end.
    offsets = []
    nodes = _api_client(paging([first, rest], offsets=offsets)).all_nodes()
    check(len(nodes) == limit + 50,
          f"a short page must not truncate the walk: {len(nodes)}")
    check(offsets == [0, limit], offsets)

    # (c) a total that never arrives (10**6 with 250 nodes): the short page and
    # then the empty one end it, so the walk stays bounded.
    offsets = []
    nodes = _api_client(
        paging([first, rest], total=10 ** 6, offsets=offsets)).all_nodes()
    check(len(nodes) == limit + 50, len(nodes))
    check(offsets == [0, limit, limit + 50],
          f"an empty page is the only stop left here: {offsets}")

    # (d) an empty first page: one request, no nodes, no spin.
    offsets = []
    check(_api_client(
        paging([], total=10 ** 6, offsets=offsets)).all_nodes() == [],
        "an empty page must end the walk")
    check(offsets == [0], f"an empty page must end it at once: {offsets}")
    print("test_api_all_nodes_pages OK")


def test_api_non_json_is_api_error():
    """kcilib/api.py: a body that is not JSON is an APIError, not a ValueError.

    A proxy answers an HTML page; response.json() raises ValueError, which used
    to escape the client and kill callers that catch only API errors.  The stub
    raises what requests really raises, not a bare ValueError.
    """
    import kcilib.api as kcapi

    check(issubclass(kcapi.APIError, RuntimeError),
          "APIError is the client's own error type")
    check(not issubclass(kcapi.APIError, ValueError),
          "APIError must not be a ValueError - it replaces that escape")
    # The exception response.json() really raises for an HTML body: requests'
    # JSONDecodeError where it has one (2.27+), json.JSONDecodeError before.
    # Both are ValueError, which is what _json() catches.
    decoder_error = getattr(_real_requests.exceptions, "JSONDecodeError",
                            json.JSONDecodeError)
    check(issubclass(decoder_error, ValueError),
          "the decoder error _json() catches must be a ValueError")

    # NB: raise_for_status() runs first, so the not-JSON path is a 2xx whose
    # body is HTML (a captive proxy, an SSO page).
    html = _Response(200, json_error=decoder_error(
        "Expecting value", "<html>not json</html>", 0))
    definition_url = "http://scheduler/job.yaml"
    # get() hands back whatever parsed; the typed readers are the ones that owe
    # the caller a shape, and they refuse a page that is not an object (below).
    typed_reads = (
        ("nodes()", lambda client: client.nodes()),
        ("all_nodes()", lambda client: client.all_nodes()),
        ("node()", lambda client: client.node("abc")),
        ("events()", lambda client: client.events()),
        ("job_definition()", lambda client: client.job_definition(
            definition_url)),
    )
    for label, call in (("get()", lambda client: client.get("/nodes")),
                        *typed_reads):
        try:
            call(_api_client(lambda _url, _kwargs: html))
        except kcapi.APIError as error:
            check("did not return JSON" in str(error), f"{label}: {error}")
        else:
            check(False, f"{label} must refuse a body that is not JSON")

    # JSON that is not an object: each reader says so, instead of handing a
    # list to code that indexes it as a page.
    not_an_object = _Response(200, json_body=["no"])
    for label, call in typed_reads:
        try:
            call(_api_client(lambda _url, _kwargs: not_an_object))
        except kcapi.APIError:
            pass
        else:
            check(False, f"{label} must refuse JSON that is not an object")

    # A 5xx stays requests' HTTPError (callers catch RequestException) and must
    # never be turned into an empty page.
    server_error = _Response(502, json_body={})
    try:
        _api_client(lambda _url, _kwargs: server_error).get("/nodes")
    except _real_requests.exceptions.HTTPError:
        pass
    else:
        check(False, "a 502 must raise, not return an empty page")
    print("test_api_non_json_is_api_error OK")


def test_api_refuses_redirect():
    """kcilib/api.py: job_definition() refuses a redirect.

    A redirect means something in between is answering, so the refusal comes
    first - a 3xx carrying a good JSON body is exactly what a "does the body
    parse?" check would wave through.
    """
    import kcilib.api as kcapi

    url = "http://scheduler/job.yaml"
    for status in (301, 302, 303, 307, 308):
        redirect = _Response(status, headers={"Location": "http://whom/"},
                             json_body={"artifacts": {}, "tests": []})
        # The response is bound as a default so the lambda does not close over
        # the loop variable (ruff B023: every call would see the last redirect).
        client = _api_client(lambda _url, _kwargs, reply=redirect: reply)
        try:
            client.job_definition(url)
        except kcapi.APIError as error:
            check("redirect" in str(error), f"{status}: {error}")
        else:
            check(False, f"a {status} redirect must be refused")
        check(client.session.calls[0][1].get("allow_redirects") is False,
              f"the {status} refusal holds only because allow_redirects=False "
              "reaches the session")
        check(client.session.calls[0][0] == url,
              "the definition URL is absolute: it must be used as given, not "
              "re-based under /latest")

    # The same flag on the successful path, so an endpoint that STARTS
    # redirecting is never silently followed.
    client = _api_client(lambda _url, _kwargs: _Response(
        200, json_body={"artifacts": {"kernel": "http://x/Image"},
                        "tests": [{"type": "boot"}]}))
    definition = client.job_definition(url)
    check(definition["tests"][0]["type"] == "boot", definition)
    check(client.session.calls[0][1].get("allow_redirects") is False,
          "even a plain definition fetch must not follow redirects")
    print("test_api_refuses_redirect OK")


def test_api_retries_a_dropped_connection():
    """kcilib/api.py: a dropped connection is retried; a 5xx is not.

    The local API closes idle keep-alive connections, so a dropped connection
    used to lose a page; retrying a 5xx would only slow a refusal down.
    """
    import kcilib.api as kcapi

    check(kcapi.KernelCI("http://x:8001").retries == 3,
          "the documented default is three attempts")
    attempts = []

    def dropped(_url, _kwargs):
        attempts.append(1)
        raise _real_requests.exceptions.ConnectionError("connection reset")

    def fails(client, **kwargs):
        try:
            client.get("/nodes", **kwargs)
        except _real_requests.exceptions.ConnectionError:
            return True
        return False

    client = _api_client(dropped)
    with no_sleep():
        check(fails(client), "a connection error must reach the caller")
        check(len(attempts) == 3, f"expected 3 attempts, got {len(attempts)}")
        attempts.clear()
        check(fails(client, retries=1), "retries=1 must still raise")
        check(len(attempts) == 1, attempts)
        attempts.clear()
        check(fails(client, retries=0), "retries=0 must still raise")
        check(len(attempts) == 1,
              f"retries=0 must still make one attempt: {len(attempts)}")

        # ... and a retry that succeeds returns the page.
        attempts.clear()

        def once_then_ok(_url, _kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise _real_requests.exceptions.ConnectionError("dropped")
            page = {"items": [{"id": "n"}], "total": 1}
            return _Response(200, json_body=page)

        nodes = _api_client(once_then_ok).all_nodes()
        check(nodes == [{"id": "n"}],
              f"the second attempt's page must be returned: {nodes}")

    attempts.clear()

    def refused(_url, _kwargs):
        attempts.append(1)
        return _Response(503, json_body={})

    try:
        _api_client(refused).get("/nodes")
    except _real_requests.exceptions.HTTPError:
        pass
    else:
        check(False, "a 503 must raise")
    check(len(attempts) == 1, f"a 5xx must not be retried: {len(attempts)}")
    print("test_api_retries_a_dropped_connection OK")
