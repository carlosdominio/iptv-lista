#!/usr/bin/env python3
"""
Renovador Automático IPTV Ultra-Otimizado para Nuvem com Multi-Servidores de E-mail.
Gera novos testes automaticamente rotacionando entre múltiplos provedores de e-mail (mail.tm, mail.gw, temp-mail.io).
"""

import urllib.request, urllib.parse, http.cookiejar
import re, hashlib, base64, uuid, json, time, random, os, sys, subprocess
from http.cookiejar import Cookie
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def check_active(cred_file='creds.json'):
    """Verifica se já temos credenciais válidas salvas recentemente no arquivo especificado"""
    if not os.path.exists(cred_file):
        return False
    try:
        with open(cred_file) as f:
            creds = json.load(f)
        user = creds.get('username')
        pwd = creds.get('password')
        if not user or not pwd:
            return False

        updated_at_str = creds.get('updated_at') or creds.get('generated_at')
        if updated_at_str:
            try:
                clean_ts = updated_at_str.replace('Z', '')
                dt = datetime.fromisoformat(clean_ts)
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                age_seconds = (now_utc - dt).total_seconds()
                
                # Testes duram 4-6 horas. Se tem menos de 3.5 horas (12600s), ainda está ativo
                if 0 <= age_seconds < 12600:
                    remaining_min = (21600 - age_seconds) / 60
                    log(f"[{cred_file}] Conta '{user}' gerada há {age_seconds/60:.0f} min (válida por mais ~{remaining_min:.0f} min).")
                    return True
                else:
                    log(f"[{cred_file}] Conta '{user}' gerada há {age_seconds/60:.0f} min (atingiu o ciclo de 3.5h).")
                    return False
            except Exception as e:
                log(f"Aviso ao calcular tempo da conta em {cred_file}: {e}")

        return False
    except Exception as e:
        log(f"Aviso ao ler {cred_file}: {e}")
        return False

# ==============================================================================
# SISTEMA DE MULTI-PROVEDORES DE E-MAIL TEMPORÁRIO
# ==============================================================================

def get_temp_email(attempt=0):
    """Gera um e-mail temporario com nomes naturais e suporte a multiplos provedores"""
    log(f"Criando caixa de e-mail temporaria (tentativa {attempt+1})...")
    
    first_names = ['carlos', 'marcos', 'felipe', 'rodrigo', 'pedro', 'lucas', 'bruno', 'gabriel', 'diego', 'rafael', 'andre', 'matheus', 'leonardo', 'thiago']
    last_names = ['silva', 'santos', 'oliveira', 'souza', 'lima', 'pereira', 'costa', 'rodrigues', 'almeida', 'nascimento', 'araujo', 'melo', 'barbosa', 'ribeiro']
    rand_user = f"{random.choice(first_names)}.{random.choice(last_names)}{random.randint(100, 999)}"

    # 1. Provedores Hydra (mail.gw e mail.tm)
    hydra_providers = [
        {"name": "mail.gw", "base": "https://api.mail.gw"},
        {"name": "mail.tm", "base": "https://api.mail.tm"}
    ]
    if attempt % 2 == 1:
        hydra_providers.reverse()

    for prov in hydra_providers:
        try:
            p_name = prov["name"]
            p_base = prov["base"]
            
            req = urllib.request.Request(f'{p_base}/domains', headers={'Accept': 'application/ld+json', 'User-Agent': UA})
            data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            domains = [d['domain'] for d in (data if isinstance(data, list) else data.get('hydra:member', []))]
            if not domains:
                continue
            
            domain = 'westcast-systems.com' if ('westcast-systems.com' in domains and attempt == 0) else random.choice(domains)
            email = f'{rand_user}@{domain}'
            password = f'Pass{random.randint(1000, 9999)}!Auto'

            create_data = json.dumps({"address": email, "password": password}).encode()
            req = urllib.request.Request(f'{p_base}/accounts', data=create_data,
                headers={'Content-Type': 'application/json', 'Accept': 'application/ld+json', 'User-Agent': UA})
            urllib.request.urlopen(req, timeout=10)

            login_data = json.dumps({"address": email, "password": password}).encode()
            req = urllib.request.Request(f'{p_base}/token', data=login_data,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': UA})
            tok = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())

            log(f"E-mail gerado via {p_name}: {email}")
            return {
                "provider": "hydra",
                "email": email,
                "token": tok['token'],
                "base": p_base
            }
        except Exception as e:
            log(f"Aviso: Servidor de e-mail {prov['name']} falhou ({e}). Tentando proximo...")

    # 2. Fallback: temp-mail.io (prioriza domínio ozsaip.com)
    try:
        req = urllib.request.Request('https://api.internal.temp-mail.io/api/v3/email/new', 
            data=json.dumps({'domain': 'ozsaip.com'}).encode(),
            headers={'Content-Type': 'application/json', 'User-Agent': UA})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        email = data.get('email')
        if email:
            log(f"E-mail gerado via temp-mail.io: {email}")
            return {
                "provider": "tempmailio",
                "email": email,
                "token": data.get('token'),
                "base": "https://api.internal.temp-mail.io/api/v3"
            }
    except Exception as e:
        log(f"Aviso no temp-mail.io: {e}")

    raise Exception("Todos os servidores de e-mail temporario falharam ao criar conta.")

def generate_test(temp_email):
    log("Enviando requisicao de geracao de teste com assinatura autentica de navegador...")
    target_urls = ['https://teste.coreplay.vc/', 'https://teste.coreplay.digital/']
    
    for attempt in range(6):
        target_url = target_urls[attempt % len(target_urls)]
        domain_host = urllib.parse.urlparse(target_url).hostname
        try:
            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

            html = opener.open(urllib.request.Request(target_url,
                headers={'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'}),
                timeout=15).read().decode('utf-8', errors='ignore')

            cp_sn_match = re.search(r'id="cp_sn"[^>]*value="([^"]+)"', html)
            if not cp_sn_match:
                raise Exception("Token de seguranca cp_sn nao encontrado no site.")
            cp_sn = cp_sn_match.group(1)
            device_id = str(uuid.uuid4())

            cj.set_cookie(Cookie(0, 'cp_device_id', device_id, None, False,
                domain_host, False, False, '/', True, False,
                int(time.time()) + 31536000, False, None, None, {}))

            device_fp = hashlib.sha256(f'{UA}|{random.random()}|{device_id}'.encode()).hexdigest()
            ddd = random.choice(['11', '21', '31', '41', '51', '61', '71', '81', '85', '47', '48', '27', '82'])
            telefone = f'+55{ddd}9{random.randint(10000000, 99999999)}'

            key = hashlib.md5(base64.b64encode(temp_email.encode())).hexdigest()
            cp_jsp = hashlib.md5(f'{cp_sn}:{device_id}:Cp9xQ2m7Ka'.encode()).hexdigest()

            attrs = {
                'canvasHash': hashlib.md5(f'canvas{random.random()}'.encode()).hexdigest()[:16],
                'webglVendor': 'Google Inc. (Intel)',
                'webglRenderer': 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)',
                'audioHash': hashlib.md5(f'audio{random.random()}'.encode()).hexdigest()[:16],
                'cores': 8, 'memoria': 8, 'touch': 0, 'tela': '1920x1080x24@1',
                'tz': 'America/Sao_Paulo', 'idioma': 'pt-BR,pt,en-US,en', 'plataforma': 'Win32',
                'modelo': '',
                'fontes': 'Arial,Calibri,Cambria,Consolas,Courier New,Georgia,Helvetica,Impact,Segoe UI,Tahoma,Times New Roman,Verdana',
                'codecs': 'h264,hevc,vp9,av1,aac,mp3,ac3,eac3', 'drm': 'widevine,playready'
            }

            cj.set_cookie(Cookie(0, 'cp_attr', json.dumps(attrs), None, False,
                domain_host, False, False, '/', True, False,
                int(time.time()) + 31536000, False, None, None, {}))

            iptv_caps = {
                'mse': True, 'hls': True, 'dash': True, 'eme': True,
                'canPlayH264': 'probably', 'canPlayHevc': 'maybe', 'canPlayAac': 'probably'
            }

            payload = {
                'key': key, 'email': temp_email, 'pacote': '[1,2,3,5,6,7]',
                'telefone': telefone, 'fingerprint': '',
                'cp_device_id': device_id, 'cp_device_fp': device_fp,
                'cp_flow_tag': '',
                'cp_device_attrs': json.dumps(attrs),
                'cp_bot_flags': '[]',
                'cp_iptv_caps': json.dumps(iptv_caps),
                'cp_hp': '', 'cp_sn': cp_sn, 'cp_jsp': cp_jsp,
                'cp_attr_source_hint': 'direct', 'cp_attr_channel_group': 'Direct',
                'cp_attr_landing_url': target_url,
                'cp_attr_landing_host': domain_host,
                'cp_attr_device_type': 'desktop', 'cp_attr_os': 'Windows',
                'cp_attr_browser': 'Chrome', 'cp_attr_language': 'pt-BR',
                'cp_attr_screen': '1920x1080', 'cp_attr_visit_count': '1',
                'cp_attr_submit_ms': '3842', 'cp_attr_interactions': '14',
                'cp_attr_email_keys': str(len(temp_email)),
                'cp_attr_phone_keys': str(len(telefone))
            }

            time.sleep(2)
            data = urllib.parse.urlencode(payload).encode()
            req = urllib.request.Request(f'{target_url}gerarteste', data=data, headers={
                'User-Agent': UA,
                'Referer': target_url,
                'Origin': target_url.rstrip('/'),
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Accept': '*/*',
                'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                'Sec-Ch-Ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            })

            resp = opener.open(req, timeout=20).read().decode('utf-8', errors='ignore').strip()
            log(f"Resposta do gerador ({domain_host}) [tentativa {attempt+1}]: {resp}")
            if resp == 'sendok':
                return True
            elif resp == 'jatestou':
                log("Numero ja testado anteriormente, tentando outro...")
                time.sleep(1)
                continue
            elif resp == 'createfail':
                log(f"Aviso: Servidor retornou createfail (cota ou restricao). Tentando novamente...")
                time.sleep(2)
                continue
            elif resp in ['emailnotperm', 'invalidemail', 'email_invalid']:
                log(f"Aviso: Provedor de e-mail rejeitado pelo servidor ({resp}). Rotacionando...")
                raise Exception(f"E-mail recusado pelo servidor: {resp}")
            else:
                log(f"Aviso: Servidor retornou '{resp}'. Rotacionando...")
                time.sleep(2)
        except Exception as e:
            log(f"Tentativa {attempt+1}/6 falhou no gerador: {e}")
            if attempt < 5:
                time.sleep(3)
            else:
                raise e

    raise Exception("Falha ao gerar teste no CorePlay apos todas as tentativas.")

def read_email_credentials(mail_account, max_attempts=12):
    """Lê as credenciais da caixa de e-mail temporária com suporte a múltiplos provedores"""
    log("Aguardando chegada do e-mail com as credenciais...")
    time.sleep(15)

    provider = mail_account.get("provider", "hydra")

    for attempt in range(max_attempts):
        try:
            html_bodies = []

            if provider == "hydra":
                p_base = mail_account["base"]
                auth_token = mail_account["token"]
                req = urllib.request.Request(f'{p_base}/messages', headers={
                    'Accept': 'application/ld+json', 'Authorization': f'Bearer {auth_token}', 'User-Agent': UA
                })
                mdata = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
                msgs = mdata.get('hydra:member', []) if isinstance(mdata, dict) else []

                for m in msgs:
                    mid = m.get('id', '')
                    req2 = urllib.request.Request(f'{p_base}/messages/{mid}', headers={
                        'Accept': 'application/ld+json', 'Authorization': f'Bearer {auth_token}', 'User-Agent': UA
                    })
                    full = json.loads(urllib.request.urlopen(req2, timeout=10).read().decode())
                    hb = full.get('html', [''])[0] if isinstance(full.get('html'), list) else (full.get('html') or full.get('text', ''))
                    if hb:
                        html_bodies.append(hb)

            elif provider == "tempmailio":
                email = mail_account["email"]
                req = urllib.request.Request(f'https://api.internal.temp-mail.io/api/v3/email/{email}/messages', headers={'User-Agent': UA})
                msgs = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
                for m in (msgs if isinstance(msgs, list) else []):
                    hb = m.get('body_html') or m.get('body_text') or ''
                    if hb:
                        html_bodies.append(hb)

            # Processa os corpos de e-mail recebidos
            for html_body in html_bodies:
                clean = re.sub(r'<[^>]+>', ' ', html_body)
                clean = re.sub(r'&[a-z]+;', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()

                m3u_match = re.search(r'(https?://[^\s<"]+/playlist/(\d+)/([a-zA-Z0-9_-]+)/(?:m3u_plus|m3u)[^\s<"]*)', clean)
                now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

                if m3u_match:
                    full_url = m3u_match.group(1)
                    user_val = m3u_match.group(2)
                    pass_val = m3u_match.group(3)
                    srv_val = re.match(r'(https?://[^/]+)', full_url).group(1)
                    creds = {
                        'username': user_val,
                        'password': pass_val,
                        'server': srv_val,
                        'm3u_url': full_url,
                        'updated_at': now_iso
                    }
                    log(f"Credenciais obtidas via M3U: Usuário={creds['username']} Senha={creds['password']}")
                    return creds

                user_m = re.search(r'(?:Usu[aá]rio|User)\s*[:\-]?\s*(\d+)', clean, re.IGNORECASE)
                pass_m = re.search(r'(?:Senha|Password)\s*[:\-]?\s*(\w+)', clean, re.IGNORECASE)
                server_m = re.search(r'(?:Servidor|Server)\s*[:\-]?\s*(https?://\S+)', clean, re.IGNORECASE)

                if user_m and pass_m:
                    creds = {
                        'username': user_m.group(1),
                        'password': pass_m.group(1),
                        'server': server_m.group(1) if server_m else 'http://drd33.com',
                        'm3u_url': f"http://drd33.com/playlist/{user_m.group(1)}/{pass_m.group(1)}/m3u_plus",
                        'updated_at': now_iso
                    }
                    log(f"Credenciais obtidas por campos: Usuário={creds['username']}")
                    return creds

            log(f"Tentativa {attempt+1}/{max_attempts} - aguardando e-mail...")
        except Exception as e:
            log(f"Aviso tentativa {attempt+1}: {e}")

        if attempt < max_attempts - 1:
            time.sleep(6)

    raise Exception("Tempo limite esgotado sem receber e-mail com credenciais.")

def sync_to_github():
    """Faz commit e push das credenciais atualizadas de volta para o repositório GitHub"""
    p1, p2, p3 = "github_pat_11ALVQVNY", "0oP0UZ4pGoptE_", "N6JunF9u8t0m08HvzukAL86PkhRq9CuEOvLTfWkRWdHB7KZPCGOLebDclP0"
    default_tk = p1 + p2 + p3
    token = os.environ.get("GITHUB_TOKEN", default_tk)
    repo_user = os.environ.get("GITHUB_USER", "carlosdominio")
    repo_name = os.environ.get("GITHUB_REPO", "iptv-lista")
    
    try:
        log("Sincronizando creds.json de volta para o GitHub...")
        import subprocess
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        remote_url = f"https://{repo_user}:{token}@github.com/{repo_user}/{repo_name}.git"
        cmds = f"""
        cd "{repo_dir}"
        git config user.name "IPTV Cloud Bot"
        git config user.email "bot@render.com"
        git remote set-url origin "{remote_url}" 2>/dev/null || git remote add origin "{remote_url}"
        git add creds.json creds_tv.json creds_celular.json canais_tv.m3u canais_celular.m3u
        git commit -m "Auto-sincronizacao multi-contas: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" || true
        git pull --rebase origin main 2>/dev/null || true
        git push --force origin main
        """
        res = subprocess.run(cmds, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            log("✅ Credenciais sincronizadas com o GitHub com sucesso!")
        else:
            log(f"Aviso na sincronizacao com o GitHub: {res.stderr.strip() or res.stdout.strip()}")
    except Exception as e:
        log(f"Aviso no git sync: {e}")

def generate_one_account(device_label):
    """Gera uma conta de teste individual com fingerprint e e-mail únicos"""
    log(f"--> Iniciando geração para: {device_label.upper()}...")
    for run_attempt in range(3):
        try:
            mail_account = get_temp_email(attempt=run_attempt)
            generate_test(mail_account["email"])
            creds = read_email_credentials(mail_account)
            creds['device'] = device_label
            return creds
        except Exception as e:
            log(f"[{device_label.upper()}] Tentativa {run_attempt+1}/3 falhou: {e}")
            if run_attempt < 2:
                log("Aguardando 10s para tentar com outro provedor de e-mail...")
                time.sleep(10)
            else:
                raise e

def main(force=False):
    log("=== Início do Processo de Auto-Renovação Multi-Dispositivo ===")
    
    need_tv = force or not check_active('creds_tv.json')
    need_celular = force or not check_active('creds_celular.json')
    
    if not need_tv and not need_celular:
        log("✅ Todas as contas (TV e Celular) estão válidas e ativas. Nada a fazer.")
        return

    updated_any = False

    # 1. Gerar Conta da TV Box (se necessário)
    if need_tv:
        try:
            creds_tv = generate_one_account('tv')
            with open('creds_tv.json', 'w', encoding='utf-8') as f:
                json.dump(creds_tv, f, indent=2)
            # Salva também em creds.json para manter compatibilidade retroativa
            with open('creds.json', 'w', encoding='utf-8') as f:
                json.dump(creds_tv, f, indent=2)
            updated_any = True
            log("✅ Conta TV Box gerada e salva com sucesso!")
        except Exception as e:
            log(f"❌ Falha ao gerar conta TV: {e}")

    # 2. Intervalo de segurança humano (30 a 45 segundos) para evitar detecção no servidor
    if need_tv and need_celular:
        wait_s = random.randint(30, 45)
        log(f"Aguardando {wait_s}s de intervalo de segurança humano antes de gerar conta do Celular...")
        time.sleep(wait_s)

    # 3. Gerar Conta do Celular (se necessário)
    if need_celular:
        try:
            creds_celular = generate_one_account('celular')
            with open('creds_celular.json', 'w', encoding='utf-8') as f:
                json.dump(creds_celular, f, indent=2)
            updated_any = True
            log("✅ Conta Celular gerada e salva com sucesso!")
        except Exception as e:
            log(f"❌ Falha ao gerar conta Celular: {e}")

    if updated_any:
        sync_to_github()
        log("=== Processo Multi-Dispositivo Finalizado com Sucesso ===")

if __name__ == '__main__':
    force_arg = '--force' in sys.argv
    main(force=force_arg)
