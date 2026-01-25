# ============================================================================
# WEBSOCKET SERVER
# ============================================================================

import base64, hashlib, hmac, json, logging, os, secrets, signal, socket, ssl, struct, threading, time
import urllib.parse

logger = logging.getLogger("concierge")

class WebSocketManager:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, cert, key, secret, host="0.0.0.0", port=8765, token_ttl=30):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        self.cert, self.key = cert, key
        self.host, self.port = host, port
        self.token_ttl = token_ttl
        self.clients = {}  # socket -> (user, task_id, hostname)
        self.used_nonces = {}  # nonce -> exp
        self.running = False
        self.process_streams = {}  # (task_id, hostname) -> process
        self.lock = threading.RLock()

    def issue_token(self, user_id, task_id, hostname):
        exp = int(time.time() + self.token_ttl)
        nonce = secrets.token_urlsafe(16)
        msg = f"{user_id}:{task_id}:{hostname}:{exp}:{nonce}".encode()
        sig = hmac.new(self.secret, msg, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(msg + sig).decode()

    def _verify_token(self, token):
        raw = base64.urlsafe_b64decode(token.encode())
        msg, sig = raw[:-32], raw[-32:]

        if not hmac.compare_digest(hmac.new(self.secret, msg, hashlib.sha256).digest(), sig):
            raise ValueError("Invalid signature")

        parts = msg.decode().split(":")
        user, task_id, hostname, exp, nonce = parts[0], parts[1], parts[2], int(parts[3]), parts[4]

        now = int(time.time())

        with self.lock:
            # Clean old nonces
            self.used_nonces = {n: e for n, e in self.used_nonces.items() if e > now}

            if now > exp:
                raise ValueError("Token expired")
            if nonce in self.used_nonces:
                raise ValueError("Token replay detected")

            self.used_nonces[nonce] = exp

        return user, task_id, hostname

    def _handshake(self, sock):
        req = sock.recv(8192).decode('utf-8', errors='ignore')

        path = req.split(" ", 3)[1]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        token = query.get("token", [None])[0]
        if not token:
            raise ValueError("No token provided")

        user, task_id, hostname = self._verify_token(token)

        key = None
        for line in req.split("\r\n"):
            if line.startswith("Sec-WebSocket-Key:"):
                key = line.split(": ", 1)[1].strip()
                break

        if not key:
            raise ValueError("No WebSocket key")

        accept = base64.b64encode(
            hashlib.sha1((key + self.GUID).encode()).digest()
        ).decode()

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "Sec-WebSocket-Protocol: concierge.v1\r\n\r\n"
        )
        sock.send(response.encode())

        return user, task_id, hostname

    @staticmethod
    def _recv_frame(sock):
        try:
            header = sock.recv(2)
            if len(header) < 2:
                return None, None, None

            b1, b2 = header[0], header[1]
            fin = (b1 >> 7) & 1
            opcode = b1 & 0x0f
            masked = (b2 >> 7) & 1
            length = b2 & 0x7f

            if length == 126:
                length_data = sock.recv(2)
                if len(length_data) < 2:
                    return None, None, None
                length = struct.unpack(">H", length_data)[0]
            elif length == 127:
                length_data = sock.recv(8)
                if len(length_data) < 8:
                    return None, None, None
                length = struct.unpack(">Q", length_data)[0]

            mask_key = sock.recv(4) if masked else None

            payload = b""
            while len(payload) < length:
                chunk = sock.recv(min(4096, length - len(payload)))
                if not chunk:
                    return None, None, None
                payload += chunk

            if masked and mask_key:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            return fin, opcode, payload
        except Exception:
            return None, None, None

    @staticmethod
    def _send_frame(sock, payload, opcode=0x02):
        try:
            if isinstance(payload, str) or isinstance(payload, int):
                payload = str(payload).encode('utf-8')

            length = len(payload)
            header = bytes([0x80 | opcode])

            if length < 126:
                header += bytes([length])
            elif length < 65536:
                header += bytes([126]) + struct.pack(">H", length)
            else:
                header += bytes([127]) + struct.pack(">Q", length)

            sock.sendall(header + payload)
            return True
        except Exception:
            return False

    def send_to_client(self, task_id, hostname, data):
        with self.lock:
            for sock, (user, tid, host) in self.clients.items():
                if tid == task_id and host == hostname:
                    if not self._send_frame(sock, data, 0x02):
                        self.clients.pop(sock, None)
                        try:
                            sock.close()
                        except Exception:
                            pass

    def broadcast_status(self, task_id, hostname, status):
        msg = json.dumps({"type": "status", "status": status})
        self.send_to_client(task_id, hostname, msg)

    def register_process(self, task_id, hostname, proc):
        with self.lock:
            self.process_streams[(task_id, hostname)] = proc

    def unregister_process(self, task_id, hostname):
        with self.lock:
            self.process_streams.pop((task_id, hostname), None)

    def _handle_client(self, sock):
        user, task_id, hostname = None, None, None
        try:
            user, task_id, hostname = self._handshake(sock)

            with self.lock:
                self.clients[sock] = (user, task_id, hostname)

            logger.info(f"WebSocket connected: task={task_id}, host={hostname}")

            self._send_frame(sock, json.dumps({"type": "connected"}).encode(), 0x01)

            while True:
                _, opcode, payload = self._recv_frame(sock)

                if opcode is None or opcode == 0x08:  # Close frame or error
                    break
                elif opcode == 0x09:  # Ping
                    self._send_frame(sock, payload, 0x0A)  # Pong
                elif opcode in (0x01, 0x02) and payload:  # Text or binary
                    proc_key = (task_id, hostname)
                    with self.lock:
                        proc = self.process_streams.get(proc_key)

                    if proc and proc.stdin and not proc.stdin.closed:
                        try:
                            if opcode == 0x01:  # Text frame
                                try:
                                    msg = json.loads(payload.decode('utf-8'))
                                    if isinstance(msg, dict) and msg.get("type") == "control":
                                        ctrl_char = msg.get("char")
                                        if ctrl_char == "C":
                                            if hasattr(proc, 'pid'):
                                                os.kill(proc.pid, signal.SIGINT)
                                        elif ctrl_char == "D":
                                            proc.stdin.close()
                                        elif ctrl_char == "Z":
                                            if hasattr(proc, 'pid'):
                                                os.kill(proc.pid, signal.SIGTSTP)
                                        continue
                                except (json.JSONDecodeError, KeyError):
                                    # Not a control message, treat as normal input
                                    pass

                            proc.stdin.write(payload)
                            proc.stdin.flush()
                        except Exception as e:
                            logger.error(f"Error writing to stdin: {e}")
        except Exception as e:
            logger.error(f"WebSocket client error: {e}")
        finally:
            with self.lock:
                if sock in self.clients:
                    del self.clients[sock]
            try:
                sock.close()
            except Exception:
                pass
            logger.info(f"WebSocket disconnected: task={task_id}, host={hostname}")

    def serve(self):
        self.running = True
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)

        logger.info(f"WebSocket server listening on {self.host}:{self.port}")

        while self.running:
            try:
                client_sock, _ = server_sock.accept()
                client_sock = ctx.wrap_socket(client_sock, server_side=True)
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception as e:
                if self.running:
                    logger.error(f"WebSocket accept error: {e}")

        try:
            server_sock.close()
        except Exception:
            pass

    def stop(self):
        self.running = False
        with self.lock:
            for sock in self.clients.keys():
                try:
                    sock.close()
                except Exception:
                    pass
            self.clients.clear()