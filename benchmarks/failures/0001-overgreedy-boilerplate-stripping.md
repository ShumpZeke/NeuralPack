# 0001: Over-Greedy Boilerplate Regex Stripped Configuration Code

Date: 2026-09-06.
Workload: Context Optimization Live Benchmark on NVIDIA NIM (`meta/llama-3.2-11b-vision-instruct`).
Task: `q4_cors_origins` ("What are the allowed origins listed in CORS_ALLOWED_ORIGINS?").

**Symptom:**
- Baseline answer: correct (`https://app.example.com`, `https://admin.example.com`).
- Optimized answer: failed ("There is no information provided about CORS_ALLOWED_ORIGINS in the given code snippet").

**Root Cause Analysis:**
- What context was removed: `config.py` containing `CORS_ALLOWED_ORIGINS`, `DB_TIMEOUT_SECONDS`, and `JWT_EXPIRATION_MINUTES`.
- Why planner removed it: `BOILERPLATE_PATTERNS` in `npk/context/dedup.py` used `(?:#?.*?
){2,10}` where the `#?` comment delimiter was optional. As a result, 10 lines of actual code following a copyright comment were consumed and deleted as "boilerplate". Subsequently, block deduplication replaced remaining duplicate occurrences with reference placeholders, removing `config.py` from the final prompt.
- What signal/fix saves it: 
  1. Restricting boilerplate regex strictly to contiguous lines that begin with comment syntax (`#`, `//`, `/*`, `*`).
  2. Protecting code fence blocks (````File: ...````) so boilerplate stripping never applies inside code definitions.

**Fix & Verification:**
- Fixed regex in `npk/context/dedup.py`.
- Re-verified prompt preservation: `config.py` is fully retained and `CORS_ALLOWED_ORIGINS` is present.
