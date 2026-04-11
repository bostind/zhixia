from pathlib import Path
from typing import List, Dict
import chromadb
from chromadb.utils import embedding_functions
import config
from config import get_logger

logger = get_logger(__name__)


def get_client():
    """获取 ChromaDB 持久化客户端。"""
    return chromadb.PersistentClient(path=str(config.CHROMA_DIR))


def get_embedding_function():
    """获取本地 Sentence Transformer Embedding 函数。"""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )


def get_collection():
    """获取或创建 collection。"""
    client = get_client()
    ef = get_embedding_function()
    return client.get_or_create_collection(
        name="filemind_files",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def add_document(doc_id: str, text: str, metadata: Dict):
    """添加一个文档到向量库。"""
    collection = get_collection()
    collection.add(
        ids=[doc_id],
        documents=[text],
        metadatas=[metadata],
    )


def query_documents(query_text: str, n_results: int = 5) -> List[Dict]:
    """语义检索，返回最相关的文档列表。"""
    collection = get_collection()
    # BGE 模型需要查询前缀才能达到最佳检索效果
    prefixed_query = "Represent this sentence for searching relevant passages: " + query_text
    results = collection.query(
        query_texts=[prefixed_query],
        n_results=n_results,
    )

    docs = []
    for i in range(len(results["ids"][0])):
        docs.append(
            {
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )
    return docs


def delete_document(doc_id: str):
    """从向量库删除文档。"""
    collection = get_collection()
    collection.delete(ids=[doc_id])


def update_metadata(doc_id: str, metadata: Dict):
    """更新向量库中文档的 metadata。"""
    collection = get_collection()
    collection.update(
        ids=[doc_id],
        metadatas=[metadata],
    )
