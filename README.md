# professor-match

> AI matching of prospective graduate students to Japanese university professors — a RAG
> pipeline (vector search + LLM query expansion + multi-signal tiering) extracted from a
> production system into a clean, self-hostable service. Ships with a **5,000-professor sample
> index**, so it runs end-to-end with **zero API keys** out of the box.

You describe a research interest (in Chinese or Japanese); the system returns matched professors
organized into three independent views:

| Tier | 中文 | What it means |
|------|------|----------------|
| **Best match** | 海选匹配 | Most relevant professors by semantic similarity. |
| **Prime-age** | 年富力强 | Relevant professors confidently estimated to be **33–55** (likely supervising for years), with age inferred from their researchmap CV. |
| **Value picks** | 潜力洼地 | Strong matches at **non-top-30** schools — easier admission / better value. |

The tiers are three *views* over one recall pool (overlap allowed), not a relevance list cut into thirds.

---

## Quickstart

```bash
git clone <your-fork>
cd professor-match
cp .env.example .env

docker compose up -d            # Qdrant + API + web terminal
docker compose run --rm seed    # restore the bundled 5,000-professor vector index

# open the deployment terminal:
open http://localhost:8000
```

Searching the bundled sample needs **no API keys** — the vectors are pre-built. You only need a
key to embed *brand-new* queries (DashScope or OpenAI) or to rebuild the index from your own data.
Set one in `.env`, or configure it live in the terminal's **Setup** tab.

> Want to try the algorithm without Docker? `python scripts/verify_pipeline.py` runs the whole
> retrieval → tiering → grouping chain against the sample in an in-memory Qdrant.

---

## How it works

```text
query
  └─▶ keyword expansion        (LLM; optional — degrades to the raw query)
  └─▶ discipline → cate_id      (deterministic hard filter; "economics" can't return law)
  └─▶ embed                     (DashScope text-embedding-v4 / OpenAI)
  └─▶ Qdrant vector search      (+ payload filters: region / rank / school-type / university)
  └─▶ three-tier bucketing      (relevance · prime-age 33–55 · value non-top-30)
  └─▶ group by school + stats
```

The deterministic core — age estimation, discipline detection, filter conversion, tiering,
school grouping — is a faithful port of the production PHP and is covered by tests
(`api/tests/test_core.py`). The professor age estimator infers a birth year from multiple CV
signals (explicit birth year, degree years, first appointment + title) and reports a confidence;
the prime-age tier keeps only high/medium-confidence ages in `[33, 55]`.

## Configuration

All via environment (`.env`). The important ones:

| Variable | Default | Notes |
|----------|---------|-------|
| `QDRANT_URL` | `http://qdrant:6333` | Vector DB. |
| `EMBEDDING_PROVIDER` | `dashscope` | `dashscope` (matches the bundled index) or `openai`. |
| `EMBEDDING_API_KEY` / `QWEN_API_KEY` | — | DashScope key (only needed to embed new queries). |
| `OPENAI_API_KEY` | — | If using `openai` (different model/dim → rebuild the index). |
| `LLM_PROVIDER` | `dashscope` | Keyword expansion: `dashscope` / `openai` / `none`. |
| `DEMO_MODE` | `false` | Disables admin config endpoints (use for a public demo). |
| `ADMIN_TOKEN` | — | Enables the terminal's live config (sent as `X-Admin-Token`). |

> If you switch to OpenAI embeddings, the dimensionality changes — you must rebuild the index
> (`scripts/build_index.py`); the bundled DashScope vectors are not comparable to OpenAI vectors.

## The web terminal

A single-page, zero-dependency console served at `/`. It is **backend-agnostic** — the API base
is configurable — so the same UI can point at:

- your **self-hosted Python** API (the bundled sample), or
- a **live upstream** deployment (e.g. behind a read-only proxy) for a full-scale preview.

It does double duty: a **Setup** tab (connection, health, runtime provider/key config) and a
**Match** tab (run searches, see the three tiers grouped by school with age and match-score badges).

## Bring your own data

The bundled sample is exact production vectors (zero-cost, instant). To use your own professors:

1. Prepare rows as JSONL (`product_id`, `store_name`, `extend`, `school_rank`, `school_name`,
   `school_type`, `school_region_id`, `cate_id`, `image`). `extend` is a researchmap-style CV JSON.
2. `python scripts/build_index.py --rows data/your_rows.jsonl` (needs an embedding key; re-embeds).

`scripts/export_from_prod.py` is a read-only reference exporter for pulling a sample from an
existing CRMEB-style MySQL + Qdrant source over SSH (configure via `PM_*` env vars).

## Project layout

```text
api/        FastAPI service
  app/      pipeline + deterministic core + providers + qdrant client
  tests/    behavioural tests for the core
  seed.py   restore the snapshot into Qdrant
web/        the deployment terminal (static, no build)
data/       professors_5000.jsonl.gz + qdrant_snapshot/ (pre-built vectors)
scripts/    export / build_index / verify
```

## Development

```bash
cd api && pip install -r requirements.txt && python -m pytest -q
```

## Data & privacy

The sample is drawn from public [researchmap](https://researchmap.jp) academic profiles (names,
affiliations, publication links). It contains no contact details and no business data. If you
prefer, pseudonymize before publishing your own export.

## License

[MIT](LICENSE). Set the copyright holder in `LICENSE` to your name/org before publishing.

---

## 中文说明

**professor-match** 是把一套生产中的「AI 教授匹配」功能抽离成的独立、可自部署服务：输入研究兴趣
（中文或日文），按语义检索匹配的日本大学教授，分三档呈现——**海选匹配**（最相关）、**年富力强**
（据履历推算 33–55 岁、还能稳妥带人）、**潜力洼地**（非顶尖校、性价比高）。三档是同一召回池的三个
独立视角，允许重叠。

仓库自带 **5000 位教授的预建向量索引**，`docker compose up` + `docker compose run --rm seed`
即可**零密钥**端到端运行。只有在为**新查询**做嵌入或用**自有数据**重建索引时才需要 DashScope /
OpenAI 密钥（在 `.env` 或终端「设置」页填写）。

**算法忠实性**：年龄估算、学科硬过滤、筛选转换、三档分桶、按校分组等确定性逻辑，是对生产 PHP 的
逐行移植，并有测试覆盖（`api/tests/`）。检索复用生产同款嵌入模型与向量，结果与生产同源。

**网页终端**后端无关：同一套界面既能连本机自部署的 Python，也能（经只读代理）连线上满血部署做效果预览。

数据来自公开的 [researchmap](https://researchmap.jp) 学术主页，不含联系方式与业务数据。
