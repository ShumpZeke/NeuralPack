"""Synthetic prompt fixtures retained for legacy profiler diagnostics only.

These are inspected data, not sealed tasks or answer-accuracy evidence.
"""
from dataclasses import dataclass
from typing import List

@dataclass
class EvalTask:
    id: str
    category: str  # coding, documentation, conversation, agent_trace, adversarial
    query: str
    context: str
    expected_fact: str
    forbidden_fact: str = ""


# --- 1. Coding Repository Context (Interconnected microservices) ---
CODING_CONTEXT = """
```File: config.py
DATABASE_PORT = 5432
CACHE_TTL_SECONDS = 3600
DEFAULT_PAGE_SIZE = 50
MAX_RETRIES = 5
```

```File: database.py
from config import DATABASE_PORT, MAX_RETRIES

class ConnectionPool:
    def __init__(self):
        self.port = DATABASE_PORT
        self.retries = MAX_RETRIES
    def get_connection(self):
        return {"port": self.port, "retries": self.retries, "status": "active"}
```

```File: user_model.py
class User:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
    def is_admin(self):
        return self.role == "superadmin"
```

```File: auth.py
from user_model import User

def authorize_request(user: User, resource: str) -> bool:
    # Only superadmins can delete tenant resources.
    if resource == "delete_tenant":
        return user.is_admin()
    return True
```

```File: payment_gateway.py
STRIPE_API_VERSION = "2024-06-20"
CURRENCY = "USD"

def charge_card(amount: int, token: str) -> str:
    return f"ch_success_{amount}_{token}"
```

```File: unused_graphics.py
def render_sphere():
    return 'sphere'
```

```File: unused_telemetry.py
def send_telemetry():
    return 'telemetry_sent'
```

```File: test_mock_fixture.py
def test_dummy():
    assert 1 == 1
```

```File: unused_graphics.py
def render_sphere():
    return 'sphere'
```

```File: unused_telemetry.py
def send_telemetry():
    return 'telemetry_sent'
```

```File: test_mock_fixture.py
def test_dummy():
    assert 1 == 1
```

```File: unused_graphics.py
def render_sphere():
    return 'sphere'
```

```File: unused_telemetry.py
def send_telemetry():
    return 'telemetry_sent'
```

```File: test_mock_fixture.py
def test_dummy():
    assert 1 == 1
```

```File: unused_graphics.py
def render_sphere():
    return 'sphere'
```

```File: unused_telemetry.py
def send_telemetry():
    return 'telemetry_sent'
```

```File: test_mock_fixture.py
def test_dummy():
    assert 1 == 1
```

```File: unused_graphics.py
def render_sphere():
    return 'sphere'
```

```File: unused_telemetry.py
def send_telemetry():
    return 'telemetry_sent'
```

```File: test_mock_fixture.py
def test_dummy():
    assert 1 == 1
```

```File: unused_graphics.py
def render_sphere():
    return 'sphere'
```

```File: unused_telemetry.py
def send_telemetry():
    return 'telemetry_sent'
```

```File: test_mock_fixture.py
def test_dummy():
    assert 1 == 1
```


```File: logging_utils.py
import json
def log_audit_event(event_type: str, actor: str):
    print(json.dumps({"event": event_type, "actor": actor}))
```
"""

# --- 2. Documentation Context (Versioned API Specification) ---
DOCS_CONTEXT = """
# Enterprise API Documentation v2.4

## Section 1: Authentication
All requests require an `X-API-Key` header. Requests without this header return HTTP 401.

## Section 2: Rate Limiting & Tiers
- Free Tier: 60 requests per minute.
- Pro Tier: 600 requests per minute.
- Enterprise Tier: 6,000 requests per minute.
Exceeding limits triggers HTTP 429 Too Many Requests with a `Retry-After` header in seconds.

## Section 3: Deprecated v1 Endpoints
WARNING: The legacy `/v1/users/batch_export` endpoint was deprecated on 2025-12-01.
All batch operations must now use `/v2/jobs/export` with an asynchronous webhook callback.
Do not use `/v1/users/batch_export` as it will be sunset completely.

## Section 1.1: SDK Setup
Install via pip install enterprise-api-client or npm install @enterprise/api.
Ensure Python 3.10+ or Node 18+ is available.

## Section 1.2: Environment Variables
Set ENTERPRISE_API_KEY and ENTERPRISE_ENVIRONMENT in your local .env.

## Section 1.3: Retries and Circuit Breaker
Client implements exponential backoff on HTTP 429 and 503 responses.

## Section 1.1: SDK Setup
Install via pip install enterprise-api-client or npm install @enterprise/api.
Ensure Python 3.10+ or Node 18+ is available.

## Section 1.2: Environment Variables
Set ENTERPRISE_API_KEY and ENTERPRISE_ENVIRONMENT in your local .env.

## Section 1.3: Retries and Circuit Breaker
Client implements exponential backoff on HTTP 429 and 503 responses.

## Section 1.1: SDK Setup
Install via pip install enterprise-api-client or npm install @enterprise/api.
Ensure Python 3.10+ or Node 18+ is available.

## Section 1.2: Environment Variables
Set ENTERPRISE_API_KEY and ENTERPRISE_ENVIRONMENT in your local .env.

## Section 1.3: Retries and Circuit Breaker
Client implements exponential backoff on HTTP 429 and 503 responses.

## Section 1.1: SDK Setup
Install via pip install enterprise-api-client or npm install @enterprise/api.
Ensure Python 3.10+ or Node 18+ is available.

## Section 1.2: Environment Variables
Set ENTERPRISE_API_KEY and ENTERPRISE_ENVIRONMENT in your local .env.

## Section 1.3: Retries and Circuit Breaker
Client implements exponential backoff on HTTP 429 and 503 responses.

## Section 4: Webhook Signature Verification
Webhooks include `X-Hub-Signature-256`. The signature is computed using HMAC-SHA256 with the shared webhook secret.
"""

# --- 3. Long Conversation Context (Multi-Turn Chat with State Shifts) ---
CONVERSATION_CONTEXT = """
User: Hi, I want to configure the deploy script for our backend service.
Assistant: Great, I can help. What deployment target and port are you using?
User: Target is Kubernetes on AWS EKS. Use port 3000.
Assistant: Got it. I will write a Kubernetes deployment manifest targeting port 3000 on EKS.
User: Important constraint: Never output YAML. Our pipeline only accepts JSON Kubernetes manifests.
Assistant: Understood. I will strictly output JSON formatted Kubernetes manifests.
User: Also, our team prefers us-west-2 for the cluster region.
Assistant: Noted, cluster region set to us-west-2.
User: Wait, update on the port: Our ingress changed. Disregard port 3000, we MUST use port 8080 now.
Assistant: Understood. Port is updated to 8080.
User: Can you summarize the final configuration constraints before generating?
"""

# --- 4. Agent Trace Context (Massive tool trace with needle in haystack) ---
AGENT_TRACE_CONTEXT = """
[Step 1] Tool Call: file_search("database_error") -> Result: 0 matches found.
[Step 2] Tool Call: list_dir("src/") -> Result: ['app.py', 'routes.py', 'db/', 'utils.py']
[Step 3] Tool Call: read_file("src/app.py") -> Result: 250 lines of boilerplate web framework setup.
[Step 4] Tool Call: grep("timeout", "src/") -> Result: src/utils.py: TIMEOUT = 10
[Step 5] Tool Call: run_tests("unit") -> Result: 45 passed, 1 failed in test_sync.py
[Step 6] Tool Call: read_file("tests/test_sync.py") -> Result: test asserting sync queue status.
[Step 7] Tool Call: inspect_logs("/var/log/app.log") -> Result: 500 lines of standard startup logs.
[Step 8] Tool Call: grep("CRITICAL", "/var/log/app.log") -> Result: No critical entries.
[Step 9] Tool Call: read_file("src/db/connection.py") -> Result: class DBManager...
[Step 10] Tool Call: read_file("config/secrets.json.example") -> Result: dummy keys.
[Step 11] Tool Call: run_command("env | grep REDIS") -> Result: REDIS_PORT=6379
[Step 12] Tool Call: ping("redis-master.internal") -> Result: 0% packet loss.
[Step 13] Tool Call: inspect_database_schema() -> Result: tables: users, accounts, orders.
[Step 14] Tool Call: read_file("deploy/helm/values.yaml") -> Result: replicaCount: 3
[Step 15] Tool Call: run_linter("src/") -> Result: Clean, 0 errors.
[Step 16] Tool Call: inspect_worker_queue() -> Result: Queue depth: 0 items.
[Step 17] Tool Call: check_network_firewall_rule("10.0.1.45") -> CRITICAL FINDING: Ingress port 5432 is blocked by AWS Security Group sg-0a8b1c2d3e on subnet-east.
[Step 18] Tool Call: run_command("hostname") -> Result: worker-node-04
[Step 19] Tool Call: read_file("docs/troubleshooting.md") -> Result: General tips.
[Step 20] Tool Call: get_memory_info() -> Result: 8.2 GB free out of 16 GB.
"""

# --- 5. Adversarial Context (Subtle distinctions & name collisions) ---
ADVERSARIAL_CONTEXT = """
```File: tax_us.py
TAX_RATE = 0.07

def calculate_tax(subtotal: float) -> float:
    # Calculates US State sales tax.
    return subtotal * TAX_RATE
```

```File: tax_eu.py
TAX_RATE = 0.20
VAT_IDENTIFIER = "EU-VAT-2026"

def calculate_tax(subtotal: float) -> float:
    # Calculates EU standard Value Added Tax (VAT).
    return subtotal * TAX_RATE
```

```File: billing_service.py
# CRITICAL SECURITY NOTE: Never enable DEBUG_BYPASS_PAYMENT in production under any circumstance.
DEBUG_BYPASS_PAYMENT = False

class Billing:
    def __init__(self, region="EU"):
        self.region = region
    def get_vat_id(self):
        return "EU-VAT-2026"
```
"""


TASKS: List[EvalTask] = [
    # Coding
    EvalTask(
        id="code_auth_superadmin",
        category="coding",
        query="Which role is strictly required to authorize the 'delete_tenant' resource in auth.py?",
        context=CODING_CONTEXT,
        expected_fact="superadmin",
    ),
    EvalTask(
        id="code_db_max_retries",
        category="coding",
        query="What is the maximum retry count configured for the database connection pool?",
        context=CODING_CONTEXT,
        expected_fact="5",
    ),
    # Documentation
    EvalTask(
        id="doc_rate_limit_pro",
        category="documentation",
        query="What is the exact rate limit for the Pro Tier in Section 2?",
        context=DOCS_CONTEXT,
        expected_fact="600",
    ),
    EvalTask(
        id="doc_deprecated_endpoint",
        category="documentation",
        query="Which endpoint replaces the deprecated /v1/users/batch_export endpoint according to Section 3?",
        context=DOCS_CONTEXT,
        expected_fact="/v2/jobs/export",
        forbidden_fact="/v1/users/batch_export is recommended",
    ),
    # Long Conversation
    EvalTask(
        id="convo_final_port",
        category="conversation",
        query="What is the final updated target port specified by the user? (Note: check if any earlier port was superseded)",
        context=CONVERSATION_CONTEXT,
        expected_fact="8080",
        forbidden_fact="3000 is the final port",
    ),
    EvalTask(
        id="convo_format_constraint",
        category="conversation",
        query="What strict format constraint did the user establish for outputting manifests?",
        context=CONVERSATION_CONTEXT,
        expected_fact="JSON",
        forbidden_fact="YAML is allowed",
    ),
    # Agent Trace
    EvalTask(
        id="trace_firewall_finding",
        category="agent_trace",
        query="What was the critical firewall discovery identified in the tool execution trace? State the blocked port and Security Group ID.",
        context=AGENT_TRACE_CONTEXT,
        expected_fact="sg-0a8b1c2d3e",
    ),
    # Adversarial
    EvalTask(
        id="adversarial_eu_tax",
        category="adversarial",
        query="What is the TAX_RATE and VAT_IDENTIFIER specifically defined for the EU in tax_eu.py?",
        context=ADVERSARIAL_CONTEXT,
        expected_fact="0.2",
        forbidden_fact="0.07 is the EU tax rate",
    ),
    EvalTask(
        id="adversarial_security_bypass",
        category="adversarial",
        query="What is the value of DEBUG_BYPASS_PAYMENT in billing_service.py, and what is the rule about enabling it?",
        context=ADVERSARIAL_CONTEXT,
        expected_fact="False",
        forbidden_fact="enable in production",
    ),
]
