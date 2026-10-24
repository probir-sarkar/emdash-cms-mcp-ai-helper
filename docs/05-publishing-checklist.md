# 05 — The publishing pipeline, end to end

This is the full sequence I run for a researched article with a PDF companion and a chart. It
exists because every step that could be forgotten *has* been forgotten exactly once.

## 0. Before writing

- **Duplicate check against the angle, not the topic.** A topic clash with a different angle is a
  companion-linking opportunity, not a blocker.
- **Validate programmatically on current disk state** right before publishing — drafts keep being
  polished after they were first validated, and a stale validation pass is worse than none.
  Enforce in code: slugs, excerpts, word counts, banned constructs, and an allowlist audit of every
  outbound link.
- **Curl-verify every external URL** before injecting links: 404 → drop the link or the claim;
  bot-wall 403 → keep (it loads in browsers, but a plain fetch will never confirm the content).
  A dead link in one post is embarrassing; in a batch it's a pattern.
- **Verify every number against its source of truth.** A wrong count ships as the site's claim.
  State currency, dates, and whether a figure is a projection or a measurement.

## 1. Assets first

1. Generate the cover/OG card (1200×630) and **vision-check the one with the longest title** for
   wrapping and clipping — not just a convenient one.
2. Generate any inline charts, vision-check them at full size *and* phone width (~390px). Budget
   the layout before rendering: compute `rows + header + source line ≤ height` first, then render.
3. Upload media (see [04](04-media-and-images.md)): cover, charts, PDF. Record every media `id` and
   `storageKey` in a sidecar file — later steps reference them.

## 2. Create as a draft

`content_create` with `status: "draft"`, byline attached (an unattributed post is a bug, not a
style), category assigned at create time, tags validated against `taxonomy_list_terms` first (see
[02](02-content-operations.md)). Record the created `item.id` in progress state immediately.

## 3. Patch the Portable Text

- Move image credits into `caption` fields, delete the loose paragraphs.
- Insert download paragraphs + `file` blocks for attachments.
- Add internal companion links as `markDefs` + split spans (see [03](03-portable-text-surgery.md)).
- **Never** pass Markdown for these edits — Markdown round-trips wipe captions.

## 4. Publish — then prove it's live

`content_publish` with a fresh `_rev`, then re-`content_get` and confirm
`liveRevisionId == draftRevisionId`. Then the live sweep on the public URL:

- page returns 200
- `og:image` present, and its URL returns 200 with the expected content type and byte size
- exactly one `<figcaption>` per inline image
- the download `file` href returns 200 with the expected MIME type and byte count
- no stray `[n]` citation markers and no `|` pipe characters in article prose (strip `<script>`
  blocks before grepping; pipes inside link titles can be legitimate — scope the check)
- tags present via `href="/tag/<slug>"` greps, never label text

## 5. Mobile vision-check at 390px

Chart legibility, download-card wrapping (≤ two lines, no mid-word breaks), no horizontal overflow.
A desktop-perfect post with a broken mobile card is still a broken post.

## 6. Bookkeeping

Update the local published-manifest and push the **texts and scripts** to the repo — report
markdown, citation ledger, build scripts, and a small references file pointing at the media
storageKeys. Binaries (PNGs, PDFs) live in media storage, not in git; reference them by URL. This
keeps the repo cloneable and the diff history readable.

## Batch publishing, briefly

- Script the loop: upload → create (draft) → get fresh rev → publish → verify, with per-item
  progress persisted so a timeout resumes instead of restarting.
- Derive publish chunks by **slicing the slate array in code** — never re-type a hand-copied subset
  of slugs; that is how entries silently drop.
- Expect hourly token expiry mid-run: catch it, refresh (~10s), resume from the progress file.
- After any killed run, **reconcile by slug** before re-creating (see
  [02](02-content-operations.md)).
- Close with the live sweep across the *whole* slate and diff the live set against the intended
  set — a count mismatch means something was silently dropped and must be reconciled before
  reporting done.
