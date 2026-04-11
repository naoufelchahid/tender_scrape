# 8_Result_Ingestion: Results Ingestion Service

This service handles the **eighth and final stage** of the pipeline: extracting structured award data from result markdown and enriching the Knowledge Graph.

## Purpose

- **Poll** SQS `RESULTS_INGESTION_QUEUE` for processed result documents.
- **Download** result markdown from S3.
- **Extract** winning bidders, award amounts, and excluded bidders using a **local LLM (Ollama)**.
- **Map** the extracted JSON data into RDF triples using `ResultRdfMapper`.
- **Validate** the data against SHACL shapes specifically designed for results.
- **Insert** the data into Apache Jena Fuseki to complete the tender's lifecycle.

## Key Files

| File | Purpose |
|------|---------|
| `result_ingestor.py` | SQS consumer and main orchestration logic. |
| `ollama_client.py` | Client for interacting with local Ollama instance (DeepSeek-R1). |
| `rdf_mapper.py` | Logic for mapping result JSON to RDF triples. |
| `shacl_validator.py` | Validates result RDF against `ontology/shapes_results.ttl`. |
| `jena_client.py` | Client for SPARQL updates to Fuseki. |
| `uri_builder.py` | Shared URI construction helpers for the Results namespace. |

## Workflow

1. **Trigger**: Receives a message with `tender_ref` and S3 path to a result markdown file.
2. **Fetch**: Downloads `tender_results/{tender_ref}/pv.md` from S3.
3. **Reasoning**: Sends the markdown to Ollama with a specialized prompt to extract:
   - Winner Name (Company)
   - Total Award Amount (HT and TTC)
   - Excluded Bidders and Reasons
   - Date of award
4. **Transform**: `ResultRdfMapper` converts the JSON response into an RDF graph.
5. **Validate**: `ShaclValidator` ensures the graph meets all ontology constraints (e.g., amount must be positive).
6. **Finalize**: The validated triples are inserted into the `tenders` dataset in Jena via SPARQL.

## Local Development

### Setup
```bash
cd 8_Result_Ingestion
pip install -r requirements.txt

# Ensure Ollama is running with the required model
ollama run deepseek-r1:1.5b
```

### Commands
```bash
# Run the result ingestion service
python result_ingestor.py
```

## Configuration

| Variable | Purpose | Example |
|---|---|---|
| `OLLAMA_BASE_URL` | Local LLM endpoint | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model to use for extraction | `deepseek-r1:1.5b` |
| `JENA_ENDPOINT` | URL of the Fuseki server | `http://fuseki:3030` |

## Integration Notes

- **Local LLM**: Uses Ollama locally to process result documents efficiently without incurring external API costs.
- **Knowledge Graph Enrichment**: This stage adds `ts:hasWinner`, `ts:awardAmount`, and `ts:wasExcluded` properties to existing Tender nodes.
