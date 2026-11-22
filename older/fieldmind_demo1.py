import chromadb
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer("all-MiniLM-L6-v2")
rag_client = chromadb.PersistentClient(path="./rag_db")
rag_collection = rag_client.get_collection("about")

def retrieve(query, top_k=2):
    q_emb = embedder.encode(query).tolist()
    results = rag_collection.query(query_embeddings=[q_emb], n_results=top_k)
    return "\n".join(results["documents"][0])