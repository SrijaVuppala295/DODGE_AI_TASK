"""
Data Loader — reads all part-*.jsonl files from dataset folders and loads into SQLite.
Run: python load_data.py --data-dir /path/to/dataset
"""
import sqlite3
import json
import glob
import os
import argparse

DB_PATH = "order_to_cash.db"

TABLE_MAP = {
    "sales_order_headers": "sales_order_headers",
    "sales_order_items": "sales_order_items",
    "sales_order_schedule_lines": "sales_order_schedule_lines",
    "outbound_delivery_headers": "outbound_delivery_headers",
    "outbound_delivery_items": "outbound_delivery_items",
    "billing_document_headers": "billing_document_headers",
    "billing_document_items": "billing_document_items",
    "billing_document_cancellations": "billing_document_cancellations",
    "journal_entry_items_accounts_receivable": "journal_entry_items_accounts_receivable",
    "payments_accounts_receivable": "payments_accounts_receivable",
    "business_partners": "business_partners",
    "business_partner_addresses": "business_partner_addresses",
    "customer_company_assignments": "customer_company_assignments",
    "customer_sales_area_assignments": "customer_sales_area_assignments",
    "products": "products",
    "product_descriptions": "product_descriptions",
    "product_plants": "product_plants",
    "product_storage_locations": "product_storage_locations",
    "plants": "plants",
}

def flatten(obj, prefix=""):
    """Flatten nested dicts/objects into single-level dict."""
    result = {}
    for k, v in obj.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
        if isinstance(v, dict):
            result.update(flatten(v, key))
        else:
            result[key] = v
    return result

def load_jsonl_files(conn, folder_path, table_name):
    files = glob.glob(os.path.join(folder_path, "part-*.jsonl"))
    if not files:
        print(f"  ⚠ No files found in {folder_path}")
        return 0

    total = 0
    for fpath in files:
        rows = []
        with open(fpath, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        obj = json.loads(line)
                        rows.append(flatten(obj))
                    except:
                        continue

        if not rows:
            continue

        # Collect all columns across all rows
        all_cols = set()
        for r in rows:
            all_cols.update(r.keys())
        all_cols = sorted(all_cols)

        # Create table if not exists
        col_defs = ", ".join(f'"{c}" TEXT' for c in all_cols)
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')

        # Add missing columns for existing tables
        existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")')}
        for col in all_cols:
            if col not in existing:
                conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" TEXT')

        # Insert rows
        placeholders = ", ".join("?" for _ in all_cols)
        col_str = ", ".join(f'"{c}"' for c in all_cols)
        for row in rows:
            values = [str(row.get(c, "")) if row.get(c) is not None else None for c in all_cols]
            conn.execute(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})', values)

        total += len(rows)

    conn.commit()
    return total

def create_indexes(conn):
    indexes = [
        ("sales_order_headers", "salesOrder"),
        ("sales_order_items", "salesOrder"),
        ("sales_order_items", "material"),
        ("outbound_delivery_items", "referenceSdDocument"),
        ("outbound_delivery_items", "deliveryDocument"),
        ("billing_document_headers", "billingDocument"),
        ("billing_document_headers", "soldToParty"),
        ("billing_document_headers", "accountingDocument"),
        ("billing_document_items", "referenceSdDocument"),
        ("billing_document_items", "billingDocument"),
        ("journal_entry_items_accounts_receivable", "accountingDocument"),
        ("journal_entry_items_accounts_receivable", "customer"),
        ("payments_accounts_receivable", "referenceDocument"),
        ("business_partners", "customer"),
        ("products", "product"),
        ("product_descriptions", "product"),
    ]
    for table, col in indexes:
        try:
            idx_name = f"idx_{table}_{col}"
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ("{col}")')
        except Exception as e:
            print(f"  Index warning: {e}")
    conn.commit()
    print("✅ Indexes created")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="Path to dataset root folder")
    args = parser.parse_args()

    if not os.path.exists(args.data_dir):
        print(f"❌ Data directory not found: {args.data_dir}")
        return

    conn = sqlite3.connect(DB_PATH)
    print(f"📦 Loading data from: {args.data_dir}")
    print(f"💾 Database: {DB_PATH}\n")

    for folder_name, table_name in TABLE_MAP.items():
        folder_path = os.path.join(args.data_dir, folder_name)
        if os.path.exists(folder_path):
            count = load_jsonl_files(conn, folder_path, table_name)
            print(f"  ✅ {table_name}: {count} rows loaded")
        else:
            print(f"  ⚠ Skipping {folder_name} (folder not found)")

    print("\n🔍 Creating indexes...")
    create_indexes(conn)
    conn.close()
    print("\n🎉 Data loading complete!")

if __name__ == "__main__":
    main()