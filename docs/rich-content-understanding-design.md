# Rich Content Understanding — design

**Status:** Public HTML article and GitHub README reading implemented; other rich-content capabilities remain proposed.
**Last reviewed:** 2026-11-07  
**Scope:** chatgpt-discord-bot. Deployment manifests belong in `bturetzky/homelab-gitops`.

## Objective

Make Discord conversations about images, screenshots, URLs, GitHub projects, articles and YouTube videos genuinely content-aware rather than relying on URL guesses or plain text alone. Preserve the existing mention/DM interaction model and keep API spend, network use and implementation complexity bounded.

This feature is independent of, but compatible with, [Server Awareness](server-awareness-design.md). It should provide reusable extraction/enrichment components for a future indexed message archive without automatically processing every post.

## User experiences / acceptance examples

1. Mention bot with an image: “What is wrong with this Factorio setup?” Bot examines the image and explains observable details, qualifying uncertainty.
2. Mention bot with two screenshots: “Which one looks better?” Bot can compare both, within configured attachment limits.
3. Mention bot alongside an article URL: “Summarize this and tell me what you think.” Bot retrieves article text and cites the URL; it does not infer article contents from the URL.
4. Mention bot with a GitHub repository or file URL: “What does this project do?” Bot reads bounded public README/file content and can describe what was actually retrieved.
5. Mention bot with a YouTube URL: “What's the main argument here?” Bot identifies metadata and attempts to retrieve accessible caption/transcript text. If no transcript is available, it clearly states that it can only assess metadata/description, not the video's full contents.
6. Mention bot in reply to another user's image or URL: bot can use the referenced message's attachment/link content, with explicit bounds.
7. Ordinary chat with no rich content continues to work unchanged.

## Design decisions

- **No new hardware or always-on infrastructure.** Reuse the existing Python process, discord.py, aiohttp, BeautifulSoup and OpenAI Responses API.
- **User-triggered analysis:** Process rich content when the bot is mentioned or DM'd, or when a tool is explicitly called during that response. Do not invoke OpenAI for every image/link posted on the server.
- **Direct vision:** For attached images, supply validated image bytes as multimodal input to a vision-capable model. Do not first call a separate captioning model unless later measurement justifies it.
- **Structured URL extraction:** Specialized readers behind a shared interface; distinguish metadata, fetched page content and transcript. Never imply content was read when extraction failed.
- **YouTube is metadata + transcript-aware, not full video understanding in v1.** No video download, frame analysis or audio transcription pipeline initially.
- **Conservative bounds:** small limits on images, links, bytes, tokens, duration and concurrent requests; explicit timeouts and content-type checks.
- **Security:** URLs and extracted text are untrusted input. Defend against SSRF, prompt injection, redirect-to-private-address attacks, decompression bombs, oversized downloads and unsupported formats.
- **No persistence requirement for v1:** temporary content is held in memory only and discarded after response. A future Server Awareness integration may store derived metadata or descriptions in its own archive.
- **Dev/prod isolation:** validate using the independent dev bot/server; promote to prod through the existing manual workflow.

## Current code integration

- `discord_bot/handlers/discord_handler.py` currently serializes recent Discord history as **text-only** `role/content` messages. The current message's attachments, embeds and referenced messages are not represented as multimodal inputs. Extend its message-context builder rather than bolting image URLs into plain text.
- `discord_bot/handlers/chatgpt_handler.py` sends the conversation to the OpenAI **Responses API** and supports function calls. Add support for valid multimodal content items, while retaining existing tool-call loop behavior and usage metrics.
- `discord_bot/handlers/function_handler.py` dynamically registers `BaseFunction` subclasses. Existing webpage extraction should be inspected and reused/refactored before introducing duplicate URL fetching logic.
- `discord_bot/functions/` is the natural home for a `read_url_content` tool, with readers implemented in a separate reusable service/module so the Discord input path and future archive enrichment can share them.
- `tests/` should cover attachment handling, Responses payloads, URL safety, reader fallbacks and regression of existing text-only chat.

## Component boundaries

```text
Discord mention/DM (+ optional referenced message)
    |
    +-- ConversationContextBuilder
    |      |-- ordinary text + speaker attribution
    |      |-- image attachment validation/fetch -> Responses image input
    |      +-- URL candidates / attachment metadata
    |
    +-- ChatGPTHandler (Responses API)
           |-- direct vision on images included in context
           +-- read_url_content(url, question?) tool
                  |
                  +-- URL safety / fetch policy
                  +-- ReaderRegistry
                         |-- generic HTML/article
                         |-- GitHub public content
                         +-- YouTube metadata + available transcript
                  |
                  +-- bounded structured extraction result
```

Use a shared normalized result shape for all URL readers:

```json
{
  "ok": true,
  "url": "https://example.com/post",
  "canonical_url": "https://example.com/post",
  "kind": "article",
  "title": "Example",
  "author": null,
  "published_at": null,
  "source": "fetched_html",
  "content": "bounded extracted text",
  "content_truncated": false,
  "limitations": []
}
```

For YouTube, use `kind: youtube`, `source: transcript|description|metadata`, video ID, available language, and explicit transcript availability. Return `ok: false` and a short typed error for fetch failures; do not fabricate extracted content.

## Image / multimodal ingestion

- Include the triggering message and optionally a directly replied-to message. For ordinary history, preserve existing text-only context; do **not** fetch every historical attachment by default.
- Accept supported image MIME types (initially JPEG, PNG, WebP, GIF with model-specific behavior verified). Check actual content signatures, not just file extensions or Discord-supplied MIME.
- Use Discord's attachment CDN URL or download through a bounded HTTP client; validate redirect destinations and byte size. Avoid forwarding Discord authentication tokens.
- Configure a maximum number of images per turn (proposed 3), maximum individual image bytes (proposed 8 MiB), and total input budget. These are starting limits to verify against the chosen model/API; they are not claims about provider limits.
- Pass image input using the currently supported Responses API image content format; preserve speaker attribution and ordering. Prefer a supported image data URL or supported remote URL only after verifying security and compatibility.
- Gracefully reject unsupported files or excessive attachments and continue processing any usable text.
- For replies to older image messages, fetch the referenced message only when explicitly relevant; do not recursively follow chains.
- Model output should be honest about image ambiguity; no image generation or OCR-specific pipeline is in scope for v1.
- The currently configured `OPENAI_MODEL` must be checked for image input support. Provide an independently configurable vision-capable model only if necessary; avoid an additional model call when the normal response model supports images.

## URL discovery and routing

The existing `get_webpage_contents` tool now reads public HTML on demand, preferring article/main text and the rendered GitHub README for repository or README URLs. It returns the requested and final URL, source type, title, up to 12,000 characters, truncation status, or an explicit failure. Up to two page reads are permitted per response. The model is instructed to cite sources, treat page text as untrusted, and disclose failures and truncation. The fetcher validates redirect destinations and connects to a validated public IP while retaining the original hostname for TLS; size, content-type and timeout limits remain in place. Unit tests use mocked HTTP and model calls. Live Discord article/README behavior still needs manual dev validation, including blocked or JavaScript-only pages. Images, YouTube, reply attachments, background enrichment and non-HTML raw files are not implemented by this change.

Failed reads include a category, safe hostname, elapsed milliseconds and HTTP status when available; the corresponding warning log omits paths, query strings, exception text and page contents. Timeout classification preserves connect and streamed read timeouts, and connection attempts share a bounded connect timeout across resolved addresses. HTTP errors are reported as responses from the server, not automatically attributed to bot protection. A failure after an HTTP 200 can reflect unsupported content, download size or extraction rather than an HTTP error. Manual Discord retests remain necessary to diagnose the earlier News Tribune and Ars failures in the dev network: their original generic results did not preserve the cause. From the cloud proxy, the Ars page returned HTTP 200 and its HTML extracted successfully; the News Tribune request received an upstream connection reset. Those observations do not establish what happened in the dev cluster.

- Detect URLs in the triggering message, and optionally directly referenced messages; avoid auto-reading every URL in the last 30 messages.
- Expose `read_url_content` as a model tool for explicit or contextually necessary reading. Model may read a bounded number of URLs per turn (proposed 2); do not force a network fetch for unrelated casual mentions.
- Normalize and validate URLs, strip tracking parameters only when safe, and deduplicate. Permit only HTTP(S); reject credentials in URLs, localhost, loopback, RFC1918/link-local/unique-local and metadata-service addresses, internal DNS resolutions and redirects to them. Validate DNS resolution and connection destination on each redirect; beware DNS rebinding. If secure outbound fetch restrictions cannot be implemented reliably, use a proven safe-fetch library or explicit public-domain provider API instead.
- Set request timeouts, redirect limit, compressed/uncompressed byte caps, response content-type allowlist, per-host throttling, user agent and concurrency cap. Do not log full private URLs/query strings or page contents.
- Treat retrieved content as untrusted quoted material, never instructions to the assistant. Do not follow links embedded in fetched content automatically.
- Return short source metadata and text excerpts sufficient for the user question; use deterministic truncation and report truncation. Retain canonical/source URL for attribution.
- Existing webpage reader should be assessed for reuse, including any HTML parsing and fetch safety; avoid competing tools with ambiguous responsibilities.

### Generic webpages

Extract HTML title, main article/body text, canonical URL and basic metadata; remove scripts, nav, repetitive boilerplate and hidden content where practical. Handle pages requiring JavaScript, paywalls, bot protection and unsupported MIME as explicit limitations. No headless browser in v1.

### GitHub

For public GitHub links, recognize repository, README, issue, PR, blob/file and raw content URLs. Prefer official public GitHub API/raw endpoints where appropriate; respect unauthenticated rate limits. Do not use the user's private GitHub credentials inside the Discord bot or expose private repository content to server members. Bound file sizes and number of files; don't claim to have read an entire repository from one README.

### YouTube

- Parse canonical watch URLs, `youtu.be` links and supported shorts/live URLs to a validated video ID; avoid assuming every URL variant is supported.
- Retrieve title, channel, duration, publish date and description through an appropriate metadata method. YouTube Data API may require an API key/quota; decide on the concrete provider during implementation.
- **Transcript acquisition is a separate best-effort capability.** Official YouTube Data API caption download generally requires authorization to manage the video; it is not a general public transcript service. Evaluate a maintained third-party caption retrieval library or permitted transcript source against real videos, deployment constraints, reliability and applicable terms before selecting it. Do not claim transcripts are universally available.
- Support manual/automatic captions when actually retrievable, prefer English then available original language (configurable), and preserve segment timestamps where provided.
- Bound transcript length; for long transcripts, select relevant segments or use bounded staged summarization with token/cost limits. Include time-linked citations when timestamps exist.
- Fallback order: transcript -> description -> metadata. Clearly distinguish what was actually obtained. No full video download, speech-to-text or visual scene understanding in v1.
- Fail gracefully for unavailable captions, age restrictions, private videos, live streams, rate limits and blocked requests.

## User-visible behavior

- Responses should cite URLs and, for YouTube transcripts, timestamps where available.
- If extraction succeeds only partially, say so in natural language (e.g. “I could read the description, but not the transcript”).
- Avoid claiming to have watched a video or seen content that wasn't supplied.
- Keep tool-progress messages concise; do not spam progress for each image or URL.
- If a URL is irrelevant to the question, don't fetch it just because it appears nearby.
- Don't automatically save image interpretations, URL summaries or inferred user facts to Pinecone; memory remains an independent, deliberate mechanism.

## Operational budgets (initial proposals, tune in dev)

| Resource | Proposed starting bound |
| --- | --- |
| Images per response | 3 |
| Image bytes | 8 MiB each, 16 MiB total |
| URLs fetched per response | 2 |
| HTTP redirects | 3 |
| HTTP fetch timeout | 10 s per request, within overall tool timeout |
| HTML/raw download | 2 MiB compressed, 8 MiB decompressed |
| Extracted text returned to model | ~12k characters per source initially |
| Transcript processing | Bounded by input-token budget, with truncation/segmentation |
| Additional long-running services | 0 |
| Persistent volume | None for this feature |

The current `FunctionHandler` applies a 30-second timeout to awaitable tools. Readers must fit within it or the timeout architecture must be explicitly adjusted with end-to-end limits. Measure real API costs in dev; do not assume images are free or that all videos have transcripts.

## Tests and acceptance criteria

**Unit tests**
- Text-only conversation remains unchanged; mentions and DMs still work.
- A mention with one/two images builds valid Responses multimodal input in the correct order.
- Reply-to-image handling includes the referenced attachment only when appropriate.
- Unsupported/oversized images produce a useful fallback and no unbounded download.
- URL parser and reader routing cover articles, GitHub repos/files, YouTube watch/short links, duplicates and invalid URLs.
- SSRF tests cover direct private IPs, hostname resolution, redirect chains, encoded IPs, DNS rebinding attempts and metadata endpoints.
- Tool failures return typed errors, never hallucinated content.
- YouTube transcript available, unavailable, truncated and timestamped cases are covered with fixtures.
- Prompt injection inside fetched HTML/transcripts is treated as data.
- Existing memory, tool loop, usage logging and Discord reply tests remain green.

**Dev smoke tests**
- Image troubleshooting, two-image comparison, article reading, GitHub README reading, YouTube with captions, YouTube without captions, inaccessible/paywalled page.
- Verify sources and limitations in bot responses; inspect input/output token usage and latency.
- Verify no content processing occurs for ordinary unmentioned messages.
- Confirm dev/prod credentials and server isolation, then manually promote verified image.

**Done when:** All scenarios above behave predictably, failures are transparent, cost/latency are measured, and text-only regression tests pass. No new hardware or storage services required.

## Delivery sequence

1. Refactor safe content fetching and add a normalized reader interface; preserve or replace the existing webpage tool deliberately.
2. Add URL routing and generic webpage/GitHub readers; tests and dev smoke checks.
3. Add YouTube metadata and transcript best-effort reader; prove fallback behavior on real videos.
4. Add Discord image/reply attachment context and Responses multimodal payloads; test model compatibility and spend.
5. Harden limits, metrics, failure handling and docs; promote to production using existing workflow.
6. Later: optional enrichment integration with Server Awareness's SQLite archive, but only with explicit budgets and retention rules.

## Open questions / implementation choices

- **YouTube metadata and transcript provider:** select after a small proof-of-concept against public videos, including one with no accessible captions. Do not lock into an unreliable scraper prematurely.
- **Vision model:** verify whether the configured chat model supports image input and its cost; avoid separate vision calls unless needed.
- **Automatic link fetching:** initial recommendation is model-triggered when a user asks about the link, not eager-fetch every URL.
- **Attachment formats:** start with images; PDFs, audio, animated GIF frame handling and full video understanding are out of scope for v1.
- **Link previews:** Discord embeds can be useful metadata but should not be treated as proof that the linked content was read.
- **Privacy:** don't store raw images or transcripts in Pinecone or logs; determine later whether derived summaries belong in Server Awareness.


## Server Awareness integration (design decision)

The [Server Awareness](server-awareness-design.md) archive can later reuse the same reader interface, but passive indexing is **not** permission to analyze every posted link, video or image. The interactive mention/DM path remains on-demand and prioritized over background work.

Expose reusable extraction services independently of the OpenAI tool wrapper, with normalized source provenance, timestamps, retrieval status, truncation and error metadata. Background jobs may first index only URL/attachment metadata and Discord embed hints; these hints must never be represented as verified page/video/image contents.

A future enrichment worker may fetch inexpensive metadata for selected resources using a bounded, deduplicated, expiring cache and a strict daily network/token budget. Deep transcript retrieval, vision inference and full article analysis should default to explicit user requests. Cache by canonical resource identity, but retain separate per-message Discord attribution and handle edits/deletions.

Search results can trigger on-demand rich reading of a historical link or attachment, subject to current access, availability and fetch limits. Discord attachment URLs may expire; a message or source might be deleted. Return a clear limitation rather than guessing. Derived descriptions should be marked as derived and source-backed, not silently promoted to memories.

The Server Awareness extractor may summarize what participants **said about** shared content from surrounding conversation; it must not claim to know what an unread resource **contains**. No automatic Pinecone writes based solely on unverified URL metadata, preview embeds or model speculation.

No shared persistent cache or archive database is required to ship Rich Content Understanding v1; persistence, retention and indexing are owned by the Server Awareness design.

**Implementation status:** This document specifies intended behavior and starting limits, not completed work. Update it as providers are validated and implementation decisions are confirmed.
