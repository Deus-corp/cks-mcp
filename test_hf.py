# test_hf.py
import os
import requests

token = os.environ.get("HF_TOKEN")
print(f"Token present: {token is not None}")
if token:
    print(f"Token prefix: {token[:10]}... (length {len(token)})")

    api_url = "https://router.huggingface.co/hf-inference/models/sentence-transformers/all-MiniLM-L6-v2/pipeline/feature-extraction"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(api_url, headers=headers, json={"inputs": ["test sentence"], "options": {"wait_for_model": True}})
    
    if response.status_code == 200:
        emb = response.json()
        print(f"Success! Embedding dimension: {len(emb[0]) if isinstance(emb, list) else len(emb)}")
    else:
        print(f"Error {response.status_code}: {response.text}")
else:
    print("HF_TOKEN not set. Make sure it's exported in your environment.")