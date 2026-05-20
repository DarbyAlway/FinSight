from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)

for name in ("stock_news", "company_profiles"):
    try:
        client.delete_collection(name)
        print(f"Deleted: {name}")
    except Exception as e:
        print(f"Could not delete {name}: {e}")

print("Done — collections will be recreated on next init_qdrant() call")
