"""Derinlere Kaz - çok oyunculu sunucu.

Çalıştır:  python sunucu.py
Sonra herkes tarayıcıda ekranda yazan adresi açar (aynı Wi-Fi / ağ).
Sadece Python'un kendi kütüphanelerini kullanır, ek kurulum gerekmez.

Arkadaş ekleme: oyunu açan herkes kendi adıyla "çevrimiçi" görünür. ARKADAŞLAR penceresinde
arkadaşının oyundaki adını yazınca ona davet gider. Kabul ederse, davet edenin adıyla bir oda
açılır ve ikiniz aynı dünyada oynarsınız (dünya davet edenin dünyasıdır). Reddederse bir şey olmaz.
"""
import json
import os
import socket
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8000
ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_EDITS = 20000          # her odada tutulan son blok değişikliği sayısı
PLAYER_TIMEOUT = 6         # bu kadar saniye ses gelmeyen oyuncu odadan ayrılmış sayılır
ONLINE_TIMEOUT = 8         # bu kadar saniye "merhaba" demeyen oyuncu çevrimdışı sayılır
INVITE_TIMEOUT = 60        # cevaplanmayan davet bu kadar saniye sonra düşer

lock = threading.Lock()
rooms = {}                 # oda adı (davet edenin adı) -> oda
online = {}                # küçük harfli ad -> {'name', 'last'}
invites = {}               # davet no -> {'from', 'to', 'status', 't', 'told'}
next_invite = 1
next_id = 1


def key(name):
    return str(name or '').strip().lower()


def new_room():
    return {'worlds': {}, 'versions': {}, 'meta': {}, 'meta_version': 0, 'edits': [], 'seq': 0, 'players': {}}


def room_of(name):
    r = rooms.get(key(name))
    if r is None:
        r = rooms[key(name)] = new_room()
    return r


def active_players(room):
    now = time.time()
    players = room['players']
    for pid in [p for p, v in players.items() if now - v['last'] > PLAYER_TIMEOUT]:
        del players[pid]
    return players


def online_names():
    now = time.time()
    for k in [k for k, v in online.items() if now - v['last'] > ONLINE_TIMEOUT]:
        del online[k]
    return [v['name'] for v in online.values()]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, *args):
        pass  # konsolu sessiz tut

    def send_json(self, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(n) if n else b''
        return json.loads(raw or b'{}')

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/api/world':
            q = parse_qs(url.query)
            dim = q.get('dim', [''])[0]
            with lock:
                room = room_of(q.get('room', [''])[0])
                data = room['worlds'].get(dim)
                self.send_json({
                    'data': data.decode('latin-1') if data is not None else None,
                    'version': room['versions'].get(dim, 0),
                    'seq': room['seq'],
                })
            return
        super().do_GET()

    def do_POST(self):
        global next_id, next_invite
        url = urlparse(self.path)
        body = self.read_json()

        # ---- çevrimiçi olma, davetler ----
        if url.path == '/api/hello':
            with lock:
                name = str(body.get('name', ''))[:16]
                if key(name):
                    online[key(name)] = {'name': name, 'last': time.time()}
                now = time.time()
                for i in [i for i, v in invites.items() if now - v['t'] > INVITE_TIMEOUT * 3]:
                    del invites[i]
                incoming = [{'id': i, 'from': v['from']} for i, v in invites.items()
                            if key(v['to']) == key(name) and v['status'] == 'pending' and now - v['t'] < INVITE_TIMEOUT]
                answers = []
                for i, v in invites.items():
                    if key(v['from']) == key(name) and v['status'] != 'pending' and not v['told']:
                        v['told'] = True
                        answers.append({'id': i, 'to': v['to'], 'status': v['status']})
                    elif key(v['from']) == key(name) and v['status'] == 'pending' and now - v['t'] >= INVITE_TIMEOUT and not v['told']:
                        v['told'] = True
                        v['status'] = 'timeout'
                        answers.append({'id': i, 'to': v['to'], 'status': 'timeout'})
                self.send_json({'online': online_names(), 'incoming': incoming, 'answers': answers})
            return

        if url.path == '/api/invite':
            with lock:
                frm, to = str(body.get('from', ''))[:16], str(body.get('to', ''))[:16]
                online_names()
                if not key(to) or key(to) == key(frm):
                    self.send_json({'ok': False, 'reason': 'self'})
                elif key(to) not in online:
                    self.send_json({'ok': False, 'reason': 'offline'})
                else:
                    i = next_invite
                    next_invite += 1
                    invites[i] = {'from': frm, 'to': online[key(to)]['name'], 'status': 'pending', 't': time.time(), 'told': False}
                    print(f'✉ {frm} -> {to} davet')
                    self.send_json({'ok': True, 'id': i, 'to': invites[i]['to']})
            return

        if url.path == '/api/answer':
            with lock:
                v = invites.get(body.get('id'))
                if not v or v['status'] != 'pending':
                    self.send_json({'ok': False})
                else:
                    v['status'] = 'accepted' if body.get('accept') else 'rejected'
                    if v['status'] == 'accepted':
                        rooms[key(v['from'])] = new_room()  # davet edenin odası sıfırdan kurulur
                    print(f'✉ {v["to"]} daveti {"kabul etti" if body.get("accept") else "reddetti"} ({v["from"]})')
                    self.send_json({'ok': True, 'room': v['from']})
            return

        # ---- oda içi: dünya paylaşımı ----
        room = room_of(body.get('room', ''))

        if url.path == '/api/join':
            with lock:
                host = body.get('role') == 'host'
                if not host and not room['worlds']:
                    self.send_json({'wait': True})  # davet eden dünyasını henüz yüklemedi
                    return
                pid = next_id
                next_id += 1
                room['players'][pid] = {'name': str(body.get('name', 'Madenci'))[:16], 'state': None, 'last': time.time()}
                print(f'+ {room["players"][pid]["name"]} odaya katıldı ({len(active_players(room))} oyuncu)')
                self.send_json({
                    'id': pid, 'host': host, 'seq': room['seq'], 'meta': room['meta'],
                    'metaVersion': room['meta_version'], 'dims': list(room['worlds'].keys()), 'versions': room['versions'],
                })
            return

        if url.path == '/api/world':
            with lock:
                dim = body['dim']
                room['worlds'][dim] = bytearray(body['data'].encode('latin-1'))
                room['versions'][dim] = room['versions'].get(dim, 0) + 1
                self.send_json({'version': room['versions'][dim]})
            return

        if url.path == '/api/meta':
            with lock:
                room['meta'].update(body.get('meta', {}))
                room['meta_version'] += 1
                self.send_json({'metaVersion': room['meta_version']})
            return

        if url.path == '/api/sync':
            with lock:
                pid = body.get('id')
                players = room['players']
                if pid not in players:
                    players[pid] = {'name': 'Madenci', 'state': None, 'last': 0}
                p = players[pid]
                p['last'] = time.time()
                p['state'] = body.get('state')
                if p['state'] and p['state'].get('name'):
                    p['name'] = p['state']['name']
                # blok değişikliklerini sunucudaki haritaya da uygula
                edits = room['edits']
                for dim, i, t in body.get('edits', []):
                    w = room['worlds'].get(dim)
                    if w is not None and 0 <= i < len(w):
                        w[i] = 65 + t
                    room['seq'] += 1
                    edits.append((room['seq'], dim, i, t, pid))
                if len(edits) > MAX_EDITS:
                    del edits[:len(edits) - MAX_EDITS]
                seq = room['seq']
                cursor = body.get('cursor', 0)
                oldest = edits[0][0] if edits else seq + 1
                resync = cursor + 1 < oldest and cursor < seq
                out = [[d, i, t] for (s, d, i, t, who) in edits if s > cursor and who != pid] if not resync else []
                others = [{'id': k, 'name': v['name'], **(v['state'] or {})}
                          for k, v in active_players(room).items() if k != pid and v['state']]
                self.send_json({
                    'seq': seq, 'edits': out, 'resync': resync, 'players': others,
                    'versions': room['versions'], 'metaVersion': room['meta_version'], 'meta': room['meta'],
                })
            return

        self.send_response(404)
        self.end_headers()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    ip = lan_ip()
    print('Derinlere Kaz sunucusu çalışıyor!')
    print(f'  Sen aç:              http://localhost:{PORT}')
    print(f'  Arkadaşın / telefon: http://{ip}:{PORT}   (aynı Wi-Fi / ağda olmalı)')
    print('Oyunda MENÜ → ARKADAŞLAR: arkadaşının oyundaki adını yaz, davet gönder. Kapatmak için Ctrl+C.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nSunucu kapatıldı.')
