<div align="center">

[简体中文](README.md) | **English** | [日本語](README.ja.md)

<br/>

# Professor Match

**Finds "the right one" for you among ~300,000 Japanese professors**

Vector search × LLM query expansion × multi-signal three-tier ranking — a complete RAG matching pipeline extracted from a real production system

<br/>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Skip the docs. Play with it first!

## [▶▶▶ Live Demo (full-scale) ◀◀◀](https://kafkaesque-luk.github.io/professor-match/)

### `https://kafkaesque-luk.github.io/professor-match/`

✧ Zero install · Opens in your browser · Backed by the ~300k-professor production index ✧

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

</div>

<br/>

## What is this?

One sentence: **describe your research interest in plain Chinese or Japanese, and it semantically matches you against professors across all of Japan** — results served in three tiers.

If you've ever applied to a Japanese graduate school, you know the traditional workflow:

- Open a university website → click through 200 faculty pages → by #30 you've forgotten who #3 was
- Finally find someone perfect — turns out they retire next year. There goes your research proposal (╯°□°)╯︵ ┻━┻
- Or pay an agency a fortune, and watch them Ctrl+F through an Excel sheet (true story)

So: you say what you want to research, and the machine sifts through every professor in Japan for you.

## Why not just ask ChatGPT?

Fair question. You can absolutely ask any LLM: "Which Japanese professors work on medical imaging AI?" It will name three to five famous ones **from memory** — and that's it. Web search doesn't save it: a few dozen pages at best, whatever it happens to hit.

This project does it the dumb way, which is also the accurate way: **pre-compute vectors for ~300k professors' CVs and keep all the data local**. When your query comes in:

1. **Cast the wide net** — compare semantically against *every one* of the 300k, nobody is skipped;
2. **Then filter and rank** — a deterministic discipline gate kills cross-field noise, then sort by relevance and bucket by age / school tier.

|  | Asking an LLM (even with web search) | Professor Match |
|--|--------------------------------------|-----------------|
| Coverage | A few dozen web pages, hit or miss | **All ~300k professors screened** |
| Who gets found | Famous names it "remembers" | Semantic match — obscure-but-perfect professors surface too |
| Truthfulness | May hallucinate names and topics | Every result maps to a real CV row; paper links are one click away |
| Hard filters | "Age 33–55", "non-top-30" — can't do it | Structured-field filtering |
| What you get | A paragraph of names, gone after the chat | Tiered lists + detail pages + you can even "talk" to the professor |

In short: an LLM is a well-read generalist; this job needs an investigator holding the full census. Full recall first, precise ranking second — that's why the data and vectors must live in your own hands, and why a thin prompt wrapper will never reach this accuracy.

## Show, don't tell 📸

A real query for "deep learning analysis of medical imaging":

**① Match results** — three-tier tabs + grouped by school + expanded keywords. Note the top line: the LLM expanded one Chinese sentence into ten Japanese academic keywords. That's one of the accuracy secrets.

![Match results](docs/screenshots/match.png)

**② Professor detail page** — fully parsed publications on top (peer-review badges, PDF links, one-click citation copy), CV profile on the right. Looks like a finished product? Because it's ported 1:1 from the production app.

![Professor detail](docs/screenshots/detail.png)

**③ AI simulated dialog** — the showpiece. Click "AI dialog" and the model reads this professor's public CV on the spot, then speaks in first person:

![AI dialog](docs/screenshots/chat.png)

> Watch closely: this "Professor Nemoto" (AI role-play — the drawer header clearly says so) opens with his own ML-for-medical-imaging research and asks about *my* background. Not scripted lines — a persona assembled live from each professor's papers and CV. Pick another professor, get a completely different character.

## Three tiers — not one list cut into three

Many "tiers" out there are one relevance ranking chopped into thirds. These are **three independent views over the same recall pool** (overlap allowed):

| Tier | Plainly |
|------|---------|
| **Best match** | Semantically closest to you. The raw-strength tier |
| **Prime age** | Relevant professors aged 33–55. Nobody lists their birthday on researchmap; age is inferred from "PhD in year X", "lecturer since year Y", with confidence levels. Cures the "my professor retired after one year" tragedy |
| **Value picks** | Strong matches at non-top-30 schools. Less competition, easier admission (¬‿¬) |

## Quickstart (self-hosted, zero API keys)

```bash
git clone <your-fork>
cd professor-match
cp .env.example .env

docker compose up -d            # Qdrant + API + web terminal
docker compose run --rm seed    # load the bundled 5,000-professor vector index

# open the deployment terminal:
open http://localhost:8000
```

Why does it run with zero keys? The 5,000 sample professors' vectors are **pre-computed and shipped in the repo**. You only need your own key (DashScope or OpenAI) for two things: embedding **new queries**, or rebuilding the index from **your own data**. Set it in `.env` or in the terminal's Setup tab.

> No Docker, just want to see the algorithm run? `python scripts/verify_pipeline.py` walks the whole retrieve → tier → group chain in memory. Zero dependencies, zero keys ᕕ( ᐛ )ᕗ

## Architecture: small bird, production-grade organs

Two legs, one shared brain — the web terminal is backend-agnostic, so both backends serve the same experience:

```text
                         you (browser)
                              │
               ┌──────────────┴───────────────┐
               │   web terminal web/ (no-build SPA)  │
               └──────┬────────────────┬──────┘
        self-hosted    │                │     live demo
                      ▼                ▼
        ┌──────────────────┐   ┌─────────────────────────┐
        │  FastAPI (api/)  │   │ production sandbox endpoint │
        │  search/tier/chat │   │ (read-only + 3-layer rate │
        └──┬───────────┬───┘   │ limits + auto-ban + kill  │
           ▼           ▼       │ switch)                   │
      ┌─────────┐ ┌──────────┐ └────────────┬────────────┘
      │ Qdrant  │ │ DashScope│              ▼
      │ 5k rows │ │ /OpenAI  │      full production index
      └─────────┘ │ (opt.)   │      (~300k professor vectors
                  └──────────┘       + researchmap CVs + Redis)
```

- **Retrieval**: Qdrant, 1024-dim cosine (DashScope text-embedding-v4), recall 150 candidates per query; region / school rank / school type all live in the vector payload — **filtering happens inside the store, no table round-trips**.
- **Data**: one researchmap-style CV JSON per professor (education / career / papers / awards / patents). In production, ages are **backfilled offline into a side table (140k+ rows)** — read-only at serving time; the open-source port bundles the same estimator and computes live.
- **Dialog**: a five-layer persona prompt (identity anchor / CV memory / keyword trend / methodology / style constraints + per-field anti-hallucination), assembled once per professor and cached; **the chat is fully stateless** — the browser carries the history, the server stores nothing.
- **Protection** (live demo): three-layer rate limits (per-IP hourly / per-IP daily / global daily) + automatic abuse bans + fail-closed (if the cache is down, deny rather than leak) + an env kill switch.

The pipeline a request walks through:

```text
query
  └─▶ keyword expansion     (LLM; optional — no key = degrade to the raw query)
  └─▶ discipline → cate_id  (deterministic hard filter; "economics" never returns law)
  └─▶ embed                 (DashScope text-embedding-v4 / OpenAI)
  └─▶ Qdrant vector search  (+ region / rank / school-type / university filters)
  └─▶ three-tier bucketing  (relevance · prime-age 33–55 · non-top-30 value)
  └─▶ group by school + stats
```

The deterministic core (age estimation, discipline gate, filter conversion, tiering, school grouping) is a **line-by-line faithful port of the production PHP**, watched by behavioural tests (`api/tests/test_core.py`) — historical quirks preserved on purpose, because "tastes like production" is the whole point.

## Performance & cost: what one match actually costs

We count these decimals because production actually pays this bill.

| Stage | Latency (measured, order of magnitude) | Marginal cost (DashScope public pricing, est.) |
|-------|---------------------------------------|-----------------------------------------------|
| LLM keyword expansion | 2–5 s (the bulk of the chain) | a few hundred tokens, ≈ ¥0.002 |
| Query embedding | 200–500 ms | one sentence, ≈ ¥0.0001 |
| Qdrant vector search (~300k) | < 100 ms | 0 (self-hosted) |
| Tiering + grouping + age injection | < 50 ms | 0 (pure CPU, deterministic) |
| **One full match** | **≈ 3–10 s** | **< ¥0.005 (under a US cent)** |
| One AI dialog turn (qwen-max) | 2–4 s | ≈ ¥0.02–0.05 |

The lesson: **retrieval is never the expensive part — the LLM is**. So the architecture saves everywhere:

- keyword expansion **degrades gracefully** — no key, use the raw query, slightly less sharp, completely free;
- persona prompts are **cached per professor** — assembled once, never re-built from the DB;
- corpus vectors are **computed once, reused forever** — the repo ships production-original vectors, so your clone starts with an embedding bill of zero;
- the live demo's **global daily cap seals the worst case** — script it all night, the bill is still pocket change.

## How the accuracy was earned: three rounds of iteration

This pipeline was not written correctly on the first try. A few scars worth sharing with anyone building RAG matching:

**Round 1: the fake-tiers incident.** The original tiers were "popular / niche / hidden gems" — which turned out to be one relevance ranking chopped into three. Called out on the spot ("that's one list cosplaying as three"), torn down, rebuilt: today's tiers are **three independent criteria** (relevance / age window / school tier), each judged separately, overlap allowed.

**Round 2: cross-discipline pollution.** Searching "industrial organization (economics)" returned literature and law professors — vectors think "organization" and "institution" look alike everywhere. Lesson: **semantic search drifts; you need a deterministic gate**. With the discipline hard filter in place, the LLM and the vectors only get to be creative inside the fence. Better to under-recall than to mislabel.

**Round 3: prompt hijacking.** The production version once mixed the user's profile major into query expansion for "personalization". A user whose profile said "geometry" searched "e-commerce" — and got a screen full of geometry keywords. The fix: **the current query owns the topic; conflicting context is ignored**. Prompt engineering lesson one: every piece of context you hand the model is grabbing at the steering wheel.

**The age-estimation obsession.** Nobody lists a birthday, but "PhD in year X" and "lecturer since year Y" exist. Multi-signal inference: explicit record > degree years > first appointment + title conventions, with confidence degrading at each step; **only medium/high confidence qualifies for the prime-age tier**. Better to miss than to be wrong — recommending a 60-year-old as 40 is a hundred times worse than not recommending them.

**Score calibration.** Raw cosine similarity clusters in 0.30–0.62; shown raw, users read "45%" as a bad match (it's actually very good). A monotonic re-stretch to 62–97% lets people read the gaps at a glance. What's being calibrated is human perception, not the cosine.

## Live demo vs self-hosted

|  | Live demo | Self-hosted |
|--|-----------|-------------|
| Professor pool | **~300k** (full production index) | 5,000 sample |
| Install | Nothing | Docker |
| AI dialog | Works out of the box | Works with one LLM key |
| Limits | Read-only + rate-limited: 20 matches per IP per day. The quota is shared worldwide — be kind; aggressive scrapers get auto-banned for 24 h | Go wild |

## The web terminal

A zero-dependency, no-build single-page console — **backend-agnostic**: the same UI connects to your locally self-hosted Python API or (through the read-only sandbox) to the full-scale live deployment. The Setup tab manages connection and runtime config; the Match tab is the full desktop experience from the screenshots above — tier tabs, school-grouped cards, the professor detail page (publications first + CV timelines + awards/patents), and the AI dialog drawer. Card/detail parsing (`web/professor.js`) is line-for-line identical to the production frontend.

Pointing at a different backend? Set `matchPath` / `detailPath` / `chatPath` (with the `{id}` placeholder) in `config.js`.

**Publishing your own demo to GitHub Pages:** the included workflow (`.github/workflows/pages.yml`) deploys `web/` to Pages. Point it at your backend via repository variables `DEMO_API_BASE` (plus optional `DEMO_MATCH_PATH` / `DEMO_DETAIL_PATH` / `DEMO_CHAT_PATH`) under Settings → Actions → Variables; leave them unset and the build ships the same-origin default — forks never silently call someone else's backend.

## Configuration

All via environment (`.env`). The ones that matter:

| Variable | Default | Notes |
|----------|---------|-------|
| `QDRANT_URL` | `http://qdrant:6333` | Vector DB |
| `EMBEDDING_PROVIDER` | `dashscope` | `dashscope` (matches the bundled index) or `openai` |
| `EMBEDDING_API_KEY` / `QWEN_API_KEY` | — | DashScope key (only for embedding new queries) |
| `OPENAI_API_KEY` | — | If using `openai` (different dims → rebuild index) |
| `LLM_PROVIDER` | `dashscope` | Keyword expansion: `dashscope` / `openai` / `none` |
| `DEMO_MODE` | `false` | Set true for a public demo — disables admin config endpoints |
| `ADMIN_TOKEN` | — | Enables the terminal's runtime config (header `X-Admin-Token`) |

> Switching to OpenAI embeddings changes the dimensionality — the bundled DashScope vectors won't match; rebuild with `scripts/build_index.py`.

## Bring your own data

The bundled sample is production-original vectors (zero cost, instant). To use your own professor corpus:

1. Prepare rows as JSONL (`product_id`, `store_name`, `extend`, `school_rank`, `school_name`, `school_type`, `school_region_id`, `cate_id`, `image`); `extend` is a researchmap-style CV JSON.
2. `python scripts/build_index.py --rows data/your_rows.jsonl` (needs an embedding key; re-embeds).

`scripts/export_from_prod.py` is a read-only reference exporter for pulling a sample from a CRMEB-style MySQL + Qdrant source over SSH (configured via `PM_*` env vars).

## Data & privacy

Sample data comes from public [researchmap](https://researchmap.jp) academic profiles (names, affiliations, publication links) — **no contact details, no business data**. The AI dialog is fully stateless: your browser carries the history; the server stores not a single byte. Pseudonymize before publishing your own export if you prefer.

## License

[MIT](LICENSE). Set the copyright holder in `LICENSE` to your own name before publishing your version.

<br/>

<div align="center">

**Haven't tried the demo yet? Last call →** [**https://kafkaesque-luk.github.io/professor-match/**](https://kafkaesque-luk.github.io/professor-match/)

If this saved you a week of clicking through faculty pages, a Star would be lovely ★

</div>
