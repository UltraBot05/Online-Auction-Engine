"""
client.py - Online Auction Engine (v1 - terminal)
Basic TCP client with SSL/TLS: connect, authenticate, send bids via terminal.
No GUI. Blocking recv - live broadcasts may be missed between inputs.
"""

import socket
import ssl

HOST = "127.0.0.1"
PORT = 9999


def main():
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations("server.pem")
    sock = ssl_context.wrap_socket(raw_sock, server_hostname="localhost")

    try:
        sock.connect((HOST, PORT))
    except ConnectionRefusedError:
        print(f"[ERROR] Could not connect to {HOST}:{PORT}. Is server.py running?")
        return

    print("[INFO] Connected to auction server (SSL secured).")

    # receive name prompt from server
    prompt = sock.recv(1024).decode()
    print(prompt, end="")
    name = input().strip()
    if not name:
        print("[ERROR] Name cannot be empty.")
        sock.close()
        return
    sock.send(name.encode())

    # auction welcome banner
    print(sock.recv(4096).decode())

    while True:
        bid = input("Enter bid (or 'quit'): ").strip()
        if not bid:
            continue
        sock.send(bid.encode())
        response = sock.recv(4096).decode()
        print(response)
        if bid.lower() == "quit":
            break

    sock.close()
    print("[INFO] Disconnected.")


if __name__ == "__main__":
    main()