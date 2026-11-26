KEY = [ord(c) for c in "FB1313"]           # Password= do Data.ini
ADD = [0x25,0xf6,0xe4,0x76,0x47,0x54,0xe6,0x76]

def encrypt(p):
    b = list(p)
    n = [b[5], b[4], b[7], b[6], b[1], b[0], b[3], b[2]]
    for i in range(1, 7): n[i] ^= KEY[i-1]
    v = int.from_bytes(bytes(n), "big")
    v = ((v << 3) | (v >> 61)) & (2**64 - 1)
    n = list(v.to_bytes(8, "big"))
    return bytes((x + a) & 0xff for x, a in zip(n, ADD))

def decrypt(w):
    n = [(x - a) & 0xff for x, a in zip(w, ADD)]
    v = int.from_bytes(bytes(n), "big")
    v = ((v >> 3) | (v << 61)) & (2**64 - 1)
    n = list(v.to_bytes(8, "big"))
    for i in range(1, 7): n[i] ^= KEY[i-1]
    b = [0]*8
    b[5], b[4], b[7], b[6], b[1], b[0], b[3], b[2] = n
    return bytes(b)

def checksum(p):
    return (0xff - p[0] - sum(p[1:7])) & 0xff

def build(cmd, data6=b""):
    p = bytes([cmd]) + bytes(data6).ljust(6, b"\0")
    return p + bytes([checksum(p + b"\0")])

if __name__ == "__main__":
    log = """SETF 27 27 d5 ff e4 e5 7e 76
GETF 27 68 f5 ff e4 ea ee ee
SETF 65 2b cf e4 e8 e6 ee 76
SETF 00 aa dd 3b 62 00 00 db
GETF 27 28 f5 ff e0 e5 7e 76
SETF 26 1a ad 02 10 dc 2c 5e
GETF 26 18 f5 02 10 dc 2c 5e"""
    for line in log.splitlines():
        kind, *h = line.split()
        w = bytes(int(x, 16) for x in h)
        p = decrypt(w)
        ok = p[7] == checksum(p)
        print(kind, w.hex(" "), "->", p.hex(" "), "checksum", "OK" if ok else "ruim")
