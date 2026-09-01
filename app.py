import os, json, threading, time
from datetime import datetime
from flask import Flask, Response, jsonify
import renovar

app = Flask(__name__)

# Cache global
LAST_RENEWAL = None
LOCK = threading.Lock()

def auto_loop():
    """Loop em background para renovar a cada 5 horas"""
    while True:
        try:
            print("[Cloud Daemon] Verificando/renovando lista IPTV...")
            renovar.main()
        except Exception as e:
            print(f"[Cloud Daemon Error] {e}")
        time.sleep(5 * 3600)

# Iniciar thread de renovação em background
threading.Thread(target=auto_loop, daemon=True).start()

@app.route('/')
def home():
    creds = {}
    if os.path.exists('creds.json'):
        with open('creds.json') as f:
            creds = json.load(f)
    return jsonify({
        "status": "online",
        "servico": "Auto-Renovador IPTV na Nuvem",
        "usuario_atual": creds.get("username", "N/A"),
        "atualizado_em": creds.get("updated_at", "N/A"),
        "links": {
            "canais_brasil": "/canais_brasil.m3u",
            "canais_todos": "/canais.m3u",
            "forcar_renovacao": "/cron"
        }
    })

@app.route('/cron')
@app.route('/renovar')
def trigger_cron():
    """Endpoint chamado por cron-job.org ou manualmente para forçar renovação"""
    with LOCK:
        try:
            renovar.main()
            return jsonify({"status": "success", "msg": "Lista renovada com sucesso!"}), 200
        except Exception as e:
            return jsonify({"status": "error", "msg": str(e)}), 500

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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
