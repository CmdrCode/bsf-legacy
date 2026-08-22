#!/usr/bin/env python3
"""Tiny HTTP server with Range support (Chrome needs 206 responses to play video).

    serve_range.py [PORT] [DIR] [HOST]

HOST defaults to 127.0.0.1 and `tailscale` resolves to this node's tailnet
address. Loopback is the default on purpose: this serves a directory with no
authentication of any kind, and `_local/` is the folder that is private by
design. `tailscale` binds that one address and nothing else, so the LAN does not
get a copy of the offer -- the same reason tools/editor/server.py refuses to
bind a wildcard without being asked. 0.0.0.0 is available but you have to type
it, and you should know why you are.
"""
import os, re, subprocess, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if not m:
            return super().send_head()
        size = os.path.getsize(path)
        start = int(m.group(1)) if m.group(1) else 0
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_error(416, "Requested Range Not Satisfiable")
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._range_left = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        left = getattr(self, "_range_left", None)
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            buf = source.read(min(65536, left))
            if not buf:
                break
            outputfile.write(buf)
            left -= len(buf)


def resolve_host(name):
    if name != "tailscale":
        return name
    out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True)
    addr = out.stdout.strip().splitlines()
    if not addr:
        sys.exit("tailscale ip -4 returned nothing -- is tailscaled up?")
    return addr[0]


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8735
    root = sys.argv[2] if len(sys.argv) > 2 else "."
    host = resolve_host(sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1")
    os.chdir(root)
    print(f"serving {os.getcwd()} on http://{host}:{port}/", flush=True)
    ThreadingHTTPServer((host, port), RangeHandler).serve_forever()
