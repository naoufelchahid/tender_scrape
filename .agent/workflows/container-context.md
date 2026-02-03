---
name: container-context
description: container-context
---

Acquire total situational awareness of the target Docker container, including its build manifest, file system structure, source code logic, and runtime execution flow. This context is required to prepare for a Refactoring/Modification task in the subsequent prompt.

INSTRUCTIONS: You must perform the following 5 steps sequentially. Do not summarize or skip files; ingest full raw text where specified.

1. INFRASTRUCTURE ANALYSIS

Scan: Locate and read the complete content of the Dockerfile and docker-compose.yml (if present).

Identify: * Base Image (OS/Distro).

Environment Variables (ENV).

Working Directory (WORKDIR).

Exposed Ports.

System-level dependencies installed (via apt, apk, etc.).

1. DEPENDENCY MAPPING

Locate: Identify dependency definition files (e.g., requirements.txt, package.json, go.mod, pom.xml).

Extract: List the core libraries and versions currently installed to ensure refactoring compatibility.

1. EXECUTION TRACING

Trace: Identify the ENTRYPOINT and CMD instructions from the Dockerfile.

Follow: If these point to a shell script (e.g., entrypoint.sh), read that script entirely.

Determine: Exactly what command launches the main application process.

1. CODEBASE INGESTION

Recursive Read: Read the code files residing in the WORKDIR. Focus on:

Configuration files.

Main application entry points (e.g., app.py, index.js, main.go).

Core logic modules.

Constraint: Exclude binary files, logs, node_modules, .git, or __pycache__.

1. CONTEXT ANCHOR (OUTPUT REQUIREMENT) Before waiting for the next prompt, you must output a "Refactoring Readiness Report" containing:

[ ] Architecture Summary: (How the container is built).

[ ] Execution Flow: (What happens when the container starts).

[ ] Key File Map: (List of critical files ingested).

[ ] Confirmation: "Context Loaded. Ready for refactoring instructions."
