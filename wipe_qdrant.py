from qdrant_client import QdrantClient
from tools.config import QDRANT_COLLECTION, COMPANY_PROFILES_COLLECTION

client = QdrantClient(host="localhost", port=6333)
for col in [QDRANT_COLLECTION, COMPANY_PROFILES_COLLECTION]:
    try:
        client.delete_collection(col)
        print(f"Wiped: {col}")
    except Exception as e:
        print(f"Skip {col}: {e}")
print("Done — collections will rebuild with bge-m3 on next query")
