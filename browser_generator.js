const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

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
      '--incognito', // Simulate an incognito tab
      '--lang=pt-BR,pt',
      '--proxy-server=http://177.93.49.114:999'
    ]
  });

  try {
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    
    await page.setViewport({ width: 1920, height: 1080 });
    // Use a solid Windows user agent
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36');
    await page.emulateTimezone('America/Sao_Paulo');

    // Remove old manual stealth overrides, letting puppeteer-extra-plugin-stealth do its job.

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
    await page.type('#email', email, { delay: 60 }); // Slower typing for humanity

    const ddds = ['82', '11', '21', '31', '41', '51', '71', '81', '85'];
    const ddd = ddds[Math.floor(Math.random() * ddds.length)];
    const num = '9' + Math.floor(70000000 + Math.random() * 29999999); // E.g., 987654321
    const tel = `(${ddd}) ${num.slice(0, 5)}-${num.slice(5)}`;
    await page.type('#telefone', tel, { delay: 60 });

    await new Promise(r => setTimeout(r, 4000)); // wait a bit more like a user reading
    await page.click('#gerar_user');

    for (let i = 0; i < 40; i++) {
      if (apiResponse) break;
      await new Promise(r => setTimeout(r, 500));
    }

    console.log(JSON.stringify({
      status: apiResponse || 'timeout',
      email: email,
      phone: tel
    }));
    
    if (apiResponse === 'createfail' || !apiResponse) {
      await page.screenshot({ path: 'createfail_screenshot.png' });
    }
  } catch (err) {
    console.log(JSON.stringify({ status: 'error', message: err.message }));
  } finally {
    await browser.close();
  }
}

const targetEmail = process.argv[2];
const targetUrl = process.argv[3] || 'https://teste.coreplay.vc/';
submitTrial(targetEmail, targetUrl);
