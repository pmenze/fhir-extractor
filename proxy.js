// proxy.js
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

function loadSystemPrompt() {
  const base = __dirname;
  const template = fs.readFileSync(path.join(base, 'system_prompt.txt'), 'utf8');
  const example = fs.readFileSync(path.join(base, 'example_bundle.json'), 'utf8').trim();
  return template.replace('{EXAMPLE_BUNDLE}', example);
}

http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', '*');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  if (req.method === 'GET' && req.url === '/prompt') {
    try {
      const prompt = loadSystemPrompt();
      res.writeHead(200, { 'content-type': 'text/plain; charset=utf-8' });
      res.end(prompt);
    } catch (e) {
      res.writeHead(500, { 'content-type': 'text/plain' });
      res.end('Fehler beim Laden des Prompts: ' + e.message);
    }
    return;
  }

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
