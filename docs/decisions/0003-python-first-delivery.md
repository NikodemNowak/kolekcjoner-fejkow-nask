# 0003: Python-first delivery (CLI + Streamlit + static report); drop FastAPI and React

**Status:** accepted Sat 21.11, supersedes the UI/API parts of 0001 and 0002.

**Context:** The official task (v2) asks for a demonstrator with a simple GUI (Streamlit/Gradio named, aesthetics not scored), install/run instructions, preferably a container, and will test on a hidden data set. NASK mentors asked for a solution in Python that the jury can run and check themselves from clear instructions, and said advanced similarity methods are what scores. The task text scores the demonstrator 0/1 and names Streamlit/Gradio. The current scaffold (FastAPI + React + nginx, two Dockerfiles, a mirrored TypeScript contract) costs one person the whole hackathon and adds Node to the jury's setup. The corpus is 25 case folders, so nothing needs a client/server split.

**Options:**
1. Keep FastAPI + React. Best-looking graph, but two toolchains, a duplicated contract, and D never touches the scored part.
2. **Pure-Python package: Typer CLI + Streamlit app + self-contained HTML report.** One install, one language, the pipeline is a library the app and CLI both call.
3. Gradio instead of Streamlit. Equivalent for upload-and-show; weaker for multi-page analyst views and tables.

**Decision:** option 2.
- One package `fakecollector` at the **repo root** (`pyproject.toml`, `src/fakecollector/`, `tests/`, `uv.lock`). Base install is light (parsing, graph, app); models live in the optional extra `ml` (`uv sync --extra ml`).
- CLI: `fakecollector ingest <dir>…`, `extract`, `analyze`, `report --html`, `export`, `app`, plus `run` (= all steps) and `demo`.
- A run is a directory (`runs/<name>/`: Parquet tables, `.npy` vectors, `report.html`, exports). The app and the report only read a run; uploads call the same library functions in-process. No HTTP API, no job queue.
- The graph view is one Jinja2 template with Cytoscape.js inlined (MIT, vendored): it is the report's graph and is embedded in Streamlit with `st.components.v1.html`, so there is a single graph implementation and no third-party Streamlit component.
- For the jury: three commands in the README, plus a two-command recipe for their hidden test set (`run` on known data, `assign <test-dir> --against <run>`). Because the test set is new bytes, model extractors must run on **CPU** on the jury's machine: extra `ml` works without a GPU, and the Docker image ships CPU torch with weights baked in. The content-addressed feature cache is only a team accelerator and is not committed (organizer data must not be distributed). Fixed seeds.
- No credentialed service in the default path; optional public sources are documented with license and limits.

**Task 0.5 (owner A, 30 min, first PR, blocks everyone):** `git mv backend/src src`, `backend/tests tests`, `backend/pyproject.toml` and `uv.lock` to the root; delete `frontend/`, `backend/Dockerfile`, `src/fakecollector/api/`, `main.py`; replace FastAPI/uvicorn/httpx with typer, streamlit, jinja2, duckdb, pyarrow, networkx, beautifulsoup4, lxml, tldextract, datasketch, imagehash, mmh3, stix2; add `[project.scripts] fakecollector = "fakecollector.cli:app"` and extra `ml`. `Makefile`: `setup` = `uv sync`; `check` = ruff + mypy + pytest; `demo`; `app`. One root `Dockerfile` (python:3.12-slim, ffmpeg, `uv sync --extra ml` on CPU wheels, weights fetched at build); `docker-compose.yml` has service `app` (port 8501, `./data` and `./runs` mounted) and an optional `neo4j` service behind `--profile neo4j`. **CI keeps both required check names** so branch protection needs no admin change: job `backend` = ruff, mypy, pytest at the root; job `frontend` = Streamlit smoke test (`pytest tests/app -q`, using `streamlit.testing.v1.AppTest`) plus `fakecollector demo --fixtures`. Rename the jobs only after the hackathon. `AGENTS.md` and `README.md` are updated in the same PR.

**Consequences:** D moves from React to pipeline, report, exports and profiles (scored work). No TypeScript, no eslint/prettier. Streamlit reruns the script on every interaction, so all heavy state is loaded through `st.cache_resource` from a run directory. A richer UI or an API can be added later on top of the same library without touching the pipeline. ADR 0002's reasoning about Python performance still holds.

**Status update:** `src/fakecollector/api/` was retained as a read-only JSON API behind the Next.js web UI (`web/`).
