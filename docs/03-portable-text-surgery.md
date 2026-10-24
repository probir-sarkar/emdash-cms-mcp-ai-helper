# 03 — Portable Text surgery: editing published content without breaking it

Once a content item is published and illustrated, prefer editing its **Portable Text array
directly** over resending Markdown. The rules below come from breakage I have caused and then had
to repair on a live site.

## Why: markdown round-trips are lossy

Any `content_update` that passes `data.content` as a **Markdown string** re-runs the parser and
regenerates the Portable Text. That regeneration:

- **drops `caption` fields** from existing image blocks (credit paragraphs can vanish entirely),
- re-keys blocks and spans,
- and can reflow marks in ways you won't notice until a reader does.

So: *creation* can go through Markdown; *editing an existing, illustrated post* should patch the PT
array.

## Reading the shape

`content_get` returns `item.data.content` as an array of blocks. The common types:

```json
{"_type": "block", "_key": "k1", "style": "normal", "markDefs": [],
 "children": [{"_type": "span", "_key": "k0", "text": "...", "marks": []}]}
{"_type": "image", "_key": "k17", "alt": "...", "caption": "...",
 "asset": {"url": "/_emdash/api/media/file/<storageKey>"}}
{"_type": "file",  "_key": "dl1", "url": "/_emdash/api/media/file/<storageKey>.pdf",
 "filename": "Short display name", "showDownloadButton": true}
```

Heading levels are `style: "h2"` etc.; list items are `listItem: "bullet"` with `level`.

## Appending a "Related reading" section

1. `content_get(id)` — keep the top-level `_rev`.
2. Append one `h2` block plus one bullet `block` per target, where the block's `markDefs` holds
   `{"_key": "mk1", "_type": "link", "href": "/posts/<target-slug>"}` and its child span carries
   `marks: ["mk1"]`. Internal hrefs are site-relative (`/posts/...`).
3. `content_update` with `data.content = <array>`, then `content_publish` with the fresh `_rev` —
   updates land as a **draft revision** even on published items.
4. Verify on the live HTML: extract `href="/posts/..."`, check every target returns 200, and assert
   exactly one `Related reading` heading per post.

## Linkifying a phrase inside an existing span

Split the span into three: prefix span (no marks), the phrase span (marks: `[new markDef key]`),
remainder span (no marks).

**Two pitfalls learned the hard way:**

- **One pass misses a second phrase in the same span.** Your loop iterates a snapshot, but
  splitting creates new spans; a span holding two linkable phrases only gets the first. Loop until
  a pass finds nothing.
- **Never touch a span that already has marks, and never re-key a span another mark references.**
  Preserve existing `markDefs` and only append. Rebuilding `children` from scratch drops marks.

## Image captions: the reliable credit pattern

The Markdown→PT conversion *inconsistently* absorbs a following `Image: ...` credit paragraph into
the image's `caption` field. The reliable pattern — **both steps in the same session, never ship
step one alone**:

1. Insert `![alt](url)` + a plain credit paragraph, and publish.
2. Immediately patch the PT array: move the credit text into the image block's `caption`, delete
   the separate paragraph block, and re-publish (send `data.content` as a PT array for this
   update).

A post left at step one shows loose credit paragraphs instead of `<figcaption>`s on the live site —
exactly what gets flagged on review. Verify with a `<figcaption` count on the live HTML.

## When markdown edits ARE safe

A post that uses plain credit paragraphs (no `caption` fields anywhere) can be re-edited via
Markdown without visible damage. Check which pattern the post uses **before** choosing the update
strategy — and after *any* Markdown-based edit to an illustrated post, re-check every image block's
`caption` and re-apply missing ones via a PT patch.

## A pipe-table cleanup

When a legacy post has a broken markdown table (a run of paragraph blocks full of `|` characters),
remove the **whole consecutive run** — including the `|---|` separator, which survives naive
row-conversion — and re-emit the rows as bullet blocks.
