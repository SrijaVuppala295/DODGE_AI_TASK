import os
import glob
import sqlite3

# Try to find the sap-o2c-data directory dynamically to avoid path issues
base_path = r"C:\Users\Manikanta\Downloads"
candidate = None

# Look for sap-o2c-data recursively in Downloads
for root, dirs, files in os.walk(base_path):
    if "sap-o2c-data" in dirs:
        candidate = os.path.join(root, "sap-o2c-data")
        # Check if it has our expected subfolders
        if os.path.isdir(os.path.join(candidate, "sales_order_headers")):
            break

if not candidate:
    print(f"ERROR: sap-o2c-data not found in {base_path}")
    exit(1)

print(f"FOUND DATA AT: {candidate}")
DATA_DIR = candidate
DB_PATH = r"backend/order_to_cash.db"

conn = sqlite3.connect(DB_PATH)
tables = [d for d in os.listdir(DATA_DIR) if os.path.isdir(os.path.join(DATA_DIR, d))]

print(f"{'TABLE NAME':<40} | {'RAW (JSONL)':<12} | {'DB (SQLITE)':<12} | {'STATUS':<10}")
print("-" * 80)

for t in sorted(tables):
    t_path = os.path.join(DATA_DIR, t)
    files = glob.glob(os.path.join(t_path, "part-*.jsonl"))
    
    raw_count = 0
    for f in files:
        with open(f, 'r') as fh:
            raw_count += sum(1 for line in fh)
            
    db_count = 0
    try:
        db_count = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    except:
        db_count = "ERROR"
        
    status = "OK" if raw_count == db_count else "MISSING"
    if db_count == "ERROR": status = "NO TABLE"
    
    print(f"{t:<40} | {raw_count:<12} | {db_count:<12} | {status:<10}")

conn.close()
