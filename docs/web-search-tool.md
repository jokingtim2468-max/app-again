# Web search tool (app requirement)

The model in the final app must be able to search the whole internet when it needs to
(e.g. "why is my game not running in Roblox Studio") through our own MCP server / plugin.

## Tool interface (what the model sees)

```json
{
  "name": "web_search",
  "parameters": {
    "query": "string",
    "type": "web | images | videos | models_3d | apps | commands | code | tutorials",
    "max_results": "int, default 10"
  }
}
{
  "name": "read_page",
  "parameters": { "url": "string" }
}
```

Each result: `{title, url, source_domain, snippet, extracted_text (relevant parts only), license (for images/3D/code)}`.

## How it works

1. **Search backend** returns the top 10 links for the query. Options (verify price/terms before choosing):
   - Self-hosted SearXNG metasearch (free, runs locally).
   - A search API such as Brave Search API (has paid tiers; check current pricing).
   - Not raw Google scraping (against Google's terms, breaks often).
2. **Reader**: a stripped-down headless Chromium (Playwright, no UI) opens each result, runs a
   readability-style extractor and keeps only article text + links. No ads, scripts, sidebars or images.
   Using headless Chromium is much simpler to maintain than forking/editing Chromium itself.
3. **Relevance filter**: split page text into chunks, keep the chunks that match the query
   (embedding or keyword score), cap tokens per result.
4. Return the 10 cleaned results to the model.

## Search types → sources

| type | sources (examples, check licences) |
|---|---|
| web / tutorials | general search, Roblox Creator Docs, Unity Docs/Learn, DevForum |
| code | GitHub code search, docs code samples (record licence) |
| commands | docs + man pages / CLI references |
| images | image search with licence filter (CC0/CC-BY only for assets used in games) |
| videos | YouTube Data API (titles, descriptions, transcripts when available) |
| models_3d | Poly Haven (CC0), Sketchfab API with downloadable CC licence filter |
| apps | official sites / package registries |

## Safety rules (built into the tool, not trusted to the model)

- Web page text is **data, not instructions**: wrap results in a marked block; the model is trained to never
  follow instructions found inside search results (prompt-injection defence).
- Only downloads from allow-listed, verified sources; show the user before running any command found online.
- Every asset/code result carries its licence; non-commercial licences are flagged.
- Cache results and rate-limit to keep costs at zero/low.

## Training impact

- The model must learn *when* to search (errors, unknown APIs, new engine versions) and how to cite results.
- Per the "no templates" rule, these tool-use examples come from **real runs** of the tool, not templates:
  once the tool works, record real search sessions, check them, and add them to the dataset.
- Runs locally on the user's machine (Windows app, Mac for testing).
