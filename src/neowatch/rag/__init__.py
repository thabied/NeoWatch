"""RAG (retrieval-augmented generation) package.

The local literature pipeline: ingest arXiv abstracts, chunk and embed them,
store vectors in ChromaDB, and retrieve the most relevant papers per query.
Grounding synthesis in retrieved real papers is what lets the report cite
sources instead of inventing them.
"""
