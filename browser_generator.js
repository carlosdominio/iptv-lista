const puppeteer = require('puppeteer');

async function submitTrial(email, targetUrl = 'https://teste.coreplay.vc/') {
  if (!email) {
    console.log(JSON.stringify({ status: 'error', message: 'Email not provided' }));
    process.exit(1);
  }

  const browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
      '--lang=pt-BR,pt'
    ]
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36');
    await page.emulateTimezone('America/Maceio');

    await page.evaluateOnNewDocument(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.chrome = { runtime: {} };
      Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
      Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });

      const getParameterProto = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Google Inc. (Intel)';
        if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameterProto.apply(this, arguments);
      };
      if (typeof WebGL2RenderingContext !== 'undefined') {
        const getParameter2Proto = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
          if (parameter === 37445) return 'Google Inc. (Intel)';
          if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)';
          return getParameter2Proto.apply(this, arguments);
        };
      }
    });

    let apiResponse = null;
    page.on('response', async (res) => {
      if (res.url().includes('/gerarteste')) {
        try {
          apiResponse = (await res.text()).trim();
        } catch (e) {}
      }
    });

    await page.goto(targetUrl, { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('#email', { timeout: 10000 });
    await page.type('#email', email, { delay: 40 });

    const ddds = ['82', '11', '21', '31', '41', '51', '71', '81', '85'];
    const ddd = ddds[Math.floor(Math.random() * ddds.length)];
    const num = '9' + Math.floor(70000000 + Math.random() * 29999999);
    const tel = `(${ddd}) ${num.slice(0, 5)}-${num.slice(5)}`;
    await page.type('#telefone', tel, { delay: 40 });

    await new Promise(r => setTimeout(r, 3000));
    await page.click('#gerar_user');

    for (let i = 0; i < 30; i++) {
      if (apiResponse) break;
      await new Promise(r => setTimeout(r, 500));
    }

    console.log(JSON.stringify({
      status: apiResponse || 'timeout',
      email: email,
      phone: tel
    }));
  } catch (err) {
    console.log(JSON.stringify({ status: 'error', message: err.message }));
  } finally {
    await browser.close();
  }
}

const targetEmail = process.argv[2];
const targetUrl = process.argv[3] || 'https://teste.coreplay.vc/';
submitTrial(targetEmail, targetUrl);
