# 02 — Content operations: create, update, publish without losing work

The EmDash content API separates *writing* from *publishing*, and a lot of the gotchas below fall
out of that split.

## `_rev` is at the top level of the read response

`content_get` returns `{"item": {...}, "_rev": "..."}`. The revision is **not** inside `item`.
Pass the top-level `_rev` to `content_update` / `content_publish`. On `CONFLICT`, re-read to get the
fresh `_rev` and retry; on `ENTRY_LOCKED`, a human has the entry open in the admin — report that and
wait, don't force it.

## `status: "published"` in an update response does not mean your edit is live

This one is sneaky. After `content_update`, the response can still say `status: published` while
`liveRevisionId` points at the **old** revision and `draftRevisionId` holds your edit. The site
serves the previous revision until you call `content_publish` with the fresh `_rev` — and even a
static-site rebuild can keep serving the old body until that publish lands.

**Diagnose by comparing `liveRevisionId` vs `draftRevisionId` from `content_get`, never by reading
`status`.** The safe rhythm is: update → re-read → publish → re-read and confirm
`liveRevisionId == draftRevisionId`.

## Drafts and slug conflicts

- `status: "draft"` on create never publishes accidentally. Publishing is always a separate call.
- `SLUG_CONFLICT` on create means the entry already exists. Do **not** re-create with a mangled
  slug — fetch `content_get(slug)`, take its `id` and `_rev`, and go through update + publish.
  This applies to single posts too, not just batch runs.
- A publishing loop killed by a timeout can leave entries **created but unreported**. Before
  re-creating anything, reconcile per slug: a draft means create succeeded and only publish died.
  Persist each created `item.id` to a progress file as you go — later steps should use the id, not
  re-look-up the slug (fresh entries may not surface in `content_list` pagination for seconds).
- Error results like `SLUG_CONFLICT` or `VALIDATION_ERROR` arrive as **plain text**, not JSON. Don't
  blindly `json.loads` a tool result; on a parse failure, scan the collection for the slug instead.

## The taxonomy gate: unknown tags publish tagless

This is my least favorite behavior in the whole system, so it gets its own section:

- Tag slugs must already exist. `content_create` with an unknown tag returns a `VALIDATION_ERROR`
  **and still creates the post** — which then publishes with no tags at all.
- Therefore: always call `taxonomy_list_terms` for every taxonomy you use **before** any create,
  and create missing terms first. Never trust a hardcoded tag list from last month — it goes stale.
- Verify tags on the **live page** (grep for `href="/tag/<slug>"`, not the visible label — labels
  render transformed and a label grep false-negatives on a correctly tagged post). If tags are
  missing, backfill with `content_update` + `taxonomies` and republish.

## Markdown in, Portable Text out

`data.content` accepts a Markdown string and converts it to Portable Text automatically. That
conversion is good but has sharp edges:

- **Fenced code blocks survive** and render properly, with the language taken from the fence info
  string.
- **Markdown tables do not convert.** Each table row becomes a paragraph of literal pipe
  characters. There is no table block type to target later. Convert tables to
  `- **Label** — value` bullet lines before writing, and after publishing, check the rendered HTML
  for stray `|` characters in prose.
- **YAML frontmatter in `content` ships as visible paragraphs.** Title/excerpt/slug/tags belong in
  the `data` payload; a `---` header block in the content will appear as literal text at the top of
  the live article.
- **The CMS masks credentials in URL userinfo** inside written content: `scheme://user:secret@host`
  is stored as `scheme://user:***@host`. If your article teaches URL credential encoding, write the
  example password as a placeholder and teach the encoding beside the URL, not inside it.
- A markdown `![alt](url)` image becomes a real Portable Text image block — but a following credit
  paragraph is only *sometimes* absorbed into the image's `caption`. See
  [03-portable-text-surgery.md](03-portable-text-surgery.md) for the reliable two-step pattern.

## Duplicates: check the angle, not just the slug

The CMS rejects duplicate *slugs* but says nothing about duplicate *topics*. Before writing,
check a local manifest or `content_list` for the topic — and when you find a near-match, actually
read it: a directory-style post on a subject doesn't block a narrative deep-dive on the same
subject, and the new post should link the old one as a companion.

## `_rev`, not `rev` — and what a swallowed validation error looks like

My update helper read the revision from `content_get`'s top level and then sent it back under the
key `rev`. The call returned **no JSON at all** — a short plain-text body I initially mistook for
rate limiting, then for a transport failure, because earlier in the same session an update had
returned an empty 200. Retrying made it worse: three attempts, same silence, and the record never
moved (`_rev` unchanged, `featured_image` still null).

The body was the answer, the whole time. Printed raw, it read:

```
MCP error -32602: Input validation error: Invalid arguments for tool content_update:
_rev is required: call content_get for this item and pass back the _rev it returned
```

So: the mutation arguments are `_rev` on `content_update`, `content_publish`,
`content_schedule` and `content_unschedule`, and the value is the string at the **top level** of the
`content_get` response, not inside `item`. Two habits follow.

- **Print the raw body before parsing it.** `json.loads(text)` on an error is a `JSONDecodeError`
  that tells you nothing. Log the first ~200 characters, then decide. A 176-byte body beginning
  `MCP error -32602` is a schema problem; a zero-byte body is transport or throttling; a valid
  envelope with no `content` key is a helper that forgot to unwrap `result`.
- **After a failed write, re-read before resending.** The cheapest way to know whether a mutation
  landed is a fresh `content_get` diffed against the state you expected. Blind retries turn a
  schema bug into a duplicate-write risk on the operations that are not idempotent.

Same trap, same fix, for the publish step: re-read after the update to get the *new* revision, then
publish with that — publishing the pre-update `_rev` is a conflict, not a publish.
