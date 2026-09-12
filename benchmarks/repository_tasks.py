"""Real urllib3 behavior tasks with executable, network-free answer oracles.

Curated development tasks, not sealed or independently authored observations.
Answers come from executing the pinned library, never from model grading.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import urllib3
from urllib3 import HTTPConnectionPool, PoolManager
from urllib3.exceptions import ConnectTimeoutError, ReadTimeoutError
from urllib3.response import HTTPResponse
from urllib3.util.retry import RequestHistory, Retry

PACKAGE_VERSION = "2.7.0"
SOURCE = Path(urllib3.__file__).resolve().parent


def outcome(call):
    try:
        result = call()
        return type(result).__name__
    except (urllib3.exceptions.HTTPError, ValueError) as exc:
        return type(exc).__name__


def error():
    return ReadTimeoutError(None, "/offline", "offline oracle")


def history(errors, *, redirected=False):
    prefix = (RequestHistory("GET", "/", None, 302, "/moved"),) if redirected else ()
    return prefix + tuple(RequestHistory("GET", "/", None, 503, None) for _ in range(errors))


def disabled_oracle():
    return {"disabled": outcome(lambda: Retry(total=False).increment("GET", error=error())),
            "zero": outcome(lambda: Retry(total=0).increment("GET", error=error()))}


def post_errors_oracle():
    retry = Retry(total=3, connect=2, read=2)
    connected = retry.increment("POST", error=ConnectTimeoutError("offline oracle"))
    return {"remaining_connect": connected.connect,
            "read_outcome": outcome(lambda: retry.increment("POST", error=error()))}


def allowlist_oracle():
    return {"default": Retry(status_forcelist={503}).is_retry("POST", 503),
            "empty": Retry(allowed_methods=frozenset(), status_forcelist={503}).is_retry("POST", 503),
            "none": Retry(allowed_methods=None, status_forcelist={503}).is_retry("POST", 503)}


def status_gate_oracle():
    retry = Retry(total=2)
    return {"get_413": retry.is_retry("GET", 413, True), "get_500": retry.is_retry("GET", 500, True),
            "post_503": retry.is_retry("POST", 503, True),
            "zero_total_get_503": Retry(total=0).is_retry("GET", 503, True)}


def forced_status_oracle():
    retry = Retry(total=0, status_forcelist={503}, respect_retry_after_header=False)
    return {"eligible": retry.is_retry("GET",503,False),
            "increment_outcome": outcome(lambda: retry.increment("GET", response=HTTPResponse(status=503)))}


def backoff_oracle():
    return {"one_after_redirect": Retry(backoff_factor=.5, history=history(1, redirected=True)).get_backoff_time(),
            "two_after_redirect": Retry(backoff_factor=.5, history=history(2, redirected=True)).get_backoff_time(),
            "four_without_redirect": Retry(backoff_factor=.5, history=history(4)).get_backoff_time()}


def sleep_oracle():
    result = {}
    for label, header in (("zero_header", "0"), ("positive_header", "3")):
        sleeps = []
        with patch("urllib3.util.retry.time.sleep", sleeps.append):
            Retry(backoff_factor=1, history=history(2)).sleep(HTTPResponse(headers={"Retry-After":header}))
        result[label] = sleeps
    return result


def cap_oracle():
    return {"explicit_cap": Retry(retry_after_max=12).parse_retry_after("999"),
            "default_cap": Retry().parse_retry_after("999999")}


def immutability_oracle():
    original = Retry(total=3, connect=2)
    new = original.increment("GET", error=ConnectTimeoutError("offline oracle"))
    return {"original_total": original.total, "new_total": new.total,
            "original_history_length":len(original.history), "new_history_length":len(new.history)}


def pool_oracle():
    counts = {}
    for block in (False, True):
        pool = HTTPConnectionPool("example.invalid",maxsize=1,block=block)
        first = pool._get_conn()
        second = None
        try:
            def checkout():
                nonlocal second
                second = pool._get_conn(timeout=.001)
                return second
            counts["blocking_second" if block else "nonblocking_second"] = outcome(checkout)
        finally:
            first.close()
            if second is not None:
                second.close()
            pool.close()
    return counts


def redirect_probe(status, cross_host):
    calls = []
    class OfflinePool:
        def is_same_host(self, url):
            return not cross_host

        def urlopen(self, method, url, **kwargs):
            calls.append({"method":method, "body":kwargs.get("body"),
                          "headers":sorted(h.lower() for h in kwargs["headers"])})
            location = "https://other.invalid/end" if cross_host else "/end"
            return HTTPResponse(status=status if len(calls)==1 else 200,
                                headers={"Location":location} if len(calls)==1 else {},
                                body=b"", preload_content=False, retries=Retry(total=3))
    manager = PoolManager()
    headers = {"Authorization":"SYNTHETIC_AUTH", "Cookie":"synthetic=1",
               "Proxy-Authorization":"SYNTHETIC_PROXY", "Accept":"application/json"}
    if status == 303:
        headers.update({"Content-Type":"application/json", "Content-Length":"2"})
    with patch.object(manager, "connection_from_host", return_value=OfflinePool()):
        manager.urlopen("POST", "https://example.invalid/start", body=b"{}", headers=headers)
    return calls[-1]


def headers_oracle():
    return {"same_host":redirect_probe(302,False)["headers"],
            "cross_host":redirect_probe(302,True)["headers"]}


def method_change_oracle():
    result = redirect_probe(303,False)
    return {"method": result["method"], "body_is_none":result["body"] is None, "headers":result["headers"]}


@dataclass(frozen=True)
class RepoTask:
    id: str
    question: str
    oracle: object
    required: tuple[tuple[str,str], ...]


R = "util/retry.py"
TASKS = [
    RepoTask("disabled_vs_zero", "For GET requests, compare Retry(total=False) with Retry(total=0) when a ReadTimeoutError is passed to increment. Return the raised exception class as disabled and zero.", disabled_oracle, ((R,"Retry.increment"),(R,"Retry.is_exhausted"))),
    RepoTask("post_error_categories", "With Retry(total=3, connect=2, read=2) and default method rules, a POST has a ConnectTimeoutError on one attempt and a ReadTimeoutError on another. Return remaining_connect after the first and read_outcome (returned or raised class) for the second.", post_errors_oracle, ((R,"Retry.increment"),(R,"Retry._is_method_retryable"),(R,"Retry.DEFAULT_ALLOWED_METHODS"))),
    RepoTask("empty_allowlist", "With status_forcelist={503}, is POST status 503 eligible for retry using default allowed_methods, an empty frozenset, and None? Return booleans default, empty, none.", allowlist_oracle, ((R,"Retry._is_method_retryable"),(R,"Retry.is_retry"),(R,"Retry.DEFAULT_ALLOWED_METHODS"))),
    RepoTask("retry_after_eligibility", "With total=2 and default settings and a Retry-After header, give retry eligibility for GET 413, GET 500 and POST 503. Also give GET 503 eligibility with total=0. Return get_413, get_500, post_503, zero_total_get_503.", status_gate_oracle, ((R,"Retry.is_retry"),(R,"Retry.RETRY_AFTER_STATUS_CODES"),(R,"Retry.DEFAULT_ALLOWED_METHODS"))),
    RepoTask("eligible_but_exhausted", "Retry(total=0, status_forcelist={503}, respect_retry_after_header=False) sees GET 503 without a Retry-After header. Return eligible from is_retry and increment_outcome as the returned or raised class when increment receives that response.", forced_status_oracle, ((R,"Retry.is_retry"),(R,"Retry.increment"),(R,"Retry.is_exhausted"))),
    RepoTask("redirect_resets_backoff", "Use backoff_factor=0.5 with no jitter. Give backoff seconds for one error after a redirect, two errors after a redirect, and four consecutive errors without a redirect. Return one_after_redirect, two_after_redirect, four_without_redirect.", backoff_oracle, ((R,"Retry.get_backoff_time"),)),
    RepoTask("zero_delay_header", "After two consecutive errors with backoff_factor=1 and no jitter, sleep receives a response with Retry-After: 0 or Retry-After: 3. Which time.sleep arguments are actually used? Return lists zero_header and positive_header.", sleep_oracle, ((R,"Retry.sleep"),(R,"Retry.sleep_for_retry"),(R,"Retry._sleep_backoff"),(R,"Retry.get_backoff_time"))),
    RepoTask("server_delay_cap", "In this installed version, parse a numeric Retry-After value of 999 with retry_after_max=12, and 999999 with default settings. Return seconds as explicit_cap and default_cap.", cap_oracle, ((R,"Retry.parse_retry_after"),(R,"Retry.DEFAULT_RETRY_AFTER_MAX"),(R,"Retry.__init__"))),
    RepoTask("retry_state_copy", "Start with Retry(total=3, connect=2) and call increment for GET with ConnectTimeoutError, storing its return separately. Return original_total, new_total, original_history_length and new_history_length.", immutability_oracle, ((R,"Retry.increment"),(R,"Retry.new"))),
    RepoTask("pool_capacity", "An HTTPConnectionPool with maxsize=1 has one connection checked out. What does a second _get_conn(timeout=0.001) return or raise for block=False versus block=True? No requests are sent. Return class names nonblocking_second and blocking_second.", pool_oracle, (("connectionpool.py","HTTPConnectionPool._get_conn"),("connectionpool.py","HTTPConnectionPool._new_conn"),("connectionpool.py","HTTPConnectionPool.ConnectionCls"))),
    RepoTask("redirect_header_scope", "PoolManager follows a 302 with default retries. Original headers are Authorization, Cookie, Proxy-Authorization and Accept. Return the lowercase header names forwarded for same_host and cross_host redirects, sorted in lists.", headers_oracle, (("poolmanager.py","PoolManager.urlopen"),(R,"Retry.DEFAULT_REMOVE_HEADERS_ON_REDIRECT"))),
    RepoTask("redirect_method_change", "PoolManager follows a same-host 303 after POST with a body and Authorization, Cookie, Proxy-Authorization, Accept, Content-Type, Content-Length headers. Return method, body_is_none and the sorted lowercase headers forwarded.", method_change_oracle, (("poolmanager.py","PoolManager.urlopen"),("_collections.py","HTTPHeaderDict._prepare_for_method_change"))),
]


def anchors(path):
    result = {}
    def visit(statements, prefix=""):
        for node in statements:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                name = prefix + node.name
                start = min([node.lineno]+[d.lineno for d in node.decorator_list])
                result[name] = (start,node.end_lineno)
                if isinstance(node,ast.ClassDef):
                    visit(node.body,name+".")
            elif isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets = node.targets if isinstance(node,ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target,ast.Name):
                        result[prefix+target.id] = (node.lineno,node.end_lineno)
    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return result


def dataset():
    if version("urllib3") != PACKAGE_VERSION:
        raise RuntimeError(f"oracles require urllib3=={PACKAGE_VERSION}")
    records = []
    for task in TASKS:
        required = [{"path":p, "symbol":name, "span":anchors(SOURCE/p)[name]} for p,name in task.required]
        with patch("socket.create_connection",side_effect=AssertionError("oracle attempted network")), \
             patch("socket.socket.connect",side_effect=AssertionError("oracle attempted network")):
            answer = task.oracle()
        records.append({"id":task.id, "question":task.question, "answer":answer, "required":required})
    manifest = [{"path":p.relative_to(SOURCE).as_posix(), "sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
                 "bytes":p.stat().st_size} for p in sorted(SOURCE.rglob("*.py"))]
    return {"package":"urllib3", "version":PACKAGE_VERSION, "evidence_mode":"LOCAL",
            "limitations":["Curated developer-known tasks, not an independent sealed evaluation",
                           "Required full source spans are conservative coverage diagnostics, not proven minima"],
            "source_manifest":manifest, "tasks":records}


if __name__ == "__main__":
    import json
    print(json.dumps(dataset(),indent=2))
