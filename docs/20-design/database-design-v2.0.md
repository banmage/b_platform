# b_platform 数据库设计 V2.0

**项目：** b_platform（通用业务底座平台·控制面）  
**版本：** V2.0  
**状态：** 设计基线（待评审）  
**数据库：** PostgreSQL 16+  
**对应需求：** `docs/10-requirements/requirements-v2.0.md`  
**对应技术设计：** `docs/20-design/tech-design-v2.0.md`

---

## 1. 文档定位

本文档定义 b_platform 的逻辑模型、物理 DDL、约束、索引、RLS 策略、数据库角色与授权矩阵、迁移策略和种子数据。它是 `sqlc` 查询、迁移脚本、pgTAP 用例和 Repository 实现的直接依据。

**覆盖：** 平台用户与认证、租户、组织、成员、角色与权限、平台授权、审计、服务账号、扩展注册、Outbox、幂等键、配置、Webhook。

**不覆盖：** 资源、预订、论坛、计费等扩展模块表。扩展表由扩展自行管理，位于 `ext_<module>` schema。

---

## 2. 设计原则

| 编号 | 原则 |
|---|---|
| P1 | 所有业务主键使用 UUIDv7，由应用生成；数据库不使用自增 |
| P2 | 所有租户数据必须包含 `tenant_id`，并启用 `ENABLE` + `FORCE ROW LEVEL SECURITY` |
| P3 | 运行时角色一律 `NOBYPASSRLS`；跨租户通过目标租户上下文 + 显式策略 |
| P4 | 会话级 `SET` 禁止；只允许事务级 `set_config('app.tenant_id', ..., true)` |
| P5 | 表级、列级授权显式声明；禁止 `GRANT ... ON ALL TABLES` |
| P6 | 审计只追加；应用角色无 `UPDATE` / `DELETE` 权限 |
| P7 | 状态用 `varchar + CHECK`，不用原生 enum，便于演进 |
| P8 | 时间统一 `timestamptz`，统一 UTC |
| P9 | 父子组织同租户由复合外键保证，不依赖应用自觉 |
| P10 | 平台级表不做租户 RLS，但通过角色与表级授权限制访问 |

---

## 3. 逻辑模型

```text
Platform（控制面，无 tenant_id）
├── platform_user
├── user_session / one_time_token / login_attempt
├── permission
├── role (scope = PLATFORM)
├── platform_role_permission
├── platform_role_grant ── platform_role_grant_scope
├── platform_param
├── extension_registry
└── audit_log（tenant_id 可空）

Tenant（隔离边界）
├── tenant
├── tenant_membership ── tenant_role_assignment ── role (scope = TENANT)
├── tenant_config
├── membership_invitation
├── service_account ── api_key
├── webhook_endpoint ── webhook_delivery
├── outbox_event
├── idempotency_key
└── organization
     ├── organization_closure
     ├── organization_approval
     ├── organization_membership ── organization_role_assignment ── role (scope = ORGANIZATION)
     └── ownership_transfer
```

### 3.1 关键关系

- `tenant` 1 : N `organization`；`organization.parent_id` 自引用，父子必须同 `tenant_id`。
- `tenant` 1 : N `tenant_membership`；同一用户在同一租户最多一条非 `INACTIVE` 记录。
- `organization` 1 : N `organization_membership`；组织成员必须关联有效的租户成员。
- `role` 按 `scope` 分为平台、租户、组织三层；所有者在对应层级唯一。
- `role_permission` 只存租户/组织角色权限；平台角色权限单独存 `platform_role_permission`，避免 `tenant_id` 可空带来的 RLS 歧义。
- `audit_log` 按 `occurred_at` 月分区，`tenant_id` 可空（平台事件）。

---

## 4. 公共约定

### 4.1 命名

| 对象 | 规范 | 示例 |
|---|---|---|
| schema | 小写 | `core`、`ext_booking` |
| 表 | 小写下划线、单数 | `tenant_membership` |
| 主键 | `id` | `id uuid` |
| 外键 | `<实体>_id` | `organization_id` |
| 布尔 | `is_` / `has_` | `is_owner` |
| 时间 | `_at`，`timestamptz` | `created_at` |
| 索引 | `idx_<表>_<列>` | `idx_organization_tenant_parent` |
| 唯一索引 | `uq_<表>_<语义>` | `uq_tenant_membership_user_active` |
| 约束 | `ck_` / `fk_` / `uq_` | `ck_role_scope` |
| RLS 策略 | `pol_<表>_<角色>` | `pol_organization_core` |

### 4.2 主键与 ID

- 应用使用 UUIDv7（`github.com/google/uuid` 的新版本或内部实现）。
- 数据库列类型 `uuid`，**无默认值**，插入必须显式提供。
- 对外 API 一律字符串化，不使用 JSON number。
- 不使用 `BIGSERIAL`、`IDENTITY`、`nextval`。

### 4.3 时间与审计列

- 所有业务表包含 `created_at timestamptz NOT NULL DEFAULT now()`。
- 可变实体包含 `updated_at timestamptz NOT NULL DEFAULT now()`，由触发器维护。
- 不存储本地时间；不使用 `timestamp without time zone`。

### 4.4 状态值

- 大写蛇形字符串，`varchar(16)` 或 `varchar(24)` + `CHECK`。
- 状态值只增不改；删除状态需迁移与兼容处理。
- 终态不可逆，除非状态机文档明确回退路径。

### 4.5 JSONB

- `config`、`detail`、`payload`、`manifest` 使用 `jsonb`。
- 写入前由应用做 Schema 校验；数据库只保证是合法 JSON。
- 需要检索的字段建表达式索引或 GIN 索引，不滥用。

---

## 5. 数据库角色

### 5.1 角色清单

| 角色 | 登录 | BYPASSRLS | 用途 |
|---|---|---|---|
| `platform_migrator` | 是（仅迁移 Job） | **是（唯一例外）** | DDL、迁移、回填、分区维护 |
| `platform_auth` | 是 | 否 | 注册、登录、会话、令牌 |
| `platform_core` | 是 | 否 | 租户内业务读写、审计写入、Outbox |
| `platform_control` | 是 | 否 | 平台控制面、跨租户管理、平台授权 |
| `platform_audit_reader` | 是 | 否 | 平台审计只读 |

**关于 `platform_migrator` 的 `BYPASSRLS`：**

- 它只用于迁移 Job 与分区维护，不部署到 API/Worker 运行时。
- 迁移 Job 使用短期凭证，运行在独立 Kubernetes Job / 一次性容器中。
- API/Worker 的连接串中不包含该角色。
- 任何运行时角色拥有 `BYPASSRLS` 都视为发布阻断缺陷。

### 5.2 角色属性

```sql
-- deploy/bootstrap/roles.sql，由 DBA/平台管理员执行一次，不属于 goose 迁移
CREATE ROLE platform_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT BYPASSRLS;
CREATE ROLE platform_auth LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOBYPASSRLS;
CREATE ROLE platform_core LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOBYPASSRLS;
CREATE ROLE platform_control LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOBYPASSRLS;
CREATE ROLE platform_audit_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOBYPASSRLS;

-- 密码由 Secret Manager 注入后单独设置，不写入仓库
-- ALTER ROLE platform_core PASSWORD '...';

ALTER ROLE platform_migrator       SET search_path = core, public;
ALTER ROLE platform_auth           SET search_path = core, public;
ALTER ROLE platform_core           SET search_path = core, public;
ALTER ROLE platform_control        SET search_path = core, public;
ALTER ROLE platform_audit_reader   SET search_path = core, public;

ALTER ROLE platform_core           SET statement_timeout = '15s';
ALTER ROLE platform_core           SET lock_timeout = '3s';
ALTER ROLE platform_core           SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE platform_control        SET statement_timeout = '30s';
ALTER ROLE platform_control        SET lock_timeout = '3s';
ALTER ROLE platform_control        SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE platform_auth           SET statement_timeout = '10s';
ALTER ROLE platform_audit_reader   SET statement_timeout = '60s';

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE b_platform FROM PUBLIC;
GRANT CONNECT ON DATABASE b_platform
  TO platform_migrator, platform_auth, platform_core, platform_control, platform_audit_reader;
```

> `NOINHERIT` 表示角色只使用直接授予它的权限，不继承其他角色的权限；所有授权都显式写在本角色上。

---

## 6. 物理 DDL

> 以下 DDL 为 greenfield 初版迁移 `db/migrations/0001_init.sql` 的权威内容。迁移由 `platform_migrator` 执行。

### 6.1 Schema 与公共函数

```sql
CREATE SCHEMA IF NOT EXISTS core;
COMMENT ON SCHEMA core IS 'b_platform control plane core schema';

REVOKE ALL ON SCHEMA core FROM PUBLIC;
GRANT USAGE ON SCHEMA core
  TO platform_auth, platform_core, platform_control, platform_audit_reader;

-- 当前事务的租户上下文；未设置时返回 NULL，RLS 策略因此返回 0 行
CREATE OR REPLACE FUNCTION core.app_current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

REVOKE ALL ON FUNCTION core.app_current_tenant_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core.app_current_tenant_id()
  TO platform_auth, platform_core, platform_control, platform_audit_reader;

-- updated_at 自动维护
CREATE OR REPLACE FUNCTION core.fn_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION core.fn_touch_updated_at() FROM PUBLIC;
```

### 6.2 身份与认证

```sql
CREATE TABLE core.platform_user (
    id                  uuid PRIMARY KEY,
    account             varchar(320) NOT NULL,
    account_normalized  varchar(320) NOT NULL,
    email               varchar(320),
    phone               varchar(32),
    display_name        varchar(128) NOT NULL,
    password_hash       text,
    status              varchar(24) NOT NULL DEFAULT 'PENDING_VERIFICATION'
                        CHECK (status IN ('PENDING_VERIFICATION','ACTIVE','LOCKED','DISABLED')),
    email_verified_at   timestamptz,
    phone_verified_at   timestamptz,
    permission_version  bigint NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    failed_login_count  integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until        timestamptz,
    last_login_at       timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_platform_user_account
    ON core.platform_user (account_normalized);
CREATE UNIQUE INDEX uq_platform_user_email
    ON core.platform_user (lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX uq_platform_user_phone
    ON core.platform_user (phone) WHERE phone IS NOT NULL;
CREATE INDEX idx_platform_user_status
    ON core.platform_user (status);

CREATE TRIGGER trg_platform_user_updated_at
    BEFORE UPDATE ON core.platform_user
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.user_session (
    id                  uuid PRIMARY KEY,
    user_id             uuid NOT NULL REFERENCES core.platform_user(id) ON DELETE CASCADE,
    family_id           uuid NOT NULL,
    refresh_token_hash  bytea NOT NULL,
    audience            varchar(16) NOT NULL CHECK (audience IN ('user','platform')),
    tenant_id           uuid,
    organization_id     uuid,
    user_agent          text,
    client_ip           inet,
    status              varchar(16) NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','ROTATED','REVOKED','EXPIRED')),
    expires_at          timestamptz NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_used_at        timestamptz,
    revoked_at          timestamptz,
    replaced_by         uuid REFERENCES core.user_session(id)
);

CREATE UNIQUE INDEX uq_user_session_refresh_hash
    ON core.user_session (refresh_token_hash);
CREATE INDEX idx_user_session_user
    ON core.user_session (user_id, status);
CREATE INDEX idx_user_session_family
    ON core.user_session (family_id);
CREATE INDEX idx_user_session_expires
    ON core.user_session (expires_at) WHERE status = 'ACTIVE';

CREATE TABLE core.one_time_token (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES core.platform_user(id) ON DELETE CASCADE,
    purpose     varchar(32) NOT NULL
                CHECK (purpose IN ('EMAIL_VERIFY','PHONE_VERIFY','PASSWORD_RESET')),
    token_hash  bytea NOT NULL,
    expires_at  timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_one_time_token_hash
    ON core.one_time_token (token_hash);
CREATE INDEX idx_one_time_token_user
    ON core.one_time_token (user_id, purpose, expires_at);

CREATE TABLE core.login_attempt (
    id                  uuid PRIMARY KEY,
    account_normalized  varchar(320),
    user_id             uuid,
    client_ip           inet,
    success             boolean NOT NULL,
    failure_reason      varchar(64),
    occurred_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_login_attempt_account
    ON core.login_attempt (account_normalized, occurred_at DESC);
CREATE INDEX idx_login_attempt_ip
    ON core.login_attempt (client_ip, occurred_at DESC);
```

### 6.3 租户

```sql
CREATE TABLE core.tenant (
    id                  uuid PRIMARY KEY,
    slug                varchar(63) NOT NULL,
    name                varchar(128) NOT NULL,
    status              varchar(16) NOT NULL DEFAULT 'PROVISIONING'
                        CHECK (status IN ('PROVISIONING','ACTIVE','FROZEN','CLOSED')),
    owner_user_id       uuid REFERENCES core.platform_user(id),
    permission_version  bigint NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_tenant_slug CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')
);

CREATE UNIQUE INDEX uq_tenant_slug ON core.tenant (lower(slug));
CREATE INDEX idx_tenant_status ON core.tenant (status);

CREATE TRIGGER trg_tenant_updated_at
    BEFORE UPDATE ON core.tenant
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.tenant_membership (
    id                  uuid PRIMARY KEY,
    tenant_id           uuid NOT NULL REFERENCES core.tenant(id) ON DELETE CASCADE,
    user_id             uuid NOT NULL REFERENCES core.platform_user(id),
    status              varchar(16) NOT NULL DEFAULT 'INVITED'
                        CHECK (status IN ('INVITED','ACTIVE','SUSPENDED','INACTIVE')),
    is_owner            boolean NOT NULL DEFAULT false,
    permission_version  bigint NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    invited_by          uuid REFERENCES core.platform_user(id),
    invited_at          timestamptz,
    joined_at           timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_membership_id_tenant UNIQUE (id, tenant_id),
    CONSTRAINT uq_tenant_membership_id_user   UNIQUE (id, user_id),
    CONSTRAINT ck_tenant_membership_owner     CHECK (NOT is_owner OR status = 'ACTIVE')
);

CREATE UNIQUE INDEX uq_tenant_membership_user_active
    ON core.tenant_membership (tenant_id, user_id) WHERE status <> 'INACTIVE';
CREATE UNIQUE INDEX uq_tenant_membership_owner
    ON core.tenant_membership (tenant_id) WHERE is_owner AND status = 'ACTIVE';
CREATE INDEX idx_tenant_membership_user
    ON core.tenant_membership (user_id, status);

CREATE TRIGGER trg_tenant_membership_updated_at
    BEFORE UPDATE ON core.tenant_membership
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.tenant_config (
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id) ON DELETE CASCADE,
    key         varchar(128) NOT NULL,
    value       jsonb NOT NULL,
    updated_by  uuid REFERENCES core.platform_user(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key),
    CONSTRAINT ck_tenant_config_key CHECK (key ~ '^[a-z][a-z0-9_.-]{0,127}$')
);

```
### 6.4 组织

```sql
CREATE TABLE core.organization (
    id                  uuid PRIMARY KEY,
    tenant_id           uuid NOT NULL REFERENCES core.tenant(id) ON DELETE CASCADE,
    parent_id           uuid,
    org_type            varchar(64) NOT NULL,
    name                varchar(128) NOT NULL,
    status              varchar(16) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','ACTIVE','REJECTED','WITHDRAWN','FROZEN','ARCHIVED')),
    visibility          varchar(16) NOT NULL DEFAULT 'TENANT'
                        CHECK (visibility IN ('TENANT','SUBTREE','PRIVATE')),
    owner_user_id       uuid REFERENCES core.platform_user(id),
    config              jsonb NOT NULL DEFAULT '{}'::jsonb,
    permission_version  bigint NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    created_by          uuid REFERENCES core.platform_user(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_organization_id_tenant UNIQUE (id, tenant_id),
    CONSTRAINT fk_organization_parent FOREIGN KEY (parent_id, tenant_id)
        REFERENCES core.organization (id, tenant_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_organization_no_self_parent CHECK (parent_id IS NULL OR parent_id <> id),
    CONSTRAINT ck_organization_org_type CHECK (org_type ~ '^[a-z][a-z0-9_-]{0,63}$')
);

CREATE UNIQUE INDEX uq_organization_sibling_name
    ON core.organization
       (tenant_id,
        coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid),
        lower(name))
    WHERE status NOT IN ('REJECTED','WITHDRAWN','ARCHIVED');
CREATE INDEX idx_organization_tenant_parent
    ON core.organization (tenant_id, parent_id);
CREATE INDEX idx_organization_tenant_status
    ON core.organization (tenant_id, status);

CREATE TRIGGER trg_organization_updated_at
    BEFORE UPDATE ON core.organization
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.organization_closure (
    tenant_id      uuid NOT NULL,
    ancestor_id    uuid NOT NULL,
    descendant_id  uuid NOT NULL,
    depth          integer NOT NULL CHECK (depth >= 0),
    PRIMARY KEY (tenant_id, ancestor_id, descendant_id),
    CONSTRAINT fk_org_closure_ancestor FOREIGN KEY (ancestor_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_org_closure_descendant FOREIGN KEY (descendant_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT ck_org_closure_depth CHECK (
        (ancestor_id = descendant_id AND depth = 0) OR
        (ancestor_id <> descendant_id AND depth > 0)
    )
);

CREATE INDEX idx_org_closure_descendant
    ON core.organization_closure (tenant_id, descendant_id);

CREATE TABLE core.organization_approval (
    id                 uuid PRIMARY KEY,
    tenant_id          uuid NOT NULL,
    organization_id    uuid NOT NULL,
    applicant_user_id  uuid NOT NULL REFERENCES core.platform_user(id),
    parent_id          uuid,
    status             varchar(16) NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','APPROVED','REJECTED','WITHDRAWN')),
    decision_by        uuid REFERENCES core.platform_user(id),
    decision_at        timestamptz,
    decision_reason    text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_org_approval_org FOREIGN KEY (organization_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_org_approval_parent FOREIGN KEY (parent_id, tenant_id)
        REFERENCES core.organization (id, tenant_id),
    CONSTRAINT ck_org_approval_decision CHECK (
        (status = 'PENDING' AND decision_by IS NULL AND decision_at IS NULL) OR
        (status IN ('APPROVED','REJECTED') AND decision_by IS NOT NULL AND decision_at IS NOT NULL) OR
        (status = 'WITHDRAWN' AND decision_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_org_approval_pending
    ON core.organization_approval (organization_id) WHERE status = 'PENDING';
CREATE INDEX idx_org_approval_tenant_status
    ON core.organization_approval (tenant_id, status);

CREATE TRIGGER trg_org_approval_updated_at
    BEFORE UPDATE ON core.organization_approval
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.ownership_transfer (
    id             uuid PRIMARY KEY,
    tenant_id      uuid NOT NULL REFERENCES core.tenant(id) ON DELETE CASCADE,
    scope          varchar(16) NOT NULL CHECK (scope IN ('TENANT','ORGANIZATION')),
    target_id      uuid NOT NULL,
    from_user_id   uuid NOT NULL REFERENCES core.platform_user(id),
    to_user_id     uuid NOT NULL REFERENCES core.platform_user(id),
    status         varchar(16) NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','ACCEPTED','DECLINED','CANCELLED','EXPIRED','FORCED')),
    initiated_by   uuid NOT NULL REFERENCES core.platform_user(id),
    forced         boolean NOT NULL DEFAULT false,
    reason         text,
    expires_at     timestamptz NOT NULL,
    completed_at   timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_ownership_transfer_distinct CHECK (from_user_id <> to_user_id),
    CONSTRAINT ck_ownership_transfer_forced CHECK (
        (forced AND status = 'FORCED') OR (NOT forced AND status <> 'FORCED')
    )
);

CREATE UNIQUE INDEX uq_ownership_transfer_pending
    ON core.ownership_transfer (tenant_id, scope, target_id) WHERE status = 'PENDING';
CREATE INDEX idx_ownership_transfer_to
    ON core.ownership_transfer (to_user_id, status);

CREATE TRIGGER trg_ownership_transfer_updated_at
    BEFORE UPDATE ON core.ownership_transfer
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();
```

> `ownership_transfer.target_id` 是 `TENANT` 时为 `tenant.id`，是 `ORGANIZATION` 时为 `organization.id`。多态引用无法用外键表达，由应用在同一事务内校验目标存在且属于该租户。

### 6.5 角色与权限

```sql
CREATE TABLE core.permission (
    code           varchar(128) PRIMARY KEY,
    namespace      varchar(16) NOT NULL CHECK (namespace IN ('CORE','EXT')),
    module         varchar(64),
    scope          varchar(16) NOT NULL CHECK (scope IN ('PLATFORM','TENANT','ORGANIZATION')),
    description    text NOT NULL,
    is_dangerous   boolean NOT NULL DEFAULT false,
    status         varchar(16) NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','DEPRECATED')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_permission_namespace CHECK (
        (namespace = 'CORE' AND module IS NULL) OR
        (namespace = 'EXT' AND module IS NOT NULL AND code LIKE 'ext.%')
    )
);

CREATE INDEX idx_permission_scope ON core.permission (scope, status);

CREATE TRIGGER trg_permission_updated_at
    BEFORE UPDATE ON core.permission
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.role (
    id               uuid PRIMARY KEY,
    scope            varchar(16) NOT NULL CHECK (scope IN ('PLATFORM','TENANT','ORGANIZATION')),
    tenant_id        uuid REFERENCES core.tenant(id) ON DELETE CASCADE,
    organization_id  uuid,
    code             varchar(64) NOT NULL,
    name             varchar(128) NOT NULL,
    description      text,
    is_system        boolean NOT NULL DEFAULT false,
    is_owner_role    boolean NOT NULL DEFAULT false,
    status           varchar(16) NOT NULL DEFAULT 'ACTIVE'
                     CHECK (status IN ('ACTIVE','DISABLED')),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_role_id_tenant       UNIQUE (id, tenant_id),
    CONSTRAINT uq_role_id_scope        UNIQUE (id, scope),
    CONSTRAINT uq_role_id_organization UNIQUE (id, organization_id),
    CONSTRAINT ck_role_scope CHECK (
        (scope = 'PLATFORM' AND tenant_id IS NULL AND organization_id IS NULL) OR
        (scope = 'TENANT' AND tenant_id IS NOT NULL AND organization_id IS NULL) OR
        (scope = 'ORGANIZATION' AND tenant_id IS NOT NULL AND organization_id IS NOT NULL)
    ),
    CONSTRAINT ck_role_owner_scope CHECK (NOT is_owner_role OR scope IN ('TENANT','ORGANIZATION')),
    CONSTRAINT fk_role_organization FOREIGN KEY (organization_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_role_platform_code
    ON core.role (code) WHERE scope = 'PLATFORM';
CREATE UNIQUE INDEX uq_role_tenant_code
    ON core.role (tenant_id, code) WHERE scope = 'TENANT';
CREATE UNIQUE INDEX uq_role_org_code
    ON core.role (organization_id, code) WHERE scope = 'ORGANIZATION';
CREATE UNIQUE INDEX uq_role_tenant_owner
    ON core.role (tenant_id) WHERE scope = 'TENANT' AND is_owner_role;
CREATE UNIQUE INDEX uq_role_org_owner
    ON core.role (organization_id) WHERE scope = 'ORGANIZATION' AND is_owner_role;
CREATE INDEX idx_role_tenant ON core.role (tenant_id, scope);

CREATE TRIGGER trg_role_updated_at
    BEFORE UPDATE ON core.role
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

-- 租户 / 组织角色的权限
CREATE TABLE core.role_permission (
    role_id          uuid NOT NULL,
    tenant_id        uuid NOT NULL,
    permission_code  varchar(128) NOT NULL REFERENCES core.permission(code),
    granted_by       uuid REFERENCES core.platform_user(id),
    granted_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role_id, permission_code),
    CONSTRAINT fk_role_permission_role FOREIGN KEY (role_id, tenant_id)
        REFERENCES core.role (id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX idx_role_permission_tenant
    ON core.role_permission (tenant_id, permission_code);

-- 平台角色的权限；role_scope 仅用于复合外键，确保只关联 PLATFORM 角色
CREATE TABLE core.platform_role_permission (
    role_id          uuid NOT NULL,
    role_scope       varchar(16) NOT NULL DEFAULT 'PLATFORM'
                     CHECK (role_scope = 'PLATFORM'),
    permission_code  varchar(128) NOT NULL REFERENCES core.permission(code),
    granted_by       uuid REFERENCES core.platform_user(id),
    granted_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role_id, permission_code),
    CONSTRAINT fk_platform_role_permission_role FOREIGN KEY (role_id, role_scope)
        REFERENCES core.role (id, scope) ON DELETE CASCADE
);

CREATE TABLE core.tenant_role_assignment (
    id            uuid PRIMARY KEY,
    tenant_id     uuid NOT NULL,
    membership_id uuid NOT NULL,
    role_id       uuid NOT NULL,
    role_scope    varchar(16) NOT NULL DEFAULT 'TENANT'
                  CHECK (role_scope = 'TENANT'),
    assigned_by   uuid REFERENCES core.platform_user(id),
    assigned_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_tenant_role_assignment_membership FOREIGN KEY (membership_id, tenant_id)
        REFERENCES core.tenant_membership (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_tenant_role_assignment_role FOREIGN KEY (role_id, tenant_id)
        REFERENCES core.role (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_tenant_role_assignment_scope FOREIGN KEY (role_id, role_scope)
        REFERENCES core.role (id, scope) ON DELETE CASCADE,
    CONSTRAINT uq_tenant_role_assignment UNIQUE (membership_id, role_id)
);

CREATE INDEX idx_tenant_role_assignment_role
    ON core.tenant_role_assignment (tenant_id, role_id);

CREATE TABLE core.organization_membership (
    id                   uuid PRIMARY KEY,
    tenant_id            uuid NOT NULL,
    organization_id      uuid NOT NULL,
    tenant_membership_id uuid NOT NULL,
    user_id              uuid NOT NULL,
    status               varchar(16) NOT NULL DEFAULT 'INVITED'
                         CHECK (status IN ('INVITED','ACTIVE','SUSPENDED','INACTIVE')),
    is_owner             boolean NOT NULL DEFAULT false,
    permission_version   bigint NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    invited_by           uuid REFERENCES core.platform_user(id),
    joined_at            timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_organization_membership_id_tenant UNIQUE (id, tenant_id),
    CONSTRAINT fk_om_organization FOREIGN KEY (organization_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_om_tenant_membership FOREIGN KEY (tenant_membership_id, tenant_id)
        REFERENCES core.tenant_membership (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_om_tenant_membership_user FOREIGN KEY (tenant_membership_id, user_id)
        REFERENCES core.tenant_membership (id, user_id) ON DELETE CASCADE,
    CONSTRAINT ck_om_owner CHECK (NOT is_owner OR status = 'ACTIVE')
);

CREATE UNIQUE INDEX uq_om_user_active
    ON core.organization_membership (organization_id, user_id) WHERE status <> 'INACTIVE';
CREATE UNIQUE INDEX uq_om_owner
    ON core.organization_membership (organization_id) WHERE is_owner AND status = 'ACTIVE';
CREATE INDEX idx_om_user
    ON core.organization_membership (user_id, status);

CREATE TRIGGER trg_om_updated_at
    BEFORE UPDATE ON core.organization_membership
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.organization_role_assignment (
    id              uuid PRIMARY KEY,
    tenant_id       uuid NOT NULL,
    organization_id uuid NOT NULL,
    membership_id   uuid NOT NULL,
    role_id         uuid NOT NULL,
    role_scope      varchar(16) NOT NULL DEFAULT 'ORGANIZATION'
                    CHECK (role_scope = 'ORGANIZATION'),
    assigned_by     uuid REFERENCES core.platform_user(id),
    assigned_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_ora_membership FOREIGN KEY (membership_id, tenant_id)
        REFERENCES core.organization_membership (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_ora_role FOREIGN KEY (role_id, tenant_id)
        REFERENCES core.role (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_ora_role_scope FOREIGN KEY (role_id, role_scope)
        REFERENCES core.role (id, scope) ON DELETE CASCADE,
    CONSTRAINT fk_ora_role_organization FOREIGN KEY (role_id, organization_id)
        REFERENCES core.role (id, organization_id) ON DELETE CASCADE,
    CONSTRAINT fk_ora_organization FOREIGN KEY (organization_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT uq_org_role_assignment UNIQUE (membership_id, role_id)
);

CREATE INDEX idx_org_role_assignment_role
    ON core.organization_role_assignment (tenant_id, role_id);

CREATE TABLE core.membership_invitation (
    id              uuid PRIMARY KEY,
    tenant_id       uuid NOT NULL,
    organization_id uuid,
    email           varchar(320) NOT NULL,
    role_id         uuid,
    token_hash      bytea NOT NULL,
    invited_by      uuid NOT NULL REFERENCES core.platform_user(id),
    status          varchar(16) NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','ACCEPTED','REVOKED','EXPIRED')),
    expires_at      timestamptz NOT NULL,
    accepted_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_membership_invitation_org FOREIGN KEY (organization_id, tenant_id)
        REFERENCES core.organization(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_membership_invitation_role FOREIGN KEY (role_id, tenant_id)
        REFERENCES core.role(id, tenant_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_membership_invitation_token
    ON core.membership_invitation (token_hash);
CREATE UNIQUE INDEX uq_membership_invitation_pending
    ON core.membership_invitation
       (tenant_id,
        coalesce(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        lower(email))
    WHERE status = 'PENDING';
```
### 6.6 平台角色授予

```sql
CREATE TABLE core.platform_role_grant (
    id           uuid PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES core.platform_user(id) ON DELETE CASCADE,
    role_id      uuid NOT NULL,
    role_scope   varchar(16) NOT NULL DEFAULT 'PLATFORM'
                 CHECK (role_scope = 'PLATFORM'),
    granted_by   uuid NOT NULL REFERENCES core.platform_user(id),
    status       varchar(16) NOT NULL DEFAULT 'ACTIVE'
                 CHECK (status IN ('ACTIVE','REVOKED','EXPIRED')),
    expires_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    revoked_by   uuid REFERENCES core.platform_user(id),
    CONSTRAINT fk_prg_role FOREIGN KEY (role_id, role_scope)
        REFERENCES core.role (id, scope) ON DELETE CASCADE,
    CONSTRAINT ck_prg_expiry CHECK (status <> 'EXPIRED' OR expires_at IS NOT NULL),
    CONSTRAINT ck_prg_revoked CHECK (
        (status = 'REVOKED' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL) OR
        (status <> 'REVOKED')
    )
);

CREATE UNIQUE INDEX uq_platform_role_grant_active
    ON core.platform_role_grant (user_id, role_id) WHERE status = 'ACTIVE';
CREATE INDEX idx_platform_role_grant_user
    ON core.platform_role_grant (user_id, status);

CREATE TABLE core.platform_role_grant_scope (
    id                    uuid PRIMARY KEY,
    grant_id              uuid NOT NULL REFERENCES core.platform_role_grant(id) ON DELETE CASCADE,
    scope_type            varchar(16) NOT NULL
                          CHECK (scope_type IN ('ALL','TENANT','ORGANIZATION','ORG_TYPE')),
    tenant_id             uuid REFERENCES core.tenant(id) ON DELETE CASCADE,
    organization_id       uuid,
    org_type              varchar(64),
    include_descendants   boolean NOT NULL DEFAULT false,
    CONSTRAINT ck_prgs_shape CHECK (
        (scope_type = 'ALL'
            AND tenant_id IS NULL AND organization_id IS NULL
            AND org_type IS NULL AND NOT include_descendants) OR
        (scope_type = 'TENANT'
            AND tenant_id IS NOT NULL AND organization_id IS NULL AND org_type IS NULL) OR
        (scope_type = 'ORGANIZATION'
            AND tenant_id IS NOT NULL AND organization_id IS NOT NULL AND org_type IS NULL) OR
        (scope_type = 'ORG_TYPE'
            AND tenant_id IS NOT NULL AND organization_id IS NULL AND org_type IS NOT NULL)
    ),
    CONSTRAINT fk_prgs_organization FOREIGN KEY (organization_id, tenant_id)
        REFERENCES core.organization (id, tenant_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_prgs_all
    ON core.platform_role_grant_scope (grant_id) WHERE scope_type = 'ALL';
CREATE UNIQUE INDEX uq_prgs_target
    ON core.platform_role_grant_scope
       (grant_id, scope_type,
        coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(org_type, ''))
    WHERE scope_type <> 'ALL';
```

授予语义：

- 一个 `platform_role_grant` 至少有一条 `platform_role_grant_scope`。
- `ALL` 表示全平台范围，必须显式授予；`is_dangerous` 语义见权限模型 §8.2（一期仅审计增强，不改变授权判定）。
- `TENANT` 表示指定租户；`ORGANIZATION` 表示指定组织；`ORG_TYPE` 表示租户内某类组织。
- `include_descendants` 只对 `TENANT` / `ORGANIZATION` / `ORG_TYPE` 有意义，表示是否覆盖组织子树。
- 多条范围取并集，不取交集。

### 6.7 审计

```sql
CREATE TABLE core.audit_log (
    id               uuid NOT NULL,
    occurred_at      timestamptz NOT NULL DEFAULT now(),
    tenant_id        uuid,
    organization_id  uuid,
    actor_type       varchar(16) NOT NULL
                     CHECK (actor_type IN ('USER','SERVICE_ACCOUNT','SYSTEM')),
    actor_id         uuid,
    actor_ip         inet,
    action           varchar(128) NOT NULL,
    target_type      varchar(64) NOT NULL,
    target_id        uuid,
    result           varchar(16) NOT NULL CHECK (result IN ('SUCCESS','DENIED','FAILURE')),
    request_id       varchar(64),
    trace_id         varchar(64),
    detail           jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);

CREATE INDEX idx_audit_log_tenant_time
    ON core.audit_log (tenant_id, occurred_at DESC);
CREATE INDEX idx_audit_log_actor
    ON core.audit_log (actor_type, actor_id, occurred_at DESC);
CREATE INDEX idx_audit_log_target
    ON core.audit_log (target_type, target_id, occurred_at DESC);

CREATE TABLE core.audit_log_2026_11 PARTITION OF core.audit_log
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
CREATE TABLE core.audit_log_2026_12 PARTITION OF core.audit_log
    FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
CREATE TABLE core.audit_log_2027_01 PARTITION OF core.audit_log
    FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2027-02-01 00:00:00+00');
CREATE TABLE core.audit_log_default PARTITION OF core.audit_log DEFAULT;
```

分区规则：

- 按月分区，提前创建未来 3 个月。
- 默认分区只作为兜底，出现数据后必须尽快创建对应月份分区并迁移。
- 归档流程：`DETACH PARTITION` → 导出对象存储/SIEM → `DROP TABLE`。
- 分区维护由 `platform_migrator` 执行，Worker 不持有 DDL 权限。

### 6.8 服务账号与 API Key

```sql
CREATE TABLE core.service_account (
    id                  uuid PRIMARY KEY,
    tenant_id           uuid REFERENCES core.tenant(id) ON DELETE CASCADE,
    name                varchar(128) NOT NULL,
    client_id           varchar(64) NOT NULL,
    client_secret_hash  bytea,
    status              varchar(16) NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','DISABLED')),
    scopes              text[] NOT NULL DEFAULT '{}',
    expires_at          timestamptz,
    created_by          uuid REFERENCES core.platform_user(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_service_account_id_tenant UNIQUE (id, tenant_id),
    CONSTRAINT ck_service_account_name CHECK (name <> '')
);

CREATE UNIQUE INDEX uq_service_account_client_id
    ON core.service_account (client_id);
CREATE UNIQUE INDEX uq_service_account_name
    ON core.service_account
       (coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name));
CREATE INDEX idx_service_account_tenant
    ON core.service_account (tenant_id, status);

CREATE TRIGGER trg_service_account_updated_at
    BEFORE UPDATE ON core.service_account
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.api_key (
    id                  uuid PRIMARY KEY,
    tenant_id           uuid REFERENCES core.tenant(id) ON DELETE CASCADE,
    service_account_id  uuid NOT NULL REFERENCES core.service_account(id) ON DELETE CASCADE,
    name                varchar(128),
    key_prefix          varchar(16) NOT NULL,
    key_hash            bytea NOT NULL,
    status              varchar(16) NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','REVOKED','EXPIRED')),
    expires_at          timestamptz,
    last_used_at        timestamptz,
    created_by          uuid REFERENCES core.platform_user(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    revoked_at          timestamptz,
    CONSTRAINT fk_api_key_service_account FOREIGN KEY (service_account_id, tenant_id)
        REFERENCES core.service_account (id, tenant_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_api_key_hash ON core.api_key (key_hash);
CREATE INDEX idx_api_key_service_account
    ON core.api_key (service_account_id, status);
CREATE INDEX idx_api_key_prefix ON core.api_key (key_prefix);
```

> `service_account.scopes` 中的权限编码由应用校验必须存在于 `core.permission` 且状态为 `ACTIVE`；数组无法使用外键。

### 6.9 扩展注册

```sql
CREATE TABLE core.extension_registry (
    name          varchar(64) PRIMARY KEY,
    version       varchar(32) NOT NULL,
    api_version   varchar(16) NOT NULL,
    status        varchar(16) NOT NULL DEFAULT 'REGISTERED'
                  CHECK (status IN ('REGISTERED','ACTIVE','DISABLED')),
    schema_name   varchar(64) NOT NULL,
    manifest      jsonb NOT NULL,
    installed_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_extension_name CHECK (name ~ '^[a-z][a-z0-9-]{0,63}$'),
    CONSTRAINT ck_extension_schema CHECK (schema_name = 'ext_' || replace(name, '-', '_'))
);

CREATE UNIQUE INDEX uq_extension_schema ON core.extension_registry (schema_name);

CREATE TRIGGER trg_extension_registry_updated_at
    BEFORE UPDATE ON core.extension_registry
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();
```

### 6.10 Outbox、幂等、配置与 Webhook

```sql
CREATE TABLE core.outbox_event (
    id                 uuid PRIMARY KEY,
    tenant_id          uuid,
    aggregate_type     varchar(64) NOT NULL,
    aggregate_id       uuid NOT NULL,
    event_type         varchar(128) NOT NULL
                       CHECK (event_type NOT LIKE '%.*'), -- 具体编码禁用通配（事件目录 §5）
    event_version      integer NOT NULL CHECK (event_version > 0),
    payload            jsonb NOT NULL,
    headers            jsonb NOT NULL DEFAULT '{}'::jsonb,
    deduplication_key  varchar(128),
    status             varchar(16) NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','DISPATCHED','FAILED','DEAD')),
    attempts           integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at       timestamptz NOT NULL DEFAULT now(),
    last_error         text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    dispatched_at      timestamptz,
    CONSTRAINT uq_outbox_dedup UNIQUE (deduplication_key)
);

CREATE INDEX idx_outbox_pending
    ON core.outbox_event (available_at)
    WHERE status IN ('PENDING','FAILED');
CREATE INDEX idx_outbox_tenant
    ON core.outbox_event (tenant_id, created_at DESC);

CREATE TABLE core.idempotency_key (
    id               uuid PRIMARY KEY,
    tenant_id        uuid,
    principal_type   varchar(16) NOT NULL
                     CHECK (principal_type IN ('USER','SERVICE_ACCOUNT','SYSTEM')),
    principal_id     uuid NOT NULL,
    endpoint         varchar(128) NOT NULL,
    idem_key         varchar(128) NOT NULL,
    request_hash     varchar(64) NOT NULL,
    response_status  integer,
    response_body    jsonb,
    status           varchar(16) NOT NULL DEFAULT 'IN_PROGRESS'
                     CHECK (status IN ('IN_PROGRESS','COMPLETED','FAILED')),
    expires_at       timestamptz NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    completed_at     timestamptz
);

CREATE UNIQUE INDEX uq_idempotency_key
    ON core.idempotency_key
       (coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
        principal_type, principal_id, endpoint, idem_key);
CREATE INDEX idx_idempotency_expiry ON core.idempotency_key (expires_at);

CREATE TABLE core.platform_param (
    key          varchar(128) PRIMARY KEY,
    value        jsonb NOT NULL,
    is_public    boolean NOT NULL DEFAULT false,
    description  text,
    updated_by   uuid REFERENCES core.platform_user(id),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_platform_param_key CHECK (key ~ '^[a-z][a-z0-9_.-]{0,127}$')
);

CREATE TABLE core.webhook_endpoint (
    id                  uuid PRIMARY KEY,
    tenant_id           uuid NOT NULL REFERENCES core.tenant(id) ON DELETE CASCADE,
    url                 text NOT NULL CHECK (url ~ '^https://'),
    secret_ciphertext   bytea NOT NULL,
    events              text[] NOT NULL,
    status              varchar(16) NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','DISABLED')),
    description         text,
    created_by          uuid REFERENCES core.platform_user(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_webhook_endpoint_tenant
    ON core.webhook_endpoint (tenant_id, status);

CREATE TRIGGER trg_webhook_endpoint_updated_at
    BEFORE UPDATE ON core.webhook_endpoint
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch_updated_at();

CREATE TABLE core.webhook_delivery (
    id                uuid PRIMARY KEY,
    tenant_id         uuid NOT NULL,
    endpoint_id       uuid NOT NULL REFERENCES core.webhook_endpoint(id) ON DELETE CASCADE,
    event_id          uuid NOT NULL REFERENCES core.outbox_event(id) ON DELETE CASCADE,
    status            varchar(16) NOT NULL DEFAULT 'PENDING'
                      CHECK (status IN ('PENDING','DELIVERED','FAILED','DEAD')),
    attempts          integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at   timestamptz NOT NULL DEFAULT now(),
    response_status   integer,
    last_error        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    delivered_at      timestamptz
);

CREATE UNIQUE INDEX uq_webhook_delivery_endpoint_event
    ON core.webhook_delivery (endpoint_id, event_id);
CREATE INDEX idx_webhook_delivery_pending
    ON core.webhook_delivery (next_attempt_at)
    WHERE status IN ('PENDING','FAILED');
```

> Webhook 密钥必须加密存储（信封加密，KMS 管理 DEK），不能哈希，因为签名时需要还原明文。
---

## 7. 行级安全（RLS）

### 7.1 总则

- 所有含 `tenant_id` 的表启用 `ENABLE` + `FORCE ROW LEVEL SECURITY`。
- 策略只按 `tenant_id` 过滤，不做角色名判断。
- `app_current_tenant_id()` 返回 `NULL` 时，`tenant_id = NULL` 结果为 `NULL`，查询返回 0 行，写入被拒绝。
- `platform_control` 的跨租户能力通过“显式策略 + 目标租户上下文”实现；只有 `tenant`、`role`、`service_account`、`api_key`、`audit_log`、`outbox_event`、`idempotency_key` 允许访问 `tenant_id IS NULL` 的平台级行。
- `platform_audit_reader` 仅对 `audit_log` 有全量只读策略，且只有 `SELECT` 权限。

### 7.2 策略

```sql
-- tenant
ALTER TABLE core.tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tenant FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_tenant_core ON core.tenant
    FOR SELECT TO platform_core
    USING (id = core.app_current_tenant_id());
CREATE POLICY pol_tenant_control ON core.tenant
    FOR ALL TO platform_control
    USING (true) WITH CHECK (true);

-- tenant_membership
ALTER TABLE core.tenant_membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tenant_membership FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_tenant_membership_core ON core.tenant_membership
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_tenant_membership_control ON core.tenant_membership
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- tenant_config
ALTER TABLE core.tenant_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tenant_config FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_tenant_config_core ON core.tenant_config
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_tenant_config_control ON core.tenant_config
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- membership_invitation
ALTER TABLE core.membership_invitation ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.membership_invitation FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_membership_invitation_core ON core.membership_invitation
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_membership_invitation_control ON core.membership_invitation
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- organization
ALTER TABLE core.organization ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.organization FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_organization_core ON core.organization
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_organization_control ON core.organization
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- organization_closure
ALTER TABLE core.organization_closure ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.organization_closure FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_org_closure_core ON core.organization_closure
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_org_closure_control ON core.organization_closure
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- organization_approval
ALTER TABLE core.organization_approval ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.organization_approval FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_org_approval_core ON core.organization_approval
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_org_approval_control ON core.organization_approval
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- ownership_transfer
ALTER TABLE core.ownership_transfer ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.ownership_transfer FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_ownership_transfer_core ON core.ownership_transfer
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_ownership_transfer_control ON core.ownership_transfer
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- role：platform 角色 tenant_id 为 NULL，只有 control 可见
ALTER TABLE core.role ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.role FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_role_core ON core.role
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_role_control ON core.role
    FOR ALL TO platform_control
    USING (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id());

-- role_permission
ALTER TABLE core.role_permission ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.role_permission FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_role_permission_core ON core.role_permission
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_role_permission_control ON core.role_permission
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- tenant_role_assignment
ALTER TABLE core.tenant_role_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tenant_role_assignment FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_tenant_role_assignment_core ON core.tenant_role_assignment
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_tenant_role_assignment_control ON core.tenant_role_assignment
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- organization_membership
ALTER TABLE core.organization_membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.organization_membership FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_organization_membership_core ON core.organization_membership
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_organization_membership_control ON core.organization_membership
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- organization_role_assignment
ALTER TABLE core.organization_role_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.organization_role_assignment FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_organization_role_assignment_core ON core.organization_role_assignment
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_organization_role_assignment_control ON core.organization_role_assignment
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- service_account：tenant_id 为 NULL 表示平台级服务账号
ALTER TABLE core.service_account ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.service_account FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_service_account_core ON core.service_account
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_service_account_control ON core.service_account
    FOR ALL TO platform_control
    USING (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id());

-- api_key
ALTER TABLE core.api_key ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.api_key FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_api_key_core ON core.api_key
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_api_key_control ON core.api_key
    FOR ALL TO platform_control
    USING (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id());

-- outbox_event
ALTER TABLE core.outbox_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.outbox_event FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_outbox_event_core ON core.outbox_event
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_outbox_event_control ON core.outbox_event
    FOR ALL TO platform_control
    USING (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id());

-- idempotency_key
ALTER TABLE core.idempotency_key ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.idempotency_key FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_idempotency_key_core ON core.idempotency_key
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_idempotency_key_control ON core.idempotency_key
    FOR ALL TO platform_control
    USING (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id());

-- webhook_endpoint
ALTER TABLE core.webhook_endpoint ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.webhook_endpoint FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_webhook_endpoint_core ON core.webhook_endpoint
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_webhook_endpoint_control ON core.webhook_endpoint
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- webhook_delivery
ALTER TABLE core.webhook_delivery ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.webhook_delivery FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_webhook_delivery_core ON core.webhook_delivery
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_webhook_delivery_control ON core.webhook_delivery
    FOR ALL TO platform_control
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());

-- audit_log：auth 只能写平台级事件；core/control 读写本租户；audit_reader 全量只读
ALTER TABLE core.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_audit_log_auth_insert ON core.audit_log
    FOR INSERT TO platform_auth
    WITH CHECK (tenant_id IS NULL);
CREATE POLICY pol_audit_log_core ON core.audit_log
    FOR ALL TO platform_core
    USING (tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_audit_log_control ON core.audit_log
    FOR ALL TO platform_control
    USING (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id())
    WITH CHECK (tenant_id IS NULL OR tenant_id = core.app_current_tenant_id());
CREATE POLICY pol_audit_log_reader ON core.audit_log
    FOR SELECT TO platform_audit_reader
    USING (true);
```

### 7.3 RLS 覆盖检查

CI 必须执行以下查询，任何一行都表示策略缺失：

```sql
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'core'
  AND c.relkind = 'r'
  AND c.relrowsecurity = false
  AND c.relname IN (
    'tenant','tenant_membership','tenant_config','membership_invitation',
    'organization','organization_closure','organization_approval','ownership_transfer',
    'role','role_permission','tenant_role_assignment',
    'organization_membership','organization_role_assignment',
    'service_account','api_key','audit_log','outbox_event','idempotency_key',
    'webhook_endpoint','webhook_delivery'
  );
```

并检查所有 RLS 表均为 `relforcerowsecurity = true`。

### 7.4 平台级表

以下表不启用租户 RLS，依靠 schema、角色和表级授权保护：

`platform_user`、`user_session`、`one_time_token`、`login_attempt`、`permission`、`platform_role_permission`、`platform_role_grant`、`platform_role_grant_scope`、`extension_registry`、`platform_param`。

其中：

- `platform_role_grant*` 只允许 `platform_control` 访问；`platform_core` 通过受控函数读取当前用户的授权。
- `platform_user` 只允许 `platform_auth` 读写；其他角色通过视图读取目录信息。
- `platform_param` 只允许 `platform_control` 写；`platform_core` 通过公开视图读取。
---

## 8. 授权矩阵与最小权限

### 8.1 全局回收

迁移开始时先回收 `PUBLIC` 的默认权限，避免新表或新函数默认对所有人开放：

```sql
REVOKE ALL ON SCHEMA core FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA core FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA core FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE platform_migrator IN SCHEMA core
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE platform_migrator IN SCHEMA core
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE platform_migrator IN SCHEMA core
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;
```

原则：

1. 授权按“角色 × 表 × 操作”显式声明，禁止 `GRANT ... ON ALL TABLES`。
2. 迁移新增表、列、函数时，同一迁移内必须补充授权，否则 CI 授权检查失败。
3. 任何角色都不拥有 `TRUNCATE`；清理任务使用 `DELETE` 或分区 `DROP`。
4. 运行时角色对 `audit_log` 只有 `SELECT` / `INSERT`，没有 `UPDATE` / `DELETE` / `TRUNCATE`。

### 8.2 授权矩阵

图例：`S` = SELECT，`I` = INSERT，`U` = UPDATE，`D` = DELETE，`—` = 无权限。

| 表 | platform_auth | platform_core | platform_control | platform_audit_reader |
|---|---|---|---|---|
| `platform_user` | S, I, U* | —（通过视图 S） | S, U** | — |
| `user_session` | S, I, U*, D | — | S, U* | — |
| `one_time_token` | S, I, U*, D | — | — | — |
| `login_attempt` | S, I, D | — | — | — |
| `permission` | S | S | S, I, U | — |
| `role` | — | S, I, U | S, I, U | — |
| `platform_role_permission` | — | — | S, I, D | — |
| `platform_role_grant` | — | — | S, I, U | — |
| `platform_role_grant_scope` | — | — | S, I, D | — |
| `platform_param` | —（通过视图 S） | —（通过视图 S） | S, I, U, D | — |
| `extension_registry` | — | S | S, I, U | — |
| `tenant` | — | S | S, I, U | — |
| `tenant_membership` | — | S, I, U | S, I, U | — |
| `tenant_config` | — | S, I, U, D | S, I, U, D | — |
| `membership_invitation` | — | S, I, U* | S, I, U* | — |
| `organization` | — | S, I, U | S, I, U | — |
| `organization_closure` | — | S, I, D | S, I, D | — |
| `organization_approval` | — | S, I, U* | S, I, U* | — |
| `ownership_transfer` | — | S, I, U* | S, I, U* | — |
| `role_permission` | — | S, I, D | S, I, D | — |
| `tenant_role_assignment` | — | S, I, D | S, I, D | — |
| `organization_membership` | — | S, I, U | S, I, U | — |
| `organization_role_assignment` | — | S, I, D | S, I, D | — |
| `service_account` | — | S, I, U | S, I, U | — |
| `api_key` | — | S, I, U | S, I, U | — |
| `webhook_endpoint` | — | S, I, U | S, I, U | — |
| `webhook_delivery` | — | S, I, U | S, I, U | — |
| `outbox_event` | — | S, I, U | S, I, U, D | — |
| `idempotency_key` | — | S, I, U, D | S, I, U, D | — |
| `audit_log` | I | S, I | S, I | S |

\* 只允许更新指定列，见 §8.3。  
\*\* 平台运营只能更新用户状态与权限版本，不能改账号、密码、联系方式。

### 8.3 列级授权

敏感表禁止整表 `UPDATE`，使用列级授权：

```sql
-- 认证模块：可改资料、密码、状态、登录计数，不可改账号标识
GRANT SELECT, INSERT ON core.platform_user TO platform_auth;
GRANT UPDATE (
    display_name, email, phone, password_hash, status,
    email_verified_at, phone_verified_at, permission_version,
    failed_login_count, locked_until, last_login_at, updated_at
) ON core.platform_user TO platform_auth;

-- 平台运营：只能禁用/启用用户、递增权限版本
GRANT SELECT ON core.platform_user TO platform_control;
GRANT UPDATE (status, permission_version, updated_at)
    ON core.platform_user TO platform_control;

-- 会话：状态与撤销字段可改，token 哈希与 family 不可改
GRANT SELECT, INSERT, DELETE ON core.user_session TO platform_auth;
GRANT UPDATE (status, last_used_at, revoked_at, replaced_by)
    ON core.user_session TO platform_auth;
GRANT SELECT ON core.user_session TO platform_control;
GRANT UPDATE (status, last_used_at, revoked_at, replaced_by)
    ON core.user_session TO platform_control;

-- 一次性令牌：只允许标记已消费
GRANT SELECT, INSERT, DELETE ON core.one_time_token TO platform_auth;
GRANT UPDATE (consumed_at) ON core.one_time_token TO platform_auth;

-- 邀请：只允许更新状态与接受时间
GRANT SELECT, INSERT ON core.membership_invitation TO platform_core;
GRANT UPDATE (status, accepted_at, expires_at)
    ON core.membership_invitation TO platform_core;
GRANT SELECT, INSERT ON core.membership_invitation TO platform_control;
GRANT UPDATE (status, accepted_at, expires_at)
    ON core.membership_invitation TO platform_control;

-- 组织审批：只允许更新审批结果字段
GRANT SELECT, INSERT ON core.organization_approval TO platform_core, platform_control;
GRANT UPDATE (status, decision_by, decision_at, decision_reason, updated_at)
    ON core.organization_approval TO platform_core, platform_control;

-- 所有权转让：状态机字段可改，参与人不可改
GRANT SELECT, INSERT ON core.ownership_transfer TO platform_core, platform_control;
GRANT UPDATE (status, completed_at, updated_at)
    ON core.ownership_transfer TO platform_core, platform_control;

-- 租户：slug 不可变
GRANT SELECT ON core.tenant TO platform_core;
GRANT SELECT, INSERT ON core.tenant TO platform_control;
GRANT UPDATE (name, status, owner_user_id, permission_version, updated_at)
    ON core.tenant TO platform_control;

-- 成员：租户与用户不可改
GRANT SELECT, INSERT ON core.tenant_membership TO platform_core, platform_control;
GRANT UPDATE (status, is_owner, permission_version, joined_at, updated_at)
    ON core.tenant_membership TO platform_core, platform_control;

-- 组织：parent_id、org_type 不可改（一期不支持迁移）
GRANT SELECT, INSERT ON core.organization TO platform_core, platform_control;
GRANT UPDATE (name, status, visibility, owner_user_id, permission_version, updated_at)
    ON core.organization TO platform_core, platform_control;

-- 组织成员：成员关系与所属组织不可改
GRANT SELECT, INSERT ON core.organization_membership TO platform_core, platform_control;
GRANT UPDATE (status, is_owner, permission_version, joined_at, updated_at)
    ON core.organization_membership TO platform_core, platform_control;

-- 角色：作用域、编码、所有者标记不可改
GRANT SELECT, INSERT ON core.role TO platform_core, platform_control;
GRANT UPDATE (name, description, status, updated_at)
    ON core.role TO platform_core, platform_control;

-- 服务账号：client_id 不可改；secret 只允许写入新哈希
GRANT SELECT, INSERT ON core.service_account TO platform_core, platform_control;
GRANT UPDATE (name, client_secret_hash, status, scopes, expires_at, updated_at)
    ON core.service_account TO platform_core, platform_control;

-- API Key：key_hash / prefix 不可改
GRANT SELECT, INSERT ON core.api_key TO platform_core, platform_control;
GRANT UPDATE (status, last_used_at, expires_at, revoked_at)
    ON core.api_key TO platform_core, platform_control;

-- Webhook：密钥可轮换，事件与状态可改
GRANT SELECT, INSERT ON core.webhook_endpoint TO platform_core, platform_control;
GRANT UPDATE (url, secret_ciphertext, events, status, description, updated_at)
    ON core.webhook_endpoint TO platform_core, platform_control;

GRANT SELECT, INSERT ON core.webhook_delivery TO platform_core, platform_control;
GRANT UPDATE (status, attempts, next_attempt_at, response_status, last_error, delivered_at)
    ON core.webhook_delivery TO platform_core, platform_control;

-- Outbox / 幂等：只允许状态推进
GRANT SELECT, INSERT ON core.outbox_event TO platform_core;
GRANT UPDATE (status, attempts, available_at, last_error, dispatched_at)
    ON core.outbox_event TO platform_core;
GRANT SELECT, INSERT, DELETE ON core.outbox_event TO platform_control;
GRANT UPDATE (status, attempts, available_at, last_error, dispatched_at)
    ON core.outbox_event TO platform_control;

GRANT SELECT, INSERT, DELETE ON core.idempotency_key TO platform_core, platform_control;
GRANT UPDATE (status, response_status, response_body, completed_at)
    ON core.idempotency_key TO platform_core, platform_control;
```

### 8.4 其余整表授权

```sql
-- 认证
GRANT SELECT, INSERT, UPDATE, DELETE ON core.login_attempt TO platform_auth;
GRANT SELECT ON core.permission TO platform_auth;

-- 核心
GRANT SELECT ON core.permission TO platform_core;
GRANT SELECT ON core.extension_registry TO platform_core;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.tenant_config TO platform_core;
GRANT SELECT, INSERT, DELETE ON core.organization_closure TO platform_core;
GRANT SELECT, INSERT, DELETE ON core.role_permission TO platform_core;
GRANT SELECT, INSERT, DELETE ON core.tenant_role_assignment TO platform_core;
GRANT SELECT, INSERT, DELETE ON core.organization_role_assignment TO platform_core;

-- 平台控制
GRANT SELECT, INSERT, UPDATE ON core.permission TO platform_control;
GRANT SELECT, INSERT, UPDATE ON core.extension_registry TO platform_control;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.platform_param TO platform_control;
GRANT SELECT, INSERT, UPDATE ON core.platform_role_grant TO platform_control;
GRANT SELECT, INSERT, DELETE ON core.platform_role_grant_scope TO platform_control;
GRANT SELECT, INSERT, DELETE ON core.platform_role_permission TO platform_control;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.tenant_config TO platform_control;
GRANT SELECT, INSERT, DELETE ON core.organization_closure TO platform_control;
GRANT SELECT, INSERT, DELETE ON core.role_permission TO platform_control;
GRANT SELECT, INSERT, DELETE ON core.tenant_role_assignment TO platform_control;
GRANT SELECT, INSERT, DELETE ON core.organization_role_assignment TO platform_control;

-- 审计：只追加
GRANT SELECT, INSERT ON core.audit_log TO platform_auth, platform_core, platform_control;
GRANT SELECT ON core.audit_log TO platform_audit_reader;
REVOKE UPDATE, DELETE, TRUNCATE ON core.audit_log
    FROM platform_auth, platform_core, platform_control, platform_audit_reader;
```

### 8.5 授权验收查询

CI 与 pgTAP 必须验证：

```sql
-- 1. 运行时角色不得 BYPASSRLS
SELECT rolname
FROM pg_roles
WHERE rolname IN ('platform_auth','platform_core','platform_control','platform_audit_reader')
  AND rolbypassrls;

-- 2. PUBLIC 不得拥有 core 表权限
SELECT c.relname, p.privilege_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) p
WHERE n.nspname = 'core'
  AND p.grantee = 0;

-- 3. 审计表不得可更新/删除
SELECT r.rolname
FROM pg_roles r
WHERE r.rolname IN ('platform_auth','platform_core','platform_control','platform_audit_reader')
  AND (has_table_privilege(r.rolname, 'core.audit_log', 'UPDATE')
    OR has_table_privilege(r.rolname, 'core.audit_log', 'DELETE')
    OR has_table_privilege(r.rolname, 'core.audit_log', 'TRUNCATE'));

-- 4. 所有租户表必须 FORCE RLS
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'core'
  AND c.relkind = 'r'
  AND c.relrowsecurity
  AND NOT c.relforcerowsecurity;

-- 5. 运行时角色不得是表 owner
SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'core'
  AND pg_get_userbyid(c.relowner) <> 'platform_migrator';
```

---

## 9. 受控视图与函数

### 9.1 用户目录视图

`platform_core` 不能直接读取 `platform_user` 的账号、密码哈希、联系方式。需要展示成员姓名时使用目录视图：

```sql
CREATE VIEW core.v_platform_user_directory
WITH (security_barrier = true) AS
SELECT id, display_name, status, created_at
FROM core.platform_user;

REVOKE ALL ON core.v_platform_user_directory FROM PUBLIC;
GRANT SELECT ON core.v_platform_user_directory TO platform_core, platform_control;
```

视图由 `platform_migrator` 拥有，绕过基表授权，但只投影安全列。禁止在视图中加入 `email`、`phone`、`password_hash`。

### 9.2 公开平台参数视图

```sql
CREATE VIEW core.v_public_platform_param
WITH (security_barrier = true) AS
SELECT key, value, description
FROM core.platform_param
WHERE is_public;

REVOKE ALL ON core.v_public_platform_param FROM PUBLIC;
GRANT SELECT ON core.v_public_platform_param TO platform_auth, platform_core;
```

### 9.3 平台授权读取函数

`platform_core` 需要计算当前用户的平台权限，但不能直接读取授权表：

```sql
CREATE OR REPLACE FUNCTION core.fn_platform_permissions_for_user(p_user_id uuid)
RETURNS TABLE (
    permission_code     text,
    scope_type          text,
    tenant_id           uuid,
    organization_id     uuid,
    org_type            text,
    include_descendants boolean
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, core, pg_temp
AS $$
    SELECT rp.permission_code::text,
           s.scope_type::text,
           s.tenant_id,
           s.organization_id,
           s.org_type,
           s.include_descendants
    FROM core.platform_role_grant g
    JOIN core.platform_role_grant_scope s ON s.grant_id = g.id
    JOIN core.platform_role_permission rp ON rp.role_id = g.role_id
    WHERE g.user_id = p_user_id
      AND g.status = 'ACTIVE'
      AND (g.expires_at IS NULL OR g.expires_at > now())
      AND session_user IN ('platform_core', 'platform_control')
$$;

REVOKE ALL ON FUNCTION core.fn_platform_permissions_for_user(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core.fn_platform_permissions_for_user(uuid)
    TO platform_core, platform_control;
```

约束：

- 调用方必须传入“已认证主体”的用户 ID，不得使用请求参数中的任意 ID。
- 函数只读、`STABLE`，可被同事务内多次调用。
- 函数不缓存结果；应用层缓存键必须包含用户 `permission_version`。

### 9.4 组织子树函数

```sql
CREATE OR REPLACE FUNCTION core.fn_org_subtree(p_tenant_id uuid, p_organization_id uuid)
RETURNS TABLE (organization_id uuid, depth integer)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, core, pg_temp
AS $$
    SELECT c.descendant_id, c.depth
    FROM core.organization_closure c
    WHERE c.tenant_id = p_tenant_id
      AND c.ancestor_id = p_organization_id
      AND p_tenant_id = core.app_current_tenant_id()
$$;

REVOKE ALL ON FUNCTION core.fn_org_subtree(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core.fn_org_subtree(uuid, uuid)
    TO platform_core, platform_control;
```

### 9.5 审计分区维护函数

```sql
CREATE OR REPLACE FUNCTION core.fn_ensure_audit_partitions(p_months integer DEFAULT 3)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, core, pg_temp
AS $$
DECLARE
    v_month date;
    v_start timestamptz;
    v_end   timestamptz;
    v_name  text;
BEGIN
    IF p_months < 1 OR p_months > 12 THEN
        RAISE EXCEPTION 'p_months must be between 1 and 12';
    END IF;

    FOR i IN 0..p_months LOOP
        v_month := (date_trunc('month', now() AT TIME ZONE 'UTC')
                    + (i || ' month')::interval)::date;
        v_start := (v_month::timestamp AT TIME ZONE 'UTC');
        v_end   := ((v_month + interval '1 month')::timestamp AT TIME ZONE 'UTC');
        v_name  := format('audit_log_%s', to_char(v_month, 'YYYY_MM'));

        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS core.%I PARTITION OF core.audit_log
             FOR VALUES FROM (%L) TO (%L)',
            v_name, v_start, v_end
        );
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION core.fn_ensure_audit_partitions(integer) FROM PUBLIC;
-- 仅迁移 Job（platform_migrator）执行；不授予 API/Worker 角色
GRANT EXECUTE ON FUNCTION core.fn_ensure_audit_partitions(integer) TO platform_migrator;
```

### 9.6 触发器函数授权

```sql
GRANT EXECUTE ON FUNCTION core.fn_touch_updated_at()
    TO platform_auth, platform_core, platform_control;
```

> PostgreSQL 在创建触发器时校验触发器函数权限；仍在迁移中显式授权，避免 `FORCE RLS` 与触发器组合下的权限歧义。

---

## 10. 迁移策略

### 10.1 工具与目录

```text
db/
├── migrations/
│   ├── 0001_init.sql
│   └── 0002_xxx.sql
├── seeds/
│   └── core.sql
└── sqlc.yaml
```

- 迁移工具：`goose`。
- 迁移表：`public.goose_db_version`。
- 每个迁移包含 `-- +goose Up` / `-- +goose Down`。
- 生产禁止自动执行 `Down`；回滚通过 forward fix 或备份恢复。
- 种子数据单独执行，可重复运行（幂等）。

### 10.2 迁移执行约束

1. 只有 `platform_migrator` 可执行迁移，API/Worker 连接串不包含该角色。
2. 迁移 Job 启动时获取 `pg_advisory_lock(721001)`，防止并发迁移。
3. 默认单事务迁移；`CREATE INDEX CONCURRENTLY` 使用 `-- +goose NO TRANSACTION` 单独文件。
4. 迁移前设置 `lock_timeout = '5s'`、`statement_timeout = '60s'`；大表回填拆分为独立任务。
5. 所有 DDL 必须可重复执行（`IF NOT EXISTS` / `DROP ... IF EXISTS`）或在版本表中严格一次性执行。
6. 生产采用 expand/contract，不允许在同一发布中“加列 + 立即设为 NOT NULL + 删除旧列”。

### 10.3 expand / contract 步骤

| 阶段 | 操作 | 兼容性 |
|---|---|---|
| Expand | 加可空列、加新表、加索引（`CONCURRENTLY`） | 旧代码继续工作 |
| Backfill | 分批回填，每批 ≤ 5000 行，提交间隔 ≥ 100ms | 新旧代码共存 |
| Validate | `ALTER TABLE ... ADD CONSTRAINT ... NOT VALID` 后 `VALIDATE CONSTRAINT` | 减少锁 |
| Switch | 发布读写新结构的代码 | 双写或读旧回退 |
| Contract | 删除旧列/旧索引 | 至少一个发布周期后 |

### 10.4 分区维护

- `core.fn_ensure_audit_partitions(3)` 由迁移 Job 在每次发布前执行。
- Worker 每日检查默认分区是否出现数据；出现即告警。
- 归档：`ALTER TABLE core.audit_log DETACH PARTITION ...` → 导出 → `DROP TABLE`。
- 分区名格式固定 `audit_log_YYYY_MM`，便于自动化。

### 10.5 扩展迁移

- 扩展 schema 为 `ext_<module>`，由扩展自己的迁移器执行。
- 扩展迁移不得包含 `core.` 对象的 DDL。
- 扩展迁移记录在 `ext_<module>.goose_db_version`，版本同步写入 `core.extension_registry.manifest`。
- 扩展迁移失败不影响核心 schema；扩展保持 `REGISTERED` 或回退到上一版本。

### 10.6 回滚

- 代码回滚优先于数据库回滚。
- 数据修复使用补偿事务（新迁移），不使用 `Down`。
- 必须回滚时：停止写入 → 恢复快照/PITR → 校验迁移版本 → 启动旧版本。
- 每次生产迁移前必须完成一次同版本恢复演练。

---

## 11. 种子数据

### 11.1 平台角色

平台角色使用固定 UUID，保证多环境一致；`role.scope = 'PLATFORM'`，`tenant_id` / `organization_id` 为 `NULL`。

| 角色编码 | 名称 | 关键权限 |
|---|---|---|
| `platform_super_admin` | 平台超级管理员 | 全部 `platform.*`，含 `platform.cross_tenant.access` |
| `platform_operator` | 平台运营 | 租户创建/冻结、用户禁用/启用、扩展读取、服务账号读取、审计读取 |
| `platform_auditor` | 平台审计员 | `platform.audit.read`、`platform.tenant.read`、`platform.user.read`、`platform.role.read` |
| `platform_support` | 平台支持 | 租户/用户只读、撤销用户会话、审计读取 |

固定 ID 约定（仅种子使用，不参与业务生成）：

```text
platform_super_admin  01920000-0000-7000-8000-000000000001
platform_operator     01920000-0000-7000-8000-000000000002
platform_auditor      01920000-0000-7000-8000-000000000003
platform_support      01920000-0000-7000-8000-000000000004
```

### 11.2 租户与组织角色模板

租户创建时由应用复制模板生成租户角色；组织创建时生成组织角色。模板不在数据库中建表，定义在 `internal/core/authz/templates.go`，并由集成测试校验与文档一致。

| 模板编码 | 作用域 | 所有者角色 | 关键权限 |
|---|---|---|---|
| `tenant_owner` | TENANT | 是 | 全部 `tenant.*` 与 `organization.*` |
| `tenant_admin` | TENANT | 否 | 除 `tenant.transfer`、`tenant.organization.transfer`、`tenant.audit.export` 外的租户与组织管理权限 |
| `tenant_auditor` | TENANT | 否 | 只读 + `tenant.audit.read` / `tenant.audit.export` |
| `tenant_member` | TENANT | 否 | 基础只读 |
| `org_owner` | ORGANIZATION | 是 | 全部 `organization.*` |
| `org_admin` | ORGANIZATION | 否 | 除 `organization.transfer` 外的组织管理权限 |
| `org_member` | ORGANIZATION | 否 | `organization.read`、`organization.member.read`、`organization.role.read`、`organization.config.read` |

规则：

1. 每个租户恰好一个 `tenant_owner` 角色和一个 `is_owner=true` 的成员。
2. 每个组织恰好一个 `org_owner` 角色和一个 `is_owner=true` 的成员。
3. 所有者角色不允许删除、停用或改权限；只能通过所有权转让流程变更持有者。
4. 模板升级只影响新建租户/组织；存量角色通过显式迁移脚本升级。

### 11.3 平台参数默认值

```sql
INSERT INTO core.platform_param (key, value, is_public, description) VALUES
  ('auth.access_token_ttl_seconds',        '900'::jsonb,      false, 'Access Token TTL'),
  ('auth.refresh_token_ttl_seconds',       '2592000'::jsonb,  false, 'Refresh Token TTL'),
  ('auth.max_failed_logins',               '5'::jsonb,        false, '连续登录失败阈值'),
  ('auth.lock_duration_seconds',           '900'::jsonb,      false, '账号锁定时长'),
  ('auth.password_min_length',             '12'::jsonb,       true,  '密码最小长度'),
  ('session.max_per_user',                 '10'::jsonb,       false, '单用户最大活跃会话'),
  ('organization.max_depth',               '10'::jsonb,       true,  '组织树最大深度'),
  ('organization.require_approval',        'false'::jsonb,    true,  '组织创建是否需要审批'),
  ('audit.retention_days',                 '180'::jsonb,      false, '审计保留天数'),
  ('idempotency.ttl_seconds',              '86400'::jsonb,    false, '幂等键保留时间'),
  ('webhook.max_attempts',                 '10'::jsonb,       false, 'Webhook 最大投递次数'),
  ('webhook.timeout_seconds',              '10'::jsonb,       false, 'Webhook 单次超时'),
  ('ratelimit.login.per_ip_per_minute',    '20'::jsonb,       false, '登录 IP 限流'),
  ('ratelimit.login.per_account_per_minute','10'::jsonb,      false, '登录账号限流'),
  ('ratelimit.register.per_ip_per_hour',   '10'::jsonb,       false, '注册 IP 限流'),
  ('ratelimit.api_key.per_minute',         '600'::jsonb,      false, 'API Key 限流'),
  ('security.require_mfa_for_dangerous',   'false'::jsonb,    false, '高危操作是否要求 MFA（二期）')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    is_public = EXCLUDED.is_public,
    description = EXCLUDED.description,
    updated_at = now();
```

### 11.4 权限点种子

- 核心权限点在 `0001_init.sql` 或独立 `0002_seed_permissions.sql` 中插入，编码不可变。
- 扩展权限点由扩展启动注册，使用 `INSERT ... ON CONFLICT (code) DO UPDATE` 更新描述，不允许修改 `scope`。
- 权限点完整清单见 [`permission-model-v2.0.md`](permission-model-v2.0.md)。
- 角色权限绑定使用 `ON CONFLICT DO NOTHING`，避免覆盖运维手工调整。

### 11.5 种子执行顺序

```text
1. schema / tables / functions / RLS / grants     0001_init.sql
2. core permissions                                0002_seed_permissions.sql
3. platform roles + platform_role_permission       0003_seed_platform_roles.sql
4. platform params                                 0004_seed_platform_params.sql
```

种子脚本必须可重复执行；生产环境由迁移 Job 执行，不能由 API 启动时自动执行。

---

## 12. 索引、容量与维护

### 12.1 关键索引

| 表 | 索引 | 用途 |
|---|---|---|
| `platform_user` | `uq_platform_user_account` | 登录 |
| `user_session` | `uq_user_session_refresh_hash`、`idx_user_session_user` | 刷新、会话列表 |
| `tenant` | `uq_tenant_slug` | 租户标识解析 |
| `tenant_membership` | `uq_tenant_membership_user_active`、`idx_tenant_membership_user` | 成员唯一、用户租户列表 |
| `organization` | `idx_organization_tenant_parent`、`uq_organization_sibling_name` | 树查询、同级重名 |
| `organization_closure` | PK + `idx_org_closure_descendant` | 子树/祖先查询 |
| `role` | 三个部分唯一索引 | 角色编码唯一、所有者唯一 |
| `tenant_role_assignment` | `uq_tenant_role_assignment`、`idx_tenant_role_assignment_role` | 成员角色、角色反查 |
| `organization_role_assignment` | `uq_org_role_assignment` | 组织成员角色 |
| `permission` | `idx_permission_scope` | 按作用域加载权限 |
| `audit_log` | 三个分区索引 | 租户/操作者/目标查询 |
| `outbox_event` | `idx_outbox_pending` | Worker 拉取 |
| `idempotency_key` | `uq_idempotency_key` | 幂等重放 |
| `webhook_delivery` | `idx_webhook_delivery_pending` | 重试调度 |

### 12.2 容量预估（一期）

| 表 | 首年规模 | 增长 | 策略 |
|---|---|---|---|
| `platform_user` | 1,000,000 | 线性 | 常规索引 |
| `tenant` | 10,000 | 线性 | 常规索引 |
| `organization` | 1,000,000 | 线性 | 按租户分区可选（后期） |
| `tenant_membership` | 5,000,000 | 线性 | 按 `tenant_id` 索引 |
| `organization_membership` | 10,000,000 | 线性 | 按 `tenant_id` 索引 |
| `audit_log` | 500,000,000 | 高 | 月分区 + 归档 |
| `outbox_event` | 100,000,000 | 高 | 定期删除已投递 |
| `idempotency_key` | 50,000,000 | 高 | TTL 清理 |
| `login_attempt` | 100,000,000 | 高 | 90 天清理 |

### 12.3 清理任务

| 数据 | 保留 | 执行者 |
|---|---|---|
| 过期 `user_session` | 30 天 | `platform_auth` |
| 过期 `one_time_token` | 7 天 | `platform_auth` |
| `login_attempt` | 90 天 | `platform_auth` |
| 已完成 `idempotency_key` | TTL（默认 24h） | Worker（`platform_core`） |
| 已投递 `outbox_event` | 30 天 | Worker（`platform_core`） |
| 已投递 `webhook_delivery` | 30 天 | Worker（`platform_core`） |
| `audit_log` | 180 天（可配置） | 迁移 Job 归档 |

清理必须分批执行（每批 ≤ 5000 行），避免长事务与锁膨胀。

### 12.4 表参数

```sql
ALTER TABLE core.outbox_event SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE core.idempotency_key SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE core.audit_log SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);
```

---

## 13. 备份、归档与恢复

- 生产使用 PostgreSQL 基础备份 + WAL 归档，支持 PITR；RPO ≤ 15 分钟。
- 每日逻辑备份仅用于单表恢复与开发环境，不作为生产恢复主路径。
- 审计归档使用 `DETACH PARTITION` 后导出 Parquet/JSONL 到对象存储，再 `DROP`。
- 恢复演练每季度一次，验证：迁移版本、角色、RLS、审计追加约束。
- 恢复后必须执行 §8.5 授权验收与 §7.3 RLS 覆盖检查。
- 备份文件加密；密钥与数据库凭证分离管理。

---

## 14. 已知权衡

| 决策 | 收益 | 代价 | 缓解 |
|---|---|---|---|
| 共享库 + `tenant_id` + RLS | 运维简单、成本低 | 策略遗漏即泄露 | 强制 RLS、pgTAP 矩阵、CI 检查 |
| 5 个固定数据库角色 | 边界清晰、易审计 | 模块间权限粒度有限 | 列级授权、受控视图/函数 |
| UUIDv7 主键 | 全局唯一、时间有序 | 索引比 bigint 大 | 控制面数据量可控；必要时内部 bigint |
| 闭包表 | 子树查询快 | 写入放大 | 单事务维护、批量插入 |
| 审计月分区 | 归档/清理容易 | 分区维护复杂 | 自动建分区 + 默认分区告警 |
| 平台表不做 RLS | 平台查询简单 | 依赖角色/授权 | 仅 `platform_control` 可写，视图收敛 |
| `is_owner` 冗余字段 | 查询快、约束直观 | 三处状态需一致 | 转让事务统一维护 + 约束/测试 |
| `permission` 全局表 | 权限元数据统一 | 租户表跨 schema 引用平台表 | 只允许只读引用，不允许租户修改 |
| `service_account.scopes` 数组 | 灵活 | 无法外键约束 | 应用校验 + 定期一致性任务 |
| Webhook 密钥可逆加密 | 签名需要明文 | 密钥管理复杂 | KMS 信封加密、权限隔离、轮换 |

---

## 15. 交付检查清单

数据库设计进入实现前必须满足：

- [ ] `0001_init.sql` 可在空库一次执行成功，`Down` 可回滚开发库。
- [ ] 所有租户表 `ENABLE` + `FORCE ROW LEVEL SECURITY`。
- [ ] 所有运行时角色 `NOBYPASSRLS`，仅 `platform_migrator` 例外且不用于运行时。
- [ ] §8.5 五条授权/RLS 检查返回 0 行。
- [ ] 组织父子跨租户、成员跨租户、角色跨作用域均被数据库约束拒绝。
- [ ] 审计表对应用角色不可 `UPDATE` / `DELETE` / `TRUNCATE`。
- [ ] 未设置 `app.tenant_id` 时，所有租户表查询返回 0 行。
- [ ] 连接池复用测试：租户 A 事务结束后，租户 B 不残留上下文。
- [ ] `sqlc` 能对全部查询生成类型安全代码。
- [ ] 种子数据可重复执行，平台角色/参数与文档一致。
- [ ] 审计分区自动创建与归档演练通过。
- [ ] 备份恢复演练通过，恢复后 RLS/授权检查通过。

---

## 16. 相关文档

- [总体架构 V2.0](../00-architecture/architecture-v2.0.md)
- [架构决策 V2.0](../00-architecture/decisions-v2.0.md)
- [扩展 SPI V2.0](../00-architecture/extension-spi-v2.0.md)
- [需求规格 V2.0](../10-requirements/requirements-v2.0.md)
- [技术设计 V2.0](tech-design-v2.0.md)
- [权限模型 V2.0](permission-model-v2.0.md)
- [状态机 V2.0](state-machines-v2.0.md)
- [OpenAPI V2.0](../30-api/openapi-v2.0.yaml)
- [运维与测试 V2.0](../40-operations/operations-v2.0.md)
