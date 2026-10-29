# 04 — Media and images: uploads, URLs, and the traps in between

## Two URL forms exist; only one works on the site

A media item has an `id`, a `storageKey`, and (from `media_upload`) an `url` field. Learn the
difference the expensive way or the cheap way — this is the cheap way:

- **`/media/<storageKey>`** (the URL on the upload response) → **404s on the live site.**
- **`/_emdash/api/media/file/<storageKey>`** → the working form. This is what `og:image` uses.

After composing content, extract every `<img src>` from the **live** HTML and fetch each resolved
URL — a dead `/media/` link passes naive HTML greps but renders broken.

## The CMS rewrites media references on save

The `storageKey` from your upload is not necessarily the ID the stored content points at after a
`content_create` / `content_update`. Image URLs in the stored content get rewritten to canonical
media IDs. So: curl the storageKey URL after a save, get a 404, and conclude the upload broke —
wrong conclusion. Verify through the live page's `<img src>` / `og:image` instead.

## Uploading: limits and the two paths

- **Through an MCP tool-argument gateway**, large base64 payloads get rejected — images above
  roughly 15 KB (base64 above ~20K chars) fail with `VALIDATION_ERROR: Invalid base64 data` even
  when the base64 is valid. For anything bigger, POST directly to the MCP endpoint with the
  transport headers from [01](01-transport-and-auth.md).
- **Argument names**: check the tool schema — the upload takes `filename`, `base64`,
  `contentType`. Guessing `data`/`mimeType` fails validation (harmlessly, but confusingly).
- **Dedupe is by content hash**: re-uploading identical bytes returns the existing item with
  `deduplicated: true` rather than a new record. Useful to know when reconciling a retry loop.
- **Downscale before uploading**: a multi-megabyte screenshot fails with HTTP 413. Resize heroes
  and body images to fit within ~1600px and a few hundred KB first.
- **Folder-prefixed filenames** (`og/<slug>.png`, `charts/<slug>.png`, `pdf/<name>.pdf`) are kept
  verbatim and read as folder paths in the media library. Root-level filenames make a library
  nobody can navigate — the human using the site will flag it.

## Cover images vs body images — never swap them

A post's `featured_image` / `og:image` is its identity in feeds and share cards; body images are
content. Generated brand cards for covers, real screenshots and photos inline — a vendor screenshot
as the cover reads as an ad for that vendor and breaks the feed's visual identity. This is a design
convention, but agents are the ones who will get it wrong at scale.

## Featured-image updates and captions

A **featured-only** update (`data: {"featured_image": {"id": ..., "alt": ...}}`) never resends
`content`, so it cannot wipe inline-image captions. That makes it the safe primitive for
backfilling missing OG images on older posts: upload the PNG, then `content_update` with only the
`featured_image`, then publish and re-fetch the live HTML to confirm the `og:image` meta tag exists
and its URL returns 200.

## Downloadable attachments: PT `file` blocks

There is no markdown placeholder that survives for a downloadable file — a markdown link becomes a
literal paragraph. Create the post from Markdown, then patch the PT array:

```json
{"_type": "file", "_key": "dl1",
 "url": "/_emdash/api/media/file/<storageKey>.pdf",
 "filename": "Short display name",
 "showDownloadButton": true}
```

Keep the display filename **short** — a full sentence wraps to three lines at 390px mobile width,
and mid-word breaks look broken even at two lines. Deleting a media file later takes the media
**item id** (`01M...`), not the storageKey (`01M....pdf`) — the storageKey form answers NOT_FOUND.

## Image optimizer failures are platform-side — in two shapes

Before blaming your upload:

1. **`/_image?href=...` returns HTTP 500 or hangs for a media file that itself returns 200.** Test
   an *old* image at a *new* width — if that also fails, the image transformation binding is broken
   platform-wide while cached sizes keep serving.
2. **The featured-image URL is built from the media id with no extension** and 404s even though the
   stored key has one. Some frontends carry a fix-up script that appends the extension and retries.
   So a cover can look broken while the raw storageKey URL and the CMS record are healthy.

Verify images by reading `naturalWidth > 0` on every `<img>` after load — never by grepping the
HTML.

## The card title can be silently replaced by the post title

I keep a short display string for the OG card next to each post in the generator, on the theory that
a card wants three to five words while the article wants a real headline. On a run this week the card
came back carrying the full H1 instead, wrapping to three lines with a two-word tail.

Cause: the generator also *reads* the draft file (and falls back to the live site) to pick up the real
headline, then overwrites whatever title I passed in the array. With a short title defeated, the fix
is not to edit the string harder — it is to understand the precedence order:

1. frontmatter `title` in the local draft file,
2. the title fetched from the live site,
3. the title in the generator's `POSTS` array.

(1) and (2) both win over (3). So a display title only survives when there is no draft file and the
post is not yet published — the narrow window right after a create and before a publish. Outside that
window, either accept the headline on the card or move the draft aside for the one render.

Check by measurement, not by eye: I load the PNG and project light pixels row by row inside the title
band. One band means one line, and the band's right edge tells me whether it filled the column. That
catches an orphaned tail without a vision model and costs three lines of Python.
