import os, json, threading, time, base64
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, redirect, request, send_file
import renovar
import urllib.request

# =========================================================================
# CACHE EM MEMÓRIA RAM MULTI-DISPOSITIVO (TV BOX + CELULAR)
# =========================================================================
_CACHED_CREDS = {'tv': {}, 'celular': {}}
_LAST_FETCH_TIME = {'tv': 0, 'celular': 0}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60  # Recalibra a cada 60 segundos em segundo plano
_IS_FETCHING = {'tv': False, 'celular': False}

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

def _fetch_from_github(filename='creds.json'):
    """Busca as credenciais mais recentes direto da API do GitHub (sem cache de 5 minutos do Fastly)"""
    # 1. Tentar via API oficial do GitHub (bypass total de cache)
    try:
        url_api = f"https://api.github.com/repos/carlosdominio/iptv-lista/contents/{filename}"
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
        url_raw = f"https://raw.githubusercontent.com/carlosdominio/iptv-lista/main/{filename}?t={int(time.time())}"
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

def _fetch_from_disk(filename='creds.json'):
    """Lê as credenciais salvas no disco local (apenas se ainda forem válidas)"""
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if is_cred_valid(data):
                    return data
        except Exception:
            pass
    # Fallback para creds.json se o arquivo do dispositivo específico ainda não existir
    if filename != 'creds.json' and os.path.exists('creds.json'):
        try:
            with open('creds.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if is_cred_valid(data):
                    return data
        except Exception:
            pass
    return None

def atualizar_credenciais_background(device='tv'):
    """Atualiza as credenciais de um dispositivo específico em segundo plano sem travar a reprodução"""
    global _CACHED_CREDS, _LAST_FETCH_TIME, _IS_FETCHING
    if _IS_FETCHING[device]:
        return
    _IS_FETCHING[device] = True
    filename = f"creds_{device}.json" if device != 'tv' else "creds_tv.json"
    try:
        data = _fetch_from_github(filename)
        if not data:
            data = _fetch_from_disk(filename)
        if not data and device == 'tv':
            data = _fetch_from_github('creds.json') or _fetch_from_disk('creds.json')

        if data and data.get('username') and data.get('password'):
            with _CACHE_LOCK:
                _CACHED_CREDS[device] = data
                _LAST_FETCH_TIME[device] = time.time()
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _IS_FETCHING[device] = False

def carregar_credenciais(device='tv'):
    """Retorna instantaneamente da memória RAM (< 1ms) para o dispositivo especificado ('tv' ou 'celular')."""
    global _CACHED_CREDS, _LAST_FETCH_TIME

    now = time.time()
    filename = f"creds_{device}.json" if device != 'tv' else "creds_tv.json"

    # 1. Se já está na memória e dentro do TTL (60s) E ainda é válida, retorna na hora
    with _CACHE_LOCK:
        cached = _CACHED_CREDS.get(device, {})
        last_t = _LAST_FETCH_TIME.get(device, 0)
        if cached and (now - last_t < _CACHE_TTL) and is_cred_valid(cached):
            return cached

    # 2. Se temos cache válido mas passou de 60s, dispara atualização assíncrona e retorna o cache
    cached = _CACHED_CREDS.get(device, {})
    if cached and is_cred_valid(cached):
        threading.Thread(target=atualizar_credenciais_background, args=(device,), daemon=True).start()
        return cached

    # 3. Se não há cache válido na memória (início a frio), tenta ler do disco (se for válida)
    disk_data = _fetch_from_disk(filename)
    if disk_data:
        with _CACHE_LOCK:
            _CACHED_CREDS[device] = disk_data
            _LAST_FETCH_TIME[device] = now
        threading.Thread(target=atualizar_credenciais_background, args=(device,), daemon=True).start()
        return disk_data

    # 4. Se o disco está expirado ou vazio, busca sincronicamente do GitHub imediatamente
    gh_data = _fetch_from_github(filename)
    if gh_data:
        with _CACHE_LOCK:
            _CACHED_CREDS[device] = gh_data
            _LAST_FETCH_TIME[device] = now
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(gh_data, f, indent=2)
        except Exception:
            pass
        return gh_data

    # 5. Último recurso: retorna o arquivo creds.json legado
    fallback = _fetch_from_disk('creds.json')
    if fallback:
        return fallback

    return {}

app = Flask(__name__)

IS_RUNNING = False
LOCK = threading.Lock()

# =========================================================================
# PÁGINA INICIAL COM TODOS OS LINKS ORGANIZADOS POR DISPOSITIVO
# =========================================================================
@app.route('/')
def home():
    creds_tv = carregar_credenciais('tv')
    creds_cel = carregar_credenciais('celular')
    return jsonify({
        "status": "online",
        "servico": "Auto-Renovador IPTV Multi-Dispositivo (TV Box + Celular)",
        "tv_box": {
            "usuario_ativo": creds_tv.get("username", "N/A"),
            "atualizado_em": creds_tv.get("updated_at") or creds_tv.get("generated_at") or "N/A",
            "lista_canais": "/canais_tv.m3u",
            "lista_completa": "/completa_tv.m3u",
            "lista_legada_brasil": "/canais_brasil.m3u"
        },
        "celular": {
            "usuario_ativo": creds_cel.get("username", "N/A"),
            "atualizado_em": creds_cel.get("updated_at") or creds_cel.get("generated_at") or "N/A",
            "lista_canais": "/canais_celular.m3u",
            "lista_completa": "/completa_celular.m3u"
        },
        "guia_epg": "/epg.xml",
        "forcar_renovacao": "/cron"
    })

@app.route('/cron')
@app.route('/renovar')
@app.route('/forcar')
@app.route('/simular')
def trigger_cron():
    """Endpoint chamado pelo cron-job.org ou manualmente para renovação de ambas as contas"""
    global IS_RUNNING
    if IS_RUNNING:
        return Response("BUSY (Ja existe uma renovacao em andamento)", mimetype="text/plain", status=200)

    is_force = request.path in ['/forcar', '/simular'] or request.args.get('force') in ['1', 'true', 'sim']

    def run_worker():
        global IS_RUNNING
        with LOCK:
            IS_RUNNING = True
            try:
                renovar.main(force=is_force)
                # Imediatamente atualiza os caches em RAM para ambos os aparelhos
                for dev in ['tv', 'celular']:
                    fname = f"creds_{dev}.json"
                    disk_d = _fetch_from_disk(fname)
                    if disk_d:
                        with _CACHE_LOCK:
                            _CACHED_CREDS[dev] = disk_d
                            _LAST_FETCH_TIME[dev] = time.time()
            except Exception as e:
                print(f"[Cron Error] {e}", flush=True)
            finally:
                IS_RUNNING = False

    threading.Thread(target=run_worker, daemon=True).start()
    msg = "RENOVACAO MULTI-DISPOSITIVO INICIADA" if is_force else "OK"
    return Response(msg, mimetype="text/plain", status=200)

# =========================================================================
# ROTAS DE LISTAS M3U
# =========================================================================

# 1. TV BOX (Mantém 100% de compatibilidade com os links já configurados na TV)
@app.route('/canais_tv.m3u')
@app.route('/canais_tv.m3u8')
@app.route('/canais_brasil.m3u')
@app.route('/canais.m3u')
@app.route('/canais_brasil.m3u8')
@app.route('/canais.m3u8')
def get_canais_tv():
    file_target = 'canais_tv.m3u' if os.path.exists('canais_tv.m3u') else 'canais_brasil.m3u'
    response = send_file(file_target, mimetype='application/x-mpegURL')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

# 2. CELULAR (Lista dedicada com links para a rota do celular)
@app.route('/canais_celular.m3u')
@app.route('/canais_celular.m3u8')
def get_canais_celular():
    file_target = 'canais_celular.m3u' if os.path.exists('canais_celular.m3u') else 'canais_brasil.m3u'
    response = send_file(file_target, mimetype='application/x-mpegURL')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

# 3. LISTAS COMPLETAS (CANAIS + FILMES + SÉRIES)
@app.route('/completa_tv.m3u')
@app.route('/completa.m3u')
@app.route('/lista_completa.m3u')
@app.route('/completa_tv.m3u8')
@app.route('/completa.m3u8')
@app.route('/lista_completa.m3u8')
def get_completa_tv():
    creds = carregar_credenciais('tv')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if user and pwd:
        url_master = f"{server}/get.php?username={user}&password={pwd}&type=m3u_plus&output=ts"
        resp = redirect(url_master, code=302)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return "Nenhuma conta TV ativa para gerar a lista completa.", 503

@app.route('/completa_celular.m3u')
@app.route('/completa_celular.m3u8')
def get_completa_celular():
    creds = carregar_credenciais('celular')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if user and pwd:
        url_master = f"{server}/get.php?username={user}&password={pwd}&type=m3u_plus&output=ts"
        resp = redirect(url_master, code=302)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return "Nenhuma conta Celular ativa para gerar a lista completa.", 503

# =========================================================================
# ROTAS DINÂMICAS DE STREAMING (PROXY INTELIGENTE)
# =========================================================================

# Streams da TV e Celular (Rotas específicas primeiro)
@app.route('/live/tv/<path:stream_path>')
def proxy_live_tv(stream_path):
    creds = carregar_credenciais('tv')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if not user or not pwd:
        return "Erro: Nenhuma conta ativa no momento", 503
    resp = redirect(f"{server}/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/live/celular/<path:stream_path>')
def proxy_live_celular(stream_path):
    creds = carregar_credenciais('celular')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    if not user or not pwd:
        return "Erro: Nenhuma conta ativa no momento", 503
    resp = redirect(f"{server}/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

# Rota Legada /live/<stream_path> (Redireciona para a TV mantendo compatibilidade retroativa)
@app.route('/live/<path:stream_path>')
def proxy_live_legacy(stream_path):
    if stream_path.startswith('celular/'):
        return proxy_live_celular(stream_path[8:])
    if stream_path.startswith('tv/'):
        return proxy_live_tv(stream_path[3:])
    return proxy_live_tv(stream_path)

# Filmes
@app.route('/movie/tv/<path:stream_path>')
def proxy_movie_tv(stream_path):
    creds = carregar_credenciais('tv')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    resp = redirect(f"{server}/movie/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/movie/celular/<path:stream_path>')
def proxy_movie_celular(stream_path):
    creds = carregar_credenciais('celular')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    resp = redirect(f"{server}/movie/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/movie/<path:stream_path>')
def proxy_movie_legacy(stream_path):
    if stream_path.startswith('celular/'):
        return proxy_movie_celular(stream_path[8:])
    if stream_path.startswith('tv/'):
        return proxy_movie_tv(stream_path[3:])
    return proxy_movie_tv(stream_path)

# Séries
@app.route('/series/tv/<path:stream_path>')
def proxy_series_tv(stream_path):
    creds = carregar_credenciais('tv')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    resp = redirect(f"{server}/series/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/series/celular/<path:stream_path>')
def proxy_series_celular(stream_path):
    creds = carregar_credenciais('celular')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    resp = redirect(f"{server}/series/{user}/{pwd}/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/series/<path:stream_path>')
def proxy_series_legacy(stream_path):
    if stream_path.startswith('celular/'):
        return proxy_series_celular(stream_path[8:])
    if stream_path.startswith('tv/'):
        return proxy_series_tv(stream_path[3:])
    return proxy_series_tv(stream_path)

# HLS Chunks Fallback
@app.route('/hls/<path:stream_path>')
def proxy_hls_stream(stream_path):
    creds = carregar_credenciais('tv')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    resp = redirect(f"{server}/hls/{stream_path}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

# EPG Guia de Programação
@app.route('/epg.xml')
def get_epg():
    creds = carregar_credenciais('tv')
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
