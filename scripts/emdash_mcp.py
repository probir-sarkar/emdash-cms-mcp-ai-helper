#!/usr/bin/env python3
"""Small dependency-free client for an EmDash CMS MCP endpoint.

Encodes the transport lessons from docs/01-transport-and-auth.md:
  - the load-bearing User-Agent / MCP-Protocol-Version headers
  - ASCII-safe JSON encoding (no raw UTF-8 on the wire)
  - JSON-RPC envelope unwrapping, including SSE-shaped responses
  - token expiry handling and gentle write pacing

Usage:
    from emdash_mcp import EmDashMCP
    cms = EmDashMCP(url="https://your-site.example/_emdash/api/mcp",
                    token="...", user_agent="my-agent/1.0")
    result = cms.tool("content_get", {"collection": "posts", "id": "some-slug"})
    text   = cms.text(result)
"""
from __future__ import annotations

import json
import time
import urllib.request

DEFAULT_TIMEOUT = 120
WRITE_PAUSE = 2.0  # seconds between consecutive write calls; reads tolerate bursts


class EmDashMCPError(RuntimeError):
    pass


class EmDashMCP:
    def __init__(self, url: str, token: str | None = None,
                 user_agent: str = "emdash-mcp-ai-helper/1.0",
                 protocol_version: str = "2024-11-05",
                 timeout: int = DEFAULT_TIMEOUT):
        # url may carry the token as scheme://user:token@host — the CMS masks
        # userinfo in *written content*, but here we just split it off cleanly.
        if "://" in url and "@" in url.split("://", 1)[1]:
            scheme, rest = url.split("://", 1)
            userinfo, host = rest.rsplit("@", 1)
            self.url = f"{scheme}://{host}"
            token = token or userinfo.split(":", 1)[1]
        else:
            self.url = url
        self.token = token
        self.user_agent = user_agent
        self.protocol_version = protocol_version
        self.timeout = timeout
        self._last_write = 0.0

    # -- transport ---------------------------------------------------------

    def _headers(self) -> dict:
        # Both headers below are load-bearing: without them the identical
        # request can return 403 from the CDN, which looks like a bad token.
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": self.user_agent,
            "MCP-Protocol-Version": self.protocol_version,
        }

    def call(self, method: str, params: dict | None = None, id: int = 1) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": id,
                           "method": method, "params": params or {}}).encode()
        req = urllib.request.Request(self.url, data=body,
                                     headers=self._headers(), method="POST")
        raw = urllib.request.urlopen(req, timeout=self.timeout).read().decode()
        if raw.startswith("event:"):  # SSE shape
            raw = "\n".join(l[6:] for l in raw.splitlines() if l.startswith("data: "))
        r = json.loads(raw)
        if "error" in r:
            raise EmDashMCPError(f"JSON-RPC error: {r['error']}")
        return r["result"]

    def tool(self, name: str, args: dict | None = None) -> dict:
        # json.dumps escapes non-ASCII to \uXXXX, keeping the wire ASCII-only —
        # raw UTF-8 bodies can be double-encoded by some fronting proxies.
        if name.split("_", 1)[0] in ("content", "media", "taxonomy", "menu",
                                     "schema", "settings", "byline", "site"):
            gap = WRITE_PAUSE - (time.time() - self._last_write)
            if gap > 0:
                time.sleep(gap)
        res = self.call("tools/call", {"name": name, "arguments": args or {}})
        self._last_write = time.time()
        return res

    # -- response shapes ----------------------------------------------------

    @staticmethod
    def text(res: dict) -> str:
        """Flatten a tools/call result to text. Raises on isError payloads
        (SLUG_CONFLICT etc. arrive as plain text, not JSON-RPC errors)."""
        out = []
        for c in res.get("content", []):
            out.append(c.get("text") if c.get("type") == "text" else json.dumps(c))
        if res.get("structuredContent") is not None:
            out.append(json.dumps(res["structuredContent"]))
        joined = "\n".join(out)
        if res.get("isError"):
            raise EmDashMCPError(joined)
        return joined

    def json(self, res: dict):
        return json.loads(self.text(res))

    # -- convenience ---------------------------------------------------------

    def get(self, collection: str, ident: str, markdown: bool = False) -> dict:
        return self.json(self.tool("content_get", {
            "collection": collection, "id": ident, "markdown": markdown}))

    def update(self, collection: str, item_id: str, rev: str, data: dict) -> dict:
        return self.json(self.tool("content_update", {
            "collection": collection, "id": item_id, "_rev": rev, "data": data}))

    def publish(self, collection: str, item_id: str, rev: str) -> dict:
        return self.json(self.tool("content_publish", {
            "collection": collection, "id": item_id, "_rev": rev}))

    def edit_and_publish(self, collection: str, item_id: str, data: dict) -> dict:
        """Update + publish + confirm the live revision moved (docs/02)."""
        d = self.get(collection, item_id)
        self.update(collection, item_id, d["_rev"], data)
        d = self.get(collection, item_id)
        published = self.publish(collection, item_id, d["_rev"])
        item = published["item"]
        if item.get("liveRevisionId") != item.get("draftRevisionId"):
            raise EmDashMCPError(
                f"publish did not promote the draft revision: live={item.get('liveRevisionId')} "
                f"draft={item.get('draftRevisionId')}")
        return published
