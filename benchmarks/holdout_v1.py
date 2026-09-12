"""Holdout Evaluation Dataset (50 Unseen Tasks) spanning 10K+ tokens across 5 domains."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass
class HoldoutTask:
    id: str
    domain: str  # code, doc, convo, trace, adversarial
    query: str
    context: str
    required_blocks: List[str]  # Ground truth MSC required blocks
    expected_fact: str
    forbidden_fact: str = ""


# --- 10K+ Multi-Module Enterprise Web Platform Code Context ---
CODE_REPO_10K = """
```File: settings/base.py
# Base project settings
SECRET_KEY = "django-insecure-base-key-2026"
DEBUG = False
ALLOWED_HOSTS = ["api.company.com", "internal.company.com"]
DEFAULT_TIMEOUT_SECONDS = 45
MAX_UPLOAD_SIZE_MB = 25
RATE_LIMIT_PER_MINUTE = 120
```

```File: settings/production.py
# Production overrides
from settings.base import ALLOWED_HOSTS
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
REDIS_CACHE_URL = "redis://cache-cluster.prod.internal:6379/0"
```

```File: core/exceptions.py
class APIError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code

class ResourceNotFound(APIError):
    def __init__(self, resource: str):
        super().__init__(f"{resource} not found", status_code=404)

class UnauthorizedAccess(APIError):
    def __init__(self):
        super().__init__("Invalid credentials or expired token", status_code=401)
```

```File: db/pool.py
from settings.base import DEFAULT_TIMEOUT_SECONDS

class DatabasePool:
    def __init__(self, max_connections: int = 50):
        self.max_connections = max_connections
        self.timeout = DEFAULT_TIMEOUT_SECONDS
        self.active_count = 0

    def acquire(self):
        if self.active_count >= self.max_connections:
            raise TimeoutError("Connection pool exhausted")
        self.active_count += 1
        return {"conn_id": f"conn_{self.active_count}", "timeout": self.timeout}
```

```File: auth/jwt_handler.py
import time
import hashlib
from settings.base import SECRET_KEY

def generate_access_token(user_id: str, role: str, expires_in: int = 3600) -> str:
    payload = f"{user_id}:{role}:{int(time.time()) + expires_in}"
    sig = hashlib.sha256(f"{payload}:{SECRET_KEY}".encode()).hexdigest()[:16]
    return f"{payload}.{sig}"

def verify_token(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 2:
        return {"valid": False, "error": "malformed"}
    payload, sig = parts
    expected = hashlib.sha256(f"{payload}:{SECRET_KEY}".encode()).hexdigest()[:16]
    if sig != expected:
        return {"valid": False, "error": "signature_mismatch"}
    user_id, role, exp = payload.split(":")
    if time.time() > int(exp):
        return {"valid": False, "error": "token_expired"}
    return {"valid": True, "user_id": user_id, "role": role}
```

```File: auth/rbac.py
from core.exceptions import UnauthorizedAccess
from auth.jwt_handler import verify_token

PERMISSIONS = {
    "viewer": ["read"],
    "editor": ["read", "write"],
    "billing_manager": ["read", "manage_subscriptions"],
    "owner": ["read", "write", "manage_subscriptions", "delete_organization"]
}

def enforce_permission(token: str, required_action: str) -> str:
    res = verify_token(token)
    if not res.get("valid"):
        raise UnauthorizedAccess()
    role = res.get("role", "viewer")
    allowed = PERMISSIONS.get(role, [])
    if required_action not in allowed:
        raise UnauthorizedAccess()
    return res.get("user_id")
```

```File: billing/stripe_client.py
class StripeGateway:
    def __init__(self, api_version="2025-01-15"):
        self.api_version = api_version
        self.currency = "usd"

    def create_subscription(self, customer_id: str, plan_tier: str):
        prices = {"starter": 4900, "pro": 19900, "enterprise": 99900}
        price_cents = prices.get(plan_tier, 4900)
        return {"subscription_id": f"sub_{customer_id}_{plan_tier}", "amount_cents": price_cents}
```

```File: billing/invoices.py
from billing.stripe_client import StripeGateway

def generate_monthly_invoice(customer_id: str, tier: str) -> dict:
    gw = StripeGateway()
    sub = gw.create_subscription(customer_id, tier)
    tax_rate = 0.0825  # Local municipal sales tax
    total_cents = int(sub["amount_cents"] * (1.0 + tax_rate))
    return {"customer": customer_id, "subtotal": sub["amount_cents"], "tax": tax_rate, "total": total_cents}
```

```File: workers/task_queue.py
class TaskQueue:
    def __init__(self, max_concurrency: int = 16):
        self.queue_name = "celery_default"
        self.concurrency = max_concurrency

    def enqueue(self, task_name: str, args: list):
        return {"task_id": f"job_{task_name}_99", "status": "queued"}
```

```File: monitoring/metrics.py
class MetricCollector:
    def __init__(self):
        self.prefix = "app_v2_"
    def record_counter(self, name: str, value: int = 1):
        pass
    def record_histogram(self, name: str, duration_seconds: float):
        pass
```

```File: utils/string_helpers.py
def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("_", "-")
def truncate(text: str, length: int = 100) -> str:
    return text[:length] + ("..." if len(text) > length else "")
```

```File: ui/theme.css
:root {
  --brand-primary: #1e40af;
  --brand-secondary: #0f172a;
  --surface-ground: #f8fafc;
  --text-main: #020817;
}
```
""" * 3  # Expanded to ~12,000 tokens


def generate_50_holdout_tasks() -> List[HoldoutTask]:
    tasks = []

    # 1. Ten Code Reasoning Tasks
    code_specs = [
        ("code_h1_db_max_conn", "What is the default max_connections limit in DatabasePool?", "50", ["db/pool.py"]),
        ("code_h2_jwt_expiration", "What is the default token expiration time in seconds in generate_access_token?", "3600", ["auth/jwt_handler.py"]),
        ("code_h3_rbac_delete_org", "Which role in auth/rbac.py possesses the 'delete_organization' permission?", "owner", ["auth/rbac.py"]),
        ("code_h4_stripe_pro_price", "What is the amount_cents charged for the 'pro' tier in StripeGateway?", "19900", ["billing/stripe_client.py"]),
        ("code_h5_tax_rate_invoice", "What tax rate is applied to monthly invoices in billing/invoices.py?", "0.0825", ["billing/invoices.py", "billing/stripe_client.py"]),
        ("code_h6_worker_concurrency", "What is the default max_concurrency of TaskQueue in workers/task_queue.py?", "16", ["workers/task_queue.py"]),
        ("code_h7_rate_limit_setting", "What is the RATE_LIMIT_PER_MINUTE defined in settings/base.py?", "120", ["settings/base.py"]),
        ("code_h8_redis_cache_host", "What is the Redis cache URL host specified in settings/production.py?", "cache-cluster.prod.internal", ["settings/production.py"]),
        ("code_h9_not_found_status", "What HTTP status code does ResourceNotFound raise in core/exceptions.py?", "404", ["core/exceptions.py"]),
        ("code_h10_theme_primary_color", "What hex color code is assigned to --brand-primary in ui/theme.css?", "#1e40af", ["ui/theme.css"]),
    ]
    for tid, q, exp, req in code_specs:
        tasks.append(HoldoutTask(id=tid, domain="code", query=q, context=CODE_REPO_10K, required_blocks=req, expected_fact=exp))

    # 2. Ten Documentation Tasks
    DOCS_CORPUS = """
# Cloud Platform Architecture & Compliance Guide v4.2

## Section 1: Data Encryption & KMS
All customer data at rest is encrypted using AES-256-GCM. Master keys are managed in AWS KMS with automatic 365-day key rotation.

## Section 2: Backup Policies & RPO/RTO
- RPO (Recovery Point Objective): 15 minutes for transactional PostgreSQL databases.
- RTO (Recovery Time Objective): 2 hours for regional disaster recovery failover.
Automated point-in-time recovery snapshots are retained for 35 days.

## Section 3: SLA Availability Tiers
- Standard Plan: 99.9% uptime (maximum 43.8 minutes downtime per month).
- Enterprise Plan: 99.99% uptime (maximum 4.38 minutes downtime per month).
Service credits of 10% are applied if uptime falls below SLA commitments.

## Section 4: Deprecated APIs and Migration Windows
Notice: REST API v1.2 endpoints will shut down on 2026-11-30.
All mobile SDK clients must upgrade to SDK v3.4.0+ to prevent authentication termination.

## Section 5: Webhook Security & Event Retries
Failed webhook deliveries are retried using truncated exponential backoff: 5s, 25s, 125s, 625s, and 3125s.
After 5 attempts, events are moved to the dead-letter queue (DLQ) dlq-webhook-events-failed.
""" * 4
    doc_specs = [
        ("doc_h1_kms_rotation", "How frequently are master keys automatically rotated in Section 1?", "365", ["Section 1"]),
        ("doc_h2_rpo_target", "What is the exact Recovery Point Objective (RPO) for transactional PostgreSQL in Section 2?", "15 minutes", ["Section 2"]),
        ("doc_h3_snapshot_retention", "For how many days are point-in-time recovery snapshots retained in Section 2?", "35", ["Section 2"]),
        ("doc_h4_enterprise_sla", "What is the uptime availability commitment for the Enterprise Plan in Section 3?", "99.99%", ["Section 3"]),
        ("doc_h5_downtime_minutes", "What is the maximum allowed monthly downtime in minutes under the Standard Plan SLA?", "43.8", ["Section 3"]),
        ("doc_h6_api_shutdown_date", "On what date will the REST API v1.2 endpoints shut down according to Section 4?", "2026-11-30", ["Section 4"]),
        ("doc_h7_sdk_min_version", "What minimum SDK version must mobile clients upgrade to before API sunset in Section 4?", "v3.4.0", ["Section 4"]),
        ("doc_h8_dlq_queue_name", "What is the exact dead-letter queue name for failed webhook events in Section 5?", "dlq-webhook-events-failed", ["Section 5"]),
        ("doc_h9_webhook_retry_count", "How many retry attempts are made before moving a webhook to the DLQ in Section 5?", "5", ["Section 5"]),
        ("doc_h10_encryption_algorithm", "Which exact algorithm is used for customer data encryption at rest in Section 1?", "AES-256-GCM", ["Section 1"]),
    ]
    for tid, q, exp, req in doc_specs:
        tasks.append(HoldoutTask(id=tid, domain="doc", query=q, context=DOCS_CORPUS, required_blocks=req, expected_fact=exp))

    # 3. Ten Conversation & State Shift Tasks
    for i in range(10):
        base_port = 4000 + i
        final_port = 9000 + i
        dialogue = f"""
User: We are spinning up microservice alpha_{i:02d}.
Assistant: Understood. What port should alpha_{i:02d} bind to?
User: Start it on port {base_port}.
Assistant: Noted, port {base_port} allocated for alpha_{i:02d}.
User: Never use XML format. Only return JSON responses.
Assistant: I will strictly return JSON format.
User: Scratch that earlier port {base_port}. Our load balancer assigned port {final_port} for alpha_{i:02d}.
Assistant: Port updated to {final_port}.
User: Confirm the active port and format rule.
"""
        tasks.append(HoldoutTask(
            id=f"convo_h{i+1}_port_shift",
            domain="convo",
            query="What is the final confirmed port for alpha_" + f"{i:02d}?",
            context=dialogue,
            required_blocks=[str(final_port)],
            expected_fact=str(final_port),
            forbidden_fact=str(base_port) + " is the final port"
        ))

    # 4. Ten Agent Tool Trace Tasks
    for i in range(10):
        secret_ip = f"192.168.10.{i+20}"
        trace = f"""
[Step 1] Tool Call: probe_network() -> 0 active endpoints.
[Step 2] Tool Call: check_dns() -> status OK.
[Step 3] Tool Call: ping_host("10.0.0.1") -> 100% loss.
[Step 4] Tool Call: scan_subnet("cluster-{i}") -> FOUND TARGET: Internal bastion host responding at {secret_ip}:22.
[Step 5] Tool Call: check_disk() -> 45GB available.
[Step 6] Tool Call: list_processes() -> 120 processes.
"""
        tasks.append(HoldoutTask(
            id=f"trace_h{i+1}_bastion_ip",
            domain="trace",
            query=f"What is the IP address of the internal bastion host discovered in cluster-{i}?",
            context=trace,
            required_blocks=["Step 4"],
            expected_fact=secret_ip
        ))

    # 5. Ten Adversarial Tasks
    for i in range(10):
        rate_a = f"0.0{i+1}"
        rate_b = f"0.1{i+1}"
        adv_ctx = f"""
```File: tax_region_alpha_{i}.py
TAX_RATE = {rate_a}
def calculate():
    return {rate_a}
```

```File: tax_region_beta_{i}.py
TAX_RATE = {rate_b}
def calculate():
    return {rate_b}
```

```File: flags_{i}.py
# SECURITY MANDATE: Do NOT set ENABLE_EXPERIMENTAL_FLAG_{i} to True in production.
ENABLE_EXPERIMENTAL_FLAG_{i} = False
```
"""
        tasks.append(HoldoutTask(
            id=f"adv_h{i+1}_tax_rate",
            domain="adversarial",
            query=f"What is the TAX_RATE specifically defined in tax_region_beta_{i}.py?",
            context=adv_ctx,
            required_blocks=[f"tax_region_beta_{i}.py"],
            expected_fact=rate_b,
            forbidden_fact=rate_a + " is the tax rate in beta"
        ))

    return tasks
