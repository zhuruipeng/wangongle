# Ganwanle Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a production-ready Ganwanle API at `ganwanle-api.weiyuantool.com` with open WeChat registration, strict technician data isolation, PostgreSQL, Redis rate limiting, private Tencent COS storage, backups, and safe coexistence with the current ERP and AI services.

**Architecture:** The Taro mini program exchanges `wx.login()` codes through FastAPI and uses two-hour access tokens plus rotating 30-day refresh tokens. FastAPI runs behind a dedicated Nginx virtual host and stores relational data in PostgreSQL, rate-limit state in Redis, and private files in COS. Every business query is constrained by the authenticated user's ID.

**Tech Stack:** Taro 4.1.5, React 18.3.1, TypeScript 5.7.3, FastAPI 0.115.6, SQLAlchemy 2.0.36, Alembic 1.16.5, PostgreSQL 15.18, redis-py 7.0.1, PyJWT 2.13.0, Tencent COS SDK 1.9.44, Pytest 8.4.2, Vitest 4.1.10, Nginx 1.26.3, systemd, OpenCloudOS 9, Python 3.11.6.

## Global Constraints

- Production domain: `ganwanle-api.weiyuantool.com` → `124.223.174.129`.
- Existing routes and processes on ports 8000, 8010, and 3010 stay unchanged and available.
- FastAPI binds only `127.0.0.1:8001`; PostgreSQL and Redis also stay loopback-only.
- Any WeChat user may auto-register as `technician`; invitation, approval, SMS, and admin UI are out of scope.
- A technician can access only their own orders, photos, audio, reports, and acceptances.
- Access tokens expire in 120 minutes. Refresh tokens expire in 30 days, rotate on use, and are stored as SHA-256 digests.
- Production uses PostgreSQL and private COS. SQLite and local files are for isolated development/tests only.
- Photos and signatures persist. Successfully transcribed audio expires after seven days.
- Secrets never enter Git, bundles, logs, errors, tests, or shell output.
- Production Python is 3.11. Local import compatibility remains Python 3.9 until explicitly raised.
- Use red-green-refactor and one focused commit per task.
- Preserve and review current uncommitted AppID and Python compatibility edits before Task 1 commits them.

## File Map

- `server/settings.py`: database, auth, Redis, storage, ASR, and AI settings.
- `server/database.py`: configurable engine and request sessions.
- `server/models.py`: users, refresh sessions, orders, files, acceptances, and audit events.
- `server/security.py`: access/refresh token primitives and current-user dependency.
- `server/middleware.py`: request IDs and sanitized production errors.
- `server/services/wechat_auth.py`: WeChat code exchange.
- `server/services/rate_limit.py`: Redis fixed-window limiter.
- `server/storage/`: local and COS implementations behind one interface.
- `server/routers/auth.py`: login/session/profile API.
- `server/routers/orders.py`: owner-scoped order workflow.
- `server/alembic/`: versioned schema migrations.
- `server/tests/`: Pytest fixtures and security/integration tests.
- `src/services/session.ts`: mini-program token persistence and login bootstrap.
- `src/services/api.ts`: authenticated requests, refresh, and uploads.
- `src/context/AuthContext.tsx`: application auth/profile state.
- `src/pages/login/`, `src/pages/profile/`: login bootstrap and first-use profile.
- `src/pages/customer-acceptance/`, `src/components/SignaturePad/`: persisted acceptance.
- `deploy/`: systemd, Nginx, release, backup, restore, and verification assets.

---

### Task 1: Stabilize the baseline and add Pytest

**Files:**
- Modify: `.gitignore`, `project.config.json`
- Modify: `server/main.py`, `server/models.py`, `server/schemas.py`
- Modify: `server/services/report_generator.py`, `server/test_report_generation.py`
- Create: `server/test_python39_compat.py`, `server/requirements-dev.txt`
- Create: `server/tests/__init__.py`, `server/tests/test_baseline.py`

**Interfaces:**
- Consumes: AppID `wx08985b45c488ec5a` and current `Optional[...]` compatibility edits.
- Produces: `pytest` as the backend test command and a verified import/build baseline.

- [ ] **Step 1: Audit the dirty tree**

```bash
git status --short
git diff -- .gitignore project.config.json server/main.py server/models.py server/schemas.py server/services/report_generator.py server/test_report_generation.py server/test_python39_compat.py
```

Expected: only the known AppID, `.run/` ignore, `Optional[...]` edits, and compatibility test. Stop on unrelated overlapping changes.

- [ ] **Step 2: Write the failing baseline test**

`server/tests/test_baseline.py`:

```python
import subprocess
import sys
from fastapi.testclient import TestClient


def test_server_imports() -> None:
    result = subprocess.run([sys.executable, "-c", "import server.main"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_health_is_public() -> None:
    from server.main import app
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

`server/requirements-dev.txt`:

```text
-r requirements.txt
pytest==8.4.2
```

- [ ] **Step 3: Observe RED, then install and observe GREEN**

```bash
server/.venv/bin/python -m pytest server/tests/test_baseline.py -q
server/.venv/bin/python -m pip install -r server/requirements-dev.txt
server/.venv/bin/python -m pytest server/tests/test_baseline.py -q
server/.venv/bin/python -m server.test_smoke
server/.venv/bin/python -m server.test_report_generation
server/.venv/bin/python -m server.test_transcription
npm run build:weapp
```

Expected RED: `No module named pytest`. Expected GREEN: two Pytest tests, three scripts, and Taro build pass.

- [ ] **Step 4: Commit only reviewed baseline files**

```bash
git add .gitignore project.config.json server/main.py server/models.py server/schemas.py server/services/report_generator.py server/test_report_generation.py server/test_python39_compat.py server/requirements-dev.txt server/tests/__init__.py server/tests/test_baseline.py
git commit -m "test: establish production hardening baseline"
```

---

### Task 2: Add explicit database configuration and Alembic

**Files:**
- Modify: `server/requirements.txt`, `server/settings.py`, `server/database.py`, `server/main.py`, `server/models.py`
- Delete: `server/migrations.py`
- Create: `alembic.ini`, `server/alembic/env.py`, `server/alembic/script.py.mako`
- Create: `server/alembic/versions/0001_production_schema.py`
- Create: `server/tests/test_database_and_migrations.py`

**Interfaces:**
- Consumes: SQLAlchemy `Base` and current order fields.
- Produces: `get_database_settings()`, configurable `engine`, and Alembic revision `0001`.

- [ ] **Step 1: Write failing settings/migration tests**

```python
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_production_rejects_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("GANWANLE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unsafe.db")
    from server.settings import get_database_settings
    try:
        get_database_settings()
    except RuntimeError as error:
        assert "PostgreSQL" in str(error)
    else:
        raise AssertionError("production must reject SQLite")


def test_alembic_upgrades_empty_database(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"users", "refresh_sessions", "service_orders", "service_order_photos", "customer_acceptances", "audit_events"} <= tables
```

Run `server/.venv/bin/python -m pytest server/tests/test_database_and_migrations.py -q`; expected FAIL because Alembic/settings are absent.

- [ ] **Step 2: Pin dependencies**

Append to `server/requirements.txt`:

```text
alembic==1.16.5
psycopg[binary]==3.2.13
redis==7.0.1
PyJWT==2.13.0
cos-python-sdk-v5==1.9.44
```

- [ ] **Step 3: Implement environment-selected database settings**

```python
@dataclass(frozen=True)
class DatabaseSettings:
    environment: str
    url: str
    pool_size: int
    max_overflow: int


def get_database_settings() -> DatabaseSettings:
    environment = os.getenv("GANWANLE_ENV", "development").strip().lower()
    default = f"sqlite:///{(Path(__file__).resolve().parent / 'data' / 'ganwanle.db').as_posix()}"
    url = os.getenv("DATABASE_URL", default).strip()
    if environment == "production" and not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Production requires PostgreSQL")
    return DatabaseSettings(environment, url, int(os.getenv("DATABASE_POOL_SIZE", "5")), int(os.getenv("DATABASE_MAX_OVERFLOW", "5")))
```

`server/database.py` uses `pool_pre_ping=True`, SQLite `check_same_thread=False`, and PostgreSQL pool size/overflow. Keep `get_db()` request-scoped.

- [ ] **Step 4: Define production models and migration**

Add `User`, `RefreshSession`, `CustomerAcceptance`, and `AuditEvent`. Add `owner_user_id` and `audio_object_key` to orders; replace global `order_no` uniqueness with `UniqueConstraint("owner_user_id", "order_no")`. Photos store `object_key`, `content_type`, `size_bytes`, and `sha256`.

Exact new model fields:

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    unionid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    technician_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="technician")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
```

The acceptance table has one unique `service_order_id`, `signature_object_key`, and `accepted_at`. Audit events store user/resource/request IDs, event type, outcome, and timestamp without payloads.

Configure Alembic with `script_location = server/alembic`, environment URL from settings, and `target_metadata = Base.metadata`. Revision `0001` creates all tables/constraints/indexes and drops them in reverse order on downgrade.

- [ ] **Step 5: Remove import-time schema mutation**

Delete `Base.metadata.create_all`, `migrate(engine)`, and `server/migrations.py`. The only schema command becomes:

```bash
server/.venv/bin/alembic upgrade head
```

Change `/api/health` to execute `SELECT 1` through a request-scoped DB session. It returns `{"status":"ok"}` on success and HTTP 503 with `{"detail":"service unavailable"}` on failure; it never exposes the database URL or exception.

- [ ] **Step 6: Verify and commit**

```bash
server/.venv/bin/python -m pip install -r server/requirements-dev.txt
server/.venv/bin/python -m pytest server/tests/test_database_and_migrations.py -q
DATABASE_URL=sqlite:////tmp/ganwanle-migration.db server/.venv/bin/alembic upgrade head
DATABASE_URL=sqlite:////tmp/ganwanle-migration.db server/.venv/bin/alembic current
git add server/requirements.txt server/settings.py server/database.py server/main.py server/models.py server/migrations.py alembic.ini server/alembic server/tests/test_database_and_migrations.py
git commit -m "feat: add production database schema and migrations"
```

Expected: tests pass and Alembic reports `0001 (head)`.

---

### Task 3: Implement token security and WeChat auth

**Files:**
- Modify: `server/settings.py`, `server/schemas.py`, `server/main.py`
- Create: `server/security.py`, `server/middleware.py`, `server/services/wechat_auth.py`, `server/services/rate_limit.py`
- Create: `server/routers/__init__.py`, `server/routers/auth.py`
- Create: `server/tests/conftest.py`, `server/tests/test_security.py`, `server/tests/test_auth.py`

**Interfaces:**
- Consumes: `User`, `RefreshSession`, database sessions, Redis.
- Produces: auth endpoints and `get_current_user()`.

- [ ] **Step 1: Add isolated test fixtures**

Use in-memory SQLite with `StaticPool`, `Base.metadata.create_all`, `create_app()`, and a `get_db` dependency override. No test uses production environment values.

- [ ] **Step 2: Write RED security/auth tests**

```python
def test_token_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    token = create_access_token("user-1", timedelta(minutes=5))
    assert decode_access_token(token) == "user-1"


def test_wechat_login_auto_registers(client, monkeypatch) -> None:
    monkeypatch.setattr("server.routers.auth.exchange_code", lambda code, settings: {"openid": "openid-a", "unionid": None})
    response = client.post("/api/v1/auth/wechat", json={"code": "valid-code"})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "technician"
    assert response.json()["user"]["profile_complete"] is False
```

Also test repeat login, invalid code, two-hour access expiry, profile update, refresh rotation, replay rejection, logout, inactive user, and missing bearer token.

Run `server/.venv/bin/python -m pytest server/tests/test_security.py server/tests/test_auth.py -q`; expected import/route failures.

- [ ] **Step 3: Implement settings and token primitives**

Add `AuthSettings(wechat_app_id, wechat_app_secret, jwt_secret, access_minutes=120, refresh_days=30)` and `RedisSettings(url, key_prefix="ganwanle")`. Production rejects missing WeChat credentials and JWT secrets shorter than 32 characters.

`security.py` uses HS256 JWTs with `sub`, `iat`, `exp`, and `type="access"`; refresh tokens use `secrets.token_urlsafe(48)` and SHA-256 digests. `get_current_user()` returns 401 for missing, invalid, expired, unknown, or inactive users.

- [ ] **Step 4: Implement WeChat exchange and atomic limiter**

```python
response = httpx.get(
    "https://api.weixin.qq.com/sns/jscode2session",
    params={"appid": settings.wechat_app_id, "secret": settings.wechat_app_secret, "js_code": code, "grant_type": "authorization_code"},
    timeout=10,
)
```

Return only openid/unionid. Convert HTTP, JSON, missing-openid, and WeChat errcode failures to `WeChatLoginError("微信登录失败")` without upstream content. Redis uses one Lua script for atomic INCR/EXPIRE. Limits: login 20/5 minutes per IP; refresh 30/5 minutes per digest prefix.

- [ ] **Step 5: Implement auth routes and app factory**

Routes:

- `POST /api/v1/auth/wechat`: rate limit, exchange, upsert, tokens, audit.
- `POST /api/v1/auth/refresh`: row-lock active digest, revoke, rotate, return new pair.
- `POST /api/v1/auth/logout`: revoke and return 204.
- `GET /api/v1/auth/me`: authenticated user and `profile_complete`.
- `PATCH /api/v1/auth/me/profile`: save trimmed 1-100 character name.

`create_app()` registers CORS, auth router, and public `/api/health`; `app = create_app()` remains the Uvicorn entry.

Add request-ID middleware that accepts a valid 1-64 character `X-Request-ID` or generates a UUID, returns it in the response, and puts it on audit events. Production unhandled exceptions return only `{"detail":"服务暂时不可用","request_id":"..."}` with HTTP 500; tests assert temporary WeChat codes, tokens, and secrets never appear in captured logs.

- [ ] **Step 6: Verify and commit**

```bash
server/.venv/bin/python -m pytest server/tests/test_security.py server/tests/test_auth.py -q
git add server/settings.py server/schemas.py server/main.py server/security.py server/middleware.py server/services/wechat_auth.py server/services/rate_limit.py server/routers server/tests/conftest.py server/tests/test_security.py server/tests/test_auth.py
git commit -m "feat: add open WeChat authentication"
```

---

### Task 4: Enforce technician ownership on all order routes

**Files:**
- Modify: `server/main.py`, `server/schemas.py`, `server/models.py`
- Create: `server/routers/orders.py`, `server/tests/test_tenant_isolation.py`
- Modify: `server/test_smoke.py`, `server/test_report_generation.py`, `server/test_transcription.py`

**Interfaces:**
- Consumes: `get_current_user()` and owner-aware models.
- Produces: authenticated existing workflow under `/api/v1/service-orders`.

- [ ] **Step 1: Write RED two-user tests**

```python
def test_other_user_cannot_discover_order(client, auth_headers, create_order) -> None:
    owner = auth_headers("openid-owner")
    stranger = auth_headers("openid-stranger")
    order_id = create_order(owner)["id"]
    assert client.get(f"/api/v1/service-orders/{order_id}", headers=stranger).status_code == 404
    assert client.patch(f"/api/v1/service-orders/{order_id}", headers=stranger, json={"status": "accepted"}).status_code == 404
    assert client.get("/api/v1/service-orders", headers=stranger).json() == []
```

Cover list, detail, patch, photo upload/delete, audio, transcription, report generation/save, submission, and acceptance. Assert unauthenticated requests return 401 and different owners can reuse `order_no`.

Run `server/.venv/bin/python -m pytest server/tests/test_tenant_isolation.py -q`; expected FAIL against current public routes.

- [ ] **Step 2: Move routes and filter ownership in SQL**

```python
def get_order_or_404(db: Session, user_id: str, order_id: str) -> ServiceOrder:
    order = db.scalar(select(ServiceOrder).where(ServiceOrder.id == order_id, ServiceOrder.owner_user_id == user_id))
    if order is None:
        raise HTTPException(status_code=404, detail="服务单不存在")
    return order
```

Every route depends on `current_user: User = Depends(get_current_user)`. Creation requires a completed profile, sets `owner_user_id`, and derives `technician_name` from the user. Remove `technician_name` from create payload. List and atomic report-update predicates include owner ID. Cross-owner resources always return 404.

Write `AuditEvent` rows for order creation, upload/delete, transcription, report generation, submission, and acceptance. Store only user ID, resource type/ID, request ID, event name, outcome, and timestamp—never customer fields, transcripts, filenames, provider bodies, or secrets.

- [ ] **Step 3: Update legacy tests to authenticate and register router**

Preserve existing ASR/AI mocks and assertions. Add `application.include_router(orders.router, prefix="/api/v1/service-orders")`.

- [ ] **Step 4: Verify and commit**

```bash
server/.venv/bin/python -m pytest server/tests server/test_smoke.py server/test_report_generation.py server/test_transcription.py -q
git add server/main.py server/schemas.py server/models.py server/routers/orders.py server/tests/test_tenant_isolation.py server/test_smoke.py server/test_report_generation.py server/test_transcription.py
git commit -m "feat: isolate service orders by technician"
```

---

### Task 5: Replace public local files with private storage and COS

**Files:**
- Modify: `server/settings.py`, `server/routers/orders.py`, `server/schemas.py`
- Create: `server/storage/__init__.py`, `server/storage/base.py`, `server/storage/local.py`, `server/storage/cos.py`
- Create: `server/tests/test_storage.py`

**Interfaces:**
- Consumes: authenticated user/order IDs, validated upload streams, COS credentials.
- Produces: `StorageBackend.put()`, `download_to()`, `delete()`, `move()`, `presigned_get_url()`, and `get_storage()`.

- [ ] **Step 1: Write RED storage contract tests**

```python
from io import BytesIO

def test_local_storage_round_trip(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    key = "development/users/u1/orders/o1/photos/a.jpg"
    storage.put(key, BytesIO(b"image"), "image/jpeg")
    target = tmp_path / "download.jpg"
    storage.download_to(key, target)
    assert target.read_bytes() == b"image"
    storage.move(key, "development/archive/a.jpg")
    assert storage.exists("development/archive/a.jpg")
    storage.delete("development/archive/a.jpg")
    assert not storage.exists("development/archive/a.jpg")


def test_object_key_contains_only_ids() -> None:
    key = build_object_key("production", "user-id", "order-id", "photos", ".jpg")
    assert key.startswith("production/users/user-id/orders/order-id/photos/")
    assert key.endswith(".jpg")
```

Add a fake `CosS3Client` test for private upload, copy/delete move, and presigned GET. Run `server/.venv/bin/python -m pytest server/tests/test_storage.py -q`; expected missing-package failure.

- [ ] **Step 2: Add validated storage settings and interface**

Environment names: `STORAGE_BACKEND`, `LOCAL_STORAGE_ROOT`, `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_REGION`, `COS_BUCKET`, `COS_PRESIGNED_SECONDS`. Production requires `cos`, credentials, bucket, and a 60-900 second presign lifetime.

```python
class StorageBackend(Protocol):
    def put(self, key: str, stream: BinaryIO, content_type: str) -> None: ...
    def download_to(self, key: str, target: Path) -> None: ...
    def delete(self, key: str) -> None: ...
    def move(self, source_key: str, target_key: str) -> None: ...
    def presigned_get_url(self, key: str, expires_seconds: int) -> str: ...
```

Key rules:

- permanent files: `production/users/{user_id}/orders/{order_id}/photos|signatures/{uuid}{suffix}`;
- pending audio: `production/audio-pending/users/{user_id}/orders/{order_id}/{uuid}{suffix}`;
- expiring audio: `production/audio-expiring/users/{user_id}/orders/{order_id}/{uuid}{suffix}`.

These top-level audio prefixes make COS lifecycle rules deterministic.

- [ ] **Step 3: Implement LocalStorage and CosStorage**

Local paths must resolve beneath the configured root and reject traversal. COS uses `CosConfig`/`CosS3Client`; `move()` copies then deletes only after copy success. Default signed download lifetime is 300 seconds.

```python
@lru_cache
def get_storage() -> StorageBackend:
    settings = get_storage_settings()
    if settings.backend == "local":
        return LocalStorage(Path(settings.local_root))
    return CosStorage(settings)
```

- [ ] **Step 4: Refactor uploads and responses**

Retain MIME, extension, image 10MB, audio 20MB limits. Compute SHA-256 and byte size while reading. Upload first, then commit metadata; delete the object if the DB commit fails. Replacing audio deletes the prior object only after the new object and DB update succeed.

Photo responses generate five-minute signed `file_url` values only after owner authorization. The DB stores only private object keys and metadata. Remove the production `StaticFiles('/uploads')` mount; local storage may expose files only through an authenticated signed-file development route.

- [ ] **Step 5: Verify and commit**

```bash
server/.venv/bin/python -m pytest server/tests/test_storage.py server/tests/test_tenant_isolation.py -q
git add server/settings.py server/routers/orders.py server/schemas.py server/storage server/tests/test_storage.py
git commit -m "feat: store private delivery files in COS"
```

Expected: contract, rollback cleanup, signed URL, validation, and owner tests pass.

---

### Task 6: Add seven-day audio transition and persisted acceptance

**Files:**
- Modify: `server/routers/orders.py`, `server/models.py`, `server/schemas.py`, `server/storage/base.py`
- Create: `server/tests/test_audio_lifecycle.py`, `server/tests/test_acceptance.py`

**Interfaces:**
- Consumes: private storage, ASR, owner-authorized orders, `CustomerAcceptance`.
- Produces: audio pending→expiring transition and `POST /api/v1/service-orders/{order_id}/acceptance`.

- [ ] **Step 1: Write RED audio tests**

```python
def test_transcription_moves_audio_to_expiring_prefix(client, owner_order, fake_storage, monkeypatch) -> None:
    order_id, headers = owner_order(audio=True)
    monkeypatch.setattr("server.routers.orders.transcribe_audio", lambda path, settings: FakeAsrResult())
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 200
    source, target = fake_storage.moves[0]
    assert "/audio-pending/" in source
    assert "/audio-expiring/" in target
```

Also assert temporary downloads are deleted, failed recognition leaves pending audio retryable, and a failed COS move never loses the source.

- [ ] **Step 2: Write RED acceptance tests**

```python
def test_owner_persists_acceptance(client, owner_order, signature_png) -> None:
    order_id, headers = owner_order(status="waiting_acceptance")
    response = client.post(
        f"/api/v1/service-orders/{order_id}/acceptance",
        headers=headers,
        data={"accepted": "true"},
        files={"signature": ("signature.png", signature_png, "image/png")},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert response.json()["acceptance"]["accepted_at"]
```

Cover checkbox requirement, PNG/JPEG validation, 5MB maximum, owner isolation, duplicate 409, signature cleanup on DB failure, and signed response URL.

- [ ] **Step 3: Observe RED**

```bash
server/.venv/bin/python -m pytest server/tests/test_audio_lifecycle.py server/tests/test_acceptance.py -q
```

Expected: missing lifecycle and endpoint failures.

- [ ] **Step 4: Implement lifecycle and acceptance**

Transcription uses `TemporaryDirectory`, downloads the authorized object, invokes ASR, and removes the local file automatically. Success moves the object to `production/audio-expiring/`, updates `audio_object_key`, and stores aware UTC `audio_delete_after = now + 7 days`. A move failure preserves pending audio and records `storage.audio_transition:failed` without exposing the provider error.

Acceptance requires `waiting_acceptance`, one PNG/JPEG signature ≤5MB, and `accepted=true`; it uploads to `signatures`, writes one acceptance, changes status to `accepted`, and returns metadata plus a five-minute signed URL. Cross-user requests return 404.

- [ ] **Step 5: Verify and commit**

```bash
server/.venv/bin/python -m pytest server/tests/test_audio_lifecycle.py server/tests/test_acceptance.py server/tests/test_tenant_isolation.py -q
git add server/routers/orders.py server/models.py server/schemas.py server/storage/base.py server/tests/test_audio_lifecycle.py server/tests/test_acceptance.py
git commit -m "feat: persist acceptance and expire transcribed audio"
```

---

### Task 7: Add mini-program session management and profile gate

**Files:**
- Modify: `package.json`, `package-lock.json`, `src/app.tsx`, `src/app.config.ts`
- Modify: `src/services/api.ts`, `src/services/serviceOrders.ts`, `src/context/DeliveryContext.tsx`, `src/pages/workbench/index.tsx`
- Create: `vitest.config.ts`, `src/services/session.ts`, `src/services/session.test.ts`, `src/services/api.test.ts`
- Create: `src/context/AuthContext.tsx`
- Create: `src/pages/login/index.config.ts`, `src/pages/login/index.tsx`, `src/pages/login/index.scss`
- Create: `src/pages/profile/index.config.ts`, `src/pages/profile/index.tsx`, `src/pages/profile/index.scss`

**Interfaces:**
- Consumes: auth/profile endpoints.
- Produces: persisted tokens, login bootstrap, single-flight refresh, authenticated requests/uploads, and required technician-name profile.

- [ ] **Step 1: Add Vitest and RED session tests**

```bash
npm install --save-dev vitest@4.1.10 react-test-renderer@18.3.1 @types/react-test-renderer@18.3.1
```

Add scripts `"test:unit": "vitest run"` and `"test": "npm run test:unit && npm run build:weapp"`.

```typescript
vi.mock('@tarojs/taro', () => ({ default: {
  login: vi.fn().mockResolvedValue({ code: 'wx-code' }),
  getStorageSync: vi.fn(), setStorageSync: vi.fn(), removeStorageSync: vi.fn()
}}))

it('stores and clears both tokens', () => {
  saveSession({ access_token: 'access', refresh_token: 'refresh' })
  expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleAccessToken', 'access')
  expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleRefreshToken', 'refresh')
  clearSession()
  expect(Taro.removeStorageSync).toHaveBeenCalledTimes(2)
})
```

Run `npm run test:unit`; expected missing `session.ts` failure.

- [ ] **Step 2: Implement session API**

```typescript
export type AuthUser = { id: string; technician_name: string | null; role: 'technician'; profile_complete: boolean }
export type SessionResponse = { access_token: string; refresh_token: string; user: AuthUser }

export function getAccessToken(): string
export function getRefreshToken(): string
export function saveSession(tokens: Pick<SessionResponse, 'access_token' | 'refresh_token'>): void
export function clearSession(): void
export async function loginWithWechat(): Promise<SessionResponse>
export async function refreshSession(): Promise<SessionResponse>
```

Login uses `Taro.login()`, rejects missing code, posts to `/api/v1/auth/wechat`, and saves tokens. One module-level promise deduplicates refreshes.

- [ ] **Step 3: Authenticate API and upload calls**

Add Bearer headers. On 401, refresh and retry the original call exactly once. A second 401 clears tokens and reLaunches `/pages/login/index`. Never refresh the login/refresh endpoints. Tests mock 401→200 and repeated 401.

- [ ] **Step 4: Add auth context, login, and profile pages**

Auth states: `loading`, `authenticated`, `anonymous`. Bootstrap checks `/me`, then uses WeChat login when needed. Incomplete profiles reLaunch `/pages/profile/index`; the profile page PATCHes a trimmed 1-100 character name.

Wrap providers:

```tsx
return <AuthProvider><DeliveryProvider>{children}</DeliveryProvider></AuthProvider>
```

Register login/profile pages before workbench. Login shows progress, readable failure, and retry—no password fields.

- [ ] **Step 5: Remove hard-coded technician identity**

Workbench reads AuthContext, removes technician name from create payload, generates a unique order number `GW-${Date.now()}-${randomSuffix}`, and lists only authenticated orders. It no longer recovers conflicts through a global search.

- [ ] **Step 6: Verify and commit**

```bash
npm run test:unit
npm run build:weapp
git add package.json package-lock.json vitest.config.ts src/app.tsx src/app.config.ts src/services src/context src/pages/login src/pages/profile src/pages/workbench/index.tsx
git commit -m "feat: authenticate mini program with WeChat"
```

---

### Task 8: Persist signature and acceptance in the mini program

**Files:**
- Modify: `src/components/SignaturePad/index.tsx`, `src/pages/customer-acceptance/index.tsx`
- Modify: `src/services/api.ts`, `src/services/serviceOrders.ts`
- Create: `src/components/SignaturePad/index.test.tsx`, `src/pages/customer-acceptance/index.test.tsx`

**Interfaces:**
- Consumes: authenticated acceptance upload API.
- Produces: exported PNG temp path and server-confirmed acceptance state.

- [ ] **Step 1: Write RED UI tests**

Mock `Taro.canvasToTempFilePath`; assert drawing end reports a PNG path. Mock acceptance upload; assert `accepted=true`, multipart field `signature`, duplicate-click suppression, and finished UI only after server success.

Keep the existing `submitOrderAcceptance(id)` function that changes an order to `waiting_acceptance`. Add a separate final-customer-confirmation function:

```typescript
export const confirmOrderAcceptance = (id: string, signaturePath: string) =>
  uploadFile<ApiServiceOrder>(`/api/v1/service-orders/${id}/acceptance`, signaturePath, { accepted: 'true' }, 'signature')
```

Run the two test files; expected failure because acceptance is currently local-only.

- [ ] **Step 2: Export and upload the signature**

```typescript
type SignaturePadProps = {
  disabled: boolean
  signaturePath: string
  onSignatureChange: (path: string) => void
}
```

On drawing end call `Taro.canvasToTempFilePath({ canvasId: 'customerSignature', fileType: 'png' })`; clear reports `''`. Extend `uploadFile` with optional `fieldName='file'` and use `signature`. Acceptance awaits the backend, stores returned order/time, and keeps the page unfinished on errors.

- [ ] **Step 3: Verify and commit**

```bash
npm run test:unit
npm run build:weapp
git add src/components/SignaturePad src/pages/customer-acceptance src/services/api.ts src/services/serviceOrders.ts
git commit -m "feat: persist customer acceptance signature"
```

---

### Task 9: Add deployment, backup, restore, and verification assets

**Files:**
- Modify: `server/.env.example`, `server/README.md`
- Create: `deploy/ganwanle-api.service`, `deploy/ganwanle-api.bootstrap.nginx.conf`, `deploy/ganwanle-api.nginx.conf`
- Create: `deploy/ganwanle-backup.service`, `deploy/ganwanle-backup.timer`
- Create: `deploy/ganwanle-healthcheck.service`, `deploy/ganwanle-healthcheck.timer`, `deploy/healthcheck.sh`
- Create: `deploy/swapfile.swap`, `deploy/99-ganwanle-sysctl.conf`
- Create: `deploy/backup-postgres.sh`, `deploy/restore-drill.sh`, `deploy/release.sh`, `deploy/verify-production.sh`
- Create: `server/scripts/__init__.py`, `server/scripts/upload_backup.py`
- Create: `server/tests/test_deploy_assets.py`

**Interfaces:**
- Consumes: `/opt/ganwanle/current`, `/etc/ganwanle/ganwanle.env`, database `ganwanle`, service user `ganwanle`.
- Produces: repeatable release/rollback, isolated systemd/Nginx configs, off-host-ready backups, and smoke checks.

- [ ] **Step 1: Write RED asset tests**

```python
from pathlib import Path
import subprocess


def test_shell_scripts_parse() -> None:
    scripts = list(Path("deploy").glob("*.sh"))
    assert scripts
    for path in scripts:
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path}: {result.stderr}"


def test_service_is_private_and_restarts() -> None:
    unit = Path("deploy/ganwanle-api.service").read_text()
    assert "--host 127.0.0.1" in unit
    assert "--port 8001" in unit
    assert "--workers 2" in unit
    assert "Restart=on-failure" in unit


def test_nginx_is_isolated() -> None:
    config = Path("deploy/ganwanle-api.nginx.conf").read_text()
    assert "server_name ganwanle-api.weiyuantool.com;" in config
    assert "proxy_pass http://127.0.0.1:8001;" in config
    assert "weiyuantool.com www.weiyuantool.com" not in config
```

Run `server/.venv/bin/python -m pytest server/tests/test_deploy_assets.py -q`; expected missing assets.

- [ ] **Step 2: Create exact service and Nginx configs**

The API unit uses:

```ini
[Service]
User=ganwanle
Group=ganwanle
WorkingDirectory=/opt/ganwanle/current
EnvironmentFile=/etc/ganwanle/ganwanle.env
ExecStart=/opt/ganwanle/current/server/.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8001 --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
```

The bootstrap Nginx file serves only `/.well-known/acme-challenge/` from `/var/www/certbot` on port 80. The final file retains that challenge location, redirects other HTTP traffic, and adds port 443 for only the API subdomain. It sets `client_max_body_size 25m`, request/forwarded headers, upload/AI timeouts, rate-limit zones, and `proxy_pass http://127.0.0.1:8001` without a URI suffix. It never edits `caiwu-erp.conf`.

`swapfile.swap` declares `What=/swapfile` and `WantedBy=swap.target`. `99-ganwanle-sysctl.conf` contains exactly `vm.swappiness = 10`; both are installed from reviewed repository files.

- [ ] **Step 3: Create deterministic release and backup scripts**

`release.sh SHA` must:

1. validate a 40-character commit SHA;
2. create `/opt/ganwanle/releases/$SHA` from that exact Git object;
3. create `server/.venv` with `/usr/bin/python3.11` and install locked requirements;
4. run backend tests and `alembic upgrade head`;
5. start the candidate on `127.0.0.1:18001` and health-check it;
6. atomically switch `/opt/ganwanle/current`;
7. restart `ganwanle-api` and verify public HTTPS;
8. retain the previous symlink target for application rollback.

`ganwanle-backup.service` runs as `ganwanle`, reads `/etc/ganwanle/ganwanle.env`, and invokes `backup-postgres.sh`. The script creates a custom-format `pg_dump` through `DATABASE_URL`, validates with `pg_restore --list`, retains 7 daily and 4 weekly backups, and calls `server/scripts/upload_backup.py LOCAL_PATH COS_KEY`. That Python script uses the configured COS SDK client to upload under `production-backups/database/daily|weekly/`; it verifies the returned ETag and exits non-zero on off-host failure.

`restore-drill.sh` restores the newest dump only into `ganwanle_restore_check`, verifies Alembic head/tables/counts, then drops only that named database.

`verify-production.sh` checks HTTPS health, certificate expiry, Nginx syntax, service states, loopback listeners, and existing ERP/AI URLs without printing secrets. `ganwanle-healthcheck.timer` runs every minute; `healthcheck.sh` fails when public health, API service, PostgreSQL, disk threshold, or certificate checks fail, causing the service failure to appear in journald and systemd status.

- [ ] **Step 4: Document production environment**

`server/.env.example` lists safe empty values for `GANWANLE_ENV`, `DATABASE_URL`, pool settings, `REDIS_URL`, `JWT_SECRET`, `WECHAT_APP_ID`, `WECHAT_APP_SECRET`, all COS, ASR, AI, and CORS variables. README gives exact local SQLite/local storage and production PostgreSQL/COS commands.

- [ ] **Step 5: Verify and commit**

```bash
server/.venv/bin/python -m pytest server/tests/test_deploy_assets.py -q
bash -n deploy/backup-postgres.sh deploy/restore-drill.sh deploy/release.sh deploy/verify-production.sh
git add server/.env.example server/README.md server/scripts deploy server/tests/test_deploy_assets.py
git commit -m "ops: add isolated production deployment assets"
```

---

### Task 10: Run the complete release-candidate gate

**Files:**
- Modify only when a failing check identifies a defect in a prior task.

**Interfaces:**
- Consumes: completed backend, frontend, storage, migration, and deployment work.
- Produces: one verified release candidate SHA and tag.

- [ ] **Step 1: Test from a fresh Python environment**

```bash
test ! -e /tmp/ganwanle-release-verify-v1.0.0-rc1
python3 -m venv /tmp/ganwanle-release-verify-v1.0.0-rc1/venv
/tmp/ganwanle-release-verify-v1.0.0-rc1/venv/bin/python -m pip install -r server/requirements-dev.txt
/tmp/ganwanle-release-verify-v1.0.0-rc1/venv/bin/python -m pytest server/tests server/test_smoke.py server/test_report_generation.py server/test_transcription.py -q
```

Expected: zero failures.

- [ ] **Step 2: Verify migration repeatability**

```bash
DATABASE_URL=sqlite:////tmp/ganwanle-release-verify-v1.0.0-rc1/clean.db /tmp/ganwanle-release-verify-v1.0.0-rc1/venv/bin/alembic upgrade head
DATABASE_URL=sqlite:////tmp/ganwanle-release-verify-v1.0.0-rc1/clean.db /tmp/ganwanle-release-verify-v1.0.0-rc1/venv/bin/alembic upgrade head
DATABASE_URL=sqlite:////tmp/ganwanle-release-verify-v1.0.0-rc1/clean.db /tmp/ganwanle-release-verify-v1.0.0-rc1/venv/bin/alembic current
```

Expected: both upgrades succeed and one head is current.

- [ ] **Step 3: Test/build the mini program against production URL**

```bash
npm ci
npm run test:unit
TARO_APP_API_BASE_URL=https://ganwanle-api.weiyuantool.com npm run build:weapp
test -f dist/app.json
```

Expected: tests and build pass; `dist/app.json` exists.

- [ ] **Step 4: Scan secrets and artifacts**

```bash
rg -n 'WECHAT_APP_SECRET=.+|COS_SECRET_KEY=.+|DASHSCOPE_API_KEY=.+|TENCENTCLOUD_SECRET_KEY=.+' . -g '!node_modules' -g '!dist' -g '!server/.venv'
git status --short
git diff --check
```

Expected: no secret matches, clean diff, and only intentional tracked state. Then create local tag:

```bash
git tag -a ganwanle-v1.0.0-rc1 -m "Ganwanle production release candidate 1"
```

Do not push the tag before Task 11 prerequisites exist.

---

### Task 11: Provision the existing OpenCloudOS server safely

**Files on server:**
- Create: `/etc/ganwanle/ganwanle.env`
- Create: `/etc/nginx/conf.d/ganwanle-api.conf`
- Create: `/etc/systemd/system/ganwanle-api.service`
- Create: `/etc/systemd/system/ganwanle-backup.service`, `/etc/systemd/system/ganwanle-backup.timer`
- Create: `/etc/systemd/system/ganwanle-healthcheck.service`, `/etc/systemd/system/ganwanle-healthcheck.timer`
- Create: `/opt/ganwanle/repository`, `/opt/ganwanle/releases/`, `/var/backups/ganwanle/`

**Interfaces:**
- Consumes: release SHA, DNS, WeChat AppSecret, private COS bucket/CAM credentials, DB password.
- Produces: public HTTPS API, automatic restart/backup, preserved ERP/AI.

- [ ] **Step 1: Record the before snapshot**

```bash
ssh caiwu-server 'date -Is; nginx -t; systemctl --no-pager --full status nginx erp redis; ss -ltnp; curl --fail --silent https://weiyuantool.com/ >/dev/null; curl --fail --silent https://weiyuantool.com/ai/ >/dev/null; free -h; df -h /'
```

Expected: current configs/services/routes healthy. Save output without environment values.

- [ ] **Step 2: Complete external prerequisites**

- DNS A record: `ganwanle-api.weiyuantool.com` → `124.223.174.129`; verify with `dig +short`.
- COS: private bucket base name `ganwanle-prod`, region `ap-shanghai`.
- COS lifecycle: `production/audio-expiring/` expires after 7 days; `production/audio-pending/` expires after 30 days; photos/signatures do not expire.
- CAM sub-user: only required object read/write/delete/copy permissions for this bucket.
- WeChat AppID: `wx08985b45c488ec5a`; obtain AppSecret and store only server-side.

- [ ] **Step 3: Install PostgreSQL/certificate tooling**

```bash
dnf install -y postgresql-server-15.18 postgresql-contrib-15.18 certbot-2.8.0 python3-certbot-nginx-2.8.0
postgresql-setup --initdb
systemctl enable --now postgresql
```

Configure PostgreSQL for loopback only and SCRAM TCP auth. Verify port 5432 is not public.

- [ ] **Step 4: Create isolated identities and directories**

```bash
useradd --system --home-dir /opt/ganwanle --shell /sbin/nologin ganwanle
install -d -o ganwanle -g ganwanle -m 0750 /opt/ganwanle/releases
install -d -o root -g ganwanle -m 0750 /etc/ganwanle
install -d -o ganwanle -g ganwanle -m 0750 /var/backups/ganwanle/daily /var/backups/ganwanle/weekly
```

Clone the Git repository into `/opt/ganwanle/repository`, owned by `ganwanle`, fetch the verified SHA, and confirm `git rev-parse` matches it. Create the database interactively without exposing its password:

```sql
CREATE ROLE ganwanle_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password ganwanle_app
CREATE DATABASE ganwanle OWNER ganwanle_app;
```

Generate JWT secret on-server without printing it. Edit `/etc/ganwanle/ganwanle.env` via `sudoedit`; mode 0640, owner `root:ganwanle`.

- [ ] **Step 5: Add exactly 2GB swap**

First verify `/swapfile` does not exist:

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
install -o root -g root -m 0644 /opt/ganwanle/repository/deploy/swapfile.swap /etc/systemd/system/swapfile.swap
install -o root -g root -m 0644 /opt/ganwanle/repository/deploy/99-ganwanle-sysctl.conf /etc/sysctl.d/99-ganwanle.conf
systemctl daemon-reload
systemctl enable swapfile.swap
sysctl --system
swapon --show
```

- [ ] **Step 6: Install reviewed configs and certificate**

Confirm `admin@weiyuantool.com` receives certificate notices before execution. Install the HTTP-only bootstrap config and create the challenge root first:

```bash
install -d -o nginx -g nginx -m 0755 /var/www/certbot
install -o root -g root -m 0644 /opt/ganwanle/repository/deploy/ganwanle-api.bootstrap.nginx.conf /etc/nginx/conf.d/ganwanle-api.conf
nginx -t
systemctl reload nginx
```

Do not change `/etc/nginx/conf.d/caiwu-erp.conf`.

After DNS resolves:

```bash
certbot certonly --webroot -w /var/www/certbot -d ganwanle-api.weiyuantool.com --non-interactive --agree-tos --email admin@weiyuantool.com
```

Install the reviewed final Nginx file from `/opt/ganwanle/repository/deploy`, whose certificate paths are `/etc/letsencrypt/live/ganwanle-api.weiyuantool.com/fullchain.pem` and `privkey.pem`; validate and reload. Install systemd units from the repository and run `systemd-analyze verify` before enabling them.

- [ ] **Step 7: Deploy and compare after state**

Run `/opt/ganwanle/repository/deploy/release.sh` with the verified SHA; enable the API, backup timer, health-check timer, and Certbot renewal timer. In Tencent Cloud Monitor, create policy `ganwanle-cvm` for this CVM with filesystem utilization warning at 70%, critical at 85%, memory warning at 80%, and notification to the account's active administrator contact. Then run:

```bash
/opt/ganwanle/current/deploy/verify-production.sh
systemctl --no-pager --full status ganwanle-api ganwanle-backup.timer ganwanle-healthcheck.timer certbot-renew.timer nginx erp redis postgresql
curl --fail --silent https://weiyuantool.com/ >/dev/null
curl --fail --silent https://weiyuantool.com/ai/ >/dev/null
```

Expected: Ganwanle healthy, existing services healthy, and no public 8001/5432/6379 listener. SELinux is currently disabled; do not alter it. Cloud firewall remains 22/80/443 only. Verify `sshd_config` disables password authentication before broad rollout; restrict port 22 to the user's stable management IP only after confirming a second active SSH session succeeds with the key.

---

### Task 12: Configure WeChat domains and run the canary

**Files:**
- Modify source only through a new tested commit if canary finds a defect.

**Interfaces:**
- Consumes: deployed HTTPS API, production build, two WeChat accounts.
- Produces: verified production readiness and controlled open registration.

- [ ] **Step 1: Configure legal domains**

Add exactly `https://ganwanle-api.weiyuantool.com` to request, uploadFile, and downloadFile legal domains. Upload the build compiled with that same API base URL.

- [ ] **Step 2: Run two-account authorization acceptance**

Account A: login, set name, create order, upload before/after photos/audio, transcribe, generate/edit report, submit, sign, accept.

Account B: login with a different name, confirm A's order never lists, and direct calls using A's ID return 404 for detail, patch, upload, report, and acceptance.

- [ ] **Step 3: Verify storage and retention**

Confirm distinct user IDs/non-null owners in PostgreSQL; private objects/random keys in COS; expiring signed links; successful audio under `production/audio-expiring/`; active 7-day rule.

- [ ] **Step 4: Prove backup recovery**

Run backup manually, verify local and COS copies, then run `restore-drill.sh`. Expected: restore-check DB reaches Alembic head with expected rows; production DB untouched.

- [ ] **Step 5: Canary with 5-10 technicians for seven days**

Review HTTP 5xx, login failures, P95 latency, memory/swap/disk, PostgreSQL size, Redis errors, COS failures, ASR/AI failures, backups, and certificate status daily. Stop expansion on any cross-user access, data loss, repeated 5xx, or failed backup.

- [ ] **Step 6: Open registration broadly**

After seven stable days and a successful restore drill, publish to all technicians. Keep open registration, per-owner authorization, daily off-host backups, and seven-day audio expiry unchanged.

## Official References

- Alembic migration tutorial: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Tencent COS Python presigned URLs: https://cloud.tencent.com/document/product/436/35153
- Tencent COS presigned upload security: https://cloud.tencent.com/document/product/436/14114
- Redis atomic rate limiter: https://redis.io/docs/latest/commands/incr/
- FastAPI deployment concepts: https://fastapi.tiangolo.com/deployment/concepts/
- Nginx reverse proxy: https://nginx.org/en/docs/http/ngx_http_proxy_module.html
