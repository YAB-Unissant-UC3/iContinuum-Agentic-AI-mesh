#Unissant Challenge X — iContinuum Agentic AI Mesh

##Project Overview
This project is a proof of concept for a reusable, secure, multi-agent AI workflow that analyzes documents and produces source-cited results.

##Goals
Extract information from synthetic documents.
Identify important facts and conflicting evidence.
Generate summaries with traceable citations.
Enforce role-based document access.
Record audit information and support human review.
Support two applications through one shared API: a brief generator and a requirements checker.


##Proposed Architecture
Document Agent: Extracts text and preserves document IDs and source passages.
Analysis Agent: Analyzes evidence, detects conflicts, and produces cited findings.
Audit Agent: Validates citations, flags unsupported claims, and records audit information.
The Python backend will coordinate these agents and enforce access controls.


##Planned Technologies
Python, FastAPI, GitHub, pytest, Unissant-hosted LLM (pending access) - GPT-OSS-20b, Streamlit or another lightweight frontend


##Current Status
Initial planning and repository setup. Architecture and interfaces are subject to refinement.
Data and Security
Use only synthetic or approved public documents. No real government data, PII, CUI, or production credentials.
Can test security later on with prompt injection and testing authentication based on user role.


##Next Steps
Create sample documents.
Build the document reader.
Define the shared evidence format.
Implement analysis and audit modules.
Connect the modules through one API.
Develop and test both client applications.
