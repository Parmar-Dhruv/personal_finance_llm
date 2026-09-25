# FinSight: An Agentic Financial Intelligence Platform

## 1. Problem Statement

Individuals and small businesses generate and receive large amounts of financial information through multiple sources, including bank statements, credit-card statements, invoices, bills, receipts, spreadsheets, and other financial documents. These sources are typically heterogeneous, semi-structured, and distributed across different files and systems.

Although the underlying information contains valuable insights about income, expenditure, cash flow, recurring payments, financial anomalies, and future financial requirements, extracting and interpreting these insights manually is time-consuming, error-prone, and difficult to scale.

Traditional personal-finance and accounting applications generally depend on structured transaction data entered through predefined interfaces. They often provide dashboards and basic categorization, but they do not adequately address the problem of converting unstructured financial documents into structured information and subsequently reasoning across both structured and unstructured financial data.

At the same time, simply applying a Large Language Model (LLM) to uploaded financial documents is not sufficient for a reliable financial intelligence system. LLMs can generate fluent responses but may hallucinate information, perform numerical reasoning unreliably, or fail to provide verifiable evidence for their conclusions. Financial applications therefore require a combination of deterministic data processing, machine learning, document intelligence, information retrieval, LLM-based reasoning, and controlled agentic workflows.

The proposed system, **FinSight**, aims to address this problem by developing an AI-powered financial intelligence platform capable of ingesting heterogeneous financial documents, extracting and normalizing financial information, performing analytical and machine-learning-based processing, retrieving relevant evidence, and using controlled agentic workflows to answer complex financial questions.

The system will transform raw financial documents into a structured and queryable financial knowledge base and provide users with evidence-backed financial insights through natural-language interaction.

The project is specifically designed to go beyond a simple LLM wrapper. It will incorporate document intelligence, OCR, structured information extraction, data engineering, machine learning, deep learning/NLP concepts, embeddings, retrieval-augmented generation (RAG), tool calling, agentic orchestration, financial analytics, forecasting, anomaly detection, evaluation, observability, backend engineering, database systems, security, and production deployment.

---

# 2. Detailed Description

## 2.1 Overview

**FinSight** is an AI-powered financial intelligence platform designed for individuals and small businesses that need to understand financial information distributed across multiple documents and data sources.

The system will allow users to upload financial documents such as:

- Bank statements
- Credit-card statements
- Invoices
- Bills
- Receipts
- Spreadsheets
- Other financial records

The platform will process these documents through a multi-stage data and AI pipeline.

Instead of directly passing an uploaded document to an LLM, FinSight will first convert the document into reliable structured and searchable representations.

The high-level workflow will be:

**Document Upload → Document Processing → OCR/Extraction → Validation → Financial Data Normalization → Database Storage → ML/Financial Analytics → Retrieval → Agentic Reasoning → Evidence-backed Response**

This architecture allows different technologies to be used for different tasks according to their strengths.

For example, transaction aggregation and financial calculations will primarily be handled through deterministic software and SQL, while transaction categorization may use machine-learning models, and natural-language financial questions requiring multiple analytical operations may be handled by an LLM-powered agent.

---

# 3. Core Objective

The primary objective of FinSight is to develop a reliable AI-based financial intelligence system that can transform heterogeneous financial data into actionable and explainable insights.

The system will aim to answer questions such as:

- "How much did I spend on travel during the last six months?"
- "Which expenses increased significantly?"
- "Find all payments made to a particular vendor."
- "Which recurring payments do I have?"
- "Which expenses appear unusual?"
- "What are my largest spending categories?"
- "How much money do I typically spend each month?"
- "Can I meet next month's expected expenses?"
- "Why did my expenses increase this month?"
- "Show the documents supporting this conclusion."

The original project specification identifies natural-language financial queries, expense categorization, recurring-payment detection, duplicate detection, cash-flow forecasting, budget alerts, document search, and monthly financial reporting as core functionality.

---

# 4. Proposed System Architecture

FinSight will consist of several interconnected layers.

## 4.1 Document Ingestion Layer

The system will accept multiple financial document formats.

Examples include:

- PDF
- Scanned PDF
- Images
- CSV
- Excel spreadsheets
- Other supported business documents

When a document is uploaded, the system will first validate the file and create a persistent document record.

The original document will be retained as the source of truth, while all subsequent processing stages will generate derived representations.

---

## 4.2 Document Intelligence Layer

Financial documents frequently contain tables, inconsistent layouts, scanned text, headers, footers, account information, transaction descriptions, and other semi-structured information.

The document intelligence layer will therefore perform:

1. Document parsing
2. OCR when required
3. Layout analysis
4. Table extraction
5. Text extraction
6. Field identification
7. Structured information extraction
8. Confidence estimation
9. Validation

The system will maintain provenance information linking extracted information back to its source document and, where possible, its page or document region.

This is important because financial answers should be traceable to the underlying evidence rather than being generated solely from an LLM's internal knowledge.

---

# 5. Financial Data Normalization

Different financial institutions and documents represent similar information in different ways.

For example:

```text
01/08/26
08-01-2026
Aug 1, 2026
2026/08/01
```

may all represent the same date.

Similarly:

```text
AMZN
AMAZON
AMAZON INDIA
AMZN MKTPLACE
```

may refer to the same merchant.

FinSight will therefore contain a normalization layer that converts extracted information into a canonical financial representation.

A normalized transaction may contain:

- Transaction ID
- Account ID
- Transaction date
- Amount
- Currency
- Merchant
- Description
- Transaction type
- Category
- Subcategory
- Source document
- Source page
- Extraction confidence
- Classification confidence

This normalized representation will form the foundation for downstream analytics and machine-learning systems.

---

# 6. Financial Database and Knowledge Layer

The normalized financial information will be stored in a structured database.

The database may contain entities such as:

- Users
- Accounts
- Transactions
- Categories
- Documents
- Document pages
- Document chunks
- Invoices
- Invoice items
- Recurring payments
- Budgets
- Anomalies
- Forecasts
- Agent executions
- Tool calls
- Evaluation results
- Audit records

The system will maintain a separation between:

**Raw Data → Extracted Data → Normalized Data → Derived Intelligence**

This prevents analytical processing from destroying the original source information and makes debugging and auditing possible.

---

# 7. Machine Learning Layer

Machine learning will be used where learning from financial data provides a measurable advantage over deterministic rules.

## 7.1 Transaction Classification

The system will automatically categorize transactions into categories such as:

- Food
- Transportation
- Shopping
- Utilities
- Entertainment
- Healthcare
- Travel
- Rent
- Salary
- Business expenses

The project can compare multiple approaches, including:

- Rule-based classification
- Classical machine learning
- LLM-based classification
- Hybrid ML + LLM classification

This comparison will provide an opportunity to evaluate the trade-offs between accuracy, cost, latency, and explainability.

---

## 7.2 Duplicate Transaction Detection

The system will identify potentially duplicated transactions using a combination of structured and similarity-based analysis.

Relevant features may include:

- Merchant
- Amount
- Date/time
- Account
- Transaction description
- Transaction similarity

The system will assign a probability or confidence score to potential duplicate transactions rather than automatically deleting or modifying financial records.

---

## 7.3 Recurring Payment Detection

FinSight will identify recurring payments such as:

- Subscriptions
- Rent
- Utility payments
- Insurance
- Software services
- Memberships

The system can analyze:

- Merchant consistency
- Amount consistency
- Time intervals
- Periodicity
- Historical transaction frequency

Recurring-payment detection will primarily be implemented as a data-analysis/algorithmic component rather than an independent AI agent.

---

# 8. Financial Analytics Engine

The financial analytics engine will perform deterministic calculations over structured financial data.

It will provide functionality such as:

- Income calculation
- Expense calculation
- Net cash flow
- Spending by category
- Monthly comparisons
- Vendor spending
- Account-level summaries
- Budget utilization
- Recurring expense totals
- Historical financial trends

For example:

```text
Monthly Income
      -
Monthly Expenses
      =
Net Cash Flow
```

These calculations should be performed by deterministic software rather than delegated to an LLM.

This improves numerical reliability and makes the results reproducible.

---

# 9. Anomaly Detection

The system will identify unusual financial transactions or patterns.

Potential approaches include:

- Statistical thresholds
- Z-score based detection
- Interquartile-range methods
- Isolation Forest
- Other machine-learning approaches

The system may consider:

- Transaction amount
- Merchant
- Frequency
- Category
- Historical behavior
- Temporal patterns

An anomaly detector will not automatically classify an unusual transaction as fraud. Instead, it will identify transactions that deviate significantly from learned or predefined patterns and present them for investigation.

---

# 10. Cash-Flow Forecasting

FinSight will provide financial forecasting using historical transaction data.

The forecasting system will estimate future:

- Income
- Expenses
- Cash balance
- Recurring obligations
- Expected financial requirements

The implementation will begin with simple statistical baselines and progress toward machine-learning approaches where appropriate.

The project will compare models using appropriate forecasting metrics rather than assuming that a more complex model is automatically better.

The forecasting component will allow questions such as:

> "Can the business meet next month's expected expenses?"

to be answered using actual financial calculations and forecasts rather than purely linguistic reasoning.

---

# 11. Retrieval-Augmented Generation

FinSight will incorporate Retrieval-Augmented Generation (RAG) for questions requiring information contained in uploaded financial documents.

The RAG pipeline will approximately follow:

```text
User Question
      ↓
Query Analysis
      ↓
Metadata / SQL Retrieval
      +
Semantic Retrieval
      ↓
Candidate Evidence
      ↓
Reranking
      ↓
Relevant Context
      ↓
LLM
      ↓
Answer + Evidence
```

The system will store embeddings of appropriate document content and use vector similarity together with structured metadata.

Where appropriate, hybrid retrieval can combine:

- Keyword search
- Semantic search
- Metadata filtering
- Structured SQL queries
- Reranking

The goal is not simply to retrieve semantically similar text but to retrieve the **correct financial evidence** required to answer the user's question.

---

# 12. Financial Question Answering

The platform will provide a natural-language interface through which users can ask questions about their financial information.

For example:

> "How much did I spend on travel during the last six months?"

The system may perform a structured database query rather than RAG because the answer is fundamentally numerical.

For another question:

> "What was the reason for the unusually high expense in March?"

the system may need to combine:

- Transaction analytics
- Anomaly detection
- Document retrieval
- Invoice retrieval
- LLM-based reasoning

This distinction is important.

FinSight will not force every question through the same LLM/RAG pipeline.

---

# 13. Agentic Reasoning Layer

The agentic component will be responsible for **multi-step financial reasoning and tool selection**.

Instead of creating numerous artificial agents, FinSight will use a controlled financial reasoning agent capable of selecting appropriate tools.

Potential tools include:

- Transaction search
- SQL analytics
- Category analysis
- Recurring-payment detection
- Duplicate detection
- Anomaly detection
- Forecasting
- Document retrieval
- Invoice search
- Financial simulation
- Report generation

For example, for:

> "Can I afford next month's expected expenses?"

the agent may determine that it needs to:

```text
1. Retrieve current balance
2. Calculate expected recurring expenses
3. Estimate variable expenses
4. Run cash-flow forecast
5. Compare projected cash flow against obligations
6. Generate an evidence-backed explanation
```

The agent will therefore function as an **orchestrator over reliable financial tools**, rather than independently performing financial calculations through natural-language generation.

---

# 14. Evidence and Explainability

Because financial information is sensitive and consequential, FinSight will emphasize explainability and provenance.

Responses should ideally contain:

- Relevant transactions
- Source documents
- Source pages
- Calculation results
- Model confidence where applicable
- Retrieval evidence
- Assumptions used by forecasts
- Explanation of how the conclusion was obtained

For example:

> **Travel expenses increased by ₹8,420 in March.**

The system should be able to provide:

```text
Source:
Bank Statement — Page 3
Bank Statement — Page 5

Supporting transactions:
₹4,200 — Airline
₹2,850 — Hotel
₹1,370 — Transportation
```

This provides a verifiable connection between the generated explanation and the underlying financial records.

---

# 15. Monthly Financial Report Generation

FinSight will generate periodic financial reports summarizing a user's financial activity.

A monthly report may include:

### Income

- Total income
- Income sources
- Month-over-month change

### Expenses

- Total expenditure
- Largest categories
- Largest merchants
- Significant changes

### Cash Flow

- Net cash flow
- Cash-flow trends
- Expected upcoming obligations

### Recurring Payments

- Detected subscriptions
- Recurring bills
- Changes in recurring costs

### Anomalies

- Unusual transactions
- Significant deviations

### Forecast

- Expected upcoming expenses
- Projected cash flow

The LLM can be used to convert structured analytical results into a readable report, but the underlying numerical values should originate from deterministic analytics.

---

# 16. Budget Planning and Alerts

The system will allow users to define budgets for categories or overall spending.

Example:

```text
Food       ₹10,000/month
Travel     ₹15,000/month
Shopping   ₹8,000/month
```

FinSight can compare actual expenditure against budgets and generate alerts when spending approaches or exceeds predefined limits.

The calculation itself will be deterministic.

The LLM can optionally explain the situation in natural language.

---

# 17. Technology and AI Separation

A fundamental design principle of FinSight is that each task should be assigned to the technology most appropriate for it.

### Deterministic software

Used for:

- Financial calculations
- SQL queries
- Aggregation
- Budget calculations
- Data validation
- Authentication
- Authorization
- Audit logging
- Business rules

### Machine learning

Used for:

- Transaction classification
- Anomaly detection
- Forecasting
- Similarity detection
- Other predictive tasks

### LLMs

Used for:

- Natural-language understanding
- Structured information extraction where appropriate
- Query interpretation
- Report generation
- Explanation
- Financial reasoning over retrieved evidence

### RAG

Used for:

- Document-grounded questions
- Evidence retrieval
- Cross-document information retrieval

### Agents

Used for:

- Multi-step task planning
- Tool selection
- Workflow orchestration
- Combining multiple analytical capabilities

This separation is a central architectural principle of the project.

---

# 18. Evaluation Framework

A major component of FinSight will be the evaluation system.

The project will not evaluate success merely by asking whether the chatbot produces convincing answers.

Separate evaluation datasets and metrics will be developed for:

### Document Processing

- OCR accuracy
- Text extraction accuracy
- Table extraction accuracy

### Information Extraction

- Precision
- Recall
- F1 score
- Field-level accuracy

### Classification

- Accuracy
- Precision
- Recall
- Macro-F1
- Confusion matrix

### Duplicate Detection

- Precision
- Recall
- F1

### Recurring Payment Detection

- Precision
- Recall
- F1

### Anomaly Detection

- Precision
- Recall
- F1
- PR-AUC

### Forecasting

- MAE
- RMSE
- Other appropriate forecasting metrics

### RAG

- Retrieval Recall@K
- MRR
- NDCG
- Context relevance
- Answer relevance
- Groundedness
- Citation correctness

### Agentic System

- Tool-selection accuracy
- Tool-argument accuracy
- Successful workflow completion
- Unnecessary tool calls
- Number of execution steps
- Latency
- Cost

### System-Level Metrics

- End-to-end latency
- Reliability
- Failure rate
- API performance
- LLM cost
- Recovery from failures

The evaluation framework will allow different approaches to be benchmarked objectively.

---

# 19. Security and Privacy

Financial information is highly sensitive. Therefore, security and privacy will be treated as core system requirements rather than optional enhancements.

The system will consider:

- Authentication
- Authorization
- User-level data isolation
- Secure file handling
- Input validation
- Secret management
- Encryption in transit
- Secure storage
- Audit logging
- Data deletion
- Data retention
- Prompt-injection protection
- SQL-injection protection
- Restricted tool access
- Controlled database queries

The project will primarily use synthetic and anonymized data for development, testing, and demonstrations in order to avoid unnecessary exposure of real financial information. The original specification explicitly identifies anonymization and avoiding real people's sensitive financial information as project requirements.

---

# 20. Deployment

The completed system will be designed as a deployable web application rather than only a local notebook or prototype.

The deployment architecture will include:

```text
Frontend
   ↓
Backend API
   ↓
Application Services
   ↓
Database
   ↓
Object Storage

Background Processing
   ↓
Document Processing
   ↓
ML/AI Services

Monitoring
   ↓
Logs
Metrics
Traces
AI Evaluation
```

Containerization will be implemented using Docker, with a cloud deployment target selected after the local system is stable.

---

# 21. Expected Outcome

The expected outcome is a complete AI-powered financial intelligence platform capable of converting heterogeneous financial documents into structured, searchable, analyzable financial information.

The final system should allow a user to:

1. Upload financial documents.
2. Automatically extract relevant information.
3. Normalize financial transactions.
4. Store financial information in a structured database.
5. Search and retrieve financial documents.
6. Automatically classify transactions.
7. Detect recurring payments.
8. Detect potential duplicate transactions.
9. Identify anomalous financial activity.
10. Analyze historical income and expenses.
11. Forecast future cash flow.
12. Define and monitor budgets.
13. Ask natural-language questions about financial information.
14. Receive answers grounded in actual financial evidence.
15. Execute multi-step financial analyses through an agentic workflow.
16. Generate periodic financial reports.
17. Inspect supporting evidence for generated insights.

---

# 22. Significance of the Project

FinSight is intended to demonstrate the integration of several important areas of modern AI engineering into a single real-world system.

Rather than treating LLMs as the entire solution, the project combines:

**Data Engineering + Document AI + Machine Learning + NLP + LLMs + Embeddings + RAG + Agentic AI + Financial Analytics + Forecasting + Software Engineering + Evaluation + Production Deployment**

This makes the project suitable as a portfolio-level demonstration of practical AI/ML engineering skills.

The project's primary value is not the number of AI technologies used. Its value lies in demonstrating that each technology is applied for an appropriate problem and that the resulting system is measurable, explainable, testable, and deployable.

---

# 23. Scope Boundary

The system is intended to provide **financial intelligence and decision-support capabilities**, not regulated financial advisory services.

It should therefore avoid claiming to:

- Provide legally binding financial advice
- Guarantee investment returns
- Automatically make investment decisions
- Guarantee fraud detection
- Replace accountants, auditors, or financial professionals
- Guarantee future financial outcomes

Forecasts and recommendations should clearly communicate uncertainty and assumptions.

---

# 24. Final Project Definition

**FinSight** is an agentic financial intelligence platform that transforms heterogeneous personal and small-business financial documents into structured, searchable, and analyzable financial data. It combines document intelligence, machine learning, financial analytics, forecasting, retrieval-augmented generation, and controlled agentic workflows to provide evidence-backed answers and financial insights through natural-language interaction.

The central engineering principle is:

> **Use deterministic computation for what must be correct, machine learning for what must be predicted, retrieval for what must be grounded in documents, and LLM-powered agents for what requires flexible language understanding and multi-step orchestration.**

This approach prevents FinSight from becoming a superficial "LLM wrapper" and instead positions it as a complete AI engineering system spanning the data, ML, LLM, RAG, agentic, software-engineering, and production layers.