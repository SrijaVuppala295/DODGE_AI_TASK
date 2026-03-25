"""
Order-to-Cash Graph API — FINAL COMPLETE BACKEND

Requirement 1: Graph Construction
  - All entity nodes: Customer, SalesOrder, OrderItem, Product, Plant,
    Delivery, DeliveryItem, BillingDocument, BillingItem, JournalEntry
  - All required edges: PO→Item, Item→Material, Delivery→Plant, Customer→Delivery

Requirement 2: Graph Visualization data
  - /api/graph — full graph with metadata
  - /api/node/{id}/expand — expand any node's children
  - /api/node/{id}/metadata — rich metadata for popup

Requirement 3: Conversational Query Interface
  - /api/chat — non-streaming with full history
  - /api/chat/stream — SSE streaming with history
  - Detects trace intent → calls trace endpoint automatically
  - All answers grounded in real DB data

Requirement 4: Example Queries
  - a) Products with most billing docs → SQL
  - b) Trace full flow → dedicated /api/trace endpoint with step-by-step flow
  - c) Broken flows → /api/analysis/broken-flows with 4 categories

Requirement 5: Guardrails
  - Keyword pre-filter (fast, no LLM call)
  - LLM-level IRRELEVANT signal
  - Write-operation block
  - Returns structured guardrail response

Bonus: Streaming, conversation memory, node highlighting, semantic search
"""

import os, sqlite3, json, re, itertools
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(env_path)


from fastapi import FastAPI, HTTPException, Query as QParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from groq import Groq

app = FastAPI(title="Order to Cash API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

DB_PATH = os.path.join(os.path.dirname(__file__), "order_to_cash.db")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")


groq_keys = [v for k, v in os.environ.items() if k.startswith("GROQ_KEY_") and v]

if not groq_keys:
    fallback_key = os.getenv("GROQ_API_KEY", "")
    if fallback_key:
        groq_keys = [fallback_key]

groq_key_cycle = itertools.cycle(groq_keys) if groq_keys else None

# ──────────────────────────────────────────────────────────────
# DB HELPERS
# ──────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_query(sql: str, params=()):
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_groq():
    if not groq_key_cycle:
        raise HTTPException(500, "No GROQ keys configured")
    # Return a factory that handles retries across keys
    return next(groq_key_cycle)

def call_groq_with_retry(func, *args, **kwargs):
    """Retries a Groq call across different keys if rate limited."""
    for _ in range(len(groq_keys) or 1):
        key = next(groq_key_cycle)
        client = Groq(api_key=key, timeout=20.0)
        try:
            # We need to set the client on the completion call if passed as a method
            return func(client, *args, **kwargs)
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                print(f"WARN: Key rate limited, trying next...")
                continue
            raise e
    raise HTTPException(503, "All Groq keys are currently rate-limited. Please wait a moment.")


# ──────────────────────────────────────────────────────────────
# SCHEMA CONTEXT — comprehensive for Text-to-SQL
# ──────────────────────────────────────────────────────────────
SCHEMA_CONTEXT = """
You are a SQL expert for an Order-to-Cash ERP SQLite database.

STRICT RULES:
1. ONLY generate SELECT queries. NEVER INSERT, UPDATE, DELETE, DROP, CREATE, ALTER.
2. LIMIT to 100 rows max unless user explicitly asks for all.
3. Return ONLY raw SQL without markdown or backticks.
4. If the question is completely unrelated to ERP (Orders, Deliveries, Billing, Partners, Products, Journal Entries, Payments), return: IRRELEVANT.
5. If the user refers to an earlier document in conversation, use appropriate WHERE filters.

TABLES & KEY COLUMNS:
- sales_order_headers (salesOrder PK, soldToParty, totalNetAmount, overallDeliveryStatus[A=Not, C=Full], overallOrdReltdBillgStatus[A=Not, C=Full])
- sales_order_items (salesOrder, salesOrderItem, material[=product ID], netAmount)
- outbound_delivery_headers (deliveryDocument PK, overallGoodsMovementStatus)
- outbound_delivery_items (deliveryDocument, referenceSdDocument[=salesOrder], plant)
- billing_document_headers (billingDocument PK, totalNetAmount, accountingDocument, soldToParty, billingDocumentIsCancelled['true'/'false'])
- billing_document_items (billingDocument, material[=product ID], referenceSdDocument[=salesOrder])
- business_partners (customer PK, businessPartnerFullName, industry)
- products (product PK, productType)
- product_descriptions (product, language['EN'], productDescription)
- payments_accounts_receivable (accountingDocument PK, companyCode, fiscalYear, glAccount, amountInTransactionCurrency, transactionCurrency, postingDate, clearingDate, customer)
  NOTE: 'Journal Entry' maps to this table. accountingDocument is the Journal Entry ID.

JOIN EXAMPLES:
- Product Details: SELECT p.*, pd.productDescription FROM products p LEFT JOIN product_descriptions pd ON p.product=pd.product WHERE p.product = 'S8907367010814' AND (pd.language='EN' OR pd.language IS NULL)
- SO to Billing: FROM sales_order_headers soh JOIN billing_document_items bdi ON soh.salesOrder = bdi.referenceSdDocument
- Top Products: SELECT pd.productDescription, COUNT(*) as cnt FROM billing_document_items bdi JOIN product_descriptions pd ON bdi.material=pd.product GROUP BY 1 ORDER BY 2 DESC
- Journal Entry: SELECT * FROM payments_accounts_receivable WHERE accountingDocument = '9400172476'
- Billing to Journal: SELECT par.* FROM payments_accounts_receivable par JOIN billing_document_headers bdh ON par.accountingDocument = bdh.accountingDocument WHERE bdh.billingDocument = '90000001'

QUERY TIPS:
- 'Product Lookup': When asked about a specific product/material by ID, search the 'products' table using 'product' column. Note that 'material' in other tables is the same as 'product' in the products table.
- 'Cancelled': billingDocumentIsCancelled='true'
- 'Journal Entry' / 'Accounting Document': use the payments_accounts_receivable table, filter by accountingDocument column.
- IMPORTANT: All IDs (salesOrder, deliveryDocument, material, product, customer, accountingDocument) are TEXT columns. ALWAYS use single quotes even for numbers (e.g., WHERE accountingDocument = '9400172476').
"""

# ──────────────────────────────────────────────────────────────
# REQUIREMENT 5: GUARDRAILS
# ──────────────────────────────────────────────────────────────
DOMAIN_KEYWORDS = [
    "order","deliver","billing","invoice","payment","customer","product",
    "material","plant","journal","sales","shipment","document","account",
    "amount","quantity","status","partner","address","region","currency",
    "fiscal","company","flow","trace","find","show","list","count","which",
    "how many","total","highest","lowest","broken","incomplete","cancel",
    "revenue","billed","unbilled","shipped","entry","top","sold","purchase",
    "transaction","item","line","header","reference","storage","warehouse",
    "dispatch","credit","debit","gl","accounting","what","who","when","where",
    "profit","cost","center","organization","division","area","schedule","plant",
    "vendor","supplier","material","batch","stock","inventory","dispatch",
    "hi","hello","hey","greetings","good morning","good afternoon","hii",
    "thanks","thank you","thx","great","awesome","good job","perfect","ok","okay",
    "bye","goodbye","exit","quit","see ya"
]
BLOCKED_PATTERNS = [
    r"write (me |us )?(a |an )?(poem|story|essay|song|joke|code)",
    r"(what|who) is (the )?(president|prime minister|ceo of (?!our|the company))",
    r"(weather|forecast|temperature) (in|at|for)",
    r"(recipe|cook|bake) (for|a|the)",
    r"(bitcoin|crypto|ethereum|stock price)",
    r"(capital of|history of|geography)",
    r"(movie|film|tv show|music|celebrity)",
    r"tell me (a |about )?(joke|story|fun fact)",
]

def is_relevant(q: str) -> bool:
    ql = q.lower().strip()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, ql):
            return False
    # Relaxed keyword check for greetings (already handled by handle_greeting but safe here)
    if any(k in ql for k in ["hi", "hello", "hey"]): return True
    return any(k in ql for k in DOMAIN_KEYWORDS)

def classify_intent_llm(q: str) -> str:
    """Classifies user intent: DATA, SOCIAL, META, or IRRELEVANT."""
    def _classify(client):
        return client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": """Classify user intent for an Order-to-Cash ERP AI:
- DATA: Asking for specific records (orders, billing, delivery, customers, products, journal entries, payments) or stats from DB.
- SOCIAL: Greetings, appreciation (thanks), or closings (bye).
- META: Asking for definitions of ERP concepts (what is billing, how does sales work, explain plants).
- IRRELEVANT: Anything outside the scope of business ERP (politics, news, general facts, jokes).
Return ONLY the category name."""},
                {"role": "user", "content": q}
            ],
            temperature=0, max_tokens=10
        )
    resp = call_groq_with_retry(_classify)
    res = resp.choices[0].message.content.strip().upper()
    for cat in ["DATA", "SOCIAL", "META", "IRRELEVANT"]:
        if cat in res: return cat
    return "IRRELEVANT"

def safe_sql(sql: str) -> bool:
    s = sql.upper().strip()
    return not any(s.startswith(op) for op in
                   ["INSERT","UPDATE","DELETE","DROP","CREATE","ALTER","TRUNCATE","EXEC"])

def detect_trace_intent(q: str):
    """Returns (doc_type, doc_id) if user is asking to trace a specific document."""
    q = q.lower()
    # Match billing document trace
    m = re.search(r"(billing|bill|invoice|document)\s+(?:document\s+)?(?:#|no\.?|number\s+)?(\d{7,12})", q)
    if m:
        return ("billing", m.group(2))
    # Match sales order trace
    m = re.search(r"(sales\s+order|so|order)\s+(?:#|no\.?|number\s+)?(\d{7,12})", q)
    if m:
        return ("salesorder", m.group(2))
    return None

def handle_conversational(q: str):
    """Returns a natural response for simple non-data conversational phases."""
    ql = q.lower().strip().rstrip("?!.")
    
    greetings = ["hi", "hello", "hey", "greetings", "good morning", "good afternoon", "hii"]
    if ql in greetings or any(ql.startswith(g + " ") for g in greetings):
        return {
            "type": "greeting",
            "answer": "Hello! I'm your **Order-to-Cash AI**. I can help you analyze orders, deliveries, billing documents, and find process bottlenecks in your graph. What would you like to explore today?",
            "sql": None, "results": [], "highlighted_ids": [], "flow": None
        }
        
    appreciation = ["thanks", "thank you", "thx", "great", "awesome", "good job", "perfect", "ok", "okay"]
    if any(word == ql for word in appreciation) or ql.startswith(("thank you", "thanks")):
        return {
            "type": "greeting",
            "answer": "You're very welcome! I'm happy to help. Let me know if you have more questions about your orders, deliveries, or customers.",
            "sql": None, "results": [], "highlighted_ids": [], "flow": None
        }
        
    closings = ["bye", "goodbye", "exit", "quit", "see ya"]
    if ql in closings:
        return {
            "type": "greeting",
            "answer": "Goodbye! Have a great day ahead. Feel free to return if you need more ERP data insights.",
            "sql": None, "results": [], "highlighted_ids": [], "flow": None
        }
        
    return None

GUARDRAIL_RESPONSE = {
    "type": "guardrail",
    "answer": "This system is designed to answer questions related to the provided dataset only. Please ask about orders, deliveries, billing documents, payments, customers, or products.",
    "sql": None,
    "results": [],
    "highlighted_ids": [],
    "flow": None
}

# ──────────────────────────────────────────────────────────────
# HEALTH & SCHEMA
# ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Order to Cash API backend is running. Use /health or /api/graph for details."}

@app.get("/health")
def health():
    return {"status": "ok", "db": os.path.exists(DB_PATH), "groq": bool(groq_keys)}

@app.get("/api/schema")
def schema():
    conn = get_db()
    tables = {}
    try:
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            t = row[0]
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            tables[t] = {"columns": cols, "rowCount": count}
    finally:
        conn.close()
    return tables

# ──────────────────────────────────────────────────────────────
# REQUIREMENT 1: GRAPH CONSTRUCTION
# ──────────────────────────────────────────────────────────────
@app.get("/api/graph")
def get_graph():
    nodes, edges = [], []

    # 1. Multi-Anchor Seed: Random Customers + Random Billing Docs + Random Journal Entries
    # This guarantees all requested entity types are present in the graph.
    
    # Anchor 1: 10 random customers
    cust_data = run_query("SELECT customer FROM business_partners LIMIT 10")
    # Anchor 2: 10 random billing documents
    bill_data = run_query("SELECT billingDocument, soldToParty FROM billing_document_headers LIMIT 10")
    # Anchor 3: 10 random journal entries
    je_data = run_query("SELECT accountingDocument, customer FROM payments_accounts_receivable LIMIT 10")

    # Collect all customer IDs from these anchors
    all_cust_ids = set()
    for c in cust_data: 
        if c.get('customer'): all_cust_ids.add(c['customer'])
    for b in bill_data: 
        if b.get('soldToParty'): all_cust_ids.add(b['soldToParty'])
    for j in je_data:
        if j.get('customer'): all_cust_ids.add(j['customer'])

    if not all_cust_ids:
        return {"nodes": [], "edges": []}

    # Final list of customers to seed the graph
    cust_sql = ",".join(f"'{c}'" for c in all_cust_ids)
    customers = run_query(f"""
        SELECT bp.customer, bp.businessPartnerFullName, bp.businessPartnerName,
               bp.industry, bp.businessPartnerIsBlocked, bp.businessPartnerCategory,
               bpa.cityName, bpa.country, bpa.region
        FROM business_partners bp
        LEFT JOIN business_partner_addresses bpa ON bp.businessPartner = bpa.businessPartner
        WHERE bp.customer IN ({cust_sql})
    """)
    cust_map = {}
    for c in customers:
        nid = f"cust_{c['customer']}"
        label = c['businessPartnerFullName'] or c['businessPartnerName'] or f"Business Partner {c['customer']}"
        nodes.append({"id": nid, "type": "Business Partner", "label": label[:35], "data": dict(c), "connections": 0})
        cust_map[c['customer']] = nid

    cust_sql = ",".join(f"'{k}'" for k in cust_map)

    # ── SALES ORDERS (Smarter Seed selection) ──────────────────
    orders = run_query(f"""
        SELECT * FROM (
            SELECT salesOrder, salesOrderType, soldToParty, totalNetAmount,
                   overallDeliveryStatus, overallOrdReltdBillgStatus,
                   creationDate, transactionCurrency, requestedDeliveryDate,
                   salesOrganization, distributionChannel
            FROM sales_order_headers
            WHERE soldToParty IN ({cust_sql})
            LIMIT 40
        )
        UNION
        SELECT * FROM (
            SELECT DISTINCT soh.salesOrder, soh.salesOrderType, soh.soldToParty, soh.totalNetAmount,
                   soh.overallDeliveryStatus, soh.overallOrdReltdBillgStatus,
                   soh.creationDate, soh.transactionCurrency, soh.requestedDeliveryDate,
                   soh.salesOrganization, soh.distributionChannel
            FROM sales_order_headers soh
            JOIN billing_document_items bdi ON soh.salesOrder = bdi.referenceSdDocument
            WHERE soh.soldToParty IN ({cust_sql})
            LIMIT 40
        )
    """)
    order_map = {}
    for o in orders:
        nid = f"so_{o['salesOrder']}"
        nodes.append({"id": nid, "type": "Sales Order", "label": f"Sales Order {o['salesOrder']}", "data": dict(o), "connections": 0})
        order_map[o['salesOrder']] = nid
        if o['soldToParty'] in cust_map:
            edges.append({"id": f"e_cso_{o['salesOrder']}", "source": cust_map[o['soldToParty']], "target": nid, "label": "placed"})

    if not order_map:
        return {"nodes": nodes, "edges": edges}

    so_sql = ",".join(f"'{s}'" for s in order_map)

    # ── SALES ORDER ITEMS (PO → PO Item) ─────────────────────
    order_items = run_query(f"""
        SELECT salesOrder, salesOrderItem, material, netAmount,
               requestedQuantity, requestedQuantityUnit, productionPlant
        FROM sales_order_items
        WHERE salesOrder IN ({so_sql})
        LIMIT 200
    """)
    item_map = {}
    material_set = set()
    plant_set = set()
    for item in order_items:
        nid = f"soi_{item['salesOrder']}_{item['salesOrderItem']}"
        if nid not in item_map:
            nodes.append({"id": nid, "type": "Sales Order Item", "label": f"Sales Order Item {item['salesOrderItem']}", "data": dict(item), "connections": 0})
            item_map[nid] = item
            # Edge: SalesOrder → OrderItem  (PO → PO Item)
            if item['salesOrder'] in order_map:
                edges.append({"id": f"e_so_soi_{nid}", "source": order_map[item['salesOrder']], "target": nid, "label": "has_item"})
        if item.get('material'):
            material_set.add(item['material'])
        if item.get('productionPlant'):
            plant_set.add(item['productionPlant'])

    # ── PRODUCTS / MATERIALS ───────────────────────────────────
    prod_map = {}
    if material_set:
        mat_sql = ",".join(f"'{m}'" for m in list(material_set)[:60])
        products = run_query(f"""
            SELECT p.product, pd.productDescription, p.productGroup,
                   p.baseUnit, p.grossWeight, p.weightUnit, p.division, p.productType
            FROM products p
            LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN'
            WHERE p.product IN ({mat_sql})
        """)
        for p in products:
            nid = f"prod_{p['product']}"
            label = (p['productDescription'] or p['product'])[:30]
            nodes.append({"id": nid, "type": "Product", "label": label, "data": dict(p), "connections": 0})
            prod_map[p['product']] = nid

        # Edge: OrderItem → Material/Product  (PO Item → Material)
        for item in order_items:
            i_nid = f"soi_{item['salesOrder']}_{item['salesOrderItem']}"
            if item.get('material') and item['material'] in prod_map and i_nid in item_map:
                edges.append({
                    "id": f"e_soi_prod_{i_nid}",
                    "source": i_nid,
                    "target": prod_map[item['material']],
                    "label": "references"
                })

    # ── PLANTS ─────────────────────────────────────────────────
    plant_map = {}
    all_plants = plant_set.copy()

    # Also collect plants from delivery items ahead of time
    delivery_items_preview = run_query(f"""
        SELECT DISTINCT plant FROM outbound_delivery_items
        WHERE referenceSdDocument IN ({so_sql}) AND plant IS NOT NULL AND plant != ''
        LIMIT 50
    """)
    for pi in delivery_items_preview:
        if pi.get('plant'):
            all_plants.add(pi['plant'])

    if all_plants:
        pl_sql = ",".join(f"'{p}'" for p in all_plants)
        plants_data = run_query(f"SELECT plant, plantName, plantCategory, salesOrganization FROM plants WHERE plant IN ({pl_sql})")
        for pl in plants_data:
            nid = f"plant_{pl['plant']}"
            nodes.append({"id": nid, "type": "Plant", "label": pl['plantName'] or pl['plant'], "data": dict(pl), "connections": 0})
            plant_map[pl['plant']] = nid

    # ── DELIVERIES ─────────────────────────────────────────────
    deliveries = run_query(f"""
        SELECT DISTINCT odh.deliveryDocument, odh.overallGoodsMovementStatus,
               odh.overallPickingStatus, odh.creationDate, odh.shippingPoint,
               odh.actualGoodsMovementDate,
               odi.referenceSdDocument, odi.plant
        FROM outbound_delivery_headers odh
        JOIN outbound_delivery_items odi ON odh.deliveryDocument=odi.deliveryDocument
        WHERE odi.referenceSdDocument IN ({so_sql})
        LIMIT 100
    """)
    del_map = {}
    for d in deliveries:
        nid = f"del_{d['deliveryDocument']}"
        if nid not in del_map:
            nodes.append({"id": nid, "type": "Outbound Delivery", "label": f"Outbound Delivery {d['deliveryDocument']}", "data": dict(d), "connections": 0})
            del_map[d['deliveryDocument']] = nid

        # Edge: SalesOrder → Delivery
        if d['referenceSdDocument'] in order_map:
            edges.append({"id": f"e_so_del_{d['referenceSdDocument']}_{d['deliveryDocument']}", "source": order_map[d['referenceSdDocument']], "target": nid, "label": "delivered_via"})

        # Edge: Customer → Delivery  (Customer → Delivery)
        so_rec = next((o for o in orders if o['salesOrder'] == d['referenceSdDocument']), None)
        if so_rec and so_rec['soldToParty'] in cust_map:
            eid = f"e_cust_del_{so_rec['soldToParty']}_{d['deliveryDocument']}"
            edges.append({"id": eid, "source": cust_map[so_rec['soldToParty']], "target": nid, "label": "receives"})

        # Edge: Delivery → Plant  (Delivery → Plant)
        if d.get('plant'):
            if d['plant'] not in plant_map:
                pl_nid = f"plant_{d['plant']}"
                nodes.append({"id": pl_nid, "type": "Plant", "label": f"Plant {d['plant']}", "data": {"plant": d['plant']}, "connections": 0})
                plant_map[d['plant']] = pl_nid
            edges.append({"id": f"e_del_plant_{d['deliveryDocument']}_{d['plant']}", "source": nid, "target": plant_map[d['plant']], "label": "ships_from"})

    # ── BILLING DOCUMENTS & ITEMS ──────────────────────────────
    del_sql = ",".join(f"'{k}'" for k in del_map) if del_map else "''"
    billings = run_query(f"""
        SELECT bdh.billingDocument, bdh.totalNetAmount,
               bdh.billingDocumentIsCancelled, bdh.accountingDocument,
               bdh.creationDate, bdh.transactionCurrency,
               bdh.fiscalYear, bdh.companyCode,
               bdi.referenceSdDocument, bdi.billingDocumentItem, bdi.material
        FROM billing_document_headers bdh
        JOIN billing_document_items bdi ON bdh.billingDocument=bdi.billingDocument
        WHERE bdi.referenceSdDocument IN ({del_sql})
        LIMIT 100
    """)
    bill_map = {}
    for b in billings:
        bd_id = f"bd_{b['billingDocument']}"
        if bd_id not in bill_map:
            nodes.append({"id": bd_id, "type": "Billing Document", "label": f"Billing Document {b['billingDocument']}", "data": dict(b), "connections": 0})
            bill_map[b['billingDocument']] = bd_id
        
        # Link BD to Delivery
        if b['referenceSdDocument'] in del_map:
            edges.append({"id": f"e_del_bd_{b['billingDocument']}", "source": del_map[b['referenceSdDocument']], "target": bd_id, "label": "billed_as"})
            
        # ── BILLING ITEM ─
        bi_id = f"bi_{b['billingDocument']}_{b['billingDocumentItem']}"
        nodes.append({"id": bi_id, "type": "Billing Document Item", "label": f"Billing Document Item {b['billingDocumentItem']}", "data": dict(b), "connections": 0})
        edges.append({"id": f"e_bd_bi_{bi_id}", "source": bd_id, "target": bi_id, "label": "contains"})
        
        # Link BillingItem to Product
        if b.get('material') and f"prod_{b['material']}" in [n['id'] for n in nodes]:
            edges.append({"id": f"e_bi_prod_{bi_id}", "source": bi_id, "target": f"prod_{b['material']}", "label": "item_of"})

    # ── JOURNAL ENTRIES ────────────────────────────────────────
    acct_docs = list(set(b['accountingDocument'] for b in billings if b.get('accountingDocument')))
    if acct_docs:
        ap = ",".join(f"'{a}'" for a in acct_docs)
        journals = run_query(f"""
            SELECT DISTINCT accountingDocument, companyCode, fiscalYear,
                   glAccount, amountInTransactionCurrency, transactionCurrency,
                   postingDate, clearingDate, customer
            FROM payments_accounts_receivable WHERE accountingDocument IN ({ap}) LIMIT 80
        """)
        je_map = {}
        for j in journals:
            nid = f"je_{j['accountingDocument']}"
            if nid not in je_map:
                nodes.append({"id": nid, "type": "Journal Entry", "label": f"Journal Entry {j['accountingDocument']}", "data": dict(j), "connections": 0})
                je_map[j['accountingDocument']] = nid
            for b in billings:
                if b.get('accountingDocument') == j['accountingDocument'] and b['billingDocument'] in bill_map:
                    edges.append({"id": f"e_bd_je_{b['billingDocument']}", "source": bill_map[b['billingDocument']], "target": nid, "label": "posted_to"})

    # ── COMPUTE CONNECTION COUNTS ──────────────────────────────
    conn_count = {}
    for e in edges:
        conn_count[e['source']] = conn_count.get(e['source'], 0) + 1
        conn_count[e['target']] = conn_count.get(e['target'], 0) + 1
    for n in nodes:
        n['connections'] = conn_count.get(n['id'], 0)

    # ── DEDUPLICATE EDGES ──────────────────────────────────────
    seen_edges = set()
    unique_edges = []
    for e in edges:
        if e['id'] not in seen_edges:
            seen_edges.add(e['id'])
            unique_edges.append(e)

    return {"nodes": nodes, "edges": unique_edges}


# ──────────────────────────────────────────────────────────────
# REQUIREMENT 2: NODE EXPAND & METADATA
# ──────────────────────────────────────────────────────────────
@app.get("/api/node/{node_id}/expand")
def expand_node(node_id: str):
    parts = node_id.split("_", 1)
    if len(parts) < 2:
        return {"nodes": [], "edges": []}
    prefix, eid = parts[0], parts[1]
    nodes, edges = [], []

    if prefix == "so":
        items = run_query("SELECT * FROM sales_order_items WHERE salesOrder=? LIMIT 20", (eid,))
        for item in items:
            nid = f"soi_{eid}_{item['salesOrderItem']}"
            nodes.append({"id": nid, "type": "Sales Order Item", "label": f"Sales Order Item {item['salesOrderItem']}", "data": dict(item), "connections": 0})
            edges.append({"id": f"e_{node_id}_{nid}", "source": node_id, "target": nid, "label": "has_item"})
            if item.get('material'):
                prod = run_query("SELECT p.*, pd.productDescription FROM products p LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN' WHERE p.product=?", (item['material'],))
                if prod:
                    pnid = f"prod_{item['material']}"
                    nodes.append({"id": pnid, "type": "Product", "label": (prod[0].get('productDescription') or item['material'])[:30], "data": dict(prod[0]), "connections": 0})
                    edges.append({"id": f"e_{nid}_{pnid}", "source": nid, "target": pnid, "label": "references"})

    elif prefix == "cust":
        addrs = run_query("SELECT bpa.* FROM business_partner_addresses bpa JOIN business_partners bp ON bpa.businessPartner=bp.businessPartner WHERE bp.customer=? LIMIT 5", (eid,))
        for addr in addrs:
            nid = f"addr_{addr['businessPartner']}_{addr.get('addressId','')}"
            nodes.append({"id": nid, "type": "Address", "label": f"{addr.get('cityName','')}, {addr.get('country','')}", "data": dict(addr), "connections": 0})
            edges.append({"id": f"e_{node_id}_{nid}", "source": node_id, "target": nid, "label": "located_at"})

    elif prefix == "bd":
        items = run_query("SELECT * FROM billing_document_items WHERE billingDocument=? LIMIT 20", (eid,))
        for item in items:
            nid = f"bdi_{eid}_{item['billingDocumentItem']}"
            nodes.append({"id": nid, "type": "Billing Document Item", "label": f"Item {item['billingDocumentItem']}", "data": dict(item), "connections": 0})
            edges.append({"id": f"e_{node_id}_{nid}", "source": node_id, "target": nid, "label": "has_item"})

    elif prefix == "del":
        items = run_query("SELECT * FROM outbound_delivery_items WHERE deliveryDocument=? LIMIT 20", (eid,))
        for item in items:
            nid = f"deli_{eid}_{item['deliveryDocumentItem']}"
            nodes.append({"id": nid, "type": "DeliveryItem", "label": f"Item {item['deliveryDocumentItem']}", "data": dict(item), "connections": 0})
            edges.append({"id": f"e_{node_id}_{nid}", "source": node_id, "target": nid, "label": "has_item"})
            if item.get('plant'):
                pl = run_query("SELECT * FROM plants WHERE plant=?", (item['plant'],))
                pl_nid = f"plant_{item['plant']}"
                nodes.append({"id": pl_nid, "type": "Plant", "label": (pl[0]['plantName'] if pl else item['plant']), "data": dict(pl[0]) if pl else {"plant": item['plant']}, "connections": 0})
                edges.append({"id": f"e_{nid}_{pl_nid}", "source": nid, "target": pl_nid, "label": "ships_from"})

    elif prefix == "prod":
        pls = run_query("SELECT pp.*, pl.plantName FROM product_plants pp LEFT JOIN plants pl ON pp.plant=pl.plant WHERE pp.product=? LIMIT 10", (eid,))
        for pl in pls:
            nid = f"plant_{pl['plant']}"
            nodes.append({"id": nid, "type": "Plant", "label": pl.get('plantName') or pl['plant'], "data": dict(pl), "connections": 0})
            edges.append({"id": f"e_{node_id}_{nid}", "source": node_id, "target": nid, "label": "stored_at"})

    elif prefix == "je":
        items = run_query("SELECT * FROM payments_accounts_receivable WHERE accountingDocument=? LIMIT 10", (eid,))
        for item in items:
            nid = f"jeitem_{eid}_{item.get('accountingDocumentItem','')}"
            nodes.append({"id": nid, "type": "JournalItem", "label": f"GL {item.get('glAccount','')}", "data": dict(item), "connections": 0})
            edges.append({"id": f"e_{node_id}_{nid}", "source": node_id, "target": nid, "label": "has_entry"})

    return {"nodes": nodes, "edges": edges}


# ──────────────────────────────────────────────────────────────
# REQUIREMENT 4b: TRACE FULL FLOW
# Sales Order → Delivery → Billing → Journal Entry
# ──────────────────────────────────────────────────────────────
def build_trace(doc_type: str, doc_id: str) -> dict:
    result = {"flow": [], "details": {}, "highlighted_ids": []}
    highlighted = []

    if doc_type == "billing":
        billing = run_query("SELECT * FROM billing_document_headers WHERE billingDocument=?", (doc_id,))
        if not billing:
            return {"error": f"Billing document {doc_id} not found"}
        b = billing[0]
        result["details"]["billing"] = b
        result["details"]["billing_items"] = run_query("SELECT * FROM billing_document_items WHERE billingDocument=?", (doc_id,))
        highlighted.append(f"bd_{doc_id}")

        so_ids = list(set(i['referenceSdDocument'] for i in result["details"]["billing_items"] if i.get('referenceSdDocument')))
        if so_ids:
            ph = ",".join("?" * len(so_ids))
            result["details"]["sales_orders"] = run_query(f"SELECT * FROM sales_order_headers WHERE salesOrder IN ({ph})", so_ids)
            result["details"]["order_items"] = run_query(f"SELECT * FROM sales_order_items WHERE salesOrder IN ({ph})", so_ids)
            result["details"]["deliveries"] = run_query(f"SELECT DISTINCT odh.* FROM outbound_delivery_headers odh JOIN outbound_delivery_items odi ON odh.deliveryDocument=odi.deliveryDocument WHERE odi.referenceSdDocument IN ({ph})", so_ids)
            for sid in so_ids: highlighted.append(f"so_{sid}")
            for d in result["details"].get("deliveries",[]): highlighted.append(f"del_{d['deliveryDocument']}")

        if b.get('accountingDocument'):
            result["details"]["journal_entries"] = run_query("SELECT * FROM payments_accounts_receivable WHERE accountingDocument=?", (b['accountingDocument'],))
            highlighted.append(f"je_{b['accountingDocument']}")

        result["flow"] = [
            {"step": 1, "type": "Sales Order",       "icon": "🛒", "ids": so_ids,         "status": "found" if so_ids else "missing"},
            {"step": 2, "type": "Outbound Delivery",          "icon": "🚚", "ids": [d['deliveryDocument'] for d in result["details"].get("deliveries",[])], "status": "found" if result["details"].get("deliveries") else "missing"},
            {"step": 3, "type": "Billing Document",   "icon": "🧾", "ids": [doc_id],       "status": "found"},
            {"step": 4, "type": "Journal Entry",      "icon": "📒", "ids": [b.get('accountingDocument','')] if b.get('accountingDocument') else [], "status": "found" if b.get('accountingDocument') else "missing"},
        ]

    elif doc_type == "salesorder":
        so = run_query("SELECT * FROM sales_order_headers WHERE salesOrder=?", (doc_id,))
        if not so:
            return {"error": f"Sales order {doc_id} not found"}
        result["details"]["sales_order"] = so[0]
        result["details"]["order_items"] = run_query("SELECT * FROM sales_order_items WHERE salesOrder=?", (doc_id,))
        result["details"]["schedule_lines"] = run_query("SELECT * FROM sales_order_schedule_lines WHERE salesOrder=?", (doc_id,))
        result["details"]["deliveries"] = run_query("SELECT DISTINCT odh.* FROM outbound_delivery_headers odh JOIN outbound_delivery_items odi ON odh.deliveryDocument=odi.deliveryDocument WHERE odi.referenceSdDocument=?", (doc_id,))
        result["details"]["billings"] = run_query("SELECT DISTINCT bdh.* FROM billing_document_headers bdh JOIN billing_document_items bdi ON bdh.billingDocument=bdi.billingDocument WHERE bdi.referenceSdDocument=?", (doc_id,))
        highlighted.append(f"so_{doc_id}")
        for d in result["details"]["deliveries"]: highlighted.append(f"del_{d['deliveryDocument']}")
        for b in result["details"]["billings"]: highlighted.append(f"bd_{b['billingDocument']}")

        acct_docs = [b['accountingDocument'] for b in result["details"]["billings"] if b.get('accountingDocument')]
        if acct_docs:
            ph = ",".join("?" * len(acct_docs))
            result["details"]["journal_entries"] = run_query(f"SELECT * FROM payments_accounts_receivable WHERE accountingDocument IN ({ph})", acct_docs)
            for a in acct_docs: highlighted.append(f"je_{a}")

        result["flow"] = [
            {"step": 1, "type": "Sales Order",     "icon": "🛒", "ids": [doc_id], "status": "found"},
            {"step": 2, "type": "Outbound Delivery",        "icon": "🚚", "ids": [d['deliveryDocument'] for d in result["details"]["deliveries"]], "status": "found" if result["details"]["deliveries"] else "missing"},
            {"step": 3, "type": "Billing Document", "icon": "🧾", "ids": [b['billingDocument'] for b in result["details"]["billings"]], "status": "found" if result["details"]["billings"] else "missing"},
            {"step": 4, "type": "Journal Entry",    "icon": "📒", "ids": acct_docs, "status": "found" if acct_docs else "missing"},
        ]

    result["highlighted_ids"] = list(set(highlighted))
    return result

@app.get("/api/trace/{doc_type}/{doc_id}")
def trace_document(doc_type: str, doc_id: str):
    result = build_trace(doc_type, doc_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ──────────────────────────────────────────────────────────────
# REQUIREMENT 4c: BROKEN FLOWS ANALYSIS
# ──────────────────────────────────────────────────────────────
@app.get("/api/analysis/broken-flows")
def broken_flows():
    delivered_not_billed = run_query("""
        SELECT salesOrder, soldToParty, totalNetAmount, overallDeliveryStatus,
               overallOrdReltdBillgStatus, creationDate
        FROM sales_order_headers
        WHERE overallDeliveryStatus='C' AND overallOrdReltdBillgStatus IN ('A','B')
        ORDER BY CAST(COALESCE(totalNetAmount,'0') AS REAL) DESC LIMIT 50
    """)
    billed_no_delivery = run_query("""
        SELECT DISTINCT bdi.referenceSdDocument AS salesOrder, bdh.billingDocument,
               bdh.totalNetAmount, bdh.creationDate, bdh.soldToParty
        FROM billing_document_items bdi
        JOIN billing_document_headers bdh ON bdi.billingDocument=bdh.billingDocument
        WHERE bdi.referenceSdDocument NOT IN (
            SELECT DISTINCT referenceSdDocument FROM outbound_delivery_items
            WHERE referenceSdDocument IS NOT NULL AND referenceSdDocument != ''
        ) AND bdh.billingDocumentIsCancelled='false'
        LIMIT 50
    """)
    cancelled = run_query("""
        SELECT billingDocument, totalNetAmount, soldToParty,
               cancelledBillingDocument, creationDate, companyCode
        FROM billing_document_cancellations
        ORDER BY creationDate DESC LIMIT 50
    """)
    partial_delivery = run_query("""
        SELECT salesOrder, soldToParty, totalNetAmount,
               overallDeliveryStatus, overallOrdReltdBillgStatus, creationDate
        FROM sales_order_headers
        WHERE overallDeliveryStatus='B'
        ORDER BY CAST(COALESCE(totalNetAmount,'0') AS REAL) DESC LIMIT 50
    """)
    # Absolute counts for dashboard accuracy (ignoring SQL limits)
    c1 = run_query("SELECT count(*) as cnt FROM sales_order_headers WHERE overallDeliveryStatus='C' AND overallOrdReltdBillgStatus IN ('A','B')")
    c2 = run_query("""
        SELECT count(DISTINCT bdi.referenceSdDocument) as cnt
        FROM billing_document_items bdi
        JOIN billing_document_headers bdh ON bdi.billingDocument=bdh.billingDocument
        WHERE bdi.referenceSdDocument NOT IN (
            SELECT DISTINCT referenceSdDocument FROM outbound_delivery_items
            WHERE referenceSdDocument IS NOT NULL AND referenceSdDocument != ''
        ) AND bdh.billingDocumentIsCancelled='false'
    """)
    c3 = run_query("SELECT count(*) as cnt FROM billing_document_cancellations")
    c4 = run_query("SELECT count(*) as cnt FROM sales_order_headers WHERE overallDeliveryStatus='B'")

    return {
        "delivered_not_billed": delivered_not_billed,
        "billed_no_delivery": billed_no_delivery,
        "cancelled_billings": cancelled,
        "partial_delivery": partial_delivery,
        "summary": {
            "delivered_not_billed_count": c1[0]['cnt'],
            "billed_no_delivery_count": c2[0]['cnt'],
            "cancelled_count": c3[0]['cnt'],
            "partial_delivery_count": c4[0]['cnt']
        }
    }


# ──────────────────────────────────────────────────────────────
# REQUIREMENT 3: CONVERSATIONAL QUERY INTERFACE
# ──────────────────────────────────────────────────────────────
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[Message] = []

def build_highlighted_from_results(results, question=""):
    ids = []
    # 1. Row-based highlighting
    for r in results[:50]:
        if r.get('salesOrder'): ids.append(f"so_{r['salesOrder']}")
        if r.get('billingDocument'): ids.append(f"bd_{r['billingDocument']}")
        if r.get('deliveryDocument'): ids.append(f"del_{r['deliveryDocument']}")
        if r.get('customer'): ids.append(f"cust_{r['customer']}")
        if r.get('soldToParty'): ids.append(f"cust_{r['soldToParty']}")
        if r.get('product'): ids.append(f"prod_{r['product']}")
        if r.get('material'): ids.append(f"prod_{r['material']}")
    
    # 2. Semantic & Universal ID Highlighting
    q = question.lower()
    
    # Category-based
    if any(k in q for k in ["billing", "invoice", "payment", "je"]):
        ids += [f"bd_{r['billingDocument']}" for r in run_query("SELECT billingDocument FROM billing_document_headers LIMIT 20")]
        ids += [f"je_{r['accountingDocument']}" for r in run_query("SELECT DISTINCT accountingDocument FROM payments_accounts_receivable LIMIT 10")]
    elif any(k in q for k in ["sales", "order", "so"]):
        ids += [f"so_{r['salesOrder']}" for r in run_query("SELECT salesOrder FROM sales_order_headers LIMIT 20")]
    elif any(k in q for k in ["delivery", "delv", "ship", "outbound"]):
        ids += [f"del_{r['deliveryDocument']}" for r in run_query("SELECT deliveryDocument FROM outbound_delivery_headers LIMIT 20")]
    elif any(k in q for k in ["customer", "partner"]):
        ids += [f"cust_{r['customer']}" for r in run_query("SELECT customer FROM business_partners LIMIT 20")]

    # ID-based (Aggressive search for numbers in the question)
    import re
    tokens = re.findall(r'\d{6,10}', question) # Match 6-10 digit IDs
    for t in tokens:
        # Check if t exists as a SalesOrder, Delivery, or Billing Doc
        if run_query("SELECT salesOrder FROM sales_order_headers WHERE salesOrder=?", (t,)): ids.append(f"so_{t}")
        if run_query("SELECT deliveryDocument FROM outbound_delivery_headers WHERE deliveryDocument=?", (t,)): ids.append(f"del_{t}")
        if run_query("SELECT billingDocument FROM billing_document_headers WHERE billingDocument=?", (t,)): ids.append(f"bd_{t}")
        if run_query("SELECT customer FROM business_partners WHERE customer=?", (t,)): ids.append(f"cust_{t}")

    return list(set(ids))

@app.post("/api/chat")
def chat(req: ChatRequest):
    client = get_groq()
    history = [{"role": m.role, "content": m.content} for m in req.history[-6:]]
    question = req.message.strip()

    # 1. FAST SOCIAL (Keywords)
    conv = handle_conversational(question)
    if conv: return conv

    # 2. INTENT CLASSIFICATION (LLM)
    intent = classify_intent_llm(question)
    
    if intent == "IRRELEVANT":
        return GUARDRAIL_RESPONSE
        
    if intent == "SOCIAL":
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": "You are a friendly Order-to-Cash AI assistant. Respond politely to the user's social cue (thanks, bye, etc.)."}, {"role": "user", "content": question}],
            temperature=0.7, max_tokens=100
        )
        return {"type": "greeting", "answer": resp.choices[0].message.content, "sql": None, "results": [], "highlighted_ids": [], "flow": None}

    if intent == "META":
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": "You are an ERP expert. Explain the requested concept (billing, sales, delivery, etc.) in the context of an Order-to-Cash system. Keep it concise."}, {"role": "user", "content": question}],
            temperature=0.3, max_tokens=250
        )
        return {"type": "greeting", "answer": resp.choices[0].message.content, "sql": None, "results": [], "highlighted_ids": [], "flow": None}

    # Detect trace intent → use dedicated endpoint
    trace_intent = detect_trace_intent(question)
    if trace_intent and ("trace" in question.lower() or "flow" in question.lower() or "full" in question.lower()):
        doc_type, doc_id = trace_intent
        trace_result = build_trace(doc_type, doc_id)
        if "error" not in trace_result:
            flow_summary = " → ".join([f"{s['icon']} {s['type']} ({', '.join(s['ids'][:2]) or 'missing'})" for s in trace_result["flow"]])
            return {
                "type": "trace",
                "answer": f"Here is the full Order-to-Cash flow for {doc_type} **{doc_id}**:\n\n{flow_summary}",
                "sql": None,
                "results": [],
                "highlighted_ids": trace_result["highlighted_ids"],
                "flow": trace_result["flow"],
                "details": trace_result["details"]
            }

    # Generate SQL
    def _gen_sql(client):
        return client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": SCHEMA_CONTEXT}, *history, {"role": "user", "content": question}],
            temperature=0, max_tokens=700
        )
    sql_resp = call_groq_with_retry(_gen_sql)
    sql = sql_resp.choices[0].message.content.strip().replace("```sql","").replace("```","").strip()
    sql = sql.replace("\n", " ").replace("\r", " ")

    if sql.upper() == "IRRELEVANT":
        return GUARDRAIL_RESPONSE
    if not safe_sql(sql):
        return {**GUARDRAIL_RESPONSE, "answer": "⚠️ Only read operations are permitted on this system."}

    # Execute SQL with one auto-fix attempt
    try:
        results = run_query(sql)
        # 3. FUZZY FALLBACK: If SQL returned nothing but there's a 6+ char token in the question, try searching for it
        if not results:
            tokens = re.findall(r'[A-Za-z0-9]{6,20}', question)
            for t in tokens:
                fallback_results = run_query("SELECT p.*, pd.productDescription FROM products p LEFT JOIN product_descriptions pd ON p.product=pd.product WHERE p.product LIKE ? LIMIT 5", (f"%{t}%",))
                if fallback_results:
                    results = fallback_results
                    break
    except Exception as e:
        try:
            def _fix(client):
                return client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "system", "content": SCHEMA_CONTEXT},
                              {"role": "user", "content": f"Fix this SQL (error: {e}):\n{sql}\nReturn only corrected SQL."}],
                    temperature=0, max_tokens=600
                )
            fix = call_groq_with_retry(_fix)
            sql = fix.choices[0].message.content.strip().replace("```sql","").replace("```","").strip()
            results = run_query(sql)
        except Exception as e2:
            print(f"CRITICAL ERROR: {e2}")
            return {"type": "error", "answer": f"Could not execute query: {e2}", "sql": sql, "results": [], "highlighted_ids": [], "flow": None}

    # Generate natural language answer grounded in data
    preview = json.dumps(results[:15], indent=2, default=str)
    def _answer(client):
        return client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a business analyst. Answer ONLY based on the SQL results provided. Be specific with numbers and IDs from the data. If no results, say 'No matching records found.' Keep under 200 words. Use bullet points for lists."},
                *history,
                {"role": "user", "content": f"Question: {question}\n\nSQL Results ({len(results)} rows total, showing first 15):\n{preview}\n\nAnswer with specific data from the results."}
            ],
            temperature=0.2, max_tokens=400
        )
    ans_resp = call_groq_with_retry(_answer)

    return {
        "type": "data",
        "answer": ans_resp.choices[0].message.content.strip(),
        "sql": sql,
        "results": results[:50],
        "highlighted_ids": build_highlighted_from_results(results, question),
        "flow": None
    }


# ──────────────────────────────────────────────────────────────
# STREAMING CHAT
# ──────────────────────────────────────────────────────────────
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    client = get_groq()
    history = [{"role": m.role, "content": m.content} for m in req.history[-6:]]
    question = req.message.strip()

    # 1. FAST SOCIAL (Keywords)
    conv = handle_conversational(question)
    if conv:
        async def stream_conv():
            yield "data: " + json.dumps({"type": "token", "token": conv["answer"]}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream_conv(), media_type="text/event-stream")

    # 2. INTENT CLASSIFICATION (LLM)
    intent = classify_intent_llm(question)
    
    if intent == "IRRELEVANT":
        async def blocked():
            yield "data: " + json.dumps({"type": "guardrail", "token": GUARDRAIL_RESPONSE["answer"]}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(blocked(), media_type="text/event-stream")

    if intent in ["SOCIAL", "META"]:
        async def stream_natural():
            sys_prompt = "You are a friendly ERP AI assistant." if intent == "SOCIAL" else "You are an ERP Expert. Explain the requested concept concisely."
            sys_prompt = "You are a friendly ERP AI assistant." if intent == "SOCIAL" else "You are an ERP Expert. Explain the requested concept concisely."
            def _get_natural(client):
                return client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": question}],
                    temperature=0.5, max_tokens=300, stream=True
                )
            stream = call_groq_with_retry(_get_natural)
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield "data: " + json.dumps({"type": "token", "token": token}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream_natural(), media_type="text/event-stream")

    # Trace intent → stream trace result
    trace_intent = detect_trace_intent(question)
    if trace_intent and ("trace" in question.lower() or "flow" in question.lower() or "full" in question.lower()):
        doc_type, doc_id = trace_intent
        trace_result = build_trace(doc_type, doc_id)
        async def stream_trace():
            yield "data: " + json.dumps({"type": "trace", "flow": trace_result.get("flow"), "highlighted_ids": trace_result.get("highlighted_ids", [])}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream_trace(), media_type="text/event-stream")

    def _gen_sql_stream(client):
        return client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": SCHEMA_CONTEXT}, *history, {"role": "user", "content": question}],
            temperature=0, max_tokens=700
        )
    sql_resp = call_groq_with_retry(_gen_sql_stream)
    sql = sql_resp.choices[0].message.content.strip().replace("```sql","").replace("```","").strip()
    sql = sql.replace("\n", " ").replace("\r", " ")

    results = []
    if sql.upper() != "IRRELEVANT" and safe_sql(sql):
        try:
            results = run_query(sql)
            # 3. FUZZY FALLBACK: If SQL returned nothing but there's a 6+ char token in the question, try searching for it
            if not results:
                tokens = re.findall(r'[A-Za-z0-9]{6,20}', question)
                for t in tokens:
                    fb = run_query("SELECT p.*, pd.productDescription FROM products p LEFT JOIN product_descriptions pd ON p.product=pd.product WHERE p.product LIKE ? LIMIT 5", (f"%{t}%",))
                    if fb:
                        results = fb
                        break
        except Exception:
            pass

    preview = json.dumps(results[:15], indent=2, default=str)
    highlighted = build_highlighted_from_results(results, question)

    async def generate():
        yield "data: " + json.dumps({"type": "meta", "sql": sql, "result_count": len(results), "highlighted_ids": highlighted}) + "\n\n"
        try:
            def _get_ans_stream(client):
                return client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are a professional Business ERP Analyst. The user will refer to entities using proper terms. MAP THEM to the tables: Business Partner -> business_partners, Sales Order -> sales_order_headers/items, Outbound Delivery -> outbound_delivery_headers/items, Billing Document -> billing_document_headers/items, Journal Entry -> payments_accounts_receivable. Answer ONLY based on the SQL results provided. Be precise with IDs and amounts. If no results are found, state that clearly and offer to help with a different query. If the results show 'Not available' for a field, explain that it means the data is missing for that specific property. Keep under 150 words."},
                        *history,
                        {"role": "user", "content": f"Question: {question}\n\nSQL Results ({len(results)} rows):\n{preview}\n\nAnswer concisely with data."}
                    ],
                    temperature=0.2, max_tokens=400, stream=True
                )
            stream = call_groq_with_retry(_get_ans_stream)
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield "data: " + json.dumps({"type": "token", "token": token}) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "token": f"Error during streaming: {e}"}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ──────────────────────────────────────────────────────────────
# BONUS: SEMANTIC SEARCH
# ──────────────────────────────────────────────────────────────
@app.get("/api/search")
def semantic_search(q: str = QParam(..., min_length=2)):
    q_like = f"%{q}%"
    return {
        "customers": run_query("SELECT customer, businessPartnerFullName, businessPartnerName, industry FROM business_partners WHERE businessPartnerFullName LIKE ? OR businessPartnerName LIKE ? OR customer LIKE ? LIMIT 8", (q_like, q_like, q_like)),
        "products": run_query("SELECT p.product, pd.productDescription, p.productGroup FROM products p LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN' WHERE pd.productDescription LIKE ? OR p.product LIKE ? LIMIT 8", (q_like, q_like)),
        "orders": run_query("SELECT salesOrder, soldToParty, totalNetAmount, overallDeliveryStatus, overallOrdReltdBillgStatus, creationDate FROM sales_order_headers WHERE salesOrder LIKE ? OR soldToParty LIKE ? LIMIT 8", (q_like, q_like)),
        "billings": run_query("SELECT billingDocument, totalNetAmount, soldToParty, billingDocumentIsCancelled, creationDate FROM billing_document_headers WHERE billingDocument LIKE ? OR soldToParty LIKE ? LIMIT 8", (q_like, q_like)),
    }