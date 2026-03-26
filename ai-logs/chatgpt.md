# AI Session Logs — Dodge AI Assignment (Order-to-Cash Graph System)

**Tools Used:** ChatGPT (primary planning & debugging), Claude AI (code generation), Windsurf (editor)  
**Project:** Order-to-Cash Graph API with LLM-powered conversational interface  
**Submission Deadline:** 26th March 2026

---

## Session 1 — Assignment Understanding & Architecture Planning

**Prompt:**
> I got an assignment for a Dodge AI company. Explain the task and also how to do it, everything in free tier. I need to complete it by 26th or before only.

**AI Response Summary:**
- Explained the assignment as building a mini system combining a database, graph model, and chat UI
- Core flow: Dataset (CSV/Excel) → Database → Graph Model → Backend → LLM → Frontend
- Recommended tech stack: Python + FastAPI, SQLite, React + react-force-graph, Google Gemini or Groq (free)
- Provided a 9-step implementation plan: load dataset, store in SQLite, build graph, create API, build graph UI, implement chat with LLM, execute SQL, convert to natural language answer, add guardrails
- Provided a 3-day execution plan: Day 1 (DB + graph), Day 2 (API + UI), Day 3 (LLM + guardrails + deploy)

**My Takeaway:**
Decided to follow the FastAPI + SQLite + Groq (free) stack. Noted the core flow: question → LLM → SQL → result → natural language answer.

---

## Session 2 — Tech Stack Decision (Neo4j vs PostgreSQL vs SQLite)

**Prompt:**
> Why not Neo4j, and why not PostgreSQL? Did they mention any specific tech stack?

**AI Response Summary:**
- Assignment did NOT enforce any tech stack — evaluates reasoning behind choices
- SQLite recommended: zero setup, fast for small datasets, perfect for demo/prototyping
- PostgreSQL not needed: overkill setup for this scale, slows down delivery
- Neo4j avoided because: steep learning curve, LLMs generate SQL much better than Cypher, overengineering risk, and graph can be modelled in-memory and visualized via frontend
- Provided comparison table: SQLite + Graph vs PostgreSQL vs Neo4j across setup time, LLM compatibility, complexity, and interview value

**My Decision:**
Went with SQLite + in-memory graph + Groq. Added justification to README:
> *"We used SQLite for simplicity and leveraged an in-memory graph model, enabling efficient querying via SQL while supporting graph visualization."*

---

## Session 3 — Clarification on UI Screenshots from Assignment

**Prompt:**
> In the assignment, they mentioned a UI. Does that mean I need to use Neo4j?

**AI Response Summary:**
- The UI screenshots showed a graph visualization (nodes + edges + chat panel) — NOT a requirement to use Neo4j
- Assignment only requires: graph representation + visualization
- Can be built using React + vis.js or react-force-graph over relational data
- Suggested framing: *"We implemented a graph abstraction layer over relational data, enabling visualization and traversal without requiring a dedicated graph database."*

**My Change:**
Confirmed approach — built graph structure as nodes/edges JSON from SQLite queries, rendered via frontend graph library.

---

## Session 4 — Session Logs Requirement

**Prompt:**
> They mentioned session logs. How to manage it? Can I do it at the end after completing the project? I am using Windsurf and Claude AI — no automatic export.

**AI Response Summary:**
- Logs should reflect real workflow: prompt → AI response → what I changed → outcome
- Windsurf and Claude web don't export transcripts automatically → manual markdown logs are perfectly valid
- Should include 8–15 meaningful entries showing real thinking, not just copy-paste
- Suggested noting tool used (Claude AI, Windsurf) in a single `ai_logs.md`
- README should state: *"Since Windsurf and Claude web do not provide direct transcript exports, logs were manually curated to reflect key development steps, prompts, and iterations."*

**My Approach:**
Created this structured `ai_logs.md` manually during and after development, capturing key prompts and outcomes.

---

## Session 5 — Project Feasibility in 1 Day

**Prompt:**
> Can I complete this in 1 day?

**AI Response Summary:**
- Yes — possible if building an MVP (minimal viable product) without overengineering
- 1-day plan: 0–3 hrs (backend + data), 3–6 hrs (graph + API), 6–9 hrs (LLM), 9–12 hrs (UI + polish), last 2 hrs (README + deploy)
- Key shortcuts: skip Neo4j, skip auth, skip complex UI, support only 2–3 queries properly
- Evaluation focuses on architecture, reasoning, and LLM usage — not production completeness

**My Approach:**
Built core features only. Supported required queries: highest billing product, full flow trace, broken flows, guardrails.

---

## Session 6 — Dependency Conflict (pydantic / httpx)

**Prompt:**
> Getting error: `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`

**AI Response Summary:**
- Root cause: version mismatch between `groq==0.9.0` and a newer `httpx` that removed the `proxies` argument
- Fix: `pip install httpx==0.27.0`
- Alternatively uninstall and reinstall httpx at the pinned version

**My Fix:**
```bash
pip install httpx==0.27.0
```
Server restarted successfully after this.

---

## Session 7 — Groq Model Deprecated (llama3-70b-8192)

**Prompt:**
> Getting error: `The model llama3-70b-8192 has been decommissioned`

**AI Response Summary:**
- Groq removed the `llama3-70b-8192` model
- Suggested replacement: `llama-3.1-70b-versatile` or `llama-3.1-8b-instant`
- Recommended making model name configurable via `.env` as `MODEL_NAME`

**My Fix:**
Updated `main.py`:
```python
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")
```
And replaced all hardcoded model strings with `model=MODEL_NAME`.

---

## Session 8 — Second Model Deprecation (llama-3.1-70b-versatile)

**Prompt:**
> Now getting: `The model llama-3.1-70b-versatile has been decommissioned`

**AI Response Summary:**
- Groq deprecated this model as well
- Recommended switching to `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`
- Advised checking https://console.groq.com/playground before using any model name

**My Fix:**
Switched to `llama-3.1-8b-instant` — confirmed working in Groq playground first.

---

## Session 9 — API Key Rotation (10 Groq Keys)

**Prompt:**
> I have 10 Groq API keys stored in `.env` for rotation. How to use them instead of a single key?

**AI Response Summary:**
- Store all keys in `.env` as `GROQ_KEY_1`, `GROQ_KEY_2`, ... `GROQ_KEY_10`
- Load and cycle through using Python's `itertools.cycle`
- Provided round-robin rotation logic

**My Implementation:**
```python
import itertools

groq_keys = [v for k, v in os.environ.items() if k.startswith("GROQ_KEY_") and v]
groq_key_cycle = itertools.cycle(groq_keys) if groq_keys else None

def get_groq():
    if not groq_key_cycle:
        raise HTTPException(500, "No GROQ keys configured")
    key = next(groq_key_cycle)
    return Groq(api_key=key)
```
Added to README: *"Implemented API key rotation to handle rate limits and ensure consistent LLM availability."*

---

## Session 10 — Render Deployment Failure (Python 3.14 / pydantic-core)

**Prompt:**
> Render deploy is failing with: `pydantic-core` build error, `Read-only file system`, Python 3.14

**AI Response Summary:**
- Render defaulted to Python 3.14 which has no prebuilt wheels for `pydantic-core`
- It attempted a Rust source build → failed due to read-only filesystem on Render
- Fix: create `runtime.txt` in repo root with content `python-3.11.9`
- Push to GitHub and redeploy — Render will use Python 3.11 which has prebuilt wheels

**My Fix:**
Created `runtime.txt`:
```
python-3.11.9
```
Pushed and redeployed. Build passed successfully.

Added to README: *"Resolved deployment issues by pinning Python to 3.11 to ensure compatibility with pydantic-core and avoid Rust-based build failures."*

---

## Session 11 — Graph Construction Logic

**Prompt:**
> How to convert relational ERP data into a graph format for the Order-to-Cash flow?

**AI Response Summary:**
- Nodes: Customer, SalesOrder, OrderItem, Product, Plant, Delivery, BillingDocument, JournalEntry
- Edges: Customer → SalesOrder → OrderItem → Product, SalesOrder → Delivery → Plant, SalesOrder → BillingDocument → JournalEntry
- Build nodes/edges as Python lists, expose via `/api/graph` endpoint
- No need for a graph database — in-memory representation is sufficient

**My Implementation:**
Built the full graph in `main.py` with all required nodes and edges. Added connection count per node and edge deduplication.

---

## Session 12 — Broken Flows & Guardrails

**Prompt:**
> How to implement broken flows detection and guardrails for unrelated queries?

**AI Response Summary:**
- Broken flows: query for orders delivered but not billed, billed without delivery, cancelled billings, partial deliveries
- Guardrails: keyword pre-filter (check if question contains domain terms), regex blocklist for off-topic patterns (jokes, weather, crypto), LLM-level check returning `IRRELEVANT` signal, block all write SQL operations

**My Implementation:**
- Added `DOMAIN_KEYWORDS` list and `BLOCKED_PATTERNS` regex list
- `is_relevant()` function checks both before any LLM call
- `safe_sql()` function blocks INSERT/UPDATE/DELETE/DROP
- `/api/analysis/broken-flows` endpoint returns 4 anomaly categories with counts

---

## Summary

| Area | Tool Used | Outcome |
|---|---|---|
| Architecture planning | ChatGPT | Finalized SQLite + FastAPI + Groq stack |
| Code generation | Claude AI | Full backend (`main.py`) generated and refined |
| Dependency debugging | ChatGPT | Fixed httpx, pydantic, model deprecation issues |
| API key rotation | ChatGPT | Implemented round-robin Groq key cycling |
| Deployment fix | ChatGPT | Pinned Python 3.11 via `runtime.txt` |
| Graph construction | ChatGPT + Claude | Built full node/edge model from ERP tables |
| LLM prompting | Claude AI | Schema context, SQL generation, answer grounding |
| Guardrails | ChatGPT + Claude | Keyword filter + regex + LLM signal + SQL safety |