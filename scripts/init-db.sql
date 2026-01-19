-- MoA_MEL - Database Initialization
-- ===================================
-- Script d'initialisation PostgreSQL avec pgvector

-- Activer l'extension pgvector pour les embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Table des audits
CREATE TABLE IF NOT EXISTS audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id VARCHAR(50) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    mel_document VARCHAR(255),
    mmel_document VARCHAR(255),
    aircraft_type VARCHAR(50),
    aircraft_msn INTEGER,
    operation_type VARCHAR(20),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des items MEL parsés
CREATE TABLE IF NOT EXISTS mel_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID REFERENCES audits(id) ON DELETE CASCADE,
    ata_chapter VARCHAR(10),
    ata_section VARCHAR(10),
    item_base VARCHAR(20) NOT NULL,
    variant_suffix VARCHAR(5),
    item_description TEXT,
    category CHAR(1) CHECK (category IN ('A', 'B', 'C', 'D')),
    number_installed VARCHAR(20),
    number_required VARCHAR(20),
    rectification_interval VARCHAR(50),
    remarks_raw TEXT,
    source_page INTEGER,
    extraction_confidence FLOAT,
    needs_hitl BOOLEAN DEFAULT FALSE,
    embedding vector(1024),  -- Pour Mistral embeddings
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des items MMEL parsés
CREATE TABLE IF NOT EXISTS mmel_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID REFERENCES audits(id) ON DELETE CASCADE,
    ata_chapter VARCHAR(10),
    ata_section VARCHAR(10),
    item_base VARCHAR(20) NOT NULL,
    variant_suffix VARCHAR(5),
    item_description TEXT,
    category CHAR(1) CHECK (category IN ('A', 'B', 'C', 'D')),
    number_installed VARCHAR(20),
    number_required VARCHAR(20),
    rectification_interval VARCHAR(50),
    remarks_raw TEXT,
    source_page INTEGER,
    extraction_confidence FLOAT,
    embedding vector(1024),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des résultats de comparaison
CREATE TABLE IF NOT EXISTS comparison_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID REFERENCES audits(id) ON DELETE CASCADE,
    mel_item_id UUID REFERENCES mel_items(id),
    mmel_item_id UUID REFERENCES mmel_items(id),
    verdict VARCHAR(30) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    deviation_details JSONB,
    hitl_required BOOLEAN DEFAULT FALSE,
    hitl_status VARCHAR(20),
    hitl_validated_by VARCHAR(100),
    hitl_validated_at TIMESTAMP,
    hitl_comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des logs HITL
CREATE TABLE IF NOT EXISTS hitl_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comparison_id UUID REFERENCES comparison_results(id) ON DELETE CASCADE,
    action VARCHAR(30) NOT NULL,
    decision VARCHAR(20),
    validated_by VARCHAR(100),
    comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index pour performances
CREATE INDEX IF NOT EXISTS idx_mel_items_audit ON mel_items(audit_id);
CREATE INDEX IF NOT EXISTS idx_mel_items_item_base ON mel_items(item_base);
CREATE INDEX IF NOT EXISTS idx_mmel_items_audit ON mmel_items(audit_id);
CREATE INDEX IF NOT EXISTS idx_mmel_items_item_base ON mmel_items(item_base);
CREATE INDEX IF NOT EXISTS idx_comparison_audit ON comparison_results(audit_id);
CREATE INDEX IF NOT EXISTS idx_comparison_verdict ON comparison_results(verdict);
CREATE INDEX IF NOT EXISTS idx_comparison_hitl ON comparison_results(hitl_required) WHERE hitl_required = TRUE;

-- Index vectoriel pour recherche sémantique (IVFFlat)
CREATE INDEX IF NOT EXISTS idx_mel_embedding ON mel_items
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_mmel_embedding ON mmel_items
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Vue pour dashboard
CREATE OR REPLACE VIEW audit_summary AS
SELECT
    a.id,
    a.job_id,
    a.status,
    a.mel_document,
    a.mmel_document,
    a.aircraft_type,
    a.started_at,
    a.completed_at,
    COUNT(cr.id) AS total_comparisons,
    COUNT(CASE WHEN cr.verdict = 'COMPLIANT' THEN 1 END) AS compliant_count,
    COUNT(CASE WHEN cr.verdict = 'LESS_RESTRICTIVE' THEN 1 END) AS less_restrictive_count,
    COUNT(CASE WHEN cr.verdict = 'MORE_RESTRICTIVE' THEN 1 END) AS more_restrictive_count,
    COUNT(CASE WHEN cr.hitl_required THEN 1 END) AS hitl_pending
FROM audits a
LEFT JOIN comparison_results cr ON a.id = cr.audit_id
GROUP BY a.id;

-- Fonction pour calculer la compliance rate
CREATE OR REPLACE FUNCTION calculate_compliance_rate(audit_uuid UUID)
RETURNS FLOAT AS $$
DECLARE
    total INTEGER;
    compliant INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(CASE WHEN verdict IN ('COMPLIANT', 'MORE_RESTRICTIVE') THEN 1 END)
    INTO total, compliant
    FROM comparison_results
    WHERE audit_id = audit_uuid;

    IF total = 0 THEN
        RETURN 100.0;
    END IF;

    RETURN ROUND((compliant::FLOAT / total::FLOAT) * 100, 2);
END;
$$ LANGUAGE plpgsql;

-- Message de confirmation
DO $$
BEGIN
    RAISE NOTICE 'MoA_MEL database initialized successfully!';
END $$;
