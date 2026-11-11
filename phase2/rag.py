"""Local synthetic ingestion and retrieval; predownloaded encoder required."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import chromadb
import numpy as np
from chromadb.config import Settings
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2


class Retriever:
    def __init__(self, documents_path: Path, embedding_path: Path):
        files = ("model.onnx", "tokenizer.json", "config.json", "special_tokens_map.json",
                 "tokenizer_config.json", "vocab.txt")
        if not all((embedding_path / "onnx" / name).is_file() for name in files):
            raise ValueError("LOCAL_EMBEDDING_CACHE_REQUIRED")
        archive = embedding_path / "onnx.tar.gz"
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != (
            ONNXMiniLM_L6_V2._MODEL_SHA256
        ):
            raise ValueError("EMBEDDING_ARCHIVE_CHECKSUM_FAILED")
        ONNXMiniLM_L6_V2.DOWNLOAD_PATH = embedding_path
        self.encoder = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
        self.documents = json.loads(documents_path.read_text(encoding="utf-8"))
        ids = [doc["id"] for doc in self.documents]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("INVALID_DOCUMENT_IDS")
        self.by_id = {doc["id"]: doc for doc in self.documents}
        self.client = chromadb.EphemeralClient(Settings(anonymized_telemetry=False))
        # A fresh in-memory collection per retriever; never an evidence ledger.
        self.collection = self.client.create_collection("synthetic_" + uuid4().hex,
                                                       embedding_function=None)
        vectors = self.encoder([doc["text"] for doc in self.documents])
        self.collection.add(ids=ids, documents=[doc["text"] for doc in self.documents],
                            embeddings=np.asarray(vectors).tolist())

    def retrieve(self, query: str, count: int = 2) -> list[dict]:
        vector = self.encoder([query])
        results = self.collection.query(query_embeddings=np.asarray(vector).tolist(),
                                        n_results=min(count, len(self.documents)))
        # Return retrieved chunk content only; fixture metadata such as synthetic_value is
        # evaluation ground truth and must not reach the agent.
        return [{"source_ref": self.by_id[identifier]["source_ref"],
                 "text": self.by_id[identifier]["text"]} for identifier in results["ids"][0]]
