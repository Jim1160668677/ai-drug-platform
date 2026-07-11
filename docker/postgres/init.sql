-- 精准药物设计系统 数据库初始化
-- TimescaleDB 扩展已内置于 timescale/timescaledb 镜像

-- 启用必要的扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 临床时间线数据表（TimescaleDB hypertable）
CREATE TABLE IF NOT EXISTS clinical_timeline (
    time        TIMESTAMPTZ NOT NULL,
    patient_id  UUID NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    unit        TEXT,
    source      TEXT,
    PRIMARY KEY (patient_id, time, metric_name)
);

-- 将临床时间线表转为 hypertable（按时间分区）
SELECT create_hypertable('clinical_timeline', 'time', if_not_exists => TRUE);

-- 疗效监测时序数据表
CREATE TABLE IF NOT EXISTS efficacy_timeseries (
    time           TIMESTAMPTZ NOT NULL,
    project_id     UUID NOT NULL,
    treatment_id   UUID,
    tumor_burden   DOUBLE PRECISION,
    ctdna_level    DOUBLE PRECISION,
    immune_status  JSONB,
    PRIMARY KEY (project_id, time)
);

SELECT create_hypertable('efficacy_timeseries', 'time', if_not_exists => TRUE);

-- 审计日志（append-only，禁止更新删除）
CREATE TABLE IF NOT EXISTS audit_log_append (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    entity     TEXT,
    entity_id  TEXT,
    before_val JSONB,
    after_val  JSONB
);

-- 禁止更新和删除审计日志
CREATE OR REPLACE FUNCTION prevent_audit_modify()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log is append-only. Modification not allowed.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_no_update ON audit_log_append;
DROP TRIGGER IF EXISTS audit_no_delete ON audit_log_append;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log_append
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modify();
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log_append
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modify();

-- 完成提示
DO $$ BEGIN
    RAISE NOTICE 'Database initialized: TimescaleDB + audit log ready.';
END $$;
