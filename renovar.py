#!/usr/bin/env python3
"""
Renovador Automático IPTV Ultra-Otimizado para Nuvem.
Processa as playlists via streaming linha por linha (usa menos de 10MB de RAM).
Possui retry automático, sincronização de banco de dados e proteção contra duplicidade.
"""

import urllib.request, urllib.parse, http.cookiejar
import re, hashlib, base64, uuid, json, time, random, os, sys
from http.cookiejar import Cookie
from datetime import datetime

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

FOREIGN_GROUPS = [
    'Estados Unidos', 'Alemanha', 'França', 'Italia', 'Turquia', 'Espanha', 'Canada',
    'Argentina', 'Portugal', 'Mexico', 'Arabe', 'Africa do Sul', 'Colombia', 'Israel',
    'Australia', 'Chile', 'Bolivia', 'Uruguai', 'Peru', 'Equador', 'Paraguai', 'Venezuela',
    'Reino Unido', 'Holanda', 'Polonia', 'Russia', 'Grecia'
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def check_active():
    """Verifica se já temos credenciais válidas e ativas no servidor"""
    if not os.path.exists('creds.json'):
        return False
    try:
        with open('creds.json') as f:
            creds = json.load(f)
        user = creds.get('username')
        pwd = creds.get('password')
        server = creds.get('server', 'http://drd33.com')
        if not user or not pwd:
            return False

        url = f'{server}/player_api.php?username={user}&password={pwd}'
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read().decode('utf-8', errors='ignore'))
        info = data.get('user_info', {})
        if info.get('status') == 'Active':
            exp = datetime.fromtimestamp(int(info.get('exp_date', 0)))
            remaining = (exp - datetime.now()).total_seconds()
            log(f"Conta '{user}' ainda ATIVA. Restam {remaining/60:.0f} min (expira às {exp.strftime('%H:%M:%S')})")
            # Se ainda faltam mais de 2 horas (7200s), não precisa gerar outro teste
            if remaining > 7200:
                return True
        return False
    except Exception as e:
        log(f"Conta anterior expirada ou inacessivel ({e}). Gerando nova...")
        return False

def get_temp_email():
    log("Criando caixa de e-mail temporária...")
    for attempt in range(3):
        try:
            req = urllib.request.Request('https://api.mail.tm/domains', headers={'Accept': 'application/ld+json'})
            data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            domains = [d['domain'] for d in (data if isinstance(data, list) else data.get('hydra:member', []))]
            domain = domains[0] if domains else 'emalupe.com'

            username = f'iptv{random.randint(10000, 99999)}'
            email = f'{username}@{domain}'
            password = f'Pass{random.randint(1000, 9999)}!Auto'

            create_data = json.dumps({"address": email, "password": password}).encode()
            req = urllib.request.Request('https://api.mail.tm/accounts', data=create_data,
                headers={'Content-Type': 'application/json', 'Accept': 'application/ld+json'})
            urllib.request.urlopen(req, timeout=10)

            login_data = json.dumps({"address": email, "password": password}).encode()
            req = urllib.request.Request('https://api.mail.tm/token', data=login_data,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            tok = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())

            log(f"E-mail gerado: {email}")
            return email, tok['token']
        except Exception as e:
            log(f"Tentativa {attempt+1} ao obter e-mail: {e}. Aguardando 6s...")
            time.sleep(6)

    raise Exception("Falha ao obter e-mail temporário após várias tentativas.")

def generate_test(temp_email):
    log("Enviando requisição de geração de teste...")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    html = opener.open(urllib.request.Request('https://teste.coreplay.vc/',
        headers={'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9'}),
        timeout=15).read().decode('utf-8', errors='ignore')

    cp_sn = re.search(r'id="cp_sn"[^>]*value="([^"]+)"', html).group(1)
    device_id = str(uuid.uuid4())

    cj.set_cookie(Cookie(0, 'cp_device_id', device_id, None, False,
        'teste.coreplay.vc', False, False, '/', True, False,
        int(time.time()) + 31536000, False, None, None, {}))

    device_fp = hashlib.md5(f'{UA}|{random.random()}'.encode()).hexdigest()
    ddd = random.choice(['11', '21', '31', '41', '51', '61', '71', '81', '85', '47', '48', '27'])
    telefone = f'+55{ddd}{random.randint(900000000, 999999999)}'

    key = hashlib.md5(base64.b64encode(temp_email.encode())).hexdigest()
    cp_jsp = hashlib.md5(f'{cp_sn}:{device_id}:Cp9xQ2m7Ka'.encode()).hexdigest()

    payload = {
        'key': key, 'email': temp_email, 'pacote': '[1,2,3,5,6,7]',
        'telefone': telefone, 'fingerprint': device_fp,
        'cp_device_id': device_id, 'cp_device_fp': device_fp,
        'cp_flow_tag': '',
        'cp_device_attrs': json.dumps({"ua": UA, "lang": "pt-BR", "tz": "America/Sao_Paulo", "res": "1920x1080", "webdriver": False}),
        'cp_bot_flags': '', 'cp_iptv_caps': json.dumps({"mse": True}),
        'cp_hp': '', 'cp_sn': cp_sn, 'cp_jsp': cp_jsp,
        'cp_attr_source_hint': 'direct', 'cp_attr_channel_group': 'Direct',
        'cp_attr_landing_url': 'https://teste.coreplay.vc/',
    }

    time.sleep(2)
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request('https://teste.coreplay.vc/gerarteste', data=data, headers={
        'User-Agent': UA, 'Referer': 'https://teste.coreplay.vc/',
        'Origin': 'https://teste.coreplay.vc', 'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    })

    resp = opener.open(req, timeout=20).read().decode('utf-8', errors='ignore').strip()
    log(f"Resposta do gerador: {resp}")
    if resp != 'sendok':
        raise Exception(f"Falha ao gerar teste: {resp}")
    return True

def read_email_credentials(auth_token, max_attempts=12):
    log("Aguardando chegada do e-mail com as credenciais...")
    time.sleep(18)

    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request('https://api.mail.tm/messages', headers={
                'Accept': 'application/ld+json', 'Authorization': f'Bearer {auth_token}'
            })
            mdata = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            msgs = mdata.get('hydra:member', []) if isinstance(mdata, dict) else []

            for m in msgs:
                mid = m.get('id', '')
                req2 = urllib.request.Request(f'https://api.mail.tm/messages/{mid}', headers={
                    'Accept': 'application/ld+json', 'Authorization': f'Bearer {auth_token}'
                })
                full = json.loads(urllib.request.urlopen(req2, timeout=10).read().decode())
                html_body = full.get('html', [''])[0] if isinstance(full.get('html'), list) else (full.get('html') or full.get('text', ''))

                clean = re.sub(r'<[^>]+>', ' ', html_body)
                clean = re.sub(r'&[a-z]+;', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()

                user_m = re.search(r'(?:Usu[aá]rio|User)\s*[:\-]?\s*(\d+)', clean, re.IGNORECASE)
                pass_m = re.search(r'(?:Senha|Password)\s*[:\-]?\s*(\w+)', clean, re.IGNORECASE)
                server_m = re.search(r'(?:Servidor|Server)\s*[:\-]?\s*(https?://\S+)', clean, re.IGNORECASE)

                if user_m and pass_m:
                    creds = {
                        'username': user_m.group(1),
                        'password': pass_m.group(1),
                        'server': server_m.group(1) if server_m else 'http://drd33.com',
                        'updated_at': datetime.utcnow().isoformat() + 'Z'
                    }
                    log(f"Credenciais obtidas com sucesso: Usuário={creds['username']}")
                    return creds
            log(f"Tentativa {attempt+1}/{max_attempts} - aguardando e-mail...")
        except Exception as e:
            log(f"Aviso tentativa {attempt+1}: {e}")

        if attempt < max_attempts - 1:
            time.sleep(8)

    raise Exception("Tempo limite esgotado sem receber e-mail.")

def download_and_save_streaming(username, password, server="http://drd33.com"):
    """Baixa a playlist via streaming com retentativas se o servidor demorar para sincronizar"""
    log("Aguardando 4s para sincronização no servidor IPTV...")
    time.sleep(4)

    url = f'{server}/playlist/{username}/{password}/m3u_plus'
    
    for attempt in range(3):
        try:
            log(f"Baixando playlist via streaming (tentativa {attempt+1})...")
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            count_br = 0
            count_all = 0

            with urllib.request.urlopen(req, timeout=90) as response:
                with open('canais_brasil.m3u', 'w', encoding='utf-8') as f_br, open('canais.m3u', 'w', encoding='utf-8') as f_all:
                    f_br.write('#EXTM3U\n')
                    f_all.write('#EXTM3U\n')
                    
                    current_header = None
                    for raw_line in response:
                        line = raw_line.decode('utf-8', errors='ignore').strip()
                        if line.startswith('#EXTINF:'):
                            current_header = line
                        elif line.startswith('http') and current_header:
                            if '/series/' not in line and '/movie/' not in line:
                                f_all.write(current_header + '\n' + line + '\n')
                                count_all += 1
                                is_foreign = any(f'Canais | {k}' in current_header or f'Canais |  {k}' in current_header for k in FOREIGN_GROUPS)
                                if not is_foreign:
                                    f_br.write(current_header + '\n' + line + '\n')
                                    count_br += 1
                            current_header = None

            log(f"canais_brasil.m3u salvo ({count_br} canais)")
            log(f"canais.m3u salvo ({count_all} canais)")
            return
        except urllib.error.HTTPError as e:
            log(f"Erro HTTP {e.code} ao baixar playlist. Aguardando 5s para tentar novamente...")
            time.sleep(5)

    raise Exception("Não foi possível baixar a playlist após 3 tentativas.")

def main(force=False):
    log("=== Início do Processo de Auto-Renovação ===")
    
    if not force and check_active():
        log("✅ Credenciais atuais válidas e ativas. Nada a fazer.")
        return

    email, token = get_temp_email()
    generate_test(email)
    creds = read_email_credentials(token)

    with open('creds.json', 'w', encoding='utf-8') as f:
        json.dump(creds, f, indent=2)

    download_and_save_streaming(creds['username'], creds['password'], creds['server'])
    log("=== Processo Finalizado com Sucesso ===")

if __name__ == '__main__':
    force_arg = '--force' in sys.argv
    main(force=force_arg)
