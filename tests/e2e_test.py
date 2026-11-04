#!/usr/bin/env python3
"""End-to-end test for ocproxy; needs only python3 (no root, no TUN).

ocproxy is started with one end of a datagram socketpair as its "VPN" fd.
The other end is served by a tiny userspace TCP echo stack (in-order,
lossless) that lives on the remote IP address 10.99.0.1.  The test then
drives ocproxy through its -L, SOCKS5 and HTTP CONNECT front ends and
verifies that all data comes back intact, and that TCP window scaling
is negotiated.

Usage: e2e_test.py [/path/to/ocproxy]   (or set $OCPROXY)
"""
import os, queue, select, socket, struct, subprocess, sys, threading, time

PEER, LOCAL = "10.99.0.1", "10.99.0.2"
FWD, SOCKS, HTTP, SRV = 18000, 18001, 18002, 19000
MSS = 1024
SYN, FIN, RST, PSH, ACK = 0x02, 0x01, 0x04, 0x08, 0x10
OUR_WSCALE = 7
stats = {"peer_wscale": None, "max_peer_wnd": 0}


def csum(b):
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack(">%dH" % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def build(sip, dip, sport, dport, seq, ack, flags, payload=b"", opts=b""):
    off = (20 + len(opts)) // 4
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq & 0xFFFFFFFF,
                      ack & 0xFFFFFFFF, off << 4, flags, 65535, 0, 0) + opts + payload
    ps = socket.inet_aton(sip) + socket.inet_aton(dip) + struct.pack(">BBH", 0, 6, len(tcp))
    tcp = tcp[:16] + struct.pack(">H", csum(ps + tcp)) + tcp[18:]
    ip = struct.pack(">BBHHHBBH", 0x45, 0, 20 + len(tcp), 0, 0x4000, 64, 6, 0) \
        + socket.inet_aton(sip) + socket.inet_aton(dip)
    ip = ip[:10] + struct.pack(">H", csum(ip)) + ip[12:]
    return ip + tcp


class Conn:
    def __init__(self, sport):
        self.sport = sport
        self.iss = 1000000 + sport
        self.snd_nxt = self.iss + 1
        self.snd_una = self.iss + 1
        self.rcv_nxt = 0
        self.out = bytearray()
        self.peer_wnd = 65535
        self.peer_fin = False
        self.fin_sent = False


class FakeRemote:
    def __init__(self, sock):
        self.sock = sock
        self.conns = {}
        # a separate sender thread avoids a send/send deadlock with ocproxy
        self.txq = queue.Queue()
        threading.Thread(target=self.sender, daemon=True).start()

    def sender(self):
        while True:
            self.sock.send(self.txq.get())

    def send(self, c, seq, flags, payload=b"", opts=b""):
        self.txq.put(build(PEER, LOCAL, SRV, c.sport, seq, c.rcv_nxt,
                           flags | ACK, payload, opts))

    def pump(self, c):
        while c.out and c.snd_nxt - c.snd_una < c.peer_wnd:
            room = c.peer_wnd - (c.snd_nxt - c.snd_una)
            n = min(MSS, len(c.out), room)
            chunk = bytes(c.out[:n])
            del c.out[:n]
            self.send(c, c.snd_nxt, PSH, chunk)
            c.snd_nxt += n
        if c.peer_fin and not c.out and not c.fin_sent:
            c.fin_sent = True
            self.send(c, c.snd_nxt, FIN)
            c.snd_nxt += 1

    def handle(self, pkt):
        ihl = (pkt[0] & 15) * 4
        if pkt[9] != 6 or len(pkt) < ihl + 20:
            return
        sport, dport, seq, ack, off, flags, win = struct.unpack(">HHIIBBH", pkt[ihl:ihl + 16])
        off = (off >> 4) * 4
        payload = pkt[ihl + off:]
        if dport != SRV:
            return
        c = self.conns.get(sport)
        if flags & SYN:
            c = self.conns[sport] = Conn(sport)
            c.rcv_nxt = (seq + 1) & 0xFFFFFFFF
            opts = pkt[ihl + 20:ihl + off]
            i = 0
            while i < len(opts):
                k = opts[i]
                if k in (0, 1):
                    i += 1
                    continue
                if k == 3:
                    stats["peer_wscale"] = opts[i + 2]
                i += opts[i + 1]
            synack_opts = struct.pack(">BBH", 2, 4, 1460) + b"\x01" + \
                struct.pack(">BBB", 3, 3, OUR_WSCALE)
            self.send(c, c.iss, SYN, b"", synack_opts)
            return
        if c is None:
            return
        scale = stats["peer_wscale"] or 0
        c.peer_wnd = win << scale
        stats["max_peer_wnd"] = max(stats["max_peer_wnd"], c.peer_wnd)
        if flags & ACK:
            if 0 < ((ack - c.snd_una) & 0xFFFFFFFF) < 1 << 31:
                c.snd_una = ack
        if payload and seq == c.rcv_nxt:
            c.rcv_nxt = (c.rcv_nxt + len(payload)) & 0xFFFFFFFF
            c.out += payload
            self.send(c, c.snd_nxt, 0)
        if flags & FIN and seq + len(payload) == c.rcv_nxt:
            c.rcv_nxt = (c.rcv_nxt + 1) & 0xFFFFFFFF
            c.peer_fin = True
            self.send(c, c.snd_nxt, 0)
        if flags & RST:
            del self.conns[sport]
            return
        self.pump(c)

    def run(self, stop):
        while not stop.is_set():
            r, _, _ = select.select([self.sock], [], [], 0.2)
            if r:
                try:
                    pkt = self.sock.recv(65536)
                except OSError:
                    return
                if pkt:  # ocproxy sends 0-byte keepalive probes
                    self.handle(pkt)


def roundtrip(sock, nbytes):
    """Send nbytes through the echo path and verify they all come back."""
    pattern = bytes(range(251)) * 4
    plen = len(pattern)
    sent = recvd = 0
    start = time.time()
    sock.setblocking(False)
    while recvd < nbytes:
        w = [sock] if sent < nbytes else []
        r, w, _ = select.select([sock], w, [], 20)
        if not r and not w:
            raise RuntimeError("stalled at sent=%d recvd=%d" % (sent, recvd))
        if w:
            off = sent % plen
            chunk = (pattern[off:] + pattern)[:min(65536, nbytes - sent)]
            try:
                sent += sock.send(chunk)
            except BlockingIOError:
                pass
        if r:
            d = sock.recv(1 << 20)
            if not d:
                raise RuntimeError("early EOF at %d" % recvd)
            off = recvd % plen
            if d != (pattern[off:] + pattern * (len(d) // plen + 1))[:len(d)]:
                raise RuntimeError("data corruption near offset %d" % recvd)
            recvd += len(d)
    sock.setblocking(True)
    return nbytes / (time.time() - start) / 1e6


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        d = s.recv(n - len(buf))
        if not d:
            raise RuntimeError("short read")
        buf += d
    return buf


def test_forward():
    s = socket.create_connection(("127.0.0.1", FWD), timeout=30)
    print("  -L forward:   %.2f MB/s" % roundtrip(s, 8 * 1024 * 1024))
    s.close()


def test_window_scaling():
    assert stats["peer_wscale"] == 3, "expected TCP_RCV_SCALE 3, got %r" % stats["peer_wscale"]
    assert stats["max_peer_wnd"] > 65535, "receive window never exceeded 64 KiB"
    print("  window scale %d, max advertised window %d" %
          (stats["peer_wscale"], stats["max_peer_wnd"]))


def test_socks():
    s = socket.create_connection(("127.0.0.1", SOCKS), timeout=30)
    s.sendall(b"\x05\x01\x00")
    assert recv_exact(s, 2) == b"\x05\x00"
    s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton(PEER) + struct.pack(">H", SRV))
    rep = recv_exact(s, 10)
    assert rep[0] == 5 and rep[1] == 0, rep
    print("  SOCKS5:       %.2f MB/s" % roundtrip(s, 2 * 1024 * 1024))
    s.close()


def test_http_connect():
    s = socket.create_connection(("127.0.0.1", HTTP), timeout=30)
    s.sendall(("CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n" %
               (PEER, SRV, PEER, SRV)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = s.recv(1024)
        if not d:
            raise RuntimeError("no CONNECT reply")
        buf += d
    assert buf.split(b" ")[1] == b"200", buf
    print("  HTTP CONNECT: %.2f MB/s" % roundtrip(s, 2 * 1024 * 1024))
    s.close()


def test_parallel():
    errs = []

    def one():
        try:
            s = socket.create_connection(("127.0.0.1", FWD), timeout=30)
            roundtrip(s, 512 * 1024)
            s.close()
        except Exception as e:  # noqa
            errs.append(e)

    ts = [threading.Thread(target=one) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    print("  10 parallel connections OK")


def main():
    ocproxy = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.environ["OCPROXY"])
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    for s in (a, b):
        for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
            try:
                s.setsockopt(socket.SOL_SOCKET, opt, 4 << 20)
            except OSError:  # e.g. small hard limits on macOS
                pass
    stop = threading.Event()
    remote = FakeRemote(a)
    threading.Thread(target=remote.run, args=(stop,), daemon=True).start()

    env = dict(os.environ, VPNFD=str(b.fileno()), INTERNAL_IP4_ADDRESS=LOCAL,
               INTERNAL_IP4_MTU="1400")
    proc = subprocess.Popen(
        [ocproxy, "-L", "%d:%s:%d" % (FWD, PEER, SRV), "-D", str(SOCKS),
         "-H", str(HTTP)], env=env, pass_fds=[b.fileno()])
    time.sleep(1)
    rc = 0
    try:
        for t in (test_forward, test_window_scaling, test_socks,
                  test_http_connect, test_parallel):
            print(t.__name__)
            try:
                t()
            except Exception as e:  # noqa
                print("FAIL: %s: %r" % (t.__name__, e))
                rc = 1
        if proc.poll() is not None:
            print("FAIL: ocproxy exited early with", proc.returncode)
            rc = 1
    finally:
        proc.terminate()
        proc.wait()
        stop.set()
    print("PASS" if rc == 0 else "FAILED")
    sys.exit(rc)


if __name__ == "__main__":
    main()
