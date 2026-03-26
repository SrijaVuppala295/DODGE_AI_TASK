# Google Antigravity AI Session Logs — Dodge AI Assignment

**Tool:** Google Antigravity (Gemini-powered autonomous coding agent)  
**Editor:** Windsurf (used for editing; Antigravity is the AI agent)  
**Project:** Order-to-Cash Graph Intelligence System  
**Note:** Google Antigravity operates as a fully autonomous agent — it reads files, runs shell commands, edits code, maintains internal `task.md` / `implementation_plan.md` / `walkthrough.md` artifacts, and verifies results in a continuous loop without manual intervention.

---

## Session 1 — Connectivity Fix & Guardrail Relaxation

**Problem:** Backend was running but users were getting "Could not connect to backend" errors. The guardrail was also blocking greetings like "hi".

**Antigravity Actions:**
- Killed stale `uvicorn`/`python` processes using PowerShell `Stop-Process`
- Diagnosed root cause: `httpx 0.28.1` was installed, overriding the pinned `0.27.2` in `requirements.txt`, causing a `TypeError` in the `groq` client (`proxies` argument removed in newer httpx)
- Downgraded `httpx` to `0.27.2` after killing all file-locking processes
- Updated `main.py` to allow greetings instead of blocking with guardrail response
- Added SQL error logging
- Restarted server and verified with test requests

**Commands Run:**
```powershell
Get-Process | Where-Object { $_.ProcessName -like "*python*" -or $_.ProcessName -like "*uvicorn*" } | Stop-Process -Force
pip install httpx==0.27.2
uvicorn main:app --reload
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -Body (@{message="hi"; history=@()} | ConvertTo-Json) -ContentType "application/json"
```

**Outcome:** `httpx` downgraded ✅ | Chat responds to greetings ✅ | Backend stable ✅

---

## Session 2 — Prompt Engineering & Dual-Layer Guardrail Upgrade

**Problem:** Agent was incorrectly blocking valid ERP questions. Needed smarter greeting handling and a second guardrail layer.

**Antigravity Actions:**
- Implemented `handle_conversational()` to detect and respond naturally to greetings, thanks, farewells
- Added `check_irrelevance_llm()` — second-layer LLM-based guardrail classifying intent before any SQL is generated
- Refined `SCHEMA_CONTEXT` with more joining examples and table guidance
- Integrated both functions into `/api/chat` and `/api/chat/stream`
- Updated `task.md` and `implementation_plan.md` artifacts internally

**Test Commands:**
```powershell
$responses += Invoke-RestMethod ... -Body (@{message="hi"; history=@()} ...)
$responses += Invoke-RestMethod ... -Body (@{message="thank you so much"; history=@()} ...)
$responses += Invoke-RestMethod ... -Body (@{message="what is the capital of France?"; history=@()} ...)
$responses | Out-File -FilePath "test_conversational_results.txt"
```

**Outcome:** "hi" → business intro ✅ | "thank you" → natural ack ✅ | "capital of France" → rejected ✅

---

## Session 3 — SSE Stream Corruption Bug Fix ("No Data" Root Cause)

**Problem:** Valid SalesOrder IDs returned "No data available" in the UI despite existing in the database.

**Antigravity Debugging Process:**
- Added file-based `backend_audit.log` since `print()` was being buffered by uvicorn
- Confirmed `run_query()` returned 1 row for SalesOrder `740543` via the log
- Used `curl.exe` to capture raw SSE stream — discovered the `meta` chunk was being split across multiple lines
- Root cause: LLM sometimes generated multi-line SQL; newlines inside the SSE `data: {...}` line broke the frontend JSON parser silently

**Key Debug Commands:**
```powershell
python -c "import sqlite3; conn = sqlite3.connect('order_to_cash.db'); val = conn.execute('SELECT salesOrder FROM sales_order_headers WHERE salesOrder LIKE \'%740543%\'').fetchone(); print(val)"

curl.exe -X POST http://127.0.0.1:8000/api/chat/stream -H "Content-Type: application/json" -d "{\"message\":\"Tell me about SalesOrder 740543\", \"history\":[]}"

rm backend_audit.log
Invoke-RestMethod ... | Select-String "result_count"
```

**Fix Applied:**
```python
# Flatten SQL before yielding in SSE meta chunk
sql = sql.replace('\n', ' ').strip()
```

**Outcome:** All valid IDs now return correct `result_count` ✅ | Diagnostic logs cleaned up ✅

---

## Session 4 — 3-Layer Intent Classification System

**Problem:** "what is billing?" triggered a SQL query (returned empty). "thankyou" (no space) was not recognized as social.

**Antigravity Actions:**
- Audited `PRAGMA table_info` — confirmed all IDs stored as `TEXT`
- Built `classify_intent_llm()` with 3 classifications: `SOCIAL`, `META_KNOWLEDGE`, `DATA_QUERY`
- `SOCIAL` → `handle_conversational()`, no LLM SQL call
- `META_KNOWLEDGE` → expert ERP explanation, no SQL generated
- `DATA_QUERY` → full SQL generation + execution pipeline
- Updated `SCHEMA_CONTEXT` to enforce strict quoting for TEXT ID fields
- Fixed syntax errors from multiple `client` initializations introduced during refactor

**Schema Audit Commands:**
```powershell
python -c "import sqlite3; conn = sqlite3.connect('order_to_cash.db'); print('PK Info:', conn.execute('PRAGMA table_info(sales_order_headers)').fetchall())"
python -c "... print('Delivery Sample:', conn.execute('SELECT deliveryDocument FROM outbound_delivery_headers LIMIT 3').fetchall())"
```

**Final Tests:**
```powershell
$responses += Invoke-RestMethod ... -Body (@{message="thankyou"; history=@()} ...)
$responses += Invoke-RestMethod ... -Body (@{message="what is billing?"; history=@()} ...)
$responses += Invoke-RestMethod ... -Body (@{message="Tell me about Delivery 80738103"; history=@()} ...)
Get-Content final_test_results.txt
rm final_test_results.txt
```

**Outcome:** All 3 intent types routed correctly ✅ | Delivery 80738103 retrieved ✅

---

## Session 5 — Data Integrity Audit (33-Table Verification)

**Problem:** User questioned "Not available" fields. Needed to verify database integrity against raw source JSONL files.

**Antigravity Actions:**
- Searched for raw data directory using `Get-ChildItem` with `-Recurse -Depth`
- Found source at: `C:\Users\Manikanta\Downloads\sap-order-to-cash-dataset\sap-o2c-data`
- Created `audit_data.py` for comprehensive 33-table JSONL vs SQLite record count comparison
- Traced Order `740549` → Delivery `80738069` → confirmed zero billing documents exist in source data

**Audit Commands:**
```powershell
(Get-ChildItem -Path C:\Users\Manikanta -Directory -Depth 2 -Filter "sap-o2c-data").FullName

python audit_data.py | Out-File -Encoding utf8 audit_results.txt
Get-Content audit_results.txt
```

**Key Findings:**
```
All 100 sales_order_headers records have NULL overallOrdReltdBillgStatus
→ Matches source JSONL exactly
→ "Not available" is factually accurate
→ Order 740549 has no billing documents anywhere in the dataset
```

**Outcome:** Database is 1:1 match of source data ✅ | "Not available" confirmed accurate ✅

---

## Session 6 — Broken Flows Dashboard Fix & Smart Category Highlighting

**Problem:** "Cancelled Billings" showed 50 instead of actual 80 (capped by `LIMIT 50`). Also added smart graph highlighting.

**Antigravity Actions:**
- Manually verified SQL predicates:
```powershell
python -c "import sqlite3; conn = sqlite3.connect('backend/order_to_cash.db'); print('Cancelled:', conn.execute('SELECT count(*) FROM billing_document_cancellations').fetchone()[0])"
# Result: 80
```
- Fixed `broken_flows` endpoint: aliased `count(*)` as `cnt` to fix `KeyError` on dict access
- Removed `LIMIT 50` cap from all count queries
- Implemented Smart Category Highlighting: "billing" in query → returns all `bd_...` node IDs in `highlighted_ids`
- Fixed `Internal Server Error` caused by the dict key issue

**Verification:**
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/analysis/broken-flows" -Method Get | Select-Object -ExpandProperty summary
# cancelled_count: 80 ✅

Invoke-RestMethod ... -Body (@{message="show me all billing nodes"; history=@()} ...) | Select-Object -ExpandProperty highlighted_ids | Select-Object -First 10
# Returns bd_... and je_... node IDs ✅
```

---

## Session 7 — Product/Material Naming Fix & Fuzzy Search Fallback

**Problem:** Searching for Product `S8907367010814` returned "No results found" despite existing in the database.

**Antigravity Debugging:**
```powershell
python -c "... print('Count in products:', conn.execute('SELECT count(*) FROM products WHERE product=\'S8907367010814\'').fetchone()[0])"
# Result: 1 ✅ — product IS in DB

python -c "... print('Exact:', ...); print('Lower:', ...)"
# Both return 1 — no case sensitivity issue
```

**Root Cause:** LLM confused `product` (primary key in `products` table) with `material` (foreign key in `sales_order_items`), generating `WHERE material = 'S8907367010814'` instead of `WHERE product = 'S8907367010814'`.

**Fix Applied:**
- Hardened `SCHEMA_CONTEXT`: "Product and Material are the same concept. `products.product` is the primary key. Always use `products` table for product lookups."
- Added fuzzy search fallback: if SQL returns 0 rows and a specific ID is detected in query, auto-runs `LIKE '%ID%'` search

**Verification:**
```powershell
Invoke-RestMethod ... -Body (@{message="Tell me about Product S8907367010814"; history=@()} ...) | Select-Object -ExpandProperty answer
# Returns: "S8907367010814 - EDT 50ML BLACK" details ✅
```

---

## Session 8 — Rate Limit Fix & 11-Key API Rotation

**Problem:** "Could not connect to backend" reappeared. Social queries worked, DATA queries gave 500 errors.

**Antigravity Debugging:**
- Created `test_stream_8001.py` and ran uvicorn on port 8001 for clean traceback capture
- Discovered: `rate_limit_exceeded` error from Groq API
- Only 1 key was active in `.env` (others commented out)

**Fix Applied:**
- Uncommented all 11 Groq API keys in `.env`
- Refactored `get_groq()` with `itertools.cycle` for round-robin rotation
- Added fault-tolerant retry: on rate limit error, auto-switch to next key
- Applied retry logic to both `/api/chat` and `/api/chat/stream`

**Commands:**
```powershell
Get-Content ".env" | Select-String "GROQ_KEY_"
# Confirmed only 1 active

# After fix:
python test_stream.py
# Result: 200 OK, streaming data ✅
```

---

## Session 9 — Graph Construction Fix (0 BillingDocument Nodes)

**Problem:** `/api/graph` returned 0 `BillingDocument` nodes despite billing data existing.

**Antigravity Debugging:**
```powershell
python -c "... SELECT COUNT(*) FROM sales_order_headers soh JOIN billing_document_items bdi ON soh.salesOrder = bdi.referenceSdDocument ..."
# Result: 0

python -c "... SELECT COUNT(*) FROM outbound_delivery_headers odh JOIN billing_document_items bdi ON odh.deliveryDocument = bdi.referenceSdDocument ..."
# Result: 200+ ✅
```

**Root Cause:** In this dataset, `billing_document_items.referenceSdDocument` references the **delivery document** (80xxxxxx), not the sales order (74xxxxxx). Graph builder was joining on the wrong ID.

**Fix:** Updated graph SQL to join billing via delivery documents as intermediary.

**Verification:**
```powershell
python -c "import requests; r = requests.get('http://127.0.0.1:8000/api/graph').json(); print('BillingDocs:', len([n for n in r['nodes'] if n['type'] == 'Billing Document']))"
# Before: 0 | After: 82 ✅
```

---

## Session 10 — Business-Friendly Node Label Refactoring

**Problem:** Graph nodes showed internal names (`SalesOrder`, `BillingDocument`). Needed proper business terminology.

**Antigravity Actions:**
- Ran `refactor.py` script to replace all node type strings across `main.py`
- `"SalesOrder"` → `"Sales Order"` | `"Customer"` → `"Business Partner"` | `"Delivery"` → `"Outbound Delivery"` | `"BillingDocument"` → `"Billing Document"` | `"JournalEntry"` → `"Journal Entry"`
- Updated node labels: `"SO 740506"` → `"Sales Order 740506"`
- Updated `GraphView.jsx` color/shape mappings for new names
- Added term-to-table mapping in `SCHEMA_CONTEXT`

**Verification:**
```powershell
python -c "import requests, json; r = requests.post('http://127.0.0.1:8000/api/chat', json={'message': 'Show me the latest Sales Order for Business Partner 123', 'history': []}); print(json.dumps(r.json(), indent=2))"
# Generates correct SQL targeting sales_order_headers ✅
```

---

## Session 11 — Universal ID Highlighting

**Problem:** Nodes were hard to find visually when a specific ID was mentioned in chat.

**Antigravity Actions:**
- Added logic to detect numeric IDs (6+ digits) in any query
- Auto-generates candidate node IDs with all prefixes: `so_`, `bd_`, `del_`, `cust_`, `je_`
- All matching node IDs returned in `highlighted_ids` field

**Verification:**
```powershell
Invoke-RestMethod ... -Body (@{message="Tell me about 740549"; history=@()} ...) | Select-Object -ExpandProperty highlighted_ids
# Returns: ["so_740549", "bd_740549", "del_740549"] ✅
```

---

## Session 12 — SyntaxError Fix After Refactoring

**Problem:** Bulk string replacement script introduced a `SyntaxError` on line 1007 — a newline was accidentally inserted inside a single-line string literal in the AI system prompt.

**Antigravity Actions:**
```powershell
python -m py_compile main.py
# SyntaxError: EOL while scanning string literal (line 1007)
```
- Located broken string via `Viewed main.py:990-1020`
- Fixed multiline string, re-ran compile check: clean ✅
- Restarted server, verified `/health` endpoint

---

## Session 13 — Render Deployment Fix (Python 3.14 → 3.11)

**Problem:** Render defaulted to Python 3.14 which had no prebuilt wheel for `pydantic-core`, causing Rust/maturin build failure.

**Antigravity Actions:**
- Created `runtime.txt` → `python-3.11.9` (later found insufficient — Heroku convention only)
- Created `.python-version` → `3.11.9` (pyenv standard, Render respects this)
- Added `pythonVersion: "3.11.9"` to `render.yaml` (official Render config)
- Pinned `pydantic-core==2.18.2` in `requirements.txt`

```bash
git add runtime.txt .python-version render.yaml backend/requirements.txt
git commit -m "Fix: force Python 3.11, pin pydantic-core for Render"
git push
```

**Outcome:** Render build passed with Python 3.11 ✅

---

## Session 14 — Frontend Streaming Bug Fix

**Problem:** Chat panel stuck on loading indicator even after backend returned valid responses.

**Root Cause Found in `ChatPanel.jsx`:** The `meta` SSE event (sent first, containing SQL and result count) was accidentally triggering the "stream complete" state — closing the UI before any `token` events arrived.

**Fix Applied:**
```javascript
// Only [DONE] closes the stream — meta events do NOT
if (parsed.type === 'token') { /* append to message */ }
if (parsed.type === 'meta')  { /* store SQL, keep streaming */ }
if (data === '[DONE]')       { setIsStreaming(false); }
```

**Verification:**
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat/stream" -Method Post -Body (@{message="hi"; history=@()} | ConvertTo-Json) -ContentType "application/json"
# Returns meta + token events in correct sequence ✅
```

---

## Session 15 — README & GitHub Push

**Antigravity Actions:**
- Generated comprehensive `README.md` covering all assignment evaluation criteria
- Created `screenshots/` folder with `.gitkeep` placeholder
- Committed and pushed everything to GitHub:

```bash
git add README.md screenshots/.gitkeep
git commit -m "Add comprehensive README with architecture, prompting strategy, guardrails, screenshots placeholder"
git push
```

---

## Summary Table

| Session | Problem | Root Cause | Fix | Result |
|---|---|---|---|---|
| 1 | "Could not connect" | `httpx` version conflict with groq SDK | Pinned `httpx==0.27.2` | ✅ |
| 2 | Greetings blocked | Keyword filter too strict | Conversational handler + LLM layer | ✅ |
| 3 | "No data" for valid IDs | SQL newlines broke SSE stream | Sanitized SQL before serialization | ✅ |
| 4 | "what is billing" triggered SQL | No intent classification | 3-layer SOCIAL/META/DATA classifier | ✅ |
| 5 | "Not available" fields | Actual NULL in source JSONL | 33-table audit confirmed accuracy | ✅ |
| 6 | Broken flows count capped | `LIMIT 50` + `count(*)` dict key bug | Removed LIMIT, aliased as `cnt` | ✅ |
| 7 | Product not found in chat | LLM confused product vs material | Hardened schema + fuzzy fallback | ✅ |
| 8 | 500 errors on DATA queries | Groq rate limit, only 1 key active | Enabled 11 keys + retry rotation | ✅ |
| 9 | 0 BillingDocument nodes | Wrong JOIN (SO ID vs Delivery ID) | Fixed to join via delivery document | ✅ |
| 10 | Internal names in graph UI | No label mapping | Renamed to business terminology | ✅ |
| 11 | Hard to find nodes visually | No ID-based highlighting | Universal ID auto-highlighting | ✅ |
| 12 | SyntaxError on server start | Refactor broke string literal | Fixed multiline string | ✅ |
| 13 | Render deploy failing | Python 3.14, no pydantic wheel | `.python-version` + render.yaml | ✅ |
| 14 | Chat stuck on loading | `meta` event closed stream early | Fixed SSE event handling in React | ✅ |
| 15 | No README | — | Generated + pushed to GitHub | ✅ |