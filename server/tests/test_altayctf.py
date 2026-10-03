from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from farm.protocols import available_protocols
from farm.protocols._altayctf import classify, classify_text
from farm.protocols.altayctf_http import AltayCtfHttpProtocol, parse_results
from farm.protocols.altayctf_tcp import AltayCtfTcpProtocol
from farm.protocols.base import FlagVerdict

A, R, E = FlagVerdict.ACCEPTED, FlagVerdict.REJECTED, FlagVerdict.ERROR
F1, F2, F3 = "alt_0k1aa", "alt_b2bb", "alt_c3cc"


def test_plugins_registered_but_helper_is_not() -> None:
    protos = available_protocols()
    assert {"altayctf_http", "altayctf_tcp"} <= protos.keys()
    assert "_altayctf" not in protos


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ("Accepted", A),
        ("OK", A),
        ("[alt_x] Accepted. 12.5 flag points", A),
        ("Flag is correct", A),
        ("Incorrect flag", R),          # substring "correct" must not win
        ("Submission unsuccessful", R),  # substring "success" must not win
        ("Flag not accepted", R),
        ("Flag is too old", R),
        ("Flag already submitted", R),
        ("This is your own flag", R),
        ("Invalid flag format", R),
        ("Hold on", E),                 # "old" inside a word is no verdict
        ("Rate limit exceeded, try again later", E),
        ("Internal server error", E),
        ("Welcome to AltayCTF", E),
        ("", E),
    ],
)
def test_classify_text(text: str, verdict: str) -> None:
    assert classify_text(text) == verdict


def test_flag_body_is_not_read_as_a_verdict() -> None:
    # "alt_0k1aa" -> letter runs "alt", "k", "aa"; "alt_ok" would yield "ok".
    assert classify_text("alt_ok42: queued", "alt_ok42") == E


@pytest.mark.parametrize(
    ("item", "verdict"),
    [
        (True, A),
        (False, R),
        ({"accepted": True}, A),
        ({"success": False, "message": "ok"}, R),
        ({"status": "ACCEPTED"}, A),
        ({"msg": "flag is too old"}, R),
        ({"foo": 1}, E),
        (42, E),
    ],
)
def test_classify_items(item: object, verdict: str) -> None:
    assert classify(item) == verdict


def verdicts(results) -> list[str]:
    return [r.verdict for r in results]


def test_parse_list_keyed_by_flag_in_any_order() -> None:
    body = json.dumps({"results": [
        {"flag": F2, "status": "too old"},
        {"flag": F1, "status": "accepted"},
    ]})
    # F3 isn't mentioned: it must be retried, not guessed.
    assert verdicts(parse_results([F1, F2, F3], body)) == [A, R, E]


def test_parse_positional_list_only_when_lengths_match() -> None:
    assert verdicts(parse_results([F1, F2], json.dumps(["Accepted", "Invalid"]))) == [A, R]
    # Shorter list without flags: can't tell which is which -> retry all.
    assert verdicts(parse_results([F1, F2], json.dumps(["Accepted"]))) == [E, E]


def test_parse_strings_echoing_the_flag() -> None:
    body = json.dumps([f"[{F2}] Accepted"])
    assert verdicts(parse_results([F1, F2], body)) == [E, A]


def test_parse_object_keyed_by_flag() -> None:
    body = json.dumps({F1: "accepted", F2: False})
    assert verdicts(parse_results([F1, F2, F3], body)) == [A, R, E]


def test_parse_single_reply_only_for_single_flag() -> None:
    assert verdicts(parse_results([F1], "Accepted")) == [A]
    assert verdicts(parse_results([F1, F2], "Accepted")) == [E, E]  # never mass-accept


# ---------------------------------------------------------------- HTTP e2e

class _Jury(BaseHTTPRequestHandler):
    status = 200
    seen: list[dict] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Jury.seen.append({"path": self.path, "body": body, "token": self.headers.get("X-Team-Token")})
        reply = [{"flag": f, "msg": "Accepted" if f == F1 else "Flag is too old"} for f in body["flags"]]
        data = json.dumps({"data": reply}).encode()
        self.send_response(_Jury.status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def http_jury():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Jury)
    _Jury.status, _Jury.seen = 200, []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_http_roundtrip(http_jury: str) -> None:
    proto = AltayCtfHttpProtocol(url=http_jury, headers={"X-Team-Token": "tok"})
    res = asyncio.run(proto.submit([F1, F2]))
    assert verdicts(res) == [A, R]
    assert _Jury.seen == [{"path": "/api/v1/flags", "body": {"flags": [F1, F2]}, "token": "tok"}]


def test_http_error_status_is_retryable(http_jury: str) -> None:
    _Jury.status = 503
    res = asyncio.run(AltayCtfHttpProtocol(url=http_jury).submit([F1]))
    assert verdicts(res) == [E] and res[0].response.startswith("HTTP 503")


def test_http_unreachable() -> None:
    res = asyncio.run(AltayCtfHttpProtocol(url="127.0.0.1:1", timeout=1).submit([F1]))
    assert verdicts(res) == [E]


# ----------------------------------------------------------------- TCP e2e

def tcp_jury(*, banner: bool, close_each: bool, silent_for: set[str] = frozenset()):
    """Start a fake line jury; returns (server, port, connection counter)."""
    conns = [0]

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conns[0] += 1
        if banner:
            writer.write(b"Welcome to AltayCTF jury!\nSend flags, one per line\n\n")
            await writer.drain()
        try:
            while line := await reader.readline():
                flag = line.decode().strip()
                if flag in silent_for:
                    await asyncio.sleep(10)
                    continue
                verdict = "Accepted" if flag == F1 else "Flag is too old"
                writer.write(f"[{flag}] {verdict}\n".encode())
                await writer.drain()
                if close_each:
                    break
        finally:
            writer.close()

    return handle, conns


async def run_tcp(flags, **jury) -> tuple[list, int, float]:
    handle, conns = tcp_jury(**jury)
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    proto = AltayCtfTcpProtocol(host="127.0.0.1", port=port, timeout=1, greeting_timeout=0.3)
    t0 = time.monotonic()
    res = await proto.submit(flags)
    took = time.monotonic() - t0
    server.close()  # don't wait for handlers still sleeping on "silent" flags
    return res, conns[0], took


@pytest.mark.parametrize("banner", [False, True])
def test_tcp_one_connection_per_batch(banner: bool) -> None:
    res, conns, _ = asyncio.run(run_tcp([F1, F2, F3], banner=banner, close_each=False))
    assert verdicts(res) == [A, R, R]  # the banner is never read as a verdict
    assert conns == 1


@pytest.mark.parametrize("banner", [False, True])
def test_tcp_server_closing_after_each_flag(banner: bool) -> None:
    flags = [F1, F2, F3] * 4
    res, conns, took = asyncio.run(run_tcp(flags, banner=banner, close_each=True))
    assert verdicts(res) == [A, R, R] * 4
    assert conns >= len(flags)
    if not banner:
        assert took < 2  # no per-connection banner wait once we know there's none


def test_tcp_silent_reply_is_error_and_rest_continues() -> None:
    res, _, _ = asyncio.run(run_tcp([F2, F1, F3], banner=False, close_each=False, silent_for={F2}))
    assert verdicts(res) == [E, A, R]


def test_tcp_gives_up_after_repeated_timeouts() -> None:
    flags = [F1, F2, F3, "alt_d4", "alt_e5"]
    res, _, took = asyncio.run(
        run_tcp(flags, banner=False, close_each=False, silent_for=set(flags))
    )
    assert verdicts(res) == [E] * 5
    assert took < 5  # 3 timeouts of 1s, then the rest fail fast


def test_tcp_unreachable_fails_fast() -> None:
    proto = AltayCtfTcpProtocol(host="127.0.0.1", port=1, timeout=1)
    t0 = time.monotonic()
    res = asyncio.run(proto.submit([F1] * 50))
    assert verdicts(res) == [E] * 50 and time.monotonic() - t0 < 2
