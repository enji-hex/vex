import socket, struct, os

def check_stun(host: str, port: int = 3478, timeout: float = 2.0) -> bool:
    """Sends a STUN Binding Request and validates the response."""
    # Header: Type (0x0001), Length (0), Magic Cookie (0x2112A442), Transaction ID (12 bytes)
    header = struct.pack("!HHI12s", 0x0001, 0, 0x2112A442, os.urandom(12))
    
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(header, (host, port))
            data, addr = sock.recvfrom(1024)
            
            # Check if response type is Binding Success (0x0101)
            res_type = struct.unpack("!H", data[:2])[0]
            if res_type == 0x0101:
                print(f"[+] {host} ({addr[0]}): SUCCESS")
                return True
            print(f"[-] {host}: Unexpected response type {hex(res_type)}")
        except socket.timeout:
            print(f"[-] {host}: Timeout")
        except Exception as e:
            print(f"[-] {host}: Error {e}")
    return False

if __name__ == "__main__":
    for s in ["stun.l.google.com", "stun1.l.google.com", "stun.voipbuster.com"]:
        check_stun(s)
