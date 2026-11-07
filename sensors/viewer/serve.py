"""Run the standalone viewer; bind only to this computer by default."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial
import argparse

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',type=int,default=5174)
args=parser.parse_args()
root=Path(__file__).resolve().parent
class Handler(SimpleHTTPRequestHandler):
    extensions_map={**SimpleHTTPRequestHandler.extensions_map,'.js':'text/javascript','.glb':'model/gltf-binary','.json':'application/json'}
    def end_headers(self):
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        super().end_headers()
server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(root)))
print(f'FireWatch Node Explorer: http://127.0.0.1:{args.port}',flush=True)
print('Press Ctrl+C to stop. No FireWatch backend or frontend is required.',flush=True)
try: server.serve_forever()
except KeyboardInterrupt: pass
finally: server.server_close()
