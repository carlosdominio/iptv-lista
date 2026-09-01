#!/usr/bin/env python3
"""
Renovador Automático IPTV para GitHub Actions.
Gera credenciais de teste gratuitas, baixa o stream e atualiza as listas M3U no repositório.
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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_temp_email():
    log("Criando caixa de e-mail temporária...")
    req = urllib.request.Request('https://api.mail.tm/domains', headers={'Accept': 'application/ld+json'})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    if isinstance(data, list):
        domains = [d['domain'] for d in data if isinstance(d, dict)]
    else:
        members = data.get('hydra:member', data.get('member', []))
        domains = [d['domain'] for d in members]
    domain = domains[0]

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

    log(f"E-mail gerado com sucesso: {email}")
    return email, tok['token']

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
    time.sleep(20)

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
            log(f"Tentativa {attempt+1}/{max_attempts} - aguardando...")
        except Exception as e:
            log(f"Aviso na tentativa {attempt+1}: {e}")

        if attempt < max_attempts - 1:
            time.sleep(10)

    raise Exception("Tempo limite esgotado sem receber e-mail de ativação.")

def download_and_save(username, password, server="http://drd33.com"):
    log("Baixando playlist M3U atualizada...")
    url = f'{server}/playlist/{username}/{password}/m3u_plus'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    content = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', errors='ignore')

    all_live = []
    br_live = []
    current = None

    for line in content.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            current = line
        elif line.startswith('http') and current:
            if '/series/' not in line and '/movie/' not in line:
                all_live.append((current, line))
                is_foreign = any(f'Canais | {k}' in current or f'Canais |  {k}' in current for k in FOREIGN_GROUPS)
                if not is_foreign:
                    br_live.append((current, line))
            current = None

    with open('canais_brasil.m3u', 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for h, u in br_live:
            f.write(h + '\n' + u + '\n')
    log(f"canais_brasil.m3u salvo ({len(br_live)} canais)")

    with open('canais.m3u', 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for h, u in all_live:
            f.write(h + '\n' + u + '\n')
    log(f"canais.m3u salvo ({len(all_live)} canais)")

def main():
    log("=== Início do Processo de Auto-Renovação ===")
    email, token = get_temp_email()
    generate_test(email)
    creds = read_email_credentials(token)

    with open('creds.json', 'w', encoding='utf-8') as f:
        json.dump(creds, f, indent=2)

    download_and_save(creds['username'], creds['password'], creds['server'])
    log("=== Processo Finalizado com Sucesso ===")

if __name__ == '__main__':
    main()
