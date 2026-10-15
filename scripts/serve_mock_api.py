"""Explicit localhost-only Swagger simulator. Never bind to external interfaces."""
import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.store import Store
from core.api_simulator import LocalAPI


def handler_for(api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # no tokens or patient payloads
        def handle_api(self):
            body=None
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<0 or size>100_000: raise ValueError()
                if size: body=json.loads(self.rfile.read(size))
            except (ValueError,UnicodeError):
                self.send_response(400); self.end_headers(); return
            response=api.request(self.command,self.path,body,headers=dict(self.headers))
            data=json.dumps(response.data,ensure_ascii=False).encode('utf-8')
            self.send_response(response.status or 500)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            if self.command=='OPTIONS':
                self.send_header('Allow','GET, HEAD, OPTIONS' if '/doctors' in self.path else 'GET, POST, PATCH, HEAD, OPTIONS')
            if response.status==429: self.send_header('Retry-After',str(int(response.retry_after)))
            self.end_headers()
            try:
                if self.command!='HEAD': self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError): pass
        do_GET=do_POST=do_PATCH=do_DELETE=do_PUT=do_HEAD=do_OPTIONS=handle_api
    return Handler


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    server=ThreadingHTTPServer(('127.0.0.1',8765),handler_for(LocalAPI(Store(root/'data/clinic_demo.sqlite3'))))
    print('MOCK ONLY: http://127.0.0.1:8765/api/v1; local-demo-token (public fixture credential)')
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
