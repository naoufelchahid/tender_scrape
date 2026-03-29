# SPARQL 1.1 Quick Reference Guide

SPARQL (SPARQL Protocol and RDF Query Language) is the standard language for querying and updating RDF data.

## Query Forms

### SELECT

Retrieves values for variables.

```sparql
SELECT ?subject ?predicate ?object
WHERE {
  ?subject ?predicate ?object .
}
LIMIT 10
```

### ASK

Returns a boolean indicating if the pattern exists.

```sparql
ASK {
  ?s a <http://schema.org/Person> .
}
```

### CONSTRUCT

Returns an RDF graph constructed by substituting variables into a template.

```sparql
CONSTRUCT { ?s <http://example.org/newProp> ?o }
WHERE { ?s <http://example.org/oldProp> ?o }
```

### DESCRIBE

Returns an RDF graph that describes the resources found.

```sparql
DESCRIBE <http://example.org/resource123>
```

## Common Syntax

- **Property Paths**: Use `/` for sequences, `|` for alternatives, and `*` for zero-or-more.
  - `?person foaf:knows/foaf:name ?name`
- **Filters**: Use `FILTER` to restrict results.
  - `FILTER(?age > 18)`
  - `FILTER(regex(?name, "^J", "i"))`
- **Optional**: Use `OPTIONAL` for patterns that may not exist.
  - `OPTIONAL { ?s foaf:mbox ?email }`
- **Aggregation**: Use `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`.
  - `SELECT (COUNT(?s) as ?count) WHERE { ?s ?p ?o }`

## Update Commands

### INSERT DATA

```sparql
INSERT DATA {
  <http://ex.org/s> <http://ex.org/p> "value" .
}
```

### DELETE DATA

```sparql
DELETE DATA {
  <http://ex.org/s> <http://ex.org/p> "value" .
}
```
