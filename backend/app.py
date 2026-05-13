import os
import json
import logging
import bcrypt
import psycopg2
import psycopg2.extras
from datetime import timedelta, datetime
from flask import Flask, request, jsonify, g
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── CONFIGURAÇÃO ───────────────────────────────────────────────────────────────
app.config['JWT_SECRET_KEY'] = os.environ['JWT_SECRET_KEY']
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12MB (foto base64)

ENV = os.environ.get('FLASK_ENV', 'development')
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', 'http://localhost')

CORS(app, origins=[ALLOWED_ORIGIN, 'http://localhost', 'http://127.0.0.1'],
     supports_credentials=True)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=['300 per day', '60 per hour'],
    storage_uri='memory://'
)

jwt = JWTManager(app)

# Controle de tentativas de login (por IP)
_login_attempts: dict = {}


# ── BANCO DE DADOS ─────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        db_url = os.environ['DATABASE_URL']
        ssl = 'require' if ENV == 'production' else 'prefer'
        g.db = psycopg2.connect(
            db_url,
            sslmode=ssl,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    return g.db


@app.teardown_appcontext
def close_db(_=None):
    db = g.pop('db', None)
    if db:
        db.close()


# ── SEGURANÇA: HEADERS ─────────────────────────────────────────────────────────
@app.after_request
def security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if ENV == 'production':
        response.headers['Strict-Transport-Security'] = (
            'max-age=31536000; includeSubDomains'
        )
    return response


# ── ERROS GENÉRICOS (sem stack trace) ─────────────────────────────────────────
@app.errorhandler(404)
def not_found(_):
    return jsonify({'mensagem': 'Recurso não encontrado'}), 404


@app.errorhandler(405)
def method_not_allowed(_):
    return jsonify({'mensagem': 'Método não permitido'}), 405


@app.errorhandler(413)
def too_large(_):
    return jsonify({'mensagem': 'Requisição muito grande'}), 413


@app.errorhandler(429)
def too_many(_):
    return jsonify({'mensagem': 'Muitas requisições. Tente mais tarde.'}), 429


@app.errorhandler(500)
def internal_error(e):
    logger.error('Internal error: %s', type(e).__name__)
    return jsonify({'mensagem': 'Erro interno do servidor'}), 500


# ── HELPERS DE VALIDAÇÃO ───────────────────────────────────────────────────────
def _str(value, max_len=255, required=False, field='campo'):
    if value is None or value == '':
        if required:
            raise ValueError(f'{field} é obrigatório')
        return None
    s = str(value).strip()
    if len(s) > max_len:
        raise ValueError(f'{field}: máximo {max_len} caracteres')
    return s


def _float(value, field='valor'):
    try:
        f = float(value)
        if f <= 0:
            raise ValueError()
        return round(f, 2)
    except (TypeError, ValueError):
        raise ValueError(f'{field} inválido')


def _int(value, field='campo', min_val=1):
    try:
        i = int(value)
        if i < min_val:
            raise ValueError()
        return i
    except (TypeError, ValueError):
        raise ValueError(f'{field} inválido')


def _json_body():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        raise ValueError('Corpo da requisição inválido')
    return data


# ── SERIALIZAÇÃO camelCase → snake_case ────────────────────────────────────────
def _prod_to_api(row):
    return {
        'id': row['id'],
        'nome': row['nome'],
        'preco': float(row['preco']),
        'cor': row['cor'],
        'variacaoTipo': row['variacao_tipo'],
        'tamanhos': row['tamanhos'] if isinstance(row['tamanhos'], dict) else json.loads(row['tamanhos']),
        'foto': row['foto'],
        'createdAt': row['created_at'].isoformat() if row.get('created_at') else None,
    }


def _venda_to_api(row):
    return {
        'id': row['id'],
        'produtoId': row['produto_id'],
        'produtoNome': row['produto_nome'],
        'tamanho': row['tamanho'],
        'quantidade': row['quantidade'],
        'valorUnitario': float(row['valor_unitario']),
        'valorTotal': float(row['valor_total']),
        'pagamento': row['pagamento'],
        'numParcelas': row['num_parcelas'],
        'nomeCliente': row['nome_cliente'],
        'clienteId': row['cliente_id'],
        'data': str(row['data']),
        'createdAt': row['created_at'].isoformat() if row.get('created_at') else None,
    }


def _lanc_to_api(row):
    return {
        'id': row['id'],
        'tipo': row['tipo'],
        'descricao': row['descricao'],
        'valor': float(row['valor']),
        'data': str(row['data']),
        'categoria': row['categoria'],
        'status': row['status'],
        'origem': row['origem'],
        'referenciaId': row['referencia_id'],
        'marcadoRecebido': bool(row['marcado_recebido']),
        'createdAt': row['created_at'].isoformat() if row.get('created_at') else None,
    }


def _div_to_api(row, parcelas):
    return {
        'id': row['id'],
        'nome': row['nome'],
        'tipo': row['tipo'],
        'valorTotal': float(row['valor_total']),
        'parcelado': bool(row['parcelado']),
        'createdAt': row['created_at'].isoformat() if row.get('created_at') else None,
        'parcelas': [_parc_to_api(p) for p in parcelas],
    }


def _parc_to_api(row):
    return {
        'id': row['id'],
        'numero': row['numero'],
        'valor': float(row['valor']),
        'vencimento': str(row['vencimento']),
        'pago': bool(row['pago']),
        'dataPagamento': str(row['data_pagamento']) if row.get('data_pagamento') else None,
        'lancamentoId': row.get('lancamento_id'),
    }


def _mov_to_api(row):
    return {
        'id': row['id'],
        'produtoId': row['produto_id'],
        'produtoNome': row['produto_nome'],
        'cor': row['cor'],
        'tamanho': row['tamanho'],
        'tipo': row['tipo'],
        'quantidade': row['quantidade'],
        'motivo': row['motivo'],
        'dataHora': row['data_hora'].isoformat() if row.get('data_hora') else None,
    }


# ── SAÚDE ──────────────────────────────────────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


# ── AUTH ───────────────────────────────────────────────────────────────────────
@app.route('/api/auth/login', methods=['POST'])
@limiter.limit('10 per minute')
def login():
    ip = get_remote_address()
    entry = _login_attempts.get(ip, {'count': 0, 'locked_until': None})

    if entry['locked_until'] and datetime.utcnow() < entry['locked_until']:
        mins = max(1, int((entry['locked_until'] - datetime.utcnow()).total_seconds() / 60))
        return jsonify({'mensagem': f'IP bloqueado. Tente em {mins} min.'}), 429

    try:
        data = _json_body()
        usuario = _str(data.get('usuario'), 80, required=True, field='usuario')
        senha = str(data.get('senha', ''))
        if not senha:
            raise ValueError('senha é obrigatória')
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    admin_user = os.environ.get('ADMIN_USER', '')
    admin_hash = os.environ.get('ADMIN_PASSWORD_HASH', '').encode()

    ok = (
        usuario == admin_user
        and bool(admin_hash)
        and bcrypt.checkpw(senha.encode(), admin_hash)
    )

    if not ok:
        count = entry['count'] + 1
        locked = None
        if count >= 5:
            locked = datetime.utcnow() + timedelta(minutes=15)
            count = 0
        _login_attempts[ip] = {'count': count, 'locked_until': locked}
        logger.warning('Login falhou: ip=%s', ip)
        return jsonify({'mensagem': 'Usuário ou senha incorretos'}), 401

    _login_attempts.pop(ip, None)
    logger.info('Login bem-sucedido: ip=%s', ip)
    return jsonify({
        'access_token': create_access_token(identity=usuario),
        'refresh_token': create_refresh_token(identity=usuario),
    }), 200


@app.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh_token():
    identity = get_jwt_identity()
    return jsonify({'access_token': create_access_token(identity=identity)}), 200


@app.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    return jsonify({'mensagem': 'Logout realizado'}), 200


# ── PRODUTOS ───────────────────────────────────────────────────────────────────
@app.route('/api/produtos', methods=['GET'])
@jwt_required()
@limiter.limit('120 per minute')
def get_produtos():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM produtos ORDER BY created_at')
    rows = cur.fetchall()
    cur.close()
    return jsonify([_prod_to_api(r) for r in rows])


@app.route('/api/produtos', methods=['POST'])
@jwt_required()
@limiter.limit('60 per minute')
def upsert_produto():
    try:
        data = _json_body()
        pid = _str(data.get('id'), 36, required=True, field='id')
        nome = _str(data.get('nome'), 80, required=True, field='nome')
        preco = _float(data.get('preco'), 'preco')
        cor = _str(data.get('cor'), 50)
        vt = _str(data.get('variacaoTipo', 'tamanho'), 20)
        tamanhos = data.get('tamanhos', {})
        foto = data.get('foto')
        created_at = _str(data.get('createdAt'), 36)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    if not isinstance(tamanhos, dict):
        return jsonify({'mensagem': 'tamanhos inválidos'}), 400

    tamanhos_json = json.dumps(tamanhos)
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''INSERT INTO produtos (id, nome, preco, cor, variacao_tipo, tamanhos, foto, created_at)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
               ON CONFLICT (id) DO UPDATE
               SET nome=%s, preco=%s, cor=%s, variacao_tipo=%s, tamanhos=%s::jsonb, foto=%s''',
            (pid, nome, preco, cor, vt, tamanhos_json, foto, created_at,
             nome, preco, cor, vt, tamanhos_json, foto)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok', 'id': pid}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao salvar produto id=%s', pid)
        return jsonify({'mensagem': 'Erro ao salvar produto'}), 500


@app.route('/api/produtos/<pid>', methods=['PUT'])
@jwt_required()
@limiter.limit('60 per minute')
def update_produto(pid):
    try:
        data = _json_body()
        nome = _str(data.get('nome'), 80, required=True, field='nome')
        preco = _float(data.get('preco'), 'preco')
        cor = _str(data.get('cor'), 50)
        vt = _str(data.get('variacaoTipo', 'tamanho'), 20)
        tamanhos = data.get('tamanhos', {})
        foto = data.get('foto')
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    tamanhos_json = json.dumps(tamanhos)
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''UPDATE produtos SET nome=%s, preco=%s, cor=%s, variacao_tipo=%s,
               tamanhos=%s::jsonb, foto=%s WHERE id=%s''',
            (nome, preco, cor, vt, tamanhos_json, foto, pid)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok'}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao atualizar produto id=%s', pid)
        return jsonify({'mensagem': 'Erro ao atualizar produto'}), 500


@app.route('/api/produtos/<pid>', methods=['DELETE'])
@jwt_required()
@limiter.limit('30 per minute')
def delete_produto(pid):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute('DELETE FROM produtos WHERE id=%s', (pid,))
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok'}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao excluir produto id=%s', pid)
        return jsonify({'mensagem': 'Erro ao excluir produto'}), 500


# ── VENDAS ─────────────────────────────────────────────────────────────────────
@app.route('/api/vendas', methods=['GET'])
@jwt_required()
@limiter.limit('120 per minute')
def get_vendas():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM vendas ORDER BY created_at')
    rows = cur.fetchall()
    cur.close()
    return jsonify([_venda_to_api(r) for r in rows])


@app.route('/api/vendas', methods=['POST'])
@jwt_required()
@limiter.limit('60 per minute')
def upsert_venda():
    try:
        data = _json_body()
        vid = _str(data.get('id'), 36, required=True, field='id')
        produto_id = _str(data.get('produtoId'), 36)
        produto_nome = _str(data.get('produtoNome'), 120)
        tamanho = _str(data.get('tamanho'), 20)
        quantidade = _int(data.get('quantidade'), 'quantidade', 1)
        valor_unitario = _float(data.get('valorUnitario'), 'valorUnitario')
        valor_total = _float(data.get('valorTotal'), 'valorTotal')
        pagamento = _str(data.get('pagamento'), 20)
        num_parcelas = int(data.get('numParcelas', 1) or 1)
        nome_cliente = _str(data.get('nomeCliente'), 80)
        cliente_id = _str(data.get('clienteId'), 36)
        data_venda = _str(data.get('data'), 10, required=True, field='data')
        created_at = _str(data.get('createdAt'), 36)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''INSERT INTO vendas
               (id, produto_id, produto_nome, tamanho, quantidade,
                valor_unitario, valor_total, pagamento, num_parcelas,
                nome_cliente, cliente_id, data, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE
               SET produto_id=%s, produto_nome=%s, tamanho=%s, quantidade=%s,
                   valor_unitario=%s, valor_total=%s, pagamento=%s,
                   num_parcelas=%s, nome_cliente=%s, cliente_id=%s, data=%s''',
            (vid, produto_id, produto_nome, tamanho, quantidade,
             valor_unitario, valor_total, pagamento, num_parcelas,
             nome_cliente, cliente_id, data_venda, created_at,
             produto_id, produto_nome, tamanho, quantidade,
             valor_unitario, valor_total, pagamento,
             num_parcelas, nome_cliente, cliente_id, data_venda)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok', 'id': vid}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao salvar venda id=%s', vid)
        return jsonify({'mensagem': 'Erro ao salvar venda'}), 500


# ── LANÇAMENTOS ────────────────────────────────────────────────────────────────
@app.route('/api/lancamentos', methods=['GET'])
@jwt_required()
@limiter.limit('120 per minute')
def get_lancamentos():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM lancamentos ORDER BY data DESC, created_at DESC')
    rows = cur.fetchall()
    cur.close()
    return jsonify([_lanc_to_api(r) for r in rows])


@app.route('/api/lancamentos', methods=['POST'])
@jwt_required()
@limiter.limit('60 per minute')
def upsert_lancamento():
    try:
        data = _json_body()
        lid = _str(data.get('id'), 36, required=True, field='id')
        tipo = _str(data.get('tipo'), 10, required=True, field='tipo')
        if tipo not in ('entrada', 'saida'):
            raise ValueError('tipo deve ser entrada ou saida')
        descricao = _str(data.get('descricao'), 200, required=True, field='descricao')
        valor = _float(data.get('valor'), 'valor')
        data_lanc = _str(data.get('data'), 10, required=True, field='data')
        categoria = _str(data.get('categoria'), 40)
        status = _str(data.get('status', 'recebido'), 20)
        origem = _str(data.get('origem'), 20)
        ref_id = _str(data.get('referenciaId'), 36)
        marcado = bool(data.get('marcadoRecebido', False))
        created_at = _str(data.get('createdAt'), 36)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''INSERT INTO lancamentos
               (id, tipo, descricao, valor, data, categoria, status,
                origem, referencia_id, marcado_recebido, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE
               SET tipo=%s, descricao=%s, valor=%s, data=%s, categoria=%s,
                   status=%s, origem=%s, referencia_id=%s, marcado_recebido=%s''',
            (lid, tipo, descricao, valor, data_lanc, categoria, status,
             origem, ref_id, marcado, created_at,
             tipo, descricao, valor, data_lanc, categoria,
             status, origem, ref_id, marcado)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok', 'id': lid}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao salvar lancamento id=%s', lid)
        return jsonify({'mensagem': 'Erro ao salvar lançamento'}), 500


# ── DÍVIDAS ────────────────────────────────────────────────────────────────────
@app.route('/api/dividas', methods=['GET'])
@jwt_required()
@limiter.limit('120 per minute')
def get_dividas():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM dividas ORDER BY created_at')
    dividas = cur.fetchall()
    cur.execute('SELECT * FROM parcelas ORDER BY divida_id, numero')
    parcelas = cur.fetchall()
    cur.close()

    parcelas_map: dict = {}
    for p in parcelas:
        parcelas_map.setdefault(p['divida_id'], []).append(p)

    result = [_div_to_api(d, parcelas_map.get(d['id'], [])) for d in dividas]
    return jsonify(result)


@app.route('/api/dividas', methods=['POST'])
@jwt_required()
@limiter.limit('30 per minute')
def upsert_divida():
    try:
        data = _json_body()
        did = _str(data.get('id'), 36, required=True, field='id')
        nome = _str(data.get('nome'), 80, required=True, field='nome')
        tipo = _str(data.get('tipo'), 40, required=True, field='tipo')
        valor_total = _float(data.get('valorTotal'), 'valorTotal')
        parcelado = bool(data.get('parcelado', False))
        created_at = _str(data.get('createdAt'), 36)
        parcelas = data.get('parcelas', [])
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    if not isinstance(parcelas, list):
        return jsonify({'mensagem': 'parcelas inválidas'}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''INSERT INTO dividas (id, nome, tipo, valor_total, parcelado, created_at)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE
               SET nome=%s, tipo=%s, valor_total=%s, parcelado=%s''',
            (did, nome, tipo, valor_total, parcelado, created_at,
             nome, tipo, valor_total, parcelado)
        )

        # Upsert parcelas: mantém parcelas pagas, substitui não pagas
        cur.execute('SELECT id FROM parcelas WHERE divida_id=%s AND pago=TRUE', (did,))
        pagas_ids = {r['id'] for r in cur.fetchall()}

        # Remove parcelas não pagas antigas
        cur.execute('DELETE FROM parcelas WHERE divida_id=%s AND pago=FALSE', (did,))

        for p in parcelas:
            pid = _str(p.get('id'), 36, required=True, field='parcela.id')
            if pid in pagas_ids:
                continue  # não toca em parcelas já pagas
            numero = _int(p.get('numero'), 'numero', 1)
            valor = _float(p.get('valor'), 'parcela.valor')
            venc = _str(p.get('vencimento'), 10, required=True, field='vencimento')
            pago = bool(p.get('pago', False))
            data_pag = _str(p.get('dataPagamento'), 10)
            lanc_id = _str(p.get('lancamentoId'), 36)
            cur.execute(
                '''INSERT INTO parcelas
                   (id, divida_id, numero, valor, vencimento, pago, data_pagamento, lancamento_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE
                   SET numero=%s, valor=%s, vencimento=%s, pago=%s,
                       data_pagamento=%s, lancamento_id=%s''',
                (pid, did, numero, valor, venc, pago, data_pag, lanc_id,
                 numero, valor, venc, pago, data_pag, lanc_id)
            )

        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok', 'id': did}), 200
    except ValueError as e:
        db.rollback()
        return jsonify({'mensagem': str(e)}), 400
    except Exception:
        db.rollback()
        logger.error('Erro ao salvar divida id=%s', did)
        return jsonify({'mensagem': 'Erro ao salvar dívida'}), 500


@app.route('/api/dividas/<did>', methods=['PUT'])
@jwt_required()
@limiter.limit('30 per minute')
def update_divida(did):
    try:
        data = _json_body()
        nome = _str(data.get('nome'), 80, required=True, field='nome')
        tipo = _str(data.get('tipo'), 40, required=True, field='tipo')
        valor_total = _float(data.get('valorTotal'), 'valorTotal')
        parcelado = bool(data.get('parcelado', False))
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            'UPDATE dividas SET nome=%s, tipo=%s, valor_total=%s, parcelado=%s WHERE id=%s',
            (nome, tipo, valor_total, parcelado, did)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok'}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao atualizar divida id=%s', did)
        return jsonify({'mensagem': 'Erro ao atualizar dívida'}), 500


@app.route('/api/dividas/<did>/parcela/<pid>', methods=['PUT'])
@jwt_required()
@limiter.limit('30 per minute')
def update_parcela(did, pid):
    try:
        data = _json_body()
        pago = bool(data.get('pago', False))
        data_pag = _str(data.get('dataPagamento'), 10)
        lanc_id = _str(data.get('lancamentoId'), 36)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''UPDATE parcelas SET pago=%s, data_pagamento=%s, lancamento_id=%s
               WHERE id=%s AND divida_id=%s''',
            (pago, data_pag, lanc_id, pid, did)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok'}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao atualizar parcela id=%s', pid)
        return jsonify({'mensagem': 'Erro ao atualizar parcela'}), 500


@app.route('/api/dividas/<did>', methods=['DELETE'])
@jwt_required()
@limiter.limit('20 per minute')
def delete_divida(did):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute('DELETE FROM dividas WHERE id=%s', (did,))
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok'}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao excluir divida id=%s', did)
        return jsonify({'mensagem': 'Erro ao excluir dívida'}), 500


# ── MOVIMENTAÇÕES ──────────────────────────────────────────────────────────────
@app.route('/api/movimentacoes', methods=['GET'])
@jwt_required()
@limiter.limit('120 per minute')
def get_movimentacoes():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM movimentacoes ORDER BY data_hora')
    rows = cur.fetchall()
    cur.close()
    return jsonify([_mov_to_api(r) for r in rows])


@app.route('/api/movimentacoes', methods=['POST'])
@jwt_required()
@limiter.limit('60 per minute')
def upsert_movimentacao():
    try:
        data = _json_body()
        mid = _str(data.get('id'), 36, required=True, field='id')
        produto_id = _str(data.get('produtoId'), 36)
        produto_nome = _str(data.get('produtoNome'), 120)
        cor = _str(data.get('cor'), 50)
        tamanho = _str(data.get('tamanho'), 20)
        tipo = _str(data.get('tipo'), 20, required=True, field='tipo')
        quantidade = _int(data.get('quantidade', 1), 'quantidade', 1)
        motivo = _str(data.get('motivo'), 200)
        data_hora = _str(data.get('dataHora'), 36)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            '''INSERT INTO movimentacoes
               (id, produto_id, produto_nome, cor, tamanho, tipo, quantidade, motivo, data_hora)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO NOTHING''',
            (mid, produto_id, produto_nome, cor, tamanho, tipo, quantidade, motivo, data_hora)
        )
        db.commit()
        cur.close()
        return jsonify({'mensagem': 'ok', 'id': mid}), 200
    except Exception:
        db.rollback()
        logger.error('Erro ao salvar movimentacao id=%s', mid)
        return jsonify({'mensagem': 'Erro ao salvar movimentação'}), 500


# ── INICIALIZAÇÃO ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    debug = ENV != 'production'
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=debug)
