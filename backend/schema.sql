-- Eloana Velluto — Schema PostgreSQL
-- Execute no Railway: railway run psql < backend/schema.sql

CREATE TABLE IF NOT EXISTS produtos (
    id            TEXT        PRIMARY KEY,
    nome          TEXT        NOT NULL,
    preco         NUMERIC(10,2) NOT NULL,
    cor           TEXT,
    variacao_tipo TEXT        NOT NULL DEFAULT 'tamanho',
    tamanhos      JSONB       NOT NULL DEFAULT '{}',
    foto          TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vendas (
    id             TEXT          PRIMARY KEY,
    produto_id     TEXT,
    produto_nome   TEXT,
    tamanho        TEXT,
    quantidade     INTEGER       NOT NULL,
    valor_unitario NUMERIC(10,2) NOT NULL,
    valor_total    NUMERIC(10,2) NOT NULL,
    pagamento      TEXT,
    num_parcelas   INTEGER       DEFAULT 1,
    nome_cliente   TEXT,
    cliente_id     TEXT,
    data           DATE          NOT NULL,
    created_at     TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendas_data ON vendas (data);

CREATE TABLE IF NOT EXISTS lancamentos (
    id               TEXT          PRIMARY KEY,
    tipo             TEXT          NOT NULL CHECK (tipo IN ('entrada', 'saida')),
    descricao        TEXT          NOT NULL,
    valor            NUMERIC(10,2) NOT NULL,
    data             DATE          NOT NULL,
    categoria        TEXT,
    status           TEXT          DEFAULT 'recebido',
    origem           TEXT,
    referencia_id    TEXT,
    marcado_recebido BOOLEAN       DEFAULT FALSE,
    created_at       TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lancamentos_data ON lancamentos (data);

CREATE TABLE IF NOT EXISTS movimentacoes (
    id           TEXT        PRIMARY KEY,
    produto_id   TEXT,
    produto_nome TEXT,
    cor          TEXT,
    tamanho      TEXT,
    tipo         TEXT        NOT NULL,
    quantidade   INTEGER     NOT NULL,
    motivo       TEXT,
    data_hora    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dividas (
    id         TEXT          PRIMARY KEY,
    nome       TEXT          NOT NULL,
    tipo       TEXT          NOT NULL,
    valor_total NUMERIC(10,2) NOT NULL,
    parcelado  BOOLEAN       DEFAULT FALSE,
    created_at TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS parcelas (
    id            TEXT          PRIMARY KEY,
    divida_id     TEXT          NOT NULL REFERENCES dividas(id) ON DELETE CASCADE,
    numero        INTEGER       NOT NULL,
    valor         NUMERIC(10,2) NOT NULL,
    vencimento    DATE          NOT NULL,
    pago          BOOLEAN       DEFAULT FALSE,
    data_pagamento DATE,
    lancamento_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_parcelas_divida ON parcelas (divida_id);
