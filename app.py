import os, json, threading, time
from datetime import datetime
from flask import Flask, Response, jsonify
import renovar
import urllib.request

def carregar_credenciais():
    """Carrega sempre as credenciais mais recentes do GitHub Raw em tempo real"""
    # 1. Sempre prioriza a versão mais recente direto do GitHub Raw (Sem cache)
    try:
        url_raw = f"https://raw.githubusercontent.com/carlosdominio/iptv-lista/main/creds.json?t={int(time.time())}"
        req = urllib.request.Request(url_raw, headers={'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache, no-store, must-revalidate'})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode())
            if data.get('username') and data.get('password'):
                return data
    except Exception as e:
        pass

    # 2. Fallback caso o GitHub esteja indisponível
    if os.path.exists('creds.json'):
        try:
            with open('creds.json') as f:
                data = json.load(f)
                if data.get('username') and data.get('password'):
                    return data
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
        "servico": "Auto-Renovador IPTV na Nuvem",
        "usuario_atual": creds.get("username", "N/A"),
        "atualizado_em": creds.get("updated_at") or creds.get("generated_at") or "N/A",
        "links": {
            "canais_brasil": "/canais_brasil.m3u",
            "canais_todos": "/canais.m3u",
            "forcar_renovacao": "/cron",
            "guia_epg": "/epg.xml"
        }
    })

@app.route('/cron')
@app.route('/renovar')
@app.route('/forcar')
@app.route('/simular')
def trigger_cron():
    """Endpoint chamado pelo cron-job.org ou manualmente para forçar/simular"""
    from flask import request
    global IS_RUNNING
    if IS_RUNNING:
        return Response("BUSY (Ja existe uma renovacao em andamento)", mimetype="text/plain", status=200)

    # Permite forçar renovação se acessar /forcar, /simular ou /cron?force=1
    is_force = request.path in ['/forcar', '/simular'] or request.args.get('force') in ['1', 'true', 'sim']

    def run_worker():
        global IS_RUNNING
        with LOCK:
            IS_RUNNING = True
            try:
                renovar.main(force=is_force)
            except Exception as e:
                print(f"[Cron Error] {e}", flush=True)
            finally:
                IS_RUNNING = False

    threading.Thread(target=run_worker, daemon=True).start()
    msg = "SIMULACAO FORCADA INICIADA (Acompanhe os logs no Render)" if is_force else "OK"
    return Response(msg, mimetype="text/plain", status=200)

@app.route('/canais_brasil.m3u')
def get_canais_brasil():
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com')
    if user and pwd:
        from flask import redirect
        # Formato universal Xtream Codes 100% compatível com todas as Smart TVs
        url_universal = f"{server}/get.php?username={user}&password={pwd}&type=m3u_plus&output=ts"
        return redirect(url_universal, code=302)
    return "Lista não gerada ainda.", 404

@app.route('/canais.m3u')
def get_canais():
    creds = carregar_credenciais()
    user = creds.get('username')
    pwd = creds.get('password')
    server = creds.get('server', 'http://drd33.com')
    if user and pwd:
        from flask import redirect
        url_universal = f"{server}/get.php?username={user}&password={pwd}&type=m3u_plus&output=ts"
        return redirect(url_universal, code=302)
    return "Lista não gerada ainda.", 404


@app.route('/epg.xml')
def get_epg():
    creds = carregar_credenciais()
    if creds.get('username') and creds.get('password'):
        from flask import redirect
        epg_url = f"http://drd33.com/xmltv.php?username={creds['username']}&password={creds['password']}"
        return redirect(epg_url, code=302)
    return "Nenhuma conta ativa para gerar EPG.", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
