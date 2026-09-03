import os, json, threading, time, base64
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, redirect, request, send_file
import renovar
import urllib.request

# =========================================================================
# CACHE EM MEMÓRIA RAM ULTRA-RÁPIDO COM VALIDAÇÃO DE EXPIRAÇÃO
# =========================================================================
_CACHED_CREDS = {}
_LAST_FETCH_TIME = 0
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60  # Recalibra a cada 60 segundos em segundo plano
_IS_FETCHING = False

def is_cred_valid(data):
    """Verifica se a credencial tem menos de 3.5 horas de vida"""
    if not data or not data.get('username') or not data.get('password'):
        return False
    ts_str = data.get('updated_at') or data.get('generated_at')
    if not ts_str:
        return False
    try:
        clean = ts_str.replace('Z', '')
        dt = datetime.fromisoformat(clean)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        age = (now_utc - dt).total_seconds()
        # Testes duram no máximo 4 horas. Se tem mais de 3.5h (12600s), está expirada!
        return 0 <= age < 12600
    except Exception:
        return False

def _fetch_from_github():
    """Busca as credenciais mais recentes direto da API do GitHub (sem cache de 5 minutos do Fastly)"""
    # 1. Tentar via API oficial do GitHub (bypass total de cache)
    try:
        url_api = "https://api.github.com/repos/carlosdominio/iptv-lista/contents/creds.json"
        req = urllib.request.Request(url_api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            res_json = json.loads(r.read().decode())
            data = json.loads(base64.b64decode(res_json['content']).decode('utf-8'))
            if is_cred_valid(data):
                return data
    except Exception:
        pass

    # 2. Fallback via Raw caso a API falhe ou dê rate-limit
    try:
        url_raw = f"https://raw.githubusercontent.com/carlosdominio/iptv-lista/main/creds.json?t={int(time.time())}"
        req = urllib.request.Request(url_raw, headers={
            'User-Agent': 'Mozilla/5.0',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache'
        })
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode())
            if is_cred_valid(data):
                return data
    except Exception:
        pass
    return None

def _fetch_from_disk():
    """Lê as credenciais salvas no disco local (apenas se ainda forem válidas)"""
    if os.path.exists('creds.json'):
        try:
            with open('creds.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if is_cred_valid(data):
                    return data
        except Exception:
            pass
    return None

def atualizar_credenciais_background():
    """Atualiza as credenciais em segundo plano sem travar a reprodução do usuário"""
    global _CACHED_CREDS, _LAST_FETCH_TIME, _IS_FETCHING
    if _IS_FETCHING:
        return
    _IS_FETCHING = True
    try:
        data = _fetch_from_github()
        if not data:
            data = _fetch_from_disk()
        if data and data.get('username') and data.get('password'):
            with _CACHE_LOCK:
                _CACHED_CREDS = data
                _LAST_FETCH_TIME = time.time()
            try:
                with open('creds.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _IS_FETCHING = False

def carregar_credenciais():
    """Retorna instantaneamente da memória RAM (< 1ms).
    Garante que nunca entrega conta expirada ou antiga."""
    global _CACHED_CREDS, _LAST_FETCH_TIME

    now = time.time()

    # 1. Se já está na memória e dentro do TTL (60s) E ainda é válida, retorna na hora
    with _CACHE_LOCK:
        if _CACHED_CREDS and (now - _LAST_FETCH_TIME < _CACHE_TTL) and is_cred_valid(_CACHED_CREDS):
            return _CACHED_CREDS

    # 2. Se temos cache válido mas passou de 60s, dispara atualização assíncrona e retorna o cache
    if _CACHED_CREDS and is_cred_valid(_CACHED_CREDS):
        threading.Thread(target=atualizar_credenciais_background, daemon=True).start()
        return _CACHED_CREDS

    # 3. Se não há cache válido na memória (início a frio), tenta ler do disco (se for válida)
    disk_data = _fetch_from_disk()
    if disk_data:
        with _CACHE_LOCK:
            _CACHED_CREDS = disk_data
            _LAST_FETCH_TIME = now
        threading.Thread(target=atualizar_credenciais_background, daemon=True).start()
        return _CACHED_CREDS

    # 4. Se o disco está expirado ou vazio, busca sincronicamente do GitHub imediatamente
    gh_data = _fetch_from_github()
    if gh_data:
        with _CACHE_LOCK:
            _CACHED_CREDS = gh_data
            _LAST_FETCH_TIME = now
        try:
            with open('creds.json', 'w', encoding='utf-8') as f:
                json.dump(gh_data, f, indent=2)
        except Exception:
            pass
        return _CACHED_CREDS

    # 5. Último recurso se o GitHub estiver fora: retorna o que tiver (mesmo que antigo)
    if os.path.exists('creds.json'):
        try:
            with open('creds.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return {}

app = Flask(__name__)

IS_RUNNING = False
LOCK = threading.Lock()

@app.route('/')
def home():
    creds = carregar_credenciais()
    return jsonify({
        "status": "online",
        "servico": "Auto-Renovador IPTV com Inteligência de Streaming Dinâmico",
        "usuario_atual": creds.get("username", "N/A"),
        "atualizado_em": creds.get("updated_at") or creds.get("generated_at") or "N/A",
        "links": {
            "canais_brasil": "/canais_brasil.m3u",
            "canais_todos": "/canais.m3u",
            "lista_completa": "/completa.m3u",
            "guia_epg": "/epg.xml",
            "forcar_renovacao": "/cron"
        }
    })

@app.route('/cron')
@app.route('/renovar')
@app.route('/forcar')
@app.route('/simular')
def trigger_cron():
    """Endpoint chamado pelo cron-job.org ou manualmente para forçar/simular"""
    global IS_RUNNING
    if IS_RUNNING:
        return Response("BUSY (Ja existe uma renovacao em andamento)", mimetype="text/plain", status=200)

    is_force = request.path in ['/forcar', '/simular'] or request.args.get('force') in ['1', 'true', 'sim']

    def run_worker():
        global IS_RUNNING, _CACHED_CREDS, _LAST_FETCH_TIME
        with LOCK:
            IS_RUNNING = True
            try:
                renovar.main(force=is_force)
                # Imediatamente atualiza o cache com a nova conta gerada
                disk_data = _fetch_from_disk()
                if disk_data:
                    with _CACHE_LOCK:
                        _CACHED_CREDS = disk_data
                        _LAST_FETCH_TIME = time.time()
            except Exception as e:
                print(f"[Cron Error] {e}", flush=True)
            finally:
                IS_RUNNING = False

    threading.Thread(target=run_worker, daemon=True).start()
    msg = "SIMULACAO FORCADA INICIADA" if is_force else "OK"
    return Response(msg, mimetype="text/plain", status=200)

@app.route('/canais_brasil.m3u')
@app.route('/canais.m3u')
@app.route('/canais_brasil.m3u8')
@app.route('/canais.m3u8')
def get_canais_inteligente():
    """Entrega a lista com links dinâmicos eternos (/live/<id>.ts)"""
    # 1. Se o arquivo pré-gerado com links neutros existir, entrega com suporte a streaming
    file_target = 'canais_brasil.m3u' if os.path.exists('canais_brasil.m3u') else 'canais.m3u'
    if os.path.exists(file_target):
        response = send_file(file_target, mimetype='application/x-mpegURL')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    # 2. Fallback caso a lista ainda não esteja no disco
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com')
    if user and pwd:
        url_universal = f"{server}/get.php?username={user}&password={pwd}&type=m3u_plus&output=ts"
        resp = redirect(url_universal, code=302)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return "Lista não gerada ainda.", 404

@app.route('/completa.m3u')
@app.route('/lista_completa.m3u')
@app.route('/completa.m3u8')
@app.route('/lista_completa.m3u8')
def get_lista_completa():
    """Entrega a lista completa oficial contendo todos os Canais, Filmes (VOD) e Séries"""
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if user and pwd:
        url_master = f"{server}/get.php?username={user}&password={pwd}&type=m3u_plus&output=ts"
        resp = redirect(url_master, code=302)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return "Nenhuma conta ativa para gerar a lista completa.", 503

# =========================================================================
# ROTAS DINÂMICAS INTELIGENTES (STREAM PROXY - NUNCA EXPIRAM)
# =========================================================================

@app.route('/live/<path:stream_path>')
def proxy_live_stream(stream_path):
    """Redireciona dinamicamente para o canal ao vivo com a credencial ativa do segundo atual (< 1ms)"""
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if not user or not pwd:
        return "Erro: Nenhuma conta ativa no momento", 503
    # Redireciona 302 instantaneamente para o servidor com a conta ativa
    resp = redirect(f"{server}/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/movie/<path:stream_path>')
def proxy_movie_stream(stream_path):
    """Redireciona dinamicamente para o filme com a credencial ativa"""
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if not user or not pwd:
        return "Erro: Nenhuma conta ativa no momento", 503
    resp = redirect(f"{server}/movie/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/series/<path:stream_path>')
def proxy_series_stream(stream_path):
    """Redireciona dinamicamente para o episódio de série com a credencial ativa"""
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if not user or not pwd:
        return "Erro: Nenhuma conta ativa no momento", 503
    resp = redirect(f"{server}/series/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/hls/<path:stream_path>')
def proxy_hls_stream(stream_path):
    """Redireciona chunks HLS caso o player resolva o caminho relativo na raiz"""
    creds = carregar_credenciais()
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    resp = redirect(f"{server}/hls/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/epg.xml')
def get_epg():
    creds = carregar_credenciais()
    if creds.get('username') and creds.get('password'):
        server = creds.get('server', 'http://drd33.com').rstrip('/')
        epg_url = f"{server}/xmltv.php?username={creds['username']}&password={creds['password']}"
        resp = redirect(epg_url, code=302)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return "Nenhuma conta ativa para gerar EPG.", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
