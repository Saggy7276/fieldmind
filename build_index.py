"""
Build the FieldMind RAG index.

    python build_index.py                         # default: section-aware chunking
    python build_index.py --strategy recursive    # try another strategy
    python build_index.py --docs about_me.txt knowledge_base --show

The collection name stays "about" because fieldmind_optimized.py reads it.
"""

import argparse
import sys
from datetime import datetime, timezone

import chromadb
from sentence_transformers import SentenceTransformer

from rag.chunking import STRATEGIES, chunk_document, load_documents

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--docs", nargs="+", default=["about_me.txt", "knowledge_base"])
parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="section")
parser.add_argument("--db", default="./rag_db")
parser.add_argument("--collection", default="about")
parser.add_argument("--show", action="store_true", help="print every chunk")
args = parser.parse_args()

sys.stdout.reconfigure(encoding="utf-8")  # Windows console
EMBED_MODEL = "all-MiniLM-L6-v2"
embedder = SentenceTransformer(EMBED_MODEL)  # downloads ~80MB once, then offline

chunks = []
for source, text in load_documents(args.docs):
    doc_chunks = chunk_document(text, source, args.strategy, embed_fn=embedder.encode)
    print(f"  {source}: {len(doc_chunks)} chunks")
    chunks.extend(doc_chunks)

if not chunks:
    raise SystemExit("No documents found.")

if args.show:
    for c in chunks:
        print(f"\n--- {c.id} ({c.words} words) ---\n{c.text}")

client = chromadb.PersistentClient(path=args.db)
if args.collection in [c.name for c in client.list_collections()]:
    client.delete_collection(args.collection)
# Index metadata lets the server refuse to start on a mismatched index and shows
# up in /health, so "which index is deployed?" has an answer in the field.
collection = client.create_collection(args.collection, metadata={
    "hnsw:space": "cosine",
    "strategy": args.strategy,
    "embed_model": EMBED_MODEL,
    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "n_chunks": len(chunks),
    "docs": ", ".join(sorted({c.source for c in chunks})),
})

collection.add(
    ids=[c.id for c in chunks],
    documents=[c.text for c in chunks],
    embeddings=embedder.encode([c.text for c in chunks], normalize_embeddings=True).tolist(),
    metadatas=[c.metadata() for c in chunks],
)

print(f"OK  Indexed {len(chunks)} chunks ({args.strategy}) into {args.db}/{args.collection}.")
