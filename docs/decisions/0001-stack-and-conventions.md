# 0001: Stack and conventions

> **Status: superseded by [ADR 0003](0003-python-first-delivery.md)** (FastAPI and the React/TypeScript frontend were removed; delivery is a Python package with a Typer CLI, Streamlit app and HTML report). Kept for history.

**Context:** 2 people, about 24 h, AI-assisted development; the jury values a working demo and a clean, reproducible process.

**Decision:** Python 3.12 + FastAPI + pydantic v2 backend (uv, ruff, mypy, pytest); React + Vite + strict TypeScript frontend (eslint, prettier); Docker Compose for a one-command run; shared rules in `AGENTS.md`.

**Consequences:** one set of commands (`make check`) for humans, agents and CI; contracts are explicit (pydantic ↔ `api/types.ts`).
