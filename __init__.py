import jhtp
import json
import _thread


_LOG_PREFIX = '[DR2P]'
_DEBUG_LEVEL = 0


def set_debug_level(level):
    global _DEBUG_LEVEL
    _DEBUG_LEVEL = level


def _log(text, level=1):
    if level <= _DEBUG_LEVEL:
        print(_LOG_PREFIX, end=' ')
        print(text)


class DR2PBase:

    def __init__(self, j=None):
        self.j = jhtp.JHTPBase() if j is None else j

    def bind(self, host, port):
        self.j.bind(host, port)

    def fileno(self):
        return self.j.fileno()

    def close(self):
        return self.j.close()


class DR2PPeer(DR2PBase):

    def __init__(self, j=None, handler_dict=None):
        DR2PBase.__init__(self, jhtp.JHTPPeer() if j is None else j)
        self.handler_dict = {} if handler_dict is None else handler_dict
        self._mainloop_continue = True
        self.next_rid = 1  # Request-response id.
        self.callback_dict = {}  # rid -> callback
        self.client_id = None  # ?
        self.remote_host = None

    def set_handler(self, path, handler=None):
        self.handler_dict[path] = Handler if handler is None else handler

    def _request_callback(self, path, msg, callback):  # Callback
        rid = str(self.next_rid)
        self.next_rid += 1
        head = {
            'Type': 'request',
            'Host': self.remote_host,
            'Path': path,
            'ID': rid,
            'Version': '0'
        }
        body = json.dumps(msg).encode(encoding='utf-8')
        _log('Send request head {}'.format(head))
        _log('Send request body {}'.format(msg))
        self.j.send(head, body)
        self.callback_dict[rid] = callback

    def request(self, path, msg):
        lock = _thread.allocate_lock()
        lock.acquire()
        namespace = {}

        def callback(**kv):
            namespace['kv'] = kv
            lock.release()

        self._request_callback(path, msg, callback)
        lock.acquire()
        lock.release()
        return namespace['kv']

    def start_mainloop(self):
        _thread.start_new_thread(self.mainloop, ())

    def mainloop(self):

        def routine(head, body):
            if head['Type'] == 'request':
                _log('Receive request head {}'.format(head))
                path = head['Path']
                rid = head['ID']
                msg = json.loads(body.decode(encoding='utf-8'))  # JSON
                _log('Receive request body {}'.format(msg))
                _log('Calling handler...')
                handler = self.handler_dict[path]()
                handler.dr2p_peer = self
                handler.head = head
                handler.body = body
                res = handler.handle(msg)
                _log('Handler returned.')
                res_head = {
                    'Type': 'response',
                    'Code': 'OK',
                    'ID': rid,
                    'Version': '0'
                }
                res_body = json.dumps(res).encode(encoding='utf-8')  # JSON
                _log('Send response head {}'.format(res_head))
                _log('Send response body {}'.format(res))
                self.j.send(res_head, res_body)
            elif head['Type'] == 'response':
                _log('Receive response head {}'.format(head))
                msg = json.loads(body.decode(encoding='utf8'))
                _log('Receive response body {}'.format(msg))
                rid = head['ID']
                callback = self.callback_dict[rid]
                callback.dr2p_peer = self  # ?
                callback(
                    msg=msg,
                    head=head,
                    body=body,
                )

        while self._mainloop_continue:
            try:
                _log('Receive start.')
                _head, _body = self.j.recv()
                _thread.start_new_thread(routine, (_head, _body))
            except jhtp.TlaConnectionClose:
                _log('Session closed.')
                break
            except KeyboardInterrupt:
                _log('Keyboard interrupt, stop.')
                break


class DR2PServer(DR2PBase):

    def __init__(self, j=None, handler_dict=None):
        DR2PBase.__init__(self, jhtp.JHTPServer() if j is None else j)
        self.handler_dict = {} if handler_dict is None else handler_dict
        self._mainloop_continue = True
        self.client_dict = {}  # client_id -> dr2p_peer
        self.next_cid = 1

    def set_handler(self, path, handler=None):
        self.handler_dict[path] = Handler if handler is None else handler

    def request(self, client_id, path, msg):
        dr2p_peer = self.client_dict[client_id]
        assert isinstance(dr2p_peer, DR2PPeer)
        return dr2p_peer.request(path, msg)

    def mainloop(self):

        def on_accept(jhtp_peer):
            dr2p_peer = DR2PPeer(jhtp_peer, self.handler_dict)
            client_id = str(self.next_cid)
            self.next_cid += 1
            dr2p_peer.remote_host = client_id
            self.client_dict[client_id] = dr2p_peer
            _thread.start_new_thread(dr2p_peer.mainloop, ())

        self.j.on_accept = on_accept
        self.j.mainloop()


class DR2PClient(DR2PPeer):

    def __init__(self, j=None):
        DR2PPeer.__init__(self, jhtp.JHTPClient() if j is None else j)

    def connect(self, host, port):
        self.j.connect(host, port)
        self.remote_host = host


class Handler:

    def __init__(self):
        self.dr2p_peer = None
        self.head = None
        self.body = None

    def handle(self, msg):
        pass
