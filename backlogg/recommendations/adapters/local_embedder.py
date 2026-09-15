"""The local, multilingual embedding model — and the wall that keeps it local.

Where this runs, and where it must never run
--------------------------------------------

On the **GitHub Actions runner**, called from ``scripts/generate_embeddings.py``
and nowhere else.  Not on Render, not in a request handler, not in the nightly
sync that goes through the API.  Two independent reasons, and both matter:

1. *Cost.*  The project lives on free tiers.  An embeddings API (OpenAI, Jina)
   is the obvious alternative and it costs money — a few cents, but a recurring
   few cents and an account, a key and a vendor.  A runner has 4 vCPU, 16 GB
   and 14 GB of disk for free, and 40.000 short texts is minutes of CPU there.
2. *Image size.*  ``sentence-transformers`` drags in ``torch``: hundreds of MB
   in the image and a resident-memory footprint that does not fit next to
   uvicorn on a 512 MB Render instance.

The wall is not a convention, it is the packaging.  ``sentence-transformers``
is declared in ``[project.optional-dependencies].embeddings`` and the Dockerfile
builds with ``uv sync --no-dev --frozen`` — which installs the default
dependency set and **no extras**.  The library therefore cannot be in the
deployed image, and this module makes that survivable: the import is inside
``load()``, so importing this file (which the test suite does) needs nothing
installed.  The only thing the API ever touches is the HNSW index.

The model
---------

``intfloat/multilingual-e5-small`` (MIT, 118M params, ~470 MB on disk):

- **Multilingual is not optional.**  Synopses arrive in Spanish from some
  sources and English from others, sometimes for the same item; a monolingual
  model would put the Spanish half of the catalog in a different region of the
  space from the English half and the cross-type bridge would break along a
  language seam instead of a meaning one.
- **384 dimensions natively**, which is the number the storage budget was sized
  against.  Nothing is truncated: the model outputs exactly what is stored.
- **512-token window.**  This is what decided it over
  ``paraphrase-multilingual-MiniLM-L12-v2``, the other obvious 384-dimension
  multilingual
  candidate at this size, whose window is 128 tokens — shorter than a typical TMDB
  synopsis, so most items would be embedded on a truncated first half.
- **BGE-M3 was rejected on disk, not quality**: 1024 dimensions is 2 KB per
  item in halfvec, which alone would eat the entire Neon free headroom before
  the index is built.

E5 models expect a task prefix and lose measurable quality without one.  For
*symmetric* similarity — which is what "items like this one" is — the model
card prescribes ``"query: "`` on both sides, so every text gets it
(``EMBEDDING_TEXT_PREFIX``).

Vectors come back L2-normalised, so cosine and dot product agree and the
``<=>`` distance the index is built on is the one the model was trained for.
"""

from collections.abc import Sequence
from typing import Protocol

__all__ = ["Embedder", "SentenceTransformerEmbedder"]


class Embedder(Protocol):
    """What the generation pass needs from a model, and nothing more.

    A Protocol rather than the concrete class so the tests can inject a
    deterministic fake: the suite must not download 470 MB of weights, must not
    touch the network at all, and must still exercise the real batching,
    hashing, skipping and persistence paths.
    """

    #: Identifies the vector space.  Persisted in ``item_embeddings.model`` —
    #: a change here invalidates every stored vector, by design.
    name: str
    #: Components per vector; must equal ``settings.EMBEDDING_DIM``.
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch, returning one L2-normalised vector per input."""
        ...


class SentenceTransformerEmbedder:
    """``sentence-transformers`` behind the ``Embedder`` protocol.

    Loading is deferred to ``load()`` (and to the first ``embed`` if skipped)
    so that constructing this object — which ``scripts/generate_embeddings.py``
    does before it knows whether there is any work — costs nothing and,
    crucially, imports nothing.  The import error is caught and re-raised with
    the command that fixes it, because the expected way to hit it is running
    the job locally in an environment provisioned for the API.
    """

    def __init__(self, name: str, dim: int, *, device: str | None = None) -> None:
        self.name = name
        self.dim = dim
        self._device = device
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise RuntimeError(
                "sentence-transformers is not installed. It is an optional extra on "
                "purpose — it pulls in torch, which must never enter the image Render "
                "deploys. Install it only where embeddings are generated:\n"
                "    uv sync --extra embeddings"
            ) from exc
        model = SentenceTransformer(self.name, device=self._device)
        # Renamed in sentence-transformers 6.0; the old name still works but
        # warns. Support both so the extra can float across major versions
        # without the job printing a deprecation on every run.
        dimension_of = getattr(model, "get_embedding_dimension", None) or (
            model.get_sentence_embedding_dimension
        )
        actual = dimension_of()
        if actual != self.dim:
            raise RuntimeError(
                f"{self.name} produces {actual}-dimensional vectors but EMBEDDING_DIM "
                f"is {self.dim}. Do not truncate: the halfvec column is created at "
                f"EMBEDDING_DIM, so either the model or the variable is wrong."
            )
        self._model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.load()
        assert self._model is not None
        vectors = self._model.encode(
            list(texts),
            batch_size=32,
            # Cosine is the metric the HNSW index is built on; normalising here
            # means the stored vectors are unit-length and `<=>` is exactly the
            # angle, with no per-query renormalisation.
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [[float(component) for component in vector] for vector in vectors]
