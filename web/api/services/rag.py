import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from django.conf import settings

from api.models import ExecutionRecord
from api.services.system_config import RuntimeConfig

logger = logging.getLogger(__name__)
try:
    import faiss  # type: ignore
    import numpy as np

    HAS_FAISS = True
except Exception:  # pylint: disable=broad-except
    HAS_FAISS = False


@dataclass
class RagChunk:
    chunk_id: str
    text: str
    source: str
    source_type: str


@dataclass
class RagReference:
    chunk_id: str
    source: str
    source_type: str
    score: float
    snippet: str


class RagServiceError(Exception):
    """Base error for RAG service."""


class RagEmbeddingError(RagServiceError):
    """Raised when embedding endpoint is unavailable."""


class RagService:
    CHUNK_SIZE = 500
    CHUNK_OVERLAP = 100
    DEFAULT_TOP_K = 4

    def __init__(self):
        self.base_url = RuntimeConfig.llm_base_url().rstrip("/")
        self.api_key = RuntimeConfig.llm_api_key() or "ollama"
        self.embedding_model = RuntimeConfig.rag_embedding_model() or RuntimeConfig.llm_model()
        self.top_k = RuntimeConfig.rag_top_k() or self.DEFAULT_TOP_K
        self.index_dir = RuntimeConfig.rag_index_dir()
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.repo_root = settings.BASE_DIR.parent

    @staticmethod
    def _normalize_api_base(base_url: str) -> str:
        normalized = (base_url or "").rstrip("/")
        if normalized.endswith("/v1"):
            return f"{normalized}/"
        return f"{normalized}/v1/"

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        compact = "\n".join(line.rstrip() for line in (text or "").splitlines()).strip()
        if not compact:
            return []

        chunks: list[str] = []
        start = 0
        length = len(compact)
        while start < length:
            end = min(start + chunk_size, length)
            chunks.append(compact[start:end])
            if end >= length:
                break
            start = max(0, end - overlap)
        return chunks

    def _load_tool_center_docs(self) -> list[tuple[str, str, str]]:
        path = RuntimeConfig.tool_config_path()
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:  # pylint: disable=broad-except
            return []
        return [(str(path.relative_to(self.repo_root)), "tool_center", content)]

    def _load_markdown_docs(self) -> list[tuple[str, str, str]]:
        candidates: list[Path] = []
        readme = self.repo_root / "README.md"
        if readme.exists():
            candidates.append(readme)
        docs_dir = self.repo_root / "docs"
        if docs_dir.exists():
            candidates.extend(sorted(docs_dir.rglob("*.md")))

        docs: list[tuple[str, str, str]] = []
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:  # pylint: disable=broad-except
                continue
            docs.append((str(path.relative_to(self.repo_root)), "markdown", text))
        return docs

    def _load_rules_docs(self) -> list[tuple[str, str, str]]:
        path = RuntimeConfig.rules_config_path()
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:  # pylint: disable=broad-except
            return []
        source = str(path)
        if path.is_absolute() and self.repo_root in path.parents:
            source = str(path.relative_to(self.repo_root))
        return [(source, "rules", content)]

    def _load_history_summary_docs(self) -> list[tuple[str, str, str]]:
        records = list(ExecutionRecord.objects.all()[:30])
        if not records:
            return []

        lines: list[str] = []
        for record in records:
            summary = (record.summary or "").strip()
            if not summary:
                continue
            lines.append(f"[{record.created_at.isoformat()}] {record.title}: {summary}")

        if not lines:
            return []

        return [("execution_records", "history", "\n".join(lines))]

    def build_chunks(self) -> list[RagChunk]:
        documents: list[tuple[str, str, str]] = []
        documents.extend(self._load_tool_center_docs())
        documents.extend(self._load_markdown_docs())
        documents.extend(self._load_rules_docs())
        documents.extend(self._load_history_summary_docs())

        chunks: list[RagChunk] = []
        for source, source_type, content in documents:
            for idx, text in enumerate(
                self._chunk_text(content, chunk_size=self.CHUNK_SIZE, overlap=self.CHUNK_OVERLAP)
            ):
                chunk_key = f"{source}:{idx}:{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"  # nosec B324
                chunks.append(
                    RagChunk(
                        chunk_id=chunk_key,
                        text=text,
                        source=source,
                        source_type=source_type,
                    )
                )
        return chunks

    def _source_fingerprint(self, chunks: list[RagChunk]) -> str:
        digest = hashlib.md5()  # nosec B324
        for chunk in chunks:
            digest.update(chunk.chunk_id.encode("utf-8"))
        return digest.hexdigest()

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        endpoint = f"{self._normalize_api_base(self.base_url)}embeddings"
        payload = {
            "model": self.embedding_model,
            "input": texts,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=RuntimeConfig.llm_timeout()) as response:  # nosec B310
                data = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise RagEmbeddingError("RAG embedding 请求超时。") from exc
        except error.URLError as exc:
            raise RagEmbeddingError("RAG embedding 服务不可用。") from exc
        except error.HTTPError as exc:
            raise RagEmbeddingError(f"RAG embedding HTTP {exc.code}。") from exc
        except json.JSONDecodeError as exc:
            raise RagEmbeddingError("RAG embedding 返回无效 JSON。") from exc

        raw_items = data.get("data") if isinstance(data.get("data"), list) else []
        vectors: list[list[float]] = []
        for item in raw_items:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if isinstance(embedding, list) and embedding:
                vectors.append([float(v) for v in embedding])

        if len(vectors) != len(texts):
            raise RagEmbeddingError("RAG embedding 结果数量异常。")
        return vectors

    @staticmethod
    def _normalize_vector(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 0:
            return vec
        return [v / norm for v in vec]

    def _index_paths(self) -> tuple[Path, Path, Path]:
        return (
            self.index_dir / "chunks.json",
            self.index_dir / "vectors.json",
            self.index_dir / "meta.json",
        )

    def _save_index(self, chunks: list[RagChunk], vectors: list[list[float]], fingerprint: str) -> None:
        chunks_path, vectors_path, meta_path = self._index_paths()
        chunks_path.write_text(
            json.dumps([asdict(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        vectors_path.write_text(json.dumps(vectors), encoding="utf-8")
        meta_path.write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")

    def _load_cached_index(self) -> tuple[list[RagChunk], list[list[float]], str] | None:
        chunks_path, vectors_path, meta_path = self._index_paths()
        if not (chunks_path.exists() and vectors_path.exists() and meta_path.exists()):
            return None

        try:
            chunks_raw = json.loads(chunks_path.read_text(encoding="utf-8"))
            vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # pylint: disable=broad-except
            return None

        chunks = [RagChunk(**item) for item in chunks_raw if isinstance(item, dict)]
        fingerprint = str(meta.get("fingerprint", ""))
        if not chunks or not vectors or not fingerprint:
            return None
        if len(chunks) != len(vectors):
            return None
        return chunks, vectors, fingerprint

    def _ensure_index(self) -> tuple[list[RagChunk], list[list[float]]]:
        chunks = self.build_chunks()
        if not chunks:
            return [], []

        fingerprint = self._source_fingerprint(chunks)
        cached = self._load_cached_index()
        if cached and cached[2] == fingerprint:
            return cached[0], cached[1]

        vectors = [self._normalize_vector(v) for v in self._embed_texts([chunk.text for chunk in chunks])]
        self._save_index(chunks, vectors, fingerprint)
        return chunks, vectors

    def retrieve(self, question: str) -> list[RagReference]:
        chunks, vectors = self._ensure_index()
        if not chunks or not vectors:
            return []

        query_vector = self._normalize_vector(self._embed_texts([question])[0])
        if HAS_FAISS:
            top = self._retrieve_with_faiss(vectors, query_vector)
        else:
            top = self._retrieve_with_dot_product(vectors, query_vector)

        refs: list[RagReference] = []
        for idx, score in top:
            chunk = chunks[idx]
            refs.append(
                RagReference(
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    source_type=chunk.source_type,
                    score=round(score, 4),
                    snippet=chunk.text[:220],
                )
            )
        return refs

    def _retrieve_with_faiss(
        self,
        vectors: list[list[float]],
        query_vector: list[float],
    ) -> list[tuple[int, float]]:
        matrix = np.asarray(vectors, dtype="float32")
        query = np.asarray([query_vector], dtype="float32")
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        scores, indices = index.search(query, max(1, self.top_k))

        top: list[tuple[int, float]] = []
        for idx, score in zip(indices[0].tolist(), scores[0].tolist()):
            if idx < 0:
                continue
            top.append((int(idx), float(score)))
        return top

    def _retrieve_with_dot_product(
        self,
        vectors: list[list[float]],
        query_vector: list[float],
    ) -> list[tuple[int, float]]:
        scored: list[tuple[int, float]] = []
        for idx, vector in enumerate(vectors):
            score = sum(q * d for q, d in zip(query_vector, vector))
            scored.append((idx, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(1, self.top_k)]

    def build_augmented_prompt(self, question: str, references: list[RagReference]) -> str:
        if not references:
            return question

        lines = [
            "你正在使用平台本地知识库回答问题。",
            "请优先基于以下检索片段作答，并在答案末尾列出来源（格式：来源: xxx）。",
            "",
            "[检索片段]",
        ]
        for idx, ref in enumerate(references, start=1):
            lines.append(f"{idx}. 来源={ref.source}（{ref.source_type}）")
            lines.append(ref.snippet)
            lines.append("")

        lines.append("[用户问题]")
        lines.append(question)
        return "\n".join(lines)

    def answer_with_references(self, question: str) -> tuple[str, list[dict[str, Any]]]:
        refs = self.retrieve(question)
        prompt = self.build_augmented_prompt(question, refs)
        return prompt, [asdict(item) for item in refs]
