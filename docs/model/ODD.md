---
description: System model for enforced-planning's repository inventory and the docstring wiki generated from it; scoped to that component only.
---

# Enforced Planning system model (inventory scope)

**Scope.** This model covers only the repository inventory (`enforced_planning/relationship_context.py`) and the docstring wiki generated from it (`scripts/docstring_wiki.py`). Claims, sessions, worktrees, hooks and plans are not modelled here yet; they are out of scope, not absent.

## Entities and records

| ID | Element | Kind | Owner | Holds |
|---|---|---|---|---|
| ENT-ARTIFACT | `ArtifactRecord` | record | `relationship_context.py` | one tracked file: path, format, classification, working-tree state, `summary`, `summary_source`, symbols, diagnostics |
| ENT-SYMBOL | `SymbolRecord` | record | `relationship_context.py` | one Python module, class or function with its docstring summary |

## Processes and rules

| ID | Process or rule | Owner | Check |
|---|---|---|---|
| PROC-INVENTORY | `inventory_repository` builds one `ArtifactRecord` per git-tracked file | `relationship_context.py` | `tests/test_relationship_context.py` |
| RULE-MD-SUMMARY | A Markdown summary is, in order: the document's own front-matter `description` (`markdown:front-matter:description`), a semantic `##` section (`markdown:section:<name>`), the first body paragraph (`markdown:first-paragraph`). Other front-matter keys never become a summary. Why: AES canonical AES-CTX-004 / Decision 0013, "truth lives where it is edited" | `_markdown_record`, `_split_front_matter` | `test_markdown_front_matter_description_outranks_body`, `test_markdown_prefers_semantic_section_and_labels_fallback` |
| PROC-DOCSTRING-WIKI | `docstring_wiki` renders every `ArtifactRecord` into one Markdown page | `docstring_wiki.py` | `tests/test_docstring_wiki.py` |

## Views

| ID | View | Source | Drift check |
|---|---|---|---|
| VIEW-DOCSTRING-WIKI | `generated/docstring_wiki.md` in each repository that runs the generator | PROC-DOCSTRING-WIKI | `make docstring-wiki-check` fails when the page differs from a fresh render |
