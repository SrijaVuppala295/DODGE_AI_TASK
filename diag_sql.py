import os
import json
import re
from typing import List
from pydantic import BaseModel
from groq import Groq

# Mocking parts of main.py
MODEL_NAME = "llama-3.3-70b-versatile"
api_key = os.getenv("GROQ_API_KEY") # Ensure this is set in your env
client = Groq(api_key=api_key)

SCHEMA_CONTEXT = """
TABLES & KEY COLUMNS:
- sales_order_headers (salesOrder PK, soldToParty, totalNetAmount, overallDeliveryStatus, overallOrdReltdBillgStatus)
- sales_order_items (salesOrder, salesOrderItem, material, netAmount)
- outbound_delivery_headers (deliveryDocument PK, overallGoodsMovementStatus)
- outbound_delivery_items (deliveryDocument, referenceSdDocument[=salesOrder], plant)
- billing_document_headers (billingDocument PK, totalNetAmount, accountingDocument, soldToParty, billingDocumentIsCancelled['true'/'false'])
- billing_document_items (billingDocument, material, referenceSdDocument[=salesOrder])
- business_partners (customer PK, businessPartnerFullName, industry)
- products (product PK, productType)
- product_descriptions (product, language['EN'], productDescription)

IMPORTANT: All IDs (salesOrder, deliveryDocument, material, product, customer) are TEXT columns. ALWAYS use single quotes even for numbers (e.g., WHERE salesOrder = '740543').
"""

def test_generation(q):
    print(f"QUERY: {q}")
    # SQL Gen
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "system", "content": SCHEMA_CONTEXT}, {"role": "user", "content": q}],
        temperature=0, max_tokens=700
    )
    sql = resp.choices[0].message.content.strip().replace("```sql","").replace("```","").strip()
    print(f"GENERATED SQL: {sql}")

test_generation("Tell me about Product S8907367010814")
