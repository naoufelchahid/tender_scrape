---
trigger: always_on
---

# Scraper Project Rules & Architecture

## 1. System Architecture (Immutable)

All code and workflows MUST adhere to this strict pipeline. NO "glue scripts" or external processing steps are allowed outside these containers/stages.

**Pipeline Flow:**

1. **scraping_tenders**: Source collection.
2. **unziping lambda**: Archive handling.
3. **classification container: classify docments in markdown by type
4. **Extraction container**: Structured data extraction from documents types
5. **Lambda database Filler
6. **vectorisation**: Embedding generation.
7. ** synchronize data base and graph knowledge bae

## 2. Graph Knowledge Base Schema

The Graph Knowledge Base MUST follow this exact node and edge structure.

### Nodes

- `buyers`
- `tenders`
- `contractors`
- `lots`
- `products`
- `admin_specs`
- `gen_specs`
- `products_specs`

### Edges (Directed)

| Source | Relationship | Target |
| :--- | :--- | :--- |
| **buyers** | `has_launched` | **tenders** |
| **buyers** | `awarded` | **tenders** |
| **tenders** | `has_admin_specs` | **admin_specs** |
| **tenders** | `has_tech_specs` | **gen_tech_specs** |
| **tenders** | `has_a_lot` | **lot X** |
| **lot X** | `has_winner` | **contractors** |
| **contractors** | `has_bid` | **Lot X** |
| **lot X** | `has_product` | **products** |
| **products** | `has_specs` | **products_specs** |

## 3. Agent Operational Protocols (MANDATORY)

These rules are binding for all agents working on this project.

**CRITICAL** Use relevant skill for each prompt

### 3.1 Workspace Hygiene & Testing

- **NO Temporary Scripts**: NEVER create temporary Python files (e.g., `test_script.py`, `debug.py`) on the filesystem.

- **Direct Execution**: When testing code snippets or verifying logic, you MUST use the terminal directly:
  - `python -c "import ...; ..."`
  - Interactive Python shell
- **Clean Workspace**: The workspace must remain clean. If an artifact is generated for debugging that is NOT a pipeline output, it must be deleted immediately after use.

### 3.2 Coding Standards

- **Architecture Awareness**: Every new file MUST include a header comment stating which stage of the System Architecture it belongs to.

- **Single Source of Truth**: `database/models.py` is the absolute authority for SQL database structure. Do not redefine models elsewhere; import them.
- **Type Hinting**: All functions and methods MUST include Python type hints.

### 3.3 Infrastructure & Tools

- **AWS Interaction**: resolving problems or checking state on AWS MUST be done via **AWS CLI** commands in the terminal. Do NOT write Python/Boto3 scripts for one-off checks.

- **Error Handling**: Fail fast. Use structured JSON logging instead of `print()` where possible.
