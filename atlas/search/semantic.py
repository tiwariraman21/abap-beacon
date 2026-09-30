"""Meaning-based retrieval.

Backends, chosen automatically (best available first):
  minilm    - sentence-transformers all-MiniLM-L6-v2, runs locally, ~90 MB once.
              Needs torch, so Python <= 3.12 today.
  model2vec - static embeddings (minishlab/potion-base-8M, ~30 MB once), numpy
              only, no torch: works on Python 3.14. Nearly MiniLM quality for
              short texts and 100x faster. `pip install model2vec`.
  builtin   - TF-IDF + SVD (latent semantic analysis) with numpy only. Weaker,
              but keeps the feature alive with nothing installed.

The index is stored under <data>/index/ as an .npz plus a .json manifest and
is keyed by object id.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"
M2V_MODEL_NAME = "minishlab/potion-base-8M"
_model = None
_m2v_model = None
WORD = re.compile(r"[a-z][a-z0-9_]{1,}")


def minilm_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def model2vec_available() -> bool:
    try:
        import model2vec  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _get_m2v():
    global _m2v_model
    if _m2v_model is None:
        from model2vec import StaticModel

        _m2v_model = StaticModel.from_pretrained(M2V_MODEL_NAME, normalize=True)
    return _m2v_model


def _embed(backend: str, texts: list[str]) -> np.ndarray:
    if backend == "minilm":
        return np.asarray(_get_model().encode(texts, normalize_embeddings=True, batch_size=32), dtype=np.float32)
    if backend == "model2vec":
        vectors = np.asarray(_get_m2v().encode(list(texts), use_multiprocessing=False), dtype=np.float32)
        return _normalise_rows(vectors)
    raise ValueError(backend)


def best_backend(prefer_models: bool = True) -> str:
    if prefer_models and minilm_available():
        return "minilm"
    if prefer_models and model2vec_available():
        return "model2vec"
    return "builtin"


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(matrix, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return matrix / lengths


def _tokenise(text: str) -> list[str]:
    return WORD.findall(text.lower())


@dataclass
class SemanticIndex:
    backend: str
    ids: list[int]
    vectors: np.ndarray
    vocabulary: dict[str, int] | None = None
    idf: np.ndarray | None = None
    vt: np.ndarray | None = None

    def scores(self, query: str) -> dict[int, float]:
        if self.backend in ("minilm", "model2vec"):
            q = _embed(self.backend, [query])
        else:
            q = self._embed_builtin_query(query)
        sims = (self.vectors @ q.T).ravel()
        return {oid: float(s) for oid, s in zip(self.ids, sims)}

    def _embed_builtin_query(self, query: str) -> np.ndarray:
        assert self.vocabulary is not None and self.idf is not None and self.vt is not None
        row = np.zeros((1, len(self.vocabulary)), dtype=np.float32)
        for word in _tokenise(query):
            pos = self.vocabulary.get(word)
            if pos is not None:
                row[0, pos] += 1.0
        row = _normalise_rows(row * self.idf)
        return _normalise_rows(row @ self.vt.T)


def _build_builtin(texts: list[str]) -> tuple[np.ndarray, dict]:
    vocabulary: dict[str, int] = {}
    for text in texts:
        for word in _tokenise(text):
            vocabulary.setdefault(word, len(vocabulary))
    matrix = np.zeros((len(texts), max(1, len(vocabulary))), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in _tokenise(text):
            matrix[row, vocabulary[word]] += 1.0
    n = len(texts)
    appears = (matrix > 0).sum(axis=0)
    idf = (np.log((1 + n) / (1 + appears)) + 1.0).astype(np.float32)
    matrix = _normalise_rows(matrix * idf)
    components = int(min(96, max(2, min(matrix.shape) - 1)))
    u, s, vt = np.linalg.svd(matrix, full_matrices=False)
    vectors = _normalise_rows(u[:, :components] * s[:components]).astype(np.float32)
    return vectors, {"vocabulary": vocabulary, "idf": idf, "vt": vt[:components].astype(np.float32)}


def build_index(docs: list[tuple[int, str]], index_dir: Path, prefer_minilm: bool = True) -> dict:
    """docs: list of (object_id, text). Writes the index and returns a summary."""
    index_dir.mkdir(parents=True, exist_ok=True)
    ids = [oid for oid, _ in docs]
    texts = [text for _, text in docs]

    backend = best_backend(prefer_minilm)
    extra: dict = {}
    if backend == "builtin":
        vectors, extra = _build_builtin(texts)
    else:
        try:
            vectors = _embed(backend, texts)
        except Exception as error:  # model download failed (offline / proxy) -> keep working
            backend = "builtin"
            extra = {"fallback_reason": f"{type(error).__name__}: {str(error)[:120]}"}
            vectors, builtin_extra = _build_builtin(texts)
            extra.update(builtin_extra)

    np.savez_compressed(
        index_dir / "semantic.npz",
        vectors=vectors,
        ids=np.asarray(ids, dtype=np.int64),
        **({"idf": extra["idf"], "vt": extra["vt"]} if "idf" in extra else {}),
    )
    model_label = {"minilm": MODEL_NAME, "model2vec": M2V_MODEL_NAME}.get(backend, "tfidf-svd")
    manifest = {"backend": backend, "count": len(ids), "dimensions": int(vectors.shape[1]), "model": model_label}
    if extra.get("fallback_reason"):
        manifest["fallback_reason"] = extra["fallback_reason"]
    if "vocabulary" in extra:
        manifest["vocabulary"] = extra["vocabulary"]
    (index_dir / "semantic.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "vocabulary"}


def load_index(index_dir: Path) -> SemanticIndex | None:
    npz_path, json_path = index_dir / "semantic.npz", index_dir / "semantic.json"
    if not npz_path.exists() or not json_path.exists():
        return None
    try:
        manifest = json.loads(json_path.read_text(encoding="utf-8"))
        data = np.load(npz_path)
        index = SemanticIndex(
            backend=manifest["backend"],
            ids=[int(i) for i in data["ids"]],
            vectors=data["vectors"].astype(np.float32),
        )
        if index.backend == "builtin":
            index.vocabulary = manifest["vocabulary"]
            index.idf = data["idf"]
            index.vt = data["vt"]
        if index.backend == "minilm" and not minilm_available():
            return None  # cannot embed queries; caller falls back to keyword
        if index.backend == "model2vec" and not model2vec_available():
            return None
        return index
    except Exception:
        return None


def describe_backend(backend: str) -> str:
    if backend == "minilm":
        return f"Local model {MODEL_NAME} (runs on this machine, nothing leaves it)."
    if backend == "model2vec":
        return f"Local static embeddings {M2V_MODEL_NAME} (numpy only, nothing leaves this machine)."
    return "Built-in TF-IDF/SVD fallback. `pip install model2vec` then `atlas index` for real meaning search."
