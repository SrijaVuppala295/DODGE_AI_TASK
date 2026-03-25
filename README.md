# Order to Cash — Graph Explorer

A graph-based data modeling and query system for the Order-to-Cash business process, with an LLM-powered natural language chat interface.

## Architecture

```
Frontend (React + Vite)          Backend (FastAPI + Python)
┌─────────────────────┐          ┌──────────────────────────┐
│  D3.js Force Graph  │◄─REST───►│  /api/graph              │
│  Chat Interface     │          │  /api/chat               │
│  Node Popups        │          │  /api/schema             │
└─────────────────────┘          └──────────┬───────────────┘
         Vercel                             │         Render
                                  ┌─────────▼──────────┐
                                  │   SQLite Database   │
                                  └─────────┬──────────┘
                                            │
                                  ┌─────────▼──────────┐
                                  │   Groq LLM API      │
                                  │  (llama3-70b-8192)  │
                                  └────────────────────┘
```

## Graph Model

### Nodes
| Type | Source Table | Description |
|---|---|---|
| Customer | business_partners | Buyers / sold-to parties |
| SalesOrder | sales_order_headers | Purchase orders |
| Delivery | outbound_delivery_headers | Shipments |
| BillingDocument | billing_document_headers | Invoices |
| JournalEntry | payments_accounts_receivable | Accounting entries |

### Edges
| From | To | Relationship |
|---|---|---|
| Customer | SalesOrder | placed |
| SalesOrder | Delivery | delivered_via |
| SalesOrder | BillingDocument | billed_as |
| BillingDocument | JournalEntry | posted_to |

## LLM Prompting Strategy

1. **Schema-grounded system prompt** — The LLM receives the full table/column definitions and key relationships on every request.
2. **Two-step generation** — First call generates SQL, second call explains results in natural language.
3. **Zero-shot Text-to-SQL** — Uses `llama3-70b-8192` via Groq for fast, accurate SQL generation.

## Guardrails

- Keyword-based pre-filter checks if the question is domain-relevant before calling the LLM.
- System prompt instructs the LLM to return `IRRELEVANT` for off-topic questions.
- Only `SELECT` queries are executed — no write operations possible.
- Results capped at 100 rows.

## Database Choice

**SQLite** was chosen for:
- Zero-configuration setup
- Sufficient for read-only analytical queries on this dataset size
- Easy to bundle with the backend on Render

## Setup

### 1. Backend

```bash
cd backend
pip install -r requirements.txt

# Load data (point to your dataset folder)
python load_data.py --data-dir /path/to/dataset

# Run server
GROQ_API_KEY=your_key uvicorn main:app --reload
```

### 2. Frontend

```bash
cd frontend
npm install

# Set backend URL
echo "VITE_API_URL=http://localhost:8000" > .env

npm run dev
```

## Deployment

### Backend → Render
1. Push to GitHub
2. New Web Service → connect repo → select `backend/` as root
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add env var: `GROQ_API_KEY`

### Frontend → Vercel
1. New project → connect repo → select `frontend/` as root
2. Add env var: `VITE_API_URL=https://your-render-url.onrender.com`
3. Deploy

## Example Queries

- "Which products are associated with the highest number of billing documents?"
- "Trace the full flow of billing document 90504248"
- "Show sales orders that were delivered but not billed"
- "List customers with cancelled billing documents"
- "What is the total revenue by sales organization?"