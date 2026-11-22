"""Download model weights into the image at build time, so the jury needs no network.

Calls the extractors' own lazy loaders, so the cached weights are exactly the ones the
code uses. Each model is optional: a failure is reported and the build goes on (the
extractor then skips with a warning at run time). CPU only.

Run: `python scripts/prefetch_models.py`. `PREFETCH_BGE=1` adds bge-m3 (needs the `bge`
extra), `PREFETCH_ASR=1` adds faster-whisper.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable


def _siglip() -> object:
    from fakecollector.extractors.image_embed import _model

    return _model()


def _easyocr() -> object:
    from fakecollector.extractors.ocr import _reader

    return _reader()


def _insightface() -> object:
    from fakecollector.extractors.face import _insightface_app

    return _insightface_app(False)


def _bge() -> object:
    from fakecollector.extractors.text import _bge_model

    model = _bge_model()
    if model is None:
        raise RuntimeError("sentence-transformers missing (install the `bge` extra)")
    return model


def _whisper() -> object:
    from fakecollector.extractors.video import _whisper as load

    return load()


def main() -> int:
    """Load every model once; print a summary."""
    os.environ.setdefault("FAKECOLLECTOR_DEVICE", "cpu")
    steps: list[tuple[str, Callable[[], object]]] = [
        ("siglip2", _siglip),
        ("easyocr", _easyocr),
        ("insightface buffalo_l", _insightface),
    ]
    if os.environ.get("PREFETCH_BGE") == "1":
        steps.append(("bge-m3", _bge))
    if os.environ.get("PREFETCH_ASR") == "1":
        steps.append(("faster-whisper", _whisper))
    failed = []
    for name, load in steps:
        try:
            load()
            print(f"ok      {name}")
        except Exception as exc:  # one missing model must not fail the whole image
            failed.append(name)
            print(f"FAILED  {name}: {exc}", file=sys.stderr)
    print(f"{len(steps) - len(failed)}/{len(steps)} models cached")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
