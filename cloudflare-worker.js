/**
 * Cloudflare Worker - Relay / Mascarador de IP
 * Gratuito (100.000 requisições/dia)
 * 
 * Como usar:
 * 1. Acesse https://dash.cloudflare.com
 * 2. Vá em 'Workers & Pages' -> 'Create Application' -> 'Create Worker'
 * 3. Clique em 'Deploy' e depois em 'Edit Code'
 * 4. Cole este código no editor e clique em 'Save and Deploy'
 */

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }

    const url = new URL(request.url);
    const targetUrl = url.searchParams.get("url") || request.headers.get("X-Target-URL");

    if (!targetUrl) {
      return new Response("Cloudflare Relay Ativo! Passe o destino via ?url=https://...", {
        status: 200,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    const newHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
      const k = key.toLowerCase();
      if (!["host", "cf-connecting-ip", "cf-ray", "cf-ipcountry", "x-forwarded-for", "x-target-url"].includes(k)) {
        newHeaders.set(key, value);
      }
    }

    try {
      const hasBody = request.method !== "GET" && request.method !== "HEAD";
      const bodyData = hasBody ? await request.arrayBuffer() : undefined;

      const response = await fetch(targetUrl, {
        method: request.method,
        headers: newHeaders,
        body: bodyData,
        redirect: "follow",
      });

      const respHeaders = new Headers(response.headers);
      respHeaders.set("Access-Control-Allow-Origin", "*");

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: respHeaders,
      });
    } catch (err) {
      return new Response("Erro ao conectar no destino: " + err.message, {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
  },
};
