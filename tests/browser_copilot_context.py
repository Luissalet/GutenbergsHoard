"""Opt-in native browser/MCP regression with private data and a scripted provider.

Run using Gutenberg's Python environment, --cli pointing to the headless
DesignCraft CLI, --sdk to the built shared chat component, and --output-dir to
a test artifact directory. Playwright may be installed in this environment or
supplied through --playwright-sitepackages. No shared app or model is started.
"""
import argparse
import asyncio
import hashlib
import json
import os
import socket
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--cli', type=Path, required=True)
parser.add_argument('--sdk', type=Path, required=True)
parser.add_argument('--playwright-sitepackages', type=Path)
args = parser.parse_args()
OUT = args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)
DATA = OUT / ('private-' + uuid.uuid4().hex)
DATA.mkdir()
os.environ.update(GUTENBERG_DATA_DIR=str(DATA), HOARD_EVENTS='0', HOARD_HUB_AUTOSTART='0',
                  HOARD_HUB_URL='http://127.0.0.1:1', HOARD_HOME=str(DATA / 'home'),
                  GUTENBERG_FAUSTUS_URL='http://127.0.0.1:1',
                  GUTENBERG_DESIGNCRAFT_CLI=str(args.cli.resolve()),
                  PYTHONPATH=str(ROOT))
sys.path.insert(0, str(ROOT))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def seed():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'gutenberg_hoard.mcp_server'],
                                  cwd=str(ROOT), env=dict(os.environ))
    with (OUT / 'mcp-stderr.log').open('w', encoding='utf8') as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = [tool.name for tool in (await session.list_tools()).tools]
                async def call(name, args):
                    result = await session.call_tool(name, args)
                    assert not result.isError, result.content
                    return result.structuredContent or json.loads(result.content[0].text)
                pub = await call('gutenberg_create_publication', {'title': 'Peer native context', 'pages': 2})
                edited = await call('gutenberg_designcraft_session', {'publication_id': pub['id'], 'actions': [
                    {'name': 'execute', 'arguments': {'command': 'frame.create', 'params': {
                        'spread': 0, 'rect': [50, 50, 250, 140], 'content': 'text', 'text': f'Peer story {i+1}'}}}
                    for i in range(31)]})
                insp = await call('gutenberg_inspect_publication', {'publication_id': pub['id']})
                sid = insp['stories'][-1]['id']
                story = await call('gutenberg_get_story', {'publication_id': pub['id'], 'story_id': sid})
                (OUT / 'native-mcp.json').write_text(json.dumps({'tools': names, 'publication_id': pub['id'],
                    'story_count': len(insp['stories']), 'selected_story_id': sid, 'selected_text': story['text']}, indent=2), encoding='utf8')
                return pub, sid

async def change_selected_story(context):
    publication = next(obj for obj in context['active_objects'] if obj['kind'] == 'publication')
    story = next(obj for obj in context['active_objects'] if obj['kind'] == 'story' and obj.get('selected'))
    params = StdioServerParameters(command=sys.executable, args=['-m', 'gutenberg_hoard.mcp_server'],
                                  cwd=str(ROOT), env=dict(os.environ))
    with (OUT / 'mcp-turn-stderr.log').open('w', encoding='utf8') as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('gutenberg_designcraft_session', {
                    'publication_id': publication['object_id'], 'actions': [{
                        'name': 'set_story_text', 'arguments': {'story': story['story_id'],
                        'text': 'Updated by private native MCP'}}]})
                assert not result.isError, result.content
                return result.structuredContent or json.loads(result.content[0].text)

def main():
    pub, sid = asyncio.run(seed())
    import httpx
    import uvicorn
    from gutenberg_hoard.engine_sessions import sessions
    if args.playwright_sitepackages:
        sys.path.append(str(args.playwright_sitepackages.resolve()))
    from playwright.sync_api import sync_playwright, expect
    sdk = args.sdk.read_bytes()
    turns = []
    conversations = {}
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, body, kind='application/json'):
            body = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            path = urlsplit(self.path).path
            if path.endswith('/capabilities'): self.reply({'contract_version': '1.0'})
            elif path.endswith('/panel.js'): self.reply(sdk, 'application/javascript')
            elif path.endswith('/conversations'): self.reply({'conversations': list(conversations.values())})
            elif '/conversations/' in path: self.reply(conversations.get(path.rsplit('/', 1)[-1], {}))
            else: self.reply({})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if self.path == '/api/chat_stream':
                context = body['hoard_context']
                result = asyncio.run(change_selected_story(context))
                turns.append({'context': context, 'tool': 'gutenberg_designcraft_session', 'result': result})
                frames = [{'type': 'tool_start', 'tool': 'gutenberg_designcraft_session'},
                    {'type': 'tool_output', 'tool': 'gutenberg_designcraft_session', 'output': json.dumps(result)},
                    {'delta': 'Selected native story updated.'}, {'type': 'end'}]
                stream = b''.join(b'data: ' + json.dumps(frame).encode() + b'\n\n' for frame in frames) + b'data: [DONE]\n\n'
                self.reply(stream, 'text/event-stream')
            else:
                conversations['peer-385'] = {'id': 'peer-385', 'session_id': 'peer-385',
                    'messages': [], 'name': 'Peer review', 'context': body.get('context')}
                self.reply(conversations['peer-385'])
        def do_PATCH(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0))); self.reply({'ok': True})
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    upthread = threading.Thread(target=upstream.serve_forever, daemon=True); upthread.start()
    os.environ['GUTENBERG_FAUSTUS_URL'] = f'http://127.0.0.1:{upstream.server_port}'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    blocked_connections = []
    original_connect = socket.socket.connect
    def private_connect(sock, address):
        # Windows' asyncio control socketpair connects to its own ephemeral port.
        if sys._getframe(1).f_code.co_name == '_fallback_socketpair':
            return original_connect(sock, address)
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1', 'localhost') and address[1] == 1:
            raise OSError('Disabled QA service')
        if isinstance(address, tuple) and (address[0] not in ('127.0.0.1', '::1', 'localhost')
                                            or address[1] not in (port, upstream.server_port)):
            blocked_connections.append(str(address))
            raise OSError('QA connection outside its private ports')
        return original_connect(sock, address)
    socket.socket.connect = private_connect
    # install_copilot captures its endpoint during import, so import only now.
    from gutenberg_hoard.app import app
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    base = f'http://127.0.0.1:{port}'
    result = {'source_root': str(ROOT), 'sdk_sha256': hashlib.sha256(sdk).hexdigest()}
    try:
        for _ in range(100):
            try:
                if httpx.get(base + '/api/health', timeout=1).status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(.05)
        else: raise RuntimeError('private server did not start')
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            def private_browser(route):
                target = urlsplit(route.request.url)
                if target.scheme in ('http', 'https') and target.netloc != f'127.0.0.1:{port}':
                    blocked_connections.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*', private_browser)
            page.goto(base)
            page.locator(f'.pub-card[data-id="{pub["id"]}"]').click()
            page.locator('#story-select').select_option(str(sid))
            expect(page.locator('#story-text')).to_have_value('Peer story 31')
            draft = 'x' * 1200 + ' UNSAVED_TAIL_385'
            page.locator('#story-text').fill(draft)
            initial = page.evaluate('window.hoardCopilot.context()')
            result['initial'] = initial
            result['draft_length'] = len(draft)
            result['context_draft_length'] = len(initial['view']['editor']['fields']['text'])
            result['unsaved_tail_missing'] = 'UNSAVED_TAIL_385' not in initial['view']['editor']['fields']['text']
            result['selected_story_missing'] = not any(obj.get('kind') == 'story' and obj.get('selected') for obj in initial['active_objects'])
            assert not result['unsaved_tail_missing'] and result['context_draft_length'] == len(draft)
            assert not result['selected_story_missing']
            page.get_by_role('button', name='Faustus', exact=True).click()
            expect(page.locator('faustus-chat textarea')).to_be_visible()
            page.locator('.hoard-copilot').get_by_role('button', name='Close Faustus', exact=True).click()
            def switch_view(route):
                reply = route.fetch()
                page.get_by_role('button', name='Settings', exact=True).click()
                route.fulfill(response=reply)
            page.route(base + '/api/publications/' + pub['id'], switch_view)
            crossed = page.evaluate('window.hoardCopilot.context()')
            page.unroute(base + '/api/publications/' + pub['id'], switch_view)
            result['crossed'] = crossed
            result['mixed_view'] = crossed['view']['page'] != initial['view']['page'] and bool(crossed['active_objects'])
            result['next'] = page.evaluate('window.hoardCopilot.context()')
            assert crossed == initial, {'initial': initial, 'crossed': crossed}
            assert result['next']['view']['page'] == 'settings' and result['next']['active_objects'] == []
            page.get_by_role('button', name='Pages', exact=True).click()
            page.wait_for_load_state('networkidle')
            expect(page.locator('#story-text')).to_have_value(draft)
            page.locator('#story-text').evaluate('(e)=>window.peerDraftNode=e')
            page.get_by_role('button', name='Faustus', exact=True).click()
            composer = page.locator('faustus-chat textarea')
            expect(composer).to_be_visible()
            page.wait_for_function('Boolean(document.querySelector("faustus-chat")?.sessionId)')
            page.locator('faustus-chat').evaluate("e=>e.addEventListener('faustus:turn-end',x=>document.body.dataset.peerTurn=x.detail.reason)")
            composer.fill('Update the selected saved story through its native tool')
            page.locator('faustus-chat').get_by_role('button', name='Send message', exact=True).click()
            expect(page.locator('body')).to_have_attribute('data-peer-turn', 'done', timeout=30000)
            expect(page.locator('#story-meta')).to_contain_text('this story changed in the document', timeout=10000)
            expect(page.locator('#story-text')).to_have_value(draft)
            assert page.locator('#story-text').evaluate('(e)=>e===window.peerDraftNode')
            saved = httpx.get(base + f'/api/publications/{pub["id"]}/stories/{sid}').json()
            assert saved['text'] == 'Updated by private native MCP'
            assert turns[0]['context']['view']['editor']['fields']['text'] == draft
            result['scripted_native_turn'] = {'tool': turns[0]['tool'], 'saved_text': saved['text'],
                'draft_preserved': True, 'same_editor_node': True, 'origin': turns[0]['context']['origin']}
            other = next(obj for obj in initial['active_objects'] if obj['kind'] == 'story' and not obj['selected'])
            assert httpx.get(base + f'/api/publications/{pub["id"]}/stories/{other["story_id"]}').json()['text'] == 'Peer story 1'
            panel = page.locator('faustus-chat')
            sid_before = panel.evaluate('(e)=>e.sessionId')
            composer.fill('Retained conversation draft')
            panel.evaluate('(e)=>window.peerPanel=e')
            checked_views = []
            for label in ['Workspace', 'Engine catalog', 'Settings', 'Pages']:
                page.locator('.hoard-copilot').get_by_role('button', name='Close Faustus', exact=True).click()
                page.get_by_role('button', name=label, exact=True).click()
                page.get_by_role('button', name='Faustus', exact=True).click()
                expect(composer).to_have_value('Retained conversation draft')
                assert panel.evaluate('(e)=>e===window.peerPanel && e.sessionId===' + json.dumps(sid_before))
                checked_views.append(label)
            expect(page.locator('#canvas img')).to_be_visible()
            assert 'is not iterable' not in panel.inner_text()
            result['all_views_same_panel_sid_draft'] = checked_views
            result['other_story_unchanged'] = True
            result['page_errors'] = errors
            assert errors == [], errors
            assert blocked_connections == [], blocked_connections
            result['private_connections_only'] = True
            page.screenshot(path=str(OUT / 'native-turn.png'))
            browser.close()
    finally:
        server.should_exit = True; thread.join(10)
        upstream.shutdown(); upstream.server_close(); upthread.join(5)
        sessions.shutdown()
        socket.socket.connect = original_connect
    (OUT / 'context-receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({key: result[key] for key in ['draft_length', 'context_draft_length', 'unsaved_tail_missing', 'selected_story_missing', 'mixed_view', 'page_errors']}))

if __name__ == '__main__': main()
