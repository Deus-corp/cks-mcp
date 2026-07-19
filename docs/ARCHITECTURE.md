# ARCHITECTURE

## CKS MCP Server Architecture

**Status:** Draft  
**Applies to:** CKS MCP Server  
**Category:** Architecture  

---

## 1. Purpose

This document defines the architecture of the CKS MCP Server.

It establishes:
- The server's role within the CKS ecosystem.
- The architectural principles guiding its design.
- The components that make up the server and their interactions.
- The security and trust model for operations like source verification.

This document is intended for developers who want to understand, extend, or integrate with the server.

---

## 2. Architectural Role

The CKS MCP Server operates as an **Exposure Layer** in the CKS ecosystem. It translates external, LLM-friendly requests (MCP tools) into internal, canonical operations managed by `cks-runtime` and validated by `cks-core`.

```
LLMs (Claude Desktop, etc.)
        │
        ▼
CKS MCP Server  ← (Exposure Layer)
        │
        ▼
CKS Runtime  ← (Operational Layer)
        │
        ▼
CKS Core  ← (Semantic Layer)
```

The server contains **no semantic logic** and **no operational state management**. It is a thin, stateless translator between two protocols: Model Context Protocol and CKS Canonical Operations.

---

## 3. Architectural Principles

### 3.1 Server as a Thin Translator

The server's sole responsibility is to map MCP tool calls to `cks-runtime` operations and return the results. It must never implement validation, evolution, or persistence logic itself.

### 3.2 Provenance over Trust

LLMs can generate convincing but fabricated data. The server must not trust the content of an LLM request for operations like source verification. Instead, it must enforce **provenance**: a `VerificationRecord` is only valid if it was created by the `verify_source` tool, which performs a real-world check and cryptographically signs the result.

### 3.3 Unconditional Safety

Safety checks must not be optional or dependent on correct LLM behavior. A malicious or forgetful model might omit an `extensions` parameter, so critical integrity checks—like verification of a `VerificationRecord`'s provenance—are performed **unconditionally**.

### 3.4 Defense in Depth

Security protections, such as SSRF prevention, are implemented at multiple levels: URL scheme and hostname validation, IP allow-listing, and DNS rebinding protection via connection pinning. No single check is relied upon as the sole defense.

---

## 4. Components

The server is composed of a few key modules, each with a distinct responsibility.

### 4.1 `server.py` — MCP Transport

- Manages the JSON-RPC over stdio transport.
- Handles MCP lifecycle methods (`initialize`, `ping`, `tools/list`).
- Routes `tools/call` requests to the appropriate handler.
- Translates internal errors into structured, LLM-friendly error responses.

### 4.2 `tools/` — Operation Handlers

Each tool is a standalone module that implements a single canonical operation:

- `validate.py`: Validates a structure, applying optional extensions and unconditionally checking `VerificationRecord` provenance.
- `serialize.py`: Returns the canonical JSON representation of a structure.
- `explain.py`: Provides a human-readable summary of a structure.
- `evolve.py`: Applies a sequence of structural operators to a structure.
- `verify_source.py`: The **sole sanctioned constructor** of `VerificationRecord` objects. It performs a real HTTP check, enforces SSRF protection, and signs the result with a process-local HMAC.

### 4.3 `errors.py` — Structured Errors

Maps internal exceptions to structured error dictionaries (`error` and `message` fields) that give the calling LLM actionable information about what went wrong.

### 4.4 `provenance.py` — Cryptographic Trust

Provides `sign()` and `verify()` functions for `VerificationRecord` objects. A record is only considered genuine if it carries a valid HMAC signature, proving it was created by `verify_source` in the current server process.

---

## 5. Request Flow

The following describes the lifecycle of a `validate_knowledge` request, which is the most complex tool.

1.  **MCP Transport:** `server.py` reads a JSON-RPC request from stdin and dispatches it to `validate_knowledge`.
2.  **Parsing:** The tool parses the input `json_data` into a `KnowledgeStructure` using `cks-core`. A `cks.SerializationError` here results in a structured `invalid_json` error.
3.  **Extension Resolution:** If the LLM requested extensions (e.g., `embedding_projection`), the tool resolves these stable names to internal `Constraint` objects.
4.  **Runtime Session:** The tool creates a new `RuntimeSession` and `Transaction` via `cks-runtime`.
5.  **Validation Operation:** A `ValidateOperation`, carrying the structure and any extensions, is added to the transaction and committed.
6.  **Core Diagnostics:** The first layer of diagnostics comes from `cks-core`'s validation pipeline, returned via the `Transaction`.
7.  **Provenance Check (Unconditional):** The tool inspects the `KnowledgeStructure` for any `VerificationRecord` objects. For each one found, it verifies the HMAC signature using the `provenance` module. Records without a valid signature generate a `CKS-MCP-UNVERIFIED-PROVENANCE` diagnostic.
8.  **Response:** The final result, combining `valid` status, version/session IDs, and all diagnostics, is returned to `server.py` to be sent back to the LLM.

---

## 6. Security Model

### 6.1 Trust Boundary

The LLM and its input are considered **untrusted**. The server is responsible for enforcing all safety and integrity rules, regardless of whether the LLM correctly requests them.

### 6.2 SSRF Protection (`verify_source`)

The `verify_source` tool implements a strict outbound request policy:
- Only `http` and `https` schemes are allowed.
- The target hostname is resolved and validated against a list of public IP ranges. Private, loopback, link-local, and cloud metadata IPs are blocked.
- To prevent DNS rebinding attacks, the HTTP connection is pinned to the specific IP address that was validated, ensuring the actual request cannot be redirected to a different, internal address.
- This validation is repeated for every redirect hop.

### 6.3 Provenance Enforcement (`VerificationRecord`)

- The `verify_source` tool is the only legitimate creator of `VerificationRecord` objects.
- Each record is signed with an HMAC using a process-local secret.
- The `validate_knowledge` tool **unconditionally** checks this signature for every `VerificationRecord` in a structure, regardless of the `extensions` parameter.
- This guarantees that a hand-crafted, fabricated verification record can never pass as genuine.

---

## 7. Extension Model

The server supports **opt-in validation extensions**. These are additional constraints from `cks-core` that are not active by default but can be enabled per call via the `extensions` parameter.

- Extensions are requested by stable string names (e.g., `"embedding_projection"`), which the server maps to internal constraint objects.
- This model allows domain-specific validation rules to be distributed and activated without modifying the server or the global state.
