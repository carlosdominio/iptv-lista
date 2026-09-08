import os, json, threading, time, base64, re
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, redirect, request, send_file
import renovar
import urllib.request, urllib.parse

# =========================================================================
# CACHE EM MEMÓRIA RAM MULTI-DISPOSITIVO (TV BOX + CELULAR)
# =========================================================================
_CACHED_CREDS = {'tv': {}, 'celular': {}}
_LAST_FETCH_TIME = {'tv': 0, 'celular': 0}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60  # Recalibra a cada 60 segundos em segundo plano
_IS_FETCHING = {'tv': False, 'celular': False}
_XTREAM_CACHE = {}
_XTREAM_CACHE_TTL = 300 # 5 minutos de cache em memória para a API Xtream Codes
RELAY_URL = os.environ.get("RELAY_URL", "").strip()

def is_cred_valid(data):
    """Verifica se os dados da credencial possuem campos e estrutura minimamente validos"""
    if not isinstance(data, dict):
        return False
    return bool(data.get('username') and data.get('password'))

def is_cred_fresh(data, max_age=None):
    """Verifica se a credencial foi gerada dentro do ciclo ideal de renovacao"""
    if not is_cred_valid(data):
        return False
    is_24h = 'business-cloud-8' in data.get('server', '')
    if max_age is None:
        max_age = 79200 if is_24h else 12600 # 22h se for 24h, ou 3.5h se for 6h
    ts_str = data.get('updated_at') or data.get('generated_at')
    if not ts_str:
        return True
    try:
        clean = ts_str.replace('Z', '')
        dt = datetime.fromisoformat(clean)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        age = (now_utc - dt).total_seconds()
        return 0 <= age < max_age
    except Exception:
        return True

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
            "lista_canais_hls_anti_travamento": "/canais_tv.m3u8",
            "lista_completa": "/completa_tv.m3u",
            "lista_legada_brasil": "/canais_brasil.m3u"
        },
        "celular": {
            "usuario_ativo": creds_cel.get("username", "N/A"),
            "atualizado_em": creds_cel.get("updated_at") or creds_cel.get("generated_at") or "N/A",
            "lista_canais": "/canais_celular.m3u",
            "lista_canais_hls_anti_travamento": "/canais_celular.m3u8",
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

def gerar_playlist_direta(file_target, device='tv', is_hls=False):
    """Lê o arquivo M3U e injeta links DIRETOS para o provedor, eliminando qualquer proxy de vídeo."""
    try:
        with open(file_target, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        content = ""

    if is_hls:
        content = content.replace('.ts\n', '.m3u8\n').replace('.ts\r\n', '.m3u8\r\n')

    creds = carregar_credenciais(device)
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://pro.business-cloud-8.ru').rstrip('/')

    if user and pwd:
        route_prefix = "/live" if "business-cloud-8" in server else ""
        direct_base = f"{server}{route_prefix}/{user}/{pwd}/"
        # Substitui links diretos existentes (atualizando usuário/senha se mudar)
        content = re.sub(r'https?://[a-zA-Z0-9\.\-]+(?::\d+)?/live/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+/', direct_base, content)
        # Substitui links legados de proxy Fly (/live/tv/ ou /live/celular/)
        content = re.sub(r'https?://[a-zA-Z0-9\.\-]+(?::\d+)?/live/(?:tv|celular)/', direct_base, content)

    response = Response(content, mimetype='application/x-mpegURL')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

# 1. TV BOX (Mantém 100% de compatibilidade com links diretos sem proxy)
@app.route('/canais_tv.m3u')
@app.route('/canais_brasil.m3u')
@app.route('/canais.m3u')
def get_canais_tv():
    file_target = 'canais_tv.m3u' if os.path.exists('canais_tv.m3u') else 'canais_brasil.m3u'
    return gerar_playlist_direta(file_target, device='tv', is_hls=False)

# Rota HLS (.m3u8) para TV Box (chunks adaptativos anti-travamento direto da fonte)
@app.route('/canais_tv.m3u8')
@app.route('/canais_tv_hls.m3u')
@app.route('/canais_tv_hls.m3u8')
@app.route('/canais_brasil.m3u8')
@app.route('/canais.m3u8')
def get_canais_tv_hls():
    file_target = 'canais_tv.m3u' if os.path.exists('canais_tv.m3u') else 'canais_brasil.m3u'
    return gerar_playlist_direta(file_target, device='tv', is_hls=True)

# 2. CELULAR (Lista dedicada com links diretos para celular)
@app.route('/canais_celular.m3u')
def get_canais_celular():
    file_target = 'canais_celular.m3u' if os.path.exists('canais_celular.m3u') else 'canais_brasil.m3u'
    return gerar_playlist_direta(file_target, device='celular', is_hls=False)

# Rota HLS (.m3u8) para Celular (chunks adaptativos anti-travamento direto da fonte)
@app.route('/canais_celular.m3u8')
@app.route('/canais_celular_hls.m3u')
@app.route('/canais_celular_hls.m3u8')
def get_canais_celular_hls():
    file_target = 'canais_celular.m3u' if os.path.exists('canais_celular.m3u') else 'canais_brasil.m3u'
    return gerar_playlist_direta(file_target, device='celular', is_hls=True)

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
    clean_path = stream_path.lstrip('/').split('/')[-1]
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    
    # Bloqueia canais com tela preta / sem transmissão
    DEAD_IDS = {'1979186', '1979185', '1979184', '1979183', '1979182', '1979181', '1979180', '1979179', '1549668', '1549667', '1549666', '1549665', '1549664', '1549663', '439343', '439340', '439338', '439336', '439330', '439329', '439324'}
    if clean_path.split('.')[0] in DEAD_IDS:
        return "Canal temporariamente fora do ar (sem transmissao)", 404

    # Redireciona diretamente para a rota nativa
    route_prefix = "/live" if "business-cloud-8" in server else ""
    resp = redirect(f"{server}{route_prefix}/{user}/{pwd}/{clean_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
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
    clean_path = stream_path.lstrip('/').split('/')[-1]
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    
    # Bloqueia canais com tela preta / sem transmissão
    DEAD_IDS = {'1979186', '1979185', '1979184', '1979183', '1979182', '1979181', '1979180', '1979179', '1549668', '1549667', '1549666', '1549665', '1549664', '1549663', '439343', '439340', '439338', '439336', '439330', '439329', '439324'}
    if clean_path.split('.')[0] in DEAD_IDS:
        return "Canal temporariamente fora do ar (sem transmissao)", 404

    # Redireciona diretamente para a rota nativa
    route_prefix = "/live" if "business-cloud-8" in server else ""
    resp = redirect(f"{server}{route_prefix}/{user}/{pwd}/{clean_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

# =========================================================================
# XTREAM CODES API PROXY (COMPATIBILIDADE TOTAL COM TIVIMATE, SMARTERS, ETC)
# =========================================================================
@app.route('/player_api.php', methods=['GET', 'POST'])
def xtream_player_api():
    """Proxy Inteligente da API Xtream Codes para login fixo e renovação automática"""
    user_in = request.args.get('username') or request.form.get('username') or 'tv'
    pass_in = request.args.get('password') or request.form.get('password') or '123'
    action = request.args.get('action') or request.form.get('action')

    dev = 'celular' if 'celular' in user_in.lower() else 'tv'
    creds = carregar_credenciais(dev)
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    cp_user = creds.get('username')
    cp_pass = creds.get('password')

    # 1. Sem action: Autenticação do Player
    if not action:
        host_header = request.host
        is_https = request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https'
        port = "443" if is_https else "80"
        auth_data = {
            "user_info": {
                "username": user_in,
                "password": pass_in,
                "message": f"Conectado ao Proxy Xtream Codes ({dev.upper()})",
                "auth": 1,
                "status": "Active",
                "exp_date": "1999999999", # Válido até ano 2033
                "is_trial": "0",
                "active_cons": "0",
                "max_connections": "3",
                "allowed_output_formats": ["m3u8", "ts", "rtmp"],
                "default_output_format": "m3u8"
            },
            "server_info": {
                "url": host_header.split(':')[0],
                "port": port,
                "https_port": "443",
                "server_protocol": "https" if is_https else "http",
                "rtmp_port": "8880",
                "timezone": "America/Sao_Paulo",
                "time_now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        resp = jsonify(auth_data)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    # 2. Com action: Repassa para o servidor CorePlay com credenciais ativas
    if not cp_user or not cp_pass:
        return jsonify([])

    qs_str = request.query_string.decode('utf-8')
    cache_key = (dev, action, qs_str)
    now_t = time.time()
    if cache_key in _XTREAM_CACHE:
        cached_t, cached_resp = _XTREAM_CACHE[cache_key]
        if now_t - cached_t < _XTREAM_CACHE_TTL:
            resp = Response(cached_resp, mimetype="application/json")
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp

    # 2.1 Atalho ultra-otimizado para VOD sem category_id (evita baixar 100.000 filmes e estourar memoria)
    if action == 'get_vod_streams' and not request.args.get('category_id'):
        try:
            br_vod_cats = ['133', '848']
            all_vod = []
            for vcat in br_vod_cats:
                try:
                    v_url = f"{server}/player_api.php?username={cp_user}&password={cp_pass}&action=get_vod_streams&category_id={vcat}"
                    with urllib.request.urlopen(urllib.request.Request(v_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=8) as vr:
                        all_vod.extend(json.loads(vr.read().decode('utf-8')))
                except Exception as ve:
                    print(f"[VOD Fetch Cat {vcat} Error] {ve}", flush=True)
            content = json.dumps(all_vod).encode('utf-8')
            if len(content) > 10:
                _XTREAM_CACHE[cache_key] = (now_t, content)
            resp = Response(content, mimetype="application/json")
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp
        except Exception as e:
            print(f"[VOD Stream Error] {e}", flush=True)
            return jsonify([])

    # 2.2 Atalho ultra-otimizado para Séries sem category_id (evita baixar séries globais desnecessárias)
    if action == 'get_series' and not request.args.get('category_id'):
        try:
            br_series_cats = ['1889', '857', '851', '853', '852', '854', '864', '1341', '1397', '1407', '1349', '1370', '855', '2031']
            all_series = []
            for scat in br_series_cats:
                try:
                    s_url = f"{server}/player_api.php?username={cp_user}&password={cp_pass}&action=get_series&category_id={scat}"
                    with urllib.request.urlopen(urllib.request.Request(s_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=5) as sr:
                        all_series.extend(json.loads(sr.read().decode('utf-8')))
                except Exception:
                    pass
            content = json.dumps(all_series).encode('utf-8')
            if len(content) > 10:
                _XTREAM_CACHE[cache_key] = (now_t, content)
            resp = Response(content, mimetype="application/json")
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp
        except Exception as e:
            print(f"[Series Error] {e}", flush=True)
            return jsonify([])

    qs_dict = request.args.to_dict()
    qs_dict['username'] = cp_user
    qs_dict['password'] = cp_pass
    target_url = f"{server}/player_api.php?{urllib.parse.urlencode(qs_dict)}"
    if RELAY_URL:
        sep = "&" if "?" in RELAY_URL else "?"
        effective_target = f"{RELAY_URL.rstrip('/')}/{sep}url={urllib.parse.quote(target_url, safe='')}"
    else:
        effective_target = target_url

    try:
        req = urllib.request.Request(effective_target, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as r:
            content = r.read()
            # Filtro inteligente de categorias e canais do Brasil
            if action in ['get_live_categories', 'get_vod_categories', 'get_series_categories'] and len(content) > 10:
                try:
                    cats = json.loads(content.decode('utf-8'))
                    if isinstance(cats, list):
                        filtered_cats = [
                            c for c in cats 
                            if any(x in (c.get('category_name') or '').lower() for x in ['br|', 'br:', 'br -', 'brasil', 'brazil', 'pt/br', 'dublado', 'nacional'])
                        ]
                        content = json.dumps(filtered_cats).encode('utf-8')
                except Exception as je:
                    print(f"[Filter Categories Error] {je}", flush=True)

            elif action == 'get_live_streams' and len(content) > 10:
                try:
                    streams = json.loads(content.decode('utf-8'))
                    if isinstance(streams, list):
                        # Remove canais conhecidos de tela preta / fora do ar / câmeras inativas
                        DEAD_KEYWORDS = ['(na)', '(n/a)', 'casa do patrão', 'fazenda ']
                        DEAD_IDS = {'1979186', '1979185', '1979184', '1979183', '1979182', '1979181', '1979180', '1979179', '1549668', '1549667', '1549666', '1549665', '1549664', '1549663', '439343', '439340', '439338', '439336', '439330', '439329', '439324'}
                        streams = [
                            s for s in streams
                            if str(s.get('stream_id')) not in DEAD_IDS and not any(k in (s.get('name') or '').lower() for k in DEAD_KEYWORDS)
                        ]
                        if not request.args.get('category_id'):
                            streams = [
                                s for s in streams
                                if any(x in (s.get('name') or '').lower() for x in ['br:', 'br|', 'br -', 'brasil', 'brazil'])
                            ]
                        for st in streams:
                            st['container_extension'] = 'ts'
                        content = json.dumps(streams).encode('utf-8')
                except Exception as je:
                    print(f"[Xtream Streams Error] {je}", flush=True)

            if len(content) > 10 and len(content) < 3 * 1024 * 1024:
                if len(_XTREAM_CACHE) > 30:
                    oldest = min(_XTREAM_CACHE.keys(), key=lambda k: _XTREAM_CACHE[k][0])
                    _XTREAM_CACHE.pop(oldest, None)
                _XTREAM_CACHE[cache_key] = (now_t, content)
            resp = Response(content, mimetype="application/json")
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp
    except Exception as e:
        print(f"[Xtream Proxy Error] {e}", flush=True)
        return jsonify([])

# Rota Legada e Xtream Codes /live/<stream_path>
@app.route('/live/<path:stream_path>')
def proxy_live_legacy(stream_path):
    parts = stream_path.strip('/').split('/')
    if len(parts) >= 3:
        user_param = parts[0].lower()
        dev = 'celular' if 'celular' in user_param else 'tv'
        file_part = parts[-1]
        return proxy_live_celular(file_part) if dev == 'celular' else proxy_live_tv(file_part)
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
    clean_path = stream_path.lstrip('/').split('/')[-1]
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    resp = redirect(f"{server}/movie/{user}/{pwd}/{clean_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/movie/celular/<path:stream_path>')
def proxy_movie_celular(stream_path):
    creds = carregar_credenciais('celular')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    clean_path = stream_path.lstrip('/').split('/')[-1]
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    resp = redirect(f"{server}/movie/{user}/{pwd}/{clean_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/movie/<path:stream_path>')
def proxy_movie_legacy(stream_path):
    parts = stream_path.strip('/').split('/')
    if len(parts) >= 3:
        user_param = parts[0].lower()
        dev = 'celular' if 'celular' in user_param else 'tv'
        file_part = parts[-1]
        return proxy_movie_celular(file_part) if dev == 'celular' else proxy_movie_tv(file_part)
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
    clean_path = stream_path.lstrip('/').split('/')[-1]
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    resp = redirect(f"{server}/series/{user}/{pwd}/{clean_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/series/celular/<path:stream_path>')
def proxy_series_celular(stream_path):
    creds = carregar_credenciais('celular')
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com').rstrip('/')
    clean_path = stream_path.lstrip('/').split('/')[-1]
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    resp = redirect(f"{server}/series/{user}/{pwd}/{clean_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/series/<path:stream_path>')
def proxy_series_legacy(stream_path):
    parts = stream_path.strip('/').split('/')
    if len(parts) >= 3:
        user_param = parts[0].lower()
        dev = 'celular' if 'celular' in user_param else 'tv'
        file_part = parts[-1]
        return proxy_series_celular(file_part) if dev == 'celular' else proxy_series_tv(file_part)
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
    qs = f"?{request.query_string.decode('utf-8')}" if request.query_string else ""
    resp = redirect(f"{server}/hls/{stream_path}{qs}", code=302)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

# EPG Guia de Programação
@app.route('/epg.xml')
@app.route('/xmltv.php')
def get_epg():
    creds = carregar_credenciais('tv')
    if creds.get('username') and creds.get('password'):
        server = creds.get('server', 'http://pro.business-cloud-8.ru').rstrip('/')
        epg_url = f"{server}/xmltv.php?username={creds['username']}&password={creds['password']}"
        resp = redirect(epg_url, code=302)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return "Nenhuma conta ativa para gerar EPG.", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
