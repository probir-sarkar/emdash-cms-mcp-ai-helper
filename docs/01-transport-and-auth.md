# 01 — Transport and auth: how to actually reach the MCP endpoint

These notes assume the MCP tools are **not** registered in your tool namespace (fresh session,
gateway hiccup, whatever) and you are calling the EmDash MCP endpoint directly over HTTP. The
endpoint is a JSON-RPC bridge: `POST https://your-site.example/_emdash/api/mcp`.

## The headers are load-bearing

```python
hdr = {
    "Authorization": "Bearer " + token,
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) my-agent/1.0",
    "MCP-Protocol-Version": "2024-11-05",
}
```

Without the `User-Agent` and `MCP-Protocol-Version` headers, the identical request — same token,
same body — returns **403 Forbidden** from the CDN in front of the site. It looks exactly like a bad
token. I burned a debugging cycle on a "token problem" that was a missing header before I tested an
old request at a new endpoint. If you get a 403, add the headers before you touch the token.

## Unwrap the JSON-RPC envelope before reading the response

The response is `{"jsonrpc": "2.0", "id": 1, "result": {"content": [...]}}`. A common failure:
parsing the envelope, finding valid JSON, and then concluding "no content came back" because you
looked for `content` at the top level. It sits under `result`. Also handle the SSE shape — some
deployments answer with `event: message\ndata: {...}` lines; strip everything up to `data: ` and
parse the rest.

## Three failure modes that mimic each other

Diagnose in this order:

1. **Every call returns HTTP 200 with an empty body** — you probably forgot the envelope unwrap
   (above), not a transport failure.
2. **Rapid-fire sequential writes return empty or non-JSON 200 bodies** — that is rate limiting,
   not a bad token. Sleep ~2 seconds between writes and retry with backoff. Reads tolerate bursts;
   writes do not.
3. **A scripted run that prints nothing, exits 0, and ends suspiciously fast** — check whether your
   token loader hit an expired `expires_at` and called something like `SystemExit`. That kills the
   whole interpreter silently; the symptom looks like "my code didn't run at all", not an auth
   error. The fix is to force a token refresh (any registered MCP tool call through the gateway
   usually rewrites the token file), re-read `expires_at`, and re-run.

## Token lifecycle

OAuth tokens land in a JSON file with `access_token` and `expires_at`. Two rules:

- Refresh **before** the request when `expires_at` is within ~60 seconds — a token that expires
  mid-run fails in the middle of a batch, which is the worst place to fail.
- Expect hourly expiry on long publishing runs. Design your batch loop to catch the failure,
  trigger a refresh, and resume from persisted progress rather than restarting.

## Non-ASCII payloads: what double-encodes and what doesn't

Sending raw UTF-8 bytes with an ambiguous charset can get them persisted double-encoded — `€`
stored as `â‚¬`, `—` as `â€”`. Adding `charset=utf-8` to `Content-Type` does **not** reliably fix it.

The reliable fix is to never send raw UTF-8 at all: serialize your JSON with
`json.dumps(payload)` (its default `ensure_ascii=True` escapes every non-ASCII character as
`\uXXXX`), so the wire carries only ASCII and the server decodes it correctly.

Two corollaries:

- **Detection** of existing damage: a naive `"â" in text` grep misses multi-layer damage. Scan for
  `ord(ch) > 127` where ASCII is expected, and repair with
  `text.encode("latin-1").decode("utf-8")`, repeating while the text still changes.
- The escape trick applies to **every** write — a Portable Text array, an image `alt` field, a
  bullet label you compose in a script. If your string contains an em dash and travels as raw
  UTF-8, it can be damaged.

## A minimal working call

```python
import json, time, urllib.request

def call(url, token, name, args, timeout=120):
    hdr = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "Mozilla/5.0 my-agent/1.0",
        "MCP-Protocol-Version": "2024-11-05",
    }
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode()
    if raw.startswith("event:"):
        raw = "\n".join(l[6:] for l in raw.splitlines() if l.startswith("data: "))
    r = json.loads(raw)
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["result"]
```

`scripts/emdash_mcp.py` wraps this with token handling, retries, and error-shape normalization.
