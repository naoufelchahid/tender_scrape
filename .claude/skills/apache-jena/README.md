# Apache Jena Skill

A comprehensive skill for building, querying, and managing Knowledge Graphs using the Apache Jena framework.

## Overview

The `apache-jena` skill enables AI agents to assist with all aspects of the Apache Jena ecosystem. Whether you're a data engineer building a complex RAG pipeline or a researcher exploring Semantic Web technologies, this skill provides the patterns and knowledge needed to succeed.

## Key Features

- **SPARQL Expert**: High-quality generation of query and update commands.
- **RDF Architect**: Guidance on data modeling and serialization.
- **Fuseki Master**: Configuration and management of SPARQL servers.
- **Inference Support**: Leveraging Jena's reasoners for data discovery.
- **Client Integration**: Best practices for connecting Python applications to Jena.

## Installation

### Repository Installation

To use this skill within the current project, ensure the files are located in `.claude/skills/apache-jena/`.

### Global Installation

To make the skill available across all your projects:

```bash
mkdir -p ~/.claude/skills
ln -sf $(pwd)/.claude/skills/apache-jena ~/.claude/skills/apache-jena
```

## Usage

Simply use trigger phrases like:

- "Help me write a SPARQL query for..."
- "How do I configure Jena Fuseki for..."
- "Create an RDF model in Turtle for..."
- "Insert these triples into Jena..."

## Examples

Check the `examples/` directory for sample SPARQL queries and integration scripts.

## License

Apache License 2.0
