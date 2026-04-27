#!/usr/bin/env python3
"""
Skills Browser — Lightweight HTTP server for Hermes Skills
Three-panel layout:
  LEFT  — Agent → Skill tree
  CENTER — Skill content viewer
  RIGHT  — Agent chat (hermes --profile <agent> chat -q)
"""
import gzip, json, logging, os, re, subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('skills-browser')

SKILLS_BASE = Path.home() / '.hermes' / 'profiles'
PORT = 8383
HOST = '0.0.0.0'

INDEX_HTML = Path(__file__).parent / 'index.html'

# ── Helpers ───────────────────────────────────────────────────────────────────
HERMES_SKILLS = Path.home() / '.hermes' / 'skills'
OPENCLAW_SHARED = Path.home() / '.openclaw' / 'skills'
OPENCLAW_WORKSPACES = [
    ('openclaw-main', Path.home() / '.openclaw' / 'workspace' / 'skills'),
    ('openclaw-cad',  Path.home() / '.openclaw' / 'workspace_cad' / 'skills'),
]

def get_agents():
    base = Path(SKILLS_BASE)
    agents = set()
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and (d / 'skills').is_dir():
                agents.add(d.name)
    # ~/.hermes/skills/ → "hermes"
    if HERMES_SKILLS.exists() and any(HERMES_SKILLS.rglob('SKILL.md')):
        agents.add('hermes')
    # ~/.openclaw/skills/ → "openclaw"
    if OPENCLAW_SHARED.exists() and any(OPENCLAW_SHARED.rglob('SKILL.md')):
        agents.add('openclaw')
    # OpenClaw workspace skills → "openclaw-main", "openclaw-cad"
    for ws_name, ws_dir in OPENCLAW_WORKSPACES:
        if ws_dir.exists() and any(ws_dir.rglob('SKILL.md')):
            agents.add(ws_name)
    # hermes & openclaw pinned first, rest alphabetically
    sorted_agents = sorted(agents)
    for pinned in ('hermes', 'openclaw'):
        if pinned in sorted_agents:
            sorted_agents.remove(pinned)
            sorted_agents.insert(0, pinned)
    return sorted_agents

def get_skills_for_agent(agent):
    if agent == 'hermes':
        skills_dir = HERMES_SKILLS
    elif agent == 'openclaw':
        skills_dir = OPENCLAW_SHARED
    elif agent.startswith('openclaw-'):
        ws_map = dict(OPENCLAW_WORKSPACES)
        skills_dir = ws_map.get(agent)
    else:
        skills_dir = SKILLS_BASE / agent / 'skills'
    if not skills_dir or not skills_dir.exists():
        return [], []
    flat = []
    for md_path in sorted(skills_dir.rglob('SKILL.md')):
        rel = md_path.parent.relative_to(skills_dir)
        parts = rel.parts
        name = parts[-1] if parts else md_path.parent.name
        flat.append({
            'name': name,
            'path': str(md_path.parent),
            'relPath': str(rel),
            'depth': len(parts),
        })
    return flat, _build_tree(flat)

def _build_tree(skills):
    by_path = {}
    for s in skills:
        by_path[s['relPath']] = {**s, 'children': []}
    roots = []
    for s in skills:
        node = by_path[s['relPath']]
        if s['depth'] == 1:
            roots.append(node)
        else:
            parent_rel = str(Path(s['relPath']).parent)
            if parent_rel in by_path:
                by_path[parent_rel]['children'].append(node)
            else:
                roots.append(node)
    return roots

def get_skill_content(skill_path):
    p = Path(skill_path)
    f = p if p.is_file() else p / 'SKILL.md'
    if not f.exists():
        return None, None
    try:
        raw = f.read_text(encoding='utf-8', errors='ignore')
    except:
        return None, None
    body = re.sub(r'^---\r?\n[\s\S]*?\r?\n---\r?\n?', '', raw, count=1)
    return body.strip(), raw

def markdown_to_html(md_text):
    if not md_text:
        return ''
    lines = md_text.splitlines()
    html = []
    in_code = False
    in_ul = False

    for line in lines:
        if line.strip().startswith('```'):
            if not in_code:
                lang = line.strip()[3:]
                html.append(f'<pre><code class="lang-{lang}">')
                in_code = True
            else:
                html.append('</code></pre>')
                in_code = False
            continue
        if in_code:
            html.append(line.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'))
            continue

        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            if in_ul:
                html.append('</ul>')
                in_ul = False
            lvl = len(m.group(1))
            html.append(f'<h{lvl}>{_md_inline(m.group(2))}</h{lvl}>')
            continue

        if re.match(r'^---+$', line.strip()):
            if in_ul:
                html.append('</ul>')
                in_ul = False
            html.append('<hr>')
            continue

        if re.match(r'^    ', line):
            if in_ul:
                html.append('</ul>')
                in_ul = False
            html.append(f'<pre><code>{_md_inline(line.strip())}</code></pre>')
            continue

        m = re.match(r'^(\s*)[-*+]\s+(.*)', line)
        if m:
            indent = len(m.group(1))
            if not in_ul:
                html.append('<ul>')
                in_ul = indent
            html.append(f'<li>{_md_inline(m.group(2))}</li>')
            continue
        if in_ul and not re.match(r'^(\s*)[-*+]\s+', line) and line.strip():
            html.append('</ul>')
            in_ul = False

        m = re.match(r'^\s*\d+\.\s+(.*)', line)
        if m:
            if not in_ul:
                html.append('<ul>')
                in_ul = True
            html.append(f'<li>{_md_inline(m.group(1))}</li>')
            continue

        if line.strip():
            if in_ul:
                html.append('</ul>')
                in_ul = False
            html.append(f'<p>{_md_inline(line)}</p>')
        elif in_ul:
            html.append('</ul>')
            in_ul = False

    if in_ul:
        html.append('</ul>')
    return '\n'.join(html)

def _md_inline(text):
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank">\1</a>', text)
    return text

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass  # silent

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_html(self, body_text, status=200):
        body = body_text.encode('utf-8')
        # Try gzip
        try:
            compressed = gzip.compress(body, compresslevel=6)
            if len(compressed) < len(body):
                body = compressed
                encoding = 'gzip'
            else:
                encoding = None
        except Exception:
            encoding = None
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        if encoding:
            self.send_header('Content-Encoding', encoding)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/' or path == '/index.html':
            html = INDEX_HTML.read_text(encoding='utf-8')
            self.send_html(html)
        elif path == '/api/agents':
            self.send_json({'agents': get_agents()})
        elif path.startswith('/api/agents/'):
            agent_part = parsed.path.split('/api/agents/')[1]
            parts = agent_part.split('/')
            agent = parts[0]
            rest = '/'.join(parts[1:])
            if not rest:
                flat, tree = get_skills_for_agent(agent)
                self.send_json({'skills': flat, 'tree': tree, 'agent': agent})
            elif rest == 'content':
                qs = parse_qs(parsed.query)
                sp = qs.get('path', [''])[0]
                content, raw = get_skill_content(sp)
                if content is None:
                    self.send_json({'error': f'not found: {sp}'}, 404)
                else:
                    self.send_json({
                        'content': content,
                        'html': markdown_to_html(content),
                        'raw': raw
                    })
            else:
                self.send_json({'error': 'unknown endpoint'}, 404)
        else:
            self.send_json({'error': 'not found'}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        try:
            data = json.loads(body) if body else {}
        except:
            data = {}

        if parsed.path == '/api/log':
            log.info(f"[BROWSER] {data.get('msg','')}")
            self.send_json({'ok': True})
        elif parsed.path == '/api/chat/stream':
            self._proxy_sse(data)
        else:
            self.send_json({'error': 'not found'}, 404)

    def _proxy_sse(self, data):
        agent = data.get('agent', 'eva')
        message = data.get('message', '')
        skill_context = data.get('skill_context', '')

        if not message:
            self._send_sse({'type': 'chunk', 'content': '[Error] Empty message'})
            self._send_sse({'type': 'done'})
            return

        full_prompt = f"[Skill Context: {skill_context}]\n\n{message}" if skill_context else message

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        try:
            env = os.environ.copy()
            env['TERM'] = 'dumb'
            proc = subprocess.Popen(
                ['hermes', '--profile', agent, 'chat', '-q', full_prompt],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, env=env,
            )
            import threading
            def read_stdout():
                try:
                    buf = []
                    for line in iter(proc.stdout.readline, ''):
                        clean = self._strip_ansi(line)
                        if not clean:
                            continue
                        skip_prefixes = (
                            'MemPalace', 'Hermes Agent', 'Available Tools',
                            'Available Skills', 'Profile:', 'Session:', 'Duration:',
                            'Messages:', 'Resume this', 'hermes --resume',
                            'Initializing agent', 'Query:', 'MCP Servers',
                        )
                        skip_patterns = (
                            '...', 'tools ·', 'skills ·', 'MCP servers',
                            '/help for commands', 'bodr:', 'devops:', 'eva-self-',
                            'general:', 'knowledge-management:', 'openclaw:',
                            'system-design:', 'workflow: Supervisor',
                            'mempalace (stdio)', 'browser:', 'browser-cdp:',
                            'clarify:', 'code_execution:', 'cronjob:', 'delegation:',
                            'discord:', 'file: patch', 'write_file',
                            '(and', '· Nous', '· MiniMax',
                            '框架——', 'bbt-', 'mempalace',
                            '/home/tooyan', 'business:', 'data-processing:',
                            'windows-ssh-debug', 'system-admin:',
                            'bod:', 'kanban:', 'security:',
                            'markdown-table-parse-pipes', 'product-position-detector',
                        )
                        if any(clean.startswith(p) for p in skip_prefixes):
                            continue
                        if any(p in clean for p in skip_patterns):
                            continue
                        clean = re.sub(r'^⚕\s*Hermes\s*', '', clean)
                        if not clean:
                            continue
                        if re.match(r'^[a-z][a-z0-9\-]*:', clean):
                            continue
                        is_uppercase_start = clean[0].isupper() if clean else False
                        has_emoji = any(ord(c) > 0x1F300 for c in clean)
                        is_short = len(clean.split()) <= 15
                        if not (is_uppercase_start or has_emoji or is_short):
                            continue
                        buf.append(clean)
                        if len(buf) >= 8:
                            self._send_sse({'type': 'chunk', 'content': ' '.join(buf) + '\n'})
                            buf = []
                    if buf:
                        self._send_sse({'type': 'chunk', 'content': ' '.join(buf) + '\n'})
                except Exception:
                    pass
            t = threading.Thread(target=read_stdout, daemon=True)
            t.start()
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                self._send_sse({'type': 'chunk', 'content': '[Timeout] Agent did not respond in 90s.'})
            t.join(timeout=2)
        except FileNotFoundError:
            self._send_sse({'type': 'chunk', 'content': '[Error] hermes CLI not found'})
        except Exception as e:
            self._send_sse({'type': 'chunk', 'content': f'[Error] {str(e)}'})

        self._send_sse({'type': 'done'})

    def _send_sse(self, data):
        try:
            event = f"data: {json.dumps(data)}\n\n"
            self.wfile.write(event.encode('utf-8'))
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def _strip_ansi(self, text):
        text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        text = re.sub(r'[\u2500-\u257F\u2800-\u28FF\u2560-\u256A\u256C-\u257F]', '', text)
        if '\r' in text:
            text = text.split('\r')[-1]
        text = re.sub(r' {2,}', ' ', text)
        text = re.sub(r'\n{2,}', '\n', text)
        return text.strip()

if __name__ == '__main__':
    log.info(f'Starting Skills Browser on http://{HOST}:{PORT}')
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info(f'Open http://localhost:{PORT} in browser')
    server.serve_forever()
