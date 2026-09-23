# Repository guidelines

## Scope
- Finance Detective answers scoped annual-filing questions for SEC and OpenDART companies.
- Preserve reporting period, currency, units, consolidation scope, and filing provenance throughout collection, retrieval, tools, and responses.
- Calculate numeric results in code. Keep structured financial facts separate from narrative evidence and causal interpretations.
- Never invent financial data, citations, evaluation results, or completed features.

## Changes and verification
- Read the affected implementation and tests before changing behavior.
- Keep tools limited to their validated company, filing, period, and observed-value IDs. Do not introduce arbitrary code, SQL, Cypher, or URL execution.
- Keep credentials out of source control, logs, and responses. Do not print local configuration secrets.
- Run `.venv/bin/python -m pytest -q` with local PostgreSQL and Neo4j for backend changes; run `npm run build --prefix frontend` for frontend changes.
- Unit and integration checks must not call paid APIs. Live evaluation is separate and incurs cost.
- Keep README and the affected design or evaluation document aligned with code. Label historical measurements and distinguish development acceptance from independent quality evaluation.
- Add infrastructure when a demonstrated requirement justifies its operational cost.
- Preserve existing unrelated working-tree changes.

## Communication
- Use Korean for user-facing explanations and project documentation.
- Explain behavior, design tradeoffs, verification, and remaining limits with links to the relevant implementation.
