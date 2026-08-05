// Cloudflare Worker: релей на api.telegram.org (для обхода блокировки из РФ).
//
// Как настроить:
//   1. https://dash.cloudflare.com → Workers & Pages → Create → Create Worker
//   2. Название, например: tg-mod-bot (получишь https://tg-mod-bot.<субдомен>.workers.dev)
//   3. Удали шаблон, вставь код ниже, Deploy.
//   4. В .env бота укажи: BOT_API_BASE_URL=https://tg-mod-bot.<субдомен>.workers.dev
//
// Cloudflare в РФ не блокируется, поэтому запросы бота доходят через него.

export default {
  async fetch(request) {
    const url = new URL(request.url);
    url.protocol = "https:";
    url.hostname = "api.telegram.org";

    const headers = new Headers(request.headers);
    headers.delete("host");

    const upstream = await fetch(url.toString(), {
      method: request.method,
      headers: headers,
      body: request.body,
    });

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: upstream.headers,
    });
  },
};
