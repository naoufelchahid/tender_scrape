---
name: apache-jena
description: "This skill should be used when the user asks to work with Apache Jena, write SPARQL queries, manage RDF data, or interact with Jena Fuseki servers. It provides comprehensive guidance on Semantic Web technologies within the Jena ecosystem."
category: data-engineering
risk: safe
source: community
tags: "[rdf, sparql, apache-jena, semantic-web, fuseki, knowledge-graph]"
date_added: "2026-03-25"
version: "1.0.0"
---

# apache-jena

## Purpose

To provide expert assistance in building and maintaining Knowledge Graphs using the Apache Jena framework. This skill covers RDF data modeling, SPARQL query and update generation, Jena Fuseki configuration, and reasoning implementation. It also assists with Python-based interactions via Jena's REST API.

## When to Use This Skill

This skill should be used when:

- Creating or modifying RDF data models (Turtle, RDF/XML, JSON-LD)
- Writing, debugging, or optimizing SPARQL 1.1 queries (SELECT, ASK, CONSTRUCT, DESCRIBE)
- Performing SPARQL UPDATES (INSERT DATA, DELETE DATA)
- Configuring and deploying Apache Jena Fuseki servers
- Implementing rule-based reasoning or OWL/RDFS inference
- Working with Jena TDB2 for persistent high-performance storage
- Developing Python clients for Jena Fuseki (as seen in the `JenaClient` implementation)

## Core Capabilities

### 1. SPARQL Query Generation

Generates syntactically correct and efficient SPARQL 1.1 queries. It understands property paths, aggregations, and subqueries.

- **SELECT**: To retrieve bindings for variables.
- **ASK**: To check if a pattern exists in the graph.
- **CONSTRUCT**: To create new RDF triples based on existing data.
- **DESCRIBE**: To retrieve all triples related to a specific resource.

### 2. RDF Data Modeling

Assists in defining ontologies and instances using best practices.

- GUIDANCE on choosing appropriate namespaces and URI structures.
- CONVERSION suggestions between different RDF serializations (e.g., JSON-LD to Turtle).
- VALIDATION of RDF data according to SHACL shapes (if context is provided).

### 3. Jena Fuseki Management

Provides configuration snippets and deployment strategies for Fuseki.

- **Service Configuration**: Helping define `fuseki:Service` and `fuseki:Dataset` in TTL files.
- **Endpoint definition**: configuring `fuseki:serviceQuery`, `fuseki:serviceUpdate`, and `fuseki:serviceUpload`.
- **Security settings**: Implementing basic auth and IP-based access control.
- **Integration with TDB2**: Configuring persistent Storage backend using `tdb2:DatasetTDB2`.

### 4. Reasoning & Inference

Helps leverage Jena's inference engine to uncover implicit relationships.

- **RDFS Reasoning**: Basic subclass/subproperty inference.
- **OWL Reasoning**: More complex logic like transitive properties and functional properties.
- **Custom Rule Engine**: Defining Jena-specific rules (e.g., `(?x ts:isParentOf ?y) (?y ts:isParentOf ?z) -> (?x ts:isGrandParentOf ?z)`).
- **Performance Tuning**: Using `InferenceModel` efficiently and avoiding recursion pitfalls.

### 5. Persistent Storage with TDB2

Assists in setting up and managing TDB2 for high-performance RDF storage.

- **TDB2 Transactions**: Ensuring ACID properties using `Dataset.begin()`, `Dataset.commit()`, and `Dataset.end()`.
- **Compaction**: Guidance on running `tdb2.tdbcompact` to maintain data health.
- **Backups**: Procedures for creating snapshots of the triple store.

### 6. Python Integration

Supports the development of robust Python clients for Jena.

- IMPLEMENTATION of `JenaClient` patterns for query and update execution.
- EXCEPTION handling for network and SPARQL errors.
- MOCKING strategies for unit testing Jena interactions.

## Implementation Patterns

### SPARQL SELECT Pattern

```sparql
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?tender ?label
WHERE {
  ?tender a ts:Tenders ;
          rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), "construction"))
}
OFFSET 0
LIMIT 10
```

### SPARQL INSERT DATA Pattern

```sparql
PREFIX ts: <http://www.tenderintelligence.io/ontology/tender-structure#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {
  ts:Tender_001 a ts:Tenders ;
                ts:Ref "REF-2026-X" ;
                ts:Budget "150000"^^xsd:decimal .
}
```

### Fuseki TDB2 Configuration (config.ttl)

```turtle
PREFIX :        <#>
PREFIX fuseki:  <http://jena.apache.org/fuseki#>
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX tdb2:    <http://jena.apache.org/2016/tdb#>
PREFIX ja:      <http://jena.hpl.hp.com/2005/11/Assembler#>

:service_tenders rdf:type fuseki:Service ;
    fuseki:name              "tenders" ;
    fuseki:serviceQuery      "query" , "sparql" ;
    fuseki:serviceUpdate     "update" ;
    fuseki:serviceUpload     "upload" ;
    fuseki:serviceReadGraphStore "get" ;
    fuseki:dataset           :dataset .

:dataset rdf:type tdb2:DatasetTDB2 ;
    tdb2:location "/var/jena_fuseki/databases/tenders" .
```

### Python JenaClient Example

```python
def check_tender_exists(client, tender_ref):
    query = f"""
    PREFIX ts: <{client.TS_PREFIX}>
    ASK {{
      ts:Tender_{tender_ref} a ts:Tenders .
    }}
    """
    return client.sparql_ask(query)
```

## Best Practices

- **Use Prefixes**: Always define and use meaningful prefixes to keep queries readable.
- **Transaction Safety**: Ensure updates are transactional to maintain data integrity.
- **Limit Results**: Use `LIMIT` and `OFFSET` when working with large datasets to avoid memory issues.
- **Filter Early**: Place `FILTER` clauses as early as possible in the query to reduce the search space.
- **Type Literals**: Explicitly type literals (e.g., `^^xsd:dateTime`, `^^xsd:integer`) to ensure correct reasoning and comparison.
- **Avoid DESCRIBE and CONSTRUCT for very large graphs**: unless restricted by `LIMIT` or specific filters, as they can cause memory pressure.
- **Index Management**: Regularly monitor disk usage and run compaction if using TDB2.

## References

- **Official Documentation**: <https://jena.apache.org/>
- **SPARQL 1.1 Specification**: <https://www.w3.org/TR/sparql11-query/>
- **RDF Primer**: <https://www.w3.org/TR/rdf11-primer/>
- **Jena TDB2 Guide**: <https://jena.apache.org/documentation/tdb2/>
