# 🚀 AO_Scrape Project Timeline & Roadmap

**Start Date:** February 25, 2026
**Current Status:** The project currently uses a relational PostgreSQL (RDS) database managed by SQLAlchemy ([database/models.py](file:///home/naoufel/projects/AO_scrape/database/models.py)). Document extraction (`extraction_container`) chunks markdown files and pushes to S3/SQS. The goal is to migrate to a fully Semantic Graph architecture using AWS Neptune, enrich the ontology with temporal and constraint logic, and build a unified Knowledge Base with Vector Search inference.

---

## Phase 1: Ontology Enhancement & Finalization

**Dates:** Feb 25, 2026 – Feb 28, 2026 (4 Days)
**Objective:** Upgrade [tender_structure.ttl](file:///home/naoufel/projects/AO_scrape/ontology/tender_structure.ttl) to support advanced inference and temporal reasoning.

- **[ ] Integrate OWL-Time:** Replace standard `xsd:dateTime` data properties with true temporal entities (`time:Instant`, `time:Interval`) to enable advanced reasoning over tender execution times, submission deadlines, and event sequencing.
- **[ ] Define Axiom Property Chains:** Enhance inference (e.g., `ts:is_awarded_to` o `ts:located_in` -> `ts:serves_region`) to automatically deduce implicit relationships between contractors, tenders, and regions.
- **[ ] Implement Constraints:** Add SHACL shapes or OWL cardinality constraints to guarantee data consistency (e.g., a tender must have exactly one submission deadline; a contract must have exactly one awarded contractor).

## Phase 2: AWS Neptune Infrastructure Setup

**Dates:** Mar 1, 2026 – Mar 5, 2026 (5 Days)
**Objective:** Provision and configure the new graph database backend.

- **[ ] Cluster Provisioning:** Create an AWS Neptune cluster (Serverless recommended for burst workloads) with RDF/SPARQL enabled.
- **[ ] Security & Access:** Configure VPC, Subnets, and IAM roles to restrict access securely while allowing internal containers/Lambdas to securely connect to Neptune.
- **[ ] Testing & Validation:** Set up a Jupyter Notebook (Neptune Workbench) or test scripts to validate connection, data ingestion speeds, and basic SPARQL query capabilities.

## Phase 3: Data Migration (RDS to Neptune)

**Dates:** Mar 6, 2026 – Mar 12, 2026 (7 Days)
**Objective:** Safely transition historical tabular data into the semantic graph.

- **[ ] Data Extraction:** Export existing tables ([tenders](file:///home/naoufel/projects/AO_scrape/Db_Healer.py#179-197), `buyers`, `contractors`, `results`) from the current RDS database into CSV formats.
- **[ ] RDF Transformation Pipeline:** Write a Python script to map the CSV tabular data into RDF triples ([.ttl](file:///home/naoufel/projects/AO_scrape/ontology/morocco_regions.ttl) or `.nt` format) that strictly align with the finalized [tender_structure.ttl](file:///home/naoufel/projects/AO_scrape/ontology/tender_structure.ttl) ontology.
- **[ ] Bulk Ingestion:** Upload the generated RDF files to S3 and trigger the Neptune Bulk Loader API to ingest historical nodes and edges.

## Phase 4: Codebase Refactoring (Decoupling SQL)

**Dates:** Mar 13, 2026 – Mar 22, 2026 (10 Days)
**Objective:** Update all existing scripts to read/write directly to Neptune, completely dropping SQL.

- **[ ] Deprecate [models.py](file:///home/naoufel/projects/AO_scrape/database/models.py):** Remove SQLAlchemy dependencies across the project.
- **[ ] Refactor [Db_updater.py](file:///home/naoufel/projects/AO_scrape/Db_updater.py) & [Db_Healer.py](file:///home/naoufel/projects/AO_scrape/Db_Healer.py):** Update web scraping and synchronization scripts to generate RDF triples dynamically and insert them using SPARQL `INSERT DATA` queries.
- **[ ] Update Lambdas:** Ensure that AWS Lambda functions handling zip extraction and data syncing are refactored to query Neptune instead of RDS.

## Phase 5: Extraction Container Finalization

**Dates:** Mar 23, 2026 – Mar 28, 2026 (6 Days)
**Objective:** Solidify the `extraction_container` LLM workflows to output Knowledge Base ready configurations.

- **[ ] LLM Prompt Engineering:** Refine chunking and extraction prompts so the output directly conforms to the ontology concepts (JSON-LD format is recommended).
- **[ ] QA & Validation:** Introduce validation loops inside the extraction pipeline to ensure the output data complies with the SHACL shapes defined in Phase 1 before emitting SQS messages.

## Phase 6: Knowledge Base Ingestion & Embedding Container

**Dates:** Mar 29, 2026 – Apr 4, 2026 (7 Days)
**Objective:** Create the bridge between unstructured extraction and semantic search.

- **[ ] Container Development:** Create a new Dockerized container (`kb_ingestion_container`) that listens for extraction completion events.
- **[ ] Graph Parsing:** Parse the JSON/JSON-LD outputs from Phase 5 and insert new instances directly into AWS Neptune.
- **[ ] Embedding Generation:** Take the raw text attributes of tenders/contractors, pass them through an embedding model (e.g., OpenAI `text-embedding-3-small` or AWS Titan), and store the resulting vectors. (*Note: This can be stored in Neptune using Neptune Vector Search / OpenSearch integration*).

## Phase 7: Semantic Inference & Vector Comparison

**Dates:** Apr 5, 2026 – Apr 12, 2026 (8 Days)
**Objective:** Build the intelligent querying methods.

- **[ ] Hybrid Search Implementation:** Develop an API/method that combines structured SPARQL property path queries (e.g., retrieving all contractors in a given region) with k-NN vector similarity search (e.g., finding tenders with similar textual requirements).
- **[ ] Inferential Reasoning Testing:** Write test cases proving the property chains and OWL-Time logic work (e.g., finding conflicts in contractor schedules based on overlapping tender execution intervals).

---

# 🚀 Part 2: SaaS Application Development (Foundational to Advanced)

Once the Neptune Knowledge Base is operational, Part 2 focuses on building the user-facing SaaS application, encompassing backend APIs, frontend UI, and premium AI features.

## Phase 8: SaaS Backend & API Layer

**Dates:** Apr 13, 2026 – Apr 25, 2026 (13 Days)
**Objective:** Build a robust, scalable backend to serve frontend requests and interface with AWS Neptune/OpenSearch.

- **[ ] API Framework:** Set up a modern Python backend (e.g., FastAPI) to handle asynchronous requests efficiently.
- **[ ] Authentication & Authorization:** Implement user authentication (e.g., Auth0, AWS Cognito) with role-based access control (Standard vs. Premium tiers).
- **[ ] Graph Query Endpoints:** Create dynamic API routes that translate frontend filter requests into optimized SPARQL queries (e.g., `GET /api/tenders?region=Casablanca&budget_min=100000`).
- **[ ] Historic Data Aggregation:** Develop endpoints that aggregate historical data (e.g., contractor win rates, competitor histories) using Neptune analytics.

## Phase 9: Frontend Architecture & Core UI

**Dates:** Apr 26, 2026 – May 10, 2026 (15 Days)
**Objective:** Develop a modern, dynamic, and responsive web application (e.g., Next.js, React, or Vue).

- **[ ] Design System:** Establish a premium design aesthetic (TailwindCSS, Radix UI or similar) with dynamic interactions and dark mode support.
- **[ ] Search & Filtering Hub:** Build an advanced consulting dashboard where users can explore tenders using multi-faceted filters (by region, budget, category, publication date, etc.).
- **[ ] Historic & Competitor Views:** Implement detail pages for specific Contractors and Tenders, showcasing visual timelines, rivalries, and historical win-loss records.
- **[ ] *Proposed Feature - Saved Alerts:*:** Allow users to save their complex filter configurations and subscribe to email/push alerts when new matching tenders are published.

## Phase 10: Advanced Analytics & Monte Carlo Simulation

**Dates:** May 11, 2026 – May 20, 2026 (10 Days)
**Objective:** Implement statistical modeling for bid pricing strategy.

- **[ ] Data Modeling:** Extract historic pricing data for similar semantic categories (using vector similarity) from the Knowledge Base.
- **[ ] Monte Carlo Engine:** Build a Python simulation engine (using `numpy`/`scipy`) that runs thousands of randomized bidding scenarios based on historical variance, competitor profiles, and market conditions.
- **[ ] Simulation UI:** Create an interactive frontend dashboard where users can input baseline costs and see the probability distribution curve of winning at different price points.
- **[ ] *Proposed Feature - Market Share Dashboard:*:** Visual charts showing total spent budget per region and top 10 contractors dominating specific domains.

## Phase 11: Premium "Wise Agent" (RAG Integration)

**Dates:** May 21, 2026 – May 30, 2026 (10 Days)
**Objective:** Develop the flagship conversational AI assistant for Premium users.

- **[ ] RAG Architecture:** Implement a Retrieval-Augmented Generation (RAG) pipeline bridging the user's chat interface, the Neptune Knowledge Base, and the LLM (e.g., OpenAI or Claude).
- **[ ] Graph-to-Text Grounding:** Enable the Wise Agent to perform NL-to-SPARQL translation to answer hard factual queries (e.g., "Which contractor won the most hospital tenders in Rabat last year?").
- **[ ] Conversational UI:** Build a seamless chat interface with streaming responses, source citations, and the ability to plot charts directly in the chat.
- **[ ] *Proposed Feature - Tender Summarization:*:** Allow the Wise Agent to auto-generate a 1-page executive summary of a 100-page tender document (CPS/RC).

## Phase 12: Beta Testing, Optimization & Launch

**Dates:** Jun 1, 2026 – Jun 10, 2026 (10 Days)
**Objective:** Finalize the application for initial user onboarding.

- **[ ] Performance Tuning:** Optimize slow SPARQL queries, implement caching (Redis) for heavily accessed historic data and dashboard metrics.
- **[ ] QA & User Acceptance Testing:** Conduct end-to-end testing of the payment gateways, premium feature lockouts, and search accuracy.
- **[ ] Launch:** Deploy production frontend (e.g., Vercel/AWS Amplify) and backend (AWS ECS/Lambda), and open registration.

---
*Note: This timeline is aggressive and assumes dedicated focus. Adjust buffer days as needed for AWS infrastructure latency and LLM prompt iterations.*
