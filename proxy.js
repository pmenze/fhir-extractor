// proxy.js
const http = require('http');
const https = require('https');

http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', '*');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  let body = '';
  req.on('data', d => body += d);
  req.on('end', () => {
    const r = https.request({
      hostname: 'api.anthropic.com', path: '/v1/messages', method: 'POST',
      headers: {
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      }
    }, upstream => {
      res.writeHead(upstream.statusCode, { 'content-type': 'application/json' });
      upstream.pipe(res);
    });
    r.write(body); r.end();
  });
}).listen(8787, () => console.log('Proxy läuft auf :8787'));