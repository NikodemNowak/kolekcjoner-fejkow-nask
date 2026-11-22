# 0002: Python + FastAPI + React, no Rust rewrite

> **Status: superseded by [ADR 0003](0003-python-first-delivery.md)** (FastAPI and the React/TypeScript frontend were removed; delivery is a Python package with a Typer CLI, Streamlit app and HTML report). Kept for history.

**Context:** Proposal to use Rust (or another stack) for speed. The task text sets no technology constraints, scores the demo UI only 0/1, and scores the similarity/clustering mechanism highest.

**Analysis:**
- Time is spent in model inference (InsightFace, SigLIP2, bge-m3, OCR) on the GPU. Those run in CUDA/ONNX Runtime kernels; the Python glue is < 5% of wall time. Rust would not make them faster; Rust bindings to these models are immature or missing.
- The remaining CPU hot spots already run in native code: FAISS (C++), DuckDB (C++), igraph/leidenalg (C), datasketch/numpy (C), imagehash/pdqhash (C).
- Real speed-ups come from: batching on GPU, ONNX Runtime CUDA EP / FP16, caching features per artifact (hash-keyed), blocking (LSH/FAISS) instead of all-pairs comparison, and a cascade (cheap hashes first, heavy models only when needed).
- Rust would cost the team most of the 24 h; three of four members would not be able to use AI assistants as effectively, and the partner (NASK) gets less maintainable code.
- UI: React + Vite is already set up and gives an interactive graph (Cytoscape.js). Svelte/Solid would be marginally lighter but bring no scored benefit. Streamlit would be faster to write but weak for an interactive evidence graph.

**Decision:** keep Python 3.12 + FastAPI + React. Optimize with batching, FP16, caching, blocking, cascades. Measure ads/s and report it on a slide.

**Consequences:** if profiling shows a pure-Python hot loop, move it to numpy/numba first; Rust (PyO3) only for a proven, isolated bottleneck.
