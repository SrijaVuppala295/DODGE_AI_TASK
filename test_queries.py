import sqlite3
conn = sqlite3.connect('backend/order_to_cash.db')

def run(name, sql):
    print(f"--- {name} ---")
    try:
        res = conn.execute(sql).fetchall()
        print(res)
    except Exception as e:
        print(f"ERROR: {e}")

run("C1", "SELECT count(*) FROM sales_order_headers WHERE overallDeliveryStatus='C' AND overallOrdReltdBillgStatus IN ('A','B')")
run("C2", """
        SELECT count(DISTINCT bdi.referenceSdDocument) 
        FROM billing_document_items bdi
        JOIN billing_document_headers bdh ON bdi.billingDocument=bdh.billingDocument
        WHERE bdi.referenceSdDocument NOT IN (
            SELECT DISTINCT referenceSdDocument FROM outbound_delivery_items
            WHERE referenceSdDocument IS NOT NULL AND referenceSdDocument != ''
        ) AND bdh.billingDocumentIsCancelled='false'
    """)
run("C3", "SELECT count(*) FROM billing_document_cancellations")
run("C4", "SELECT count(*) FROM sales_order_headers WHERE overallDeliveryStatus='B'")

conn.close()
