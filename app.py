import os, json, threading, time
from datetime import datetime
from flask import Flask, Response, jsonify
import renovar

app = Flask(__name__)

IS_RUNNING = False
LOCK = threading.Lock()

@app.route('/')
def home():
    creds = {}
    if os.path.exists('creds.json'):
        try:
            with open('creds.json') as f:
                creds = json.load(f)
        except:
            pass
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
def trigger_cron():
    """Endpoint chamado pelo cron-job.org a cada 4 horas"""
    global IS_RUNNING
    if IS_RUNNING:
        return Response("BUSY", mimetype="text/plain", status=200)

    def run_worker():
        global IS_RUNNING
        with LOCK:
            IS_RUNNING = True
            try:
                renovar.main(force=False)
            except Exception as e:
                print(f"[Cron Error] {e}", flush=True)
            finally:
                IS_RUNNING = False

    threading.Thread(target=run_worker, daemon=True).start()
    return Response("OK", mimetype="text/plain", status=200)

@app.route('/canais_brasil.m3u')
def get_canais_brasil():
    if not os.path.exists('canais_brasil.m3u'):
        with LOCK:
            renovar.main()
    with open('canais_brasil.m3u', 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    return Response(content, mimetype='audio/x-mpegurl', headers={"Content-Disposition": "inline; filename=canais_brasil.m3u"})

@app.route('/canais.m3u')
def get_canais():
    if not os.path.exists('canais.m3u'):
        with LOCK:
            renovar.main()
    with open('canais.m3u', 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    return Response(content, mimetype='audio/x-mpegurl', headers={"Content-Disposition": "inline; filename=canais.m3u"})


@app.route('/epg.xml')
def get_epg():
    creds = {}
    if os.path.exists('creds.json'):
        try:
            with open('creds.json') as f:
                creds = json.load(f)
        except:
            pass
    if creds.get('username') and creds.get('password'):
        from flask import redirect
        epg_url = f"http://drd33.com/xmltv.php?username={creds['username']}&password={creds['password']}"
        return redirect(epg_url, code=302)
    return "Nenhuma conta ativa para gerar EPG.", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
