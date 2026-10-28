# ROLE

Act as a **Principal Software Architect + AI/ML Engineer + Data Engineer + DevOps Engineer + Technical Researcher**.

You are designing the complete production-grade architecture for the project described in the **attached Markdown specification**.

## SOURCE OF TRUTH

- Read the attached `finsight.md` file **completely before designing anything**.
- Treat it as the **primary and authoritative project specification**.
- Preserve its requirements, scope, terminology, constraints, and architectural principles.
- Do **not** silently remove, simplify, or replace requirements.
- If something is unspecified, explicitly label it as an **architectural decision** rather than pretending it came from the specification.
- Do not add technologies merely because they are popular.
- Avoid unnecessary microservices, agents, databases, frameworks, or infrastructure.

---

# PRIMARY OBJECTIVE

Produce a **technically rigorous but extremely concise implementation blueprint** for the entire project.

I want **maximum architectural depth with minimum words**.

Use:
- tables
- compact bullet points
- diagrams
- trees
- decision matrices
- concise annotations

Avoid:
- generic explanations
- motivational text
- repeated information
- obvious definitions
- long prose
- filler
- marketing language

Every sentence should either:
1. define architecture,
2. justify a decision,
3. specify implementation,
4. identify a dependency/risk, or
5. tell me what to build.

---

# CRITICAL RESEARCH REQUIREMENT

Before finalizing the technology stack, **research the current web extensively**.

For **EVERY major technology/tool/library/service and its version**, verify current information from authoritative sources.

Prefer sources in this order:

1. Official documentation
2. Official GitHub repository/releases
3. Official vendor documentation
4. Official technical papers/specifications
5. High-quality engineering sources

Do NOT rely on outdated knowledge.

For every selected technology, verify:

- current stable version
- release/status
- Python/Node/runtime compatibility
- database compatibility
- framework compatibility
- official support status
- major breaking changes
- security/lifecycle concerns
- suitability for this project
- licensing where relevant

If a tool has multiple viable alternatives, **research and compare them before choosing**.

Do not choose a technology merely because it is commonly used.

For versioned dependencies, give the **exact version or version range** you recommend and the reason.

If a version cannot be reliably verified, say so instead of inventing one.

---

# OUTPUT STRUCTURE

## 0. Executive Architecture

Give a compact overview containing:

- architecture style
- major components
- data stores
- AI/ML components
- external services
- deployment model
- major data flows

Then provide a single architecture diagram:

```text
User
 ↓
Frontend
 ↓
API / Application Layer
 ↓
────────────────────────────────────
│ Financial Intelligence Platform  │
│                                  │
│ Query / Agent Orchestrator       │
│ Analytics │ ML │ RAG │ Reports   │
│                                  │
────────────────────────────────────
 ↓
PostgreSQL / Vector / Object Store
 ↓
Background Processing / AI Services
```

Adapt this to the actual project.

---

# 1. ARCHITECTURE DESIGN

Design the complete architecture.

Cover:

### Application architecture
- frontend
- backend
- API layer
- domain/application services
- background workers
- AI/ML services
- agent orchestration
- document processing
- authentication/authorization
- observability

### Data architecture
Clearly distinguish:

```text
Raw → Extracted → Validated → Normalized → Derived Intelligence
```

Design:
- primary database
- vector storage
- object/blob storage
- cache if needed
- queues/event infrastructure if needed
- analytical storage if actually justified

For each storage technology explain **why it exists and what data belongs there**.

### AI architecture

Explicitly separate:

```text
Deterministic computation
ML
LLM
RAG
Agentic orchestration
```

Show exactly which component handles which responsibility.

Do not allow the LLM/agent to perform tasks that should be deterministic.

### Security architecture

Include:
- authentication
- authorization
- tenant/user isolation
- secrets
- encryption
- file security
- prompt-injection defenses
- SQL/tool restrictions
- audit logging
- retention/deletion
- sensitive-data handling

---

# 2. DATABASE DESIGN

Design the actual database, not merely list entities.

Provide:

### ERD

Use Mermaid:

```mermaid
erDiagram
    USER ||--o{ ACCOUNT : owns
    ACCOUNT ||--o{ TRANSACTION : contains
    ...
```

### Schema

For every important table provide:

| Table | Column | Type | Constraints | Purpose |
|---|---|---|---|---|

Do not document trivial fields excessively.

Include:
- primary keys
- foreign keys
- unique constraints
- indexes
- composite indexes
- timestamps
- provenance
- confidence fields
- audit fields
- soft-delete/retention strategy where appropriate

### Data separation

Explicitly show where each belongs:

- raw documents
- extracted fields
- normalized transactions
- embeddings
- analytics
- ML predictions
- anomalies
- forecasts
- agent runs
- tool calls
- evaluations
- audit records

### Vector/RAG storage

Specify:
- what gets embedded
- chunking strategy
- metadata
- embedding model
- vector dimensions if applicable
- indexing strategy
- filtering
- hybrid search
- reranking
- citation/provenance mapping

---

# 3. PROJECT FOLDER STRUCTURE

Design the complete repository structure.

Use a tree such as:

```text
finsight/
├── apps/
├── services/
├── packages/
├── data/
├── ml/
├── migrations/
├── tests/
├── infrastructure/
├── docs/
└── ...
```

Then briefly explain only the **non-obvious directories**.

The structure must reflect the actual architecture and deployment model.

Do not create directories for hypothetical future functionality.

---

# 4. FINAL TECHNOLOGY STACK

First perform the required web research.

Then provide:

| Layer | Technology | Exact Version | Why | Alternatives Rejected |
|---|---|---:|---|---|
| Frontend | ... | ... | ... | ... |
| Backend | ... | ... | ... | ... |
| Database | ... | ... | ... | ... |
| ORM | ... | ... | ... | ... |
| Queue | ... | ... | ... | ... |
| OCR | ... | ... | ... | ... |
| Document parsing | ... | ... | ... | ... |
| ML | ... | ... | ... | ... |
| Embeddings | ... | ... | ... | ... |
| Vector search | ... | ... | ... | ... |
| LLM | ... | ... | ... | ... |
| Agent framework | ... | ... | ... | ... |
| Observability | ... | ... | ... | ... |
| Testing | ... | ... | ... | ... |
| Containers | ... | ... | ... | ... |
| Deployment | ... | ... | ... | ... |

Only include technologies actually required.

### Important

Distinguish:

- **mandatory**
- **recommended**
- **optional**

Do not over-engineer a student/portfolio project into an unnecessarily expensive distributed system.

---

# 5. END-TO-END DATA PIPELINE

Describe the complete pipeline from upload to final answer.

Use a numbered flow:

```text
1. Upload
2. Validate
3. Persist original
4. Detect document type
5. Parse/OCR
6. Layout/table extraction
7. Structured extraction
8. Validation
9. Normalization
10. Deduplication
11. Classification
12. Persistence
13. Analytics
14. Embedding/indexing
15. Retrieval
16. Agent/tool orchestration
17. Answer generation
18. Evidence attachment
19. Audit/evaluation
```

For each stage specify:

| Stage | Input | Processing | Output | Technology | Failure Handling |
|---|---|---|---|---|---|

Clearly distinguish:
- synchronous vs asynchronous processing
- deterministic vs probabilistic processing
- retryable vs terminal failures
- human-review requirements, if any

---

# 6. SYSTEM WORKFLOW / BEHAVIOR

Explain how the system actually behaves at runtime.

Cover at minimum:

### A. Document upload

```text
User → API → Object Storage → Job Queue → Worker → Processing Pipeline
```

### B. Financial question

Show the decision process:

```text
Question
 ↓
Intent / Query Analysis
 ↓
Can SQL/analytics answer it?
 ├─ Yes → deterministic tool
 └─ No
      ↓
Does it require document evidence?
 ├─ Yes → retrieval
 └─ No
      ↓
Does it require multiple operations?
 ├─ Yes → agent orchestration
 └─ No → direct service
 ↓
Evidence validation
 ↓
LLM response generation
 ↓
Citations / provenance
```

Adapt this logic to the actual design.

### C. Agent workflow

Define:
- agent state
- available tools
- tool schemas
- planning
- execution
- validation
- retry policy
- maximum steps
- failure handling
- permission boundaries
- final response generation

The agent must be an **orchestrator over reliable tools**, not a replacement for deterministic financial computation.

---

# 7. FEATURE-BY-FEATURE IMPLEMENTATION MAP

Create a compact matrix:

| Feature | Backend | DB | ML | LLM | RAG | Agent | Background Job |
|---|---|---|---|---|---|---|---|

Include every major feature in the specification:
- ingestion
- OCR/extraction
- normalization
- transaction classification
- duplicate detection
- recurring payments
- analytics
- anomaly detection
- forecasting
- budgets
- RAG
- financial QA
- agentic reasoning
- evidence
- reports
- evaluation
- security

This should make implementation dependencies obvious.

---

# 8. EVALUATION ARCHITECTURE

Design the evaluation system separately from the application.

Cover:

- datasets
- ground truth
- document extraction metrics
- classification metrics
- anomaly metrics
- forecasting metrics
- retrieval metrics
- groundedness
- citation correctness
- agent/tool-selection metrics
- latency
- cost
- reliability
- regression testing

Show:

```text
Dataset
 ↓
Evaluation Runner
 ↓
Component Metrics
 ↓
Experiment Tracking
 ↓
Regression Comparison
 ↓
Release Gate
```

Explain what must be evaluated before considering the system complete.

---

# 9. OBSERVABILITY

Define:

- logs
- metrics
- traces
- model/LLM telemetry
- agent traces
- tool-call traces
- pipeline failures
- latency
- token/cost tracking
- evaluation metrics

Show the observability flow.

---

# 10. SECURITY THREAT MODEL

Create a compact table:

| Threat | Attack Surface | Mitigation |
|---|---|---|
| Prompt injection | Documents/RAG | ... |
| SQL injection | Agent tools | ... |
| Malicious files | Upload | ... |
| Cross-user access | API/DB | ... |
| Secret leakage | Logs/prompts | ... |
| Data exfiltration | Agent/tools | ... |

Focus specifically on this application's financial-data and agentic risks.

---

# 11. IMPLEMENTATION CHECKLIST

Create a **strict dependency-ordered checklist** from zero to production.

Example:

```text
PHASE 0 — Architecture
[ ] Finalize architecture
[ ] Finalize stack
[ ] Define schemas

PHASE 1 — Foundation
[ ] Repository
[ ] Docker
[ ] CI/CD
[ ] Configuration
[ ] Database
...

PHASE 2 — Data ingestion
...

PHASE N — Production
...
```

Every item must be actionable.

Order tasks by dependency, not by feature popularity.

For each phase include:
- objective
- tasks
- exit criteria

Do not mark anything complete; this is a plan.

---

# 12. MVP vs FULL SYSTEM

Separate:

### MVP
Minimum system that proves the core architecture.

### V1
Complete portfolio-grade system.

### Advanced
Only genuinely worthwhile extensions.

For each, specify exactly what moves between phases.

Avoid scope creep.

---

# 13. ARCHITECTURAL DECISIONS

Create a concise ADR-style table:

| Decision | Choice | Reason | Trade-off |
|---|---|---|---|

Include the most consequential decisions only.

Examples:
- monolith vs microservices
- PostgreSQL vs separate databases
- vector DB strategy
- synchronous vs async processing
- agent framework
- OCR approach
- LLM strategy
- cloud architecture
- model serving strategy

---

# 14. RISKS / FAILURE MODES

List the highest-risk engineering problems:

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|

Prioritize:
- extraction errors
- incorrect normalization
- numerical hallucination
- retrieval failures
- agent tool misuse
- forecasting uncertainty
- data leakage
- prompt injection
- cost/latency
- evaluation gaps

---

# 15. FINAL BUILD ORDER

End with a **single condensed dependency graph** showing exactly what should be built first, second, third, etc.

Example:

```text
Architecture
 ↓
Repository + Infrastructure
 ↓
Database + Storage
 ↓
Ingestion
 ↓
Extraction
 ↓
Normalization
 ↓
Analytics
 ↓
ML
 ↓
RAG
 ↓
Tools
 ↓
Agent
 ↓
API
 ↓
Frontend
 ↓
Evaluation
 ↓
Observability
 ↓
Security hardening
 ↓
Deployment
```

Adapt it to the final architecture.

---

# RESPONSE RULES

1. **Be concise but deep.**
2. Prefer one precise table over several paragraphs.
3. Never explain basic concepts unless they affect an architectural decision.
4. Never repeat the same architecture in different words.
5. Use Mermaid wherever a diagram improves precision.
6. Explicitly distinguish **specification requirements vs your architectural decisions**.
7. Never invent requirements.
8. Never invent technology versions.
9. Web-research all important technology/version choices before finalizing them.
10. Cite important web research claims.
11. Prefer official sources.
12. If two technologies are genuinely close, show the trade-off and select one.
13. Avoid unnecessary technologies.
14. Avoid unnecessary agents.
15. Avoid unnecessary microservices.
16. Keep financial calculations deterministic.
17. Keep provenance/evidence attached to extracted and derived data.
18. Treat security, evaluation, and observability as first-class architecture.
19. Assume the goal is a **serious portfolio-grade, deployable engineering project**, not a toy demo.
20. Do not produce implementation code unless absolutely necessary to clarify architecture.
21. Do not ask me unnecessary clarification questions. Make reasonable architectural assumptions, state them, and proceed.
22. Before the final answer, internally verify that **every requirement in the attached specification has a corresponding architectural/component/workflow/checklist item**.

## FINAL QUALITY TEST

Before responding, verify:

- Does every major requirement in the specification map to a component?
- Does every component map to a technology?
- Does every technology have a justified version?
- Does every stored entity have a database location?
- Does every pipeline stage have an input/output?
- Does every AI component have an evaluation metric?
- Does every agent action use a controlled tool?
- Can every generated financial claim be traced to evidence?
- Can the entire system actually be implemented from the checklist?
- Have unnecessary technologies/services been removed?

If any answer is "no", fix the architecture before presenting it.