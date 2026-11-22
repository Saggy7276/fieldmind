import chromadb
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./rag_db")
collection = client.get_collection("about")

print("Total chunks stored:", collection.count())

# Test retrieval directly
q = "What does Sagar do?"
q_emb = embedder.encode(q).tolist()
results = collection.query(query_embeddings=[q_emb], n_results=2)
print("\nRetrieved for:", q)
print(results["documents"][0])