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
    executablePath: '/home/carlosrikelinux/.cache/puppeteer/chrome/linux-152.0.7977.75/chrome-linux64/chrome',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
      '--incognito',
      '--lang=pt-BR,pt'
    ]
  });

  try {
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    
    await page.setViewport({ width: 1366, height: 768 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36');
    await page.emulateTimezone('America/Maceio');

    let apiResponse = null;
    let postData = null;

    page.on('request', (req) => {
      if (req.url().includes('/gerarteste') && req.method() === 'POST') {
        postData = req.postData();
      }
    });

    page.on('response', async (res) => {
      if (res.url().includes('/gerarteste')) {
        try {
          apiResponse = (await res.text()).trim();
        } catch (e) {}
      }
    });

    await page.goto(targetUrl, { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('#email', { timeout: 10000 });

    // Move mouse and click email input
    await page.click('#email');
    await page.type('#email', email, { delay: 50 });

    // Focus phone input and type clean digits (e.g. DDD 82 + 9 + 8 digits)
    const ddds = ['82', '11', '71', '81', '85'];
    const ddd = ddds[Math.floor(Math.random() * ddds.length)];
    const num = '9' + Math.floor(80000000 + Math.random() * 19999999);
    const cleanPhone = `${ddd}${num}`;

    await page.click('#telefone');
    await page.type('#telefone', cleanPhone, { delay: 50 });

    // Trigger blur/change events
    await page.evaluate(() => {
      const tel = document.getElementById('telefone');
      if (tel) {
        tel.dispatchEvent(new Event('change', { bubbles: true }));
        tel.dispatchEvent(new Event('blur', { bubbles: true }));
      }
      const em = document.getElementById('email');
      if (em) {
        em.dispatchEvent(new Event('change', { bubbles: true }));
        em.dispatchEvent(new Event('blur', { bubbles: true }));
      }
    });

    await new Promise(r => setTimeout(r, 2000));

    // Click submit button
    await page.click('#gerar_user');

    // Wait for response up to 25 seconds
    for (let i = 0; i < 50; i++) {
      if (apiResponse) break;
      await new Promise(r => setTimeout(r, 500));
    }

    console.log(JSON.stringify({
      status: apiResponse || 'timeout',
      email: email,
      phone: cleanPhone,
      postData: postData
    }));

    if (apiResponse !== 'sendok') {
      await page.screenshot({ path: 'browser_result.png' });
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
