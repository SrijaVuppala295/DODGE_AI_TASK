import requests
import json

url = "http://127.0.0.1:8000/api/chat/stream"
payload = {"message": "billing", "history": []}

try:
    print("Connecting to stream...")
    r = requests.post(url, json=payload, stream=True, timeout=15)
    print(f"Status Code: {r.status_code}")
    if r.status_code != 200:
        print(f"Error Content: {r.text}")
    else:
        for line in r.iter_lines():
            if line:
                print(f"LINE: {line.decode('utf-8')}")
except Exception as e:
    print(f"FAILURE: {e}")
