"""
server.py - Online Auction Engine
Multi-threaded TCP auction server with real-time broadcasting,
anti-sniping timer, dynamic REST API item loading, and SSL/TLS.
"""

import socket, ssl, threading, time, urllib.request, random, json

GREEN   = "\033[92m"
RED     = "\033[91m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
RESET   = "\033[0m"

AUCTION_DURATION = 300
RESET_SECONDS    = 20

# Toggle SSL/TLS on or off - set to False for plain TCP (no cert needed)
ENABLE_SSL = True

FALLBACK_ITEMS   = [
    ("Nvidia RTX 5090", 1800),
    ("MacBook Neo", 2500),
    ("Rolex Submariner", 8000),
    ("iPhone 17 Pro Max 1TB", 1600),
]

current_item   = "Nvidia RTX 5090"
current_price  = 1800
current_leader = "No one"
auction_open   = True
time_remaining = AUCTION_DURATION

bid_lock     = threading.Lock()
clients      = []
clients_lock = threading.Lock()


def discover_local_ipv4_addresses():
    """Best-effort list of local IPv4 addresses teammates can try."""
    addresses = set()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip:
                addresses.add(ip)
    except socket.gaierror:
        pass

    for probe_host in ("8.8.8.8", "1.1.1.1"):
        probe = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((probe_host, 80))
            addresses.add(probe.getsockname()[0])
        except OSError:
            pass
        finally:
            if probe is not None:
                probe.close()

    if not addresses:
        addresses.add("127.0.0.1")

    return sorted(addresses, key=lambda ip: (ip.startswith("127."), ip))


def pick_demo_ip_candidates():
    """Filter out obvious virtual/local-only adapter ranges for demo output."""
    ignored_prefixes = (
        "127.",
        "172.28.",     # WSL / Hyper-V
        "192.168.56.", # VirtualBox host-only
        "192.168.58.", # VMware host-only
        "192.168.115." # VMware NAT on this machine
    )
    all_ips = discover_local_ipv4_addresses()
    preferred = [ip for ip in all_ips if not ip.startswith(ignored_prefixes)]
    return preferred, all_ips


def fetch_todays_item():
    """Fetch a random product from DummyJSON; fall back to curated list on failure."""
    urls = [
        "https://dummyjson.com/products/category/smartphones",
        "https://dummyjson.com/products/category/laptops",
        "https://dummyjson.com/products/category/tablets",
        "https://dummyjson.com/products/category/mens-shoes",
    ]
    url = random.choice(urls)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        products = data.get("products", [])
        if not products:
            raise ValueError("API returned empty products list")
        product = random.choice(products)
        title = str(product["title"]).strip()
        price = int(product["price"])
        if not title or price <= 0:
            raise ValueError("Invalid title/price from API")
        # print(f"DEBUG: fetched product raw = {product}")
        return (title, price)
    except Exception as exc:
        print(f"{RED}[ERROR] Live item API failed: {exc}. Using fallback.{RESET}")
        return random.choice(FALLBACK_ITEMS)


def broadcast(message):
    """Send message to every connected client; prune dead sockets."""
    dead = []
    with clients_lock:
        snapshot = list(clients)
    for conn in snapshot:
        try:
            conn.send(message.encode())
        except (BrokenPipeError, OSError):
            dead.append(conn)
    if dead:
        with clients_lock:
            for conn in dead:
                if conn in clients:
                    clients.remove(conn)


def auction_timer():
    """Background countdown thread. Broadcasts warnings and final result."""
    global auction_open, time_remaining

    while True:
        time.sleep(1)
        with bid_lock:
            if not auction_open:
                break
            if time_remaining > 0:
                time_remaining -= 1
            remaining = time_remaining
            if remaining <= 0:
                winner      = current_leader
                final_price = current_price
                auction_open = False
                break

        if remaining % 10 == 0 or 0 < remaining <= 5:
            broadcast(f"\n  [TIMER] {remaining} seconds remaining!\n")
            print(f"{YELLOW}[TIMER] {remaining}s remaining{RESET}")

    closing = (
        f"\n{'#'*50}\n"
        f"  AUCTION CLOSED - {current_item}\n"
        f"  Winner : {winner}\n"
        f"  Price  : ${final_price:.2f}\n"
        f"{'#'*50}\n"
        f"  You may type 'quit' to disconnect.\n"
    )
    broadcast(closing)
    print(f"\n{MAGENTA}[AUCTION CLOSED] Winner: {winner} at ${final_price:.2f}{RESET}")


def handle_client(conn, addr):
    """Per-client thread: authentication, bid processing, broadcast relay."""
    global current_price, current_leader, time_remaining

    print(f"{GREEN}[NEW CONNECTION] {addr} connected.{RESET}")

    # Print TLS cipher details if SSL is active - proof of encryption for demo
    if ENABLE_SSL:
        print(f"{CYAN}[TLS] {addr} cipher: {conn.cipher()}{RESET}")

    try:
        conn.send("Enter your name: ".encode())
        username = conn.recv(1024).decode().strip()

        if not username:
            conn.send("Invalid name. Disconnecting.\n".encode())
            conn.close()
            return

        print(f"{CYAN}[INFO] {addr} identified as '{username}'{RESET}")

        with clients_lock:
            clients.append(conn)

        broadcast(f"\n  [JOIN] {username} has entered the auction!\n")

        conn.send((
            f"\n{'='*45}\n"
            f"  Item    : {current_item}\n"
            f"  Price   : ${current_price:.2f}\n"
            f"  Leader  : {current_leader}\n"
            f"{'='*45}\n"
            f"  Type a number to bid. Type 'quit' to leave.\n"
        ).encode())

        while True:
            data = conn.recv(1024).decode().strip()

            if not data:
                print(f"{RED}[DISCONNECT] {addr} ({username}) disconnected unexpectedly.{RESET}")
                break

            if data.lower() == "quit":
                conn.send("  You have left the auction. Goodbye!\n".encode())
                print(f"{CYAN}[LEAVE] {username} left the auction.{RESET}")
                break

            with bid_lock:
                is_open = auction_open
            if not is_open:
                conn.send("  [CLOSED] Auction has ended. No more bids accepted.\n".encode())
                continue

            if "." in data:
                conn.send("[REJECTED] Bids must be whole numbers and at least $5 higher than the current price.\n".encode())
                continue

            try:
                bid_amount = int(data)
            except ValueError:
                conn.send("[REJECTED] Bids must be whole numbers and at least $5 higher than the current price.\n".encode())
                continue

            # print(f"DEBUG: {username} attempting bid={bid_amount}, current={current_price}")
            with bid_lock:
                if auction_open and bid_amount >= (current_price + 5):
                    old_price      = current_price
                    current_price  = bid_amount
                    current_leader = username
                    time_remaining = RESET_SECONDS
                    accepted       = True
                    closed_now     = False
                elif not auction_open:
                    accepted   = False
                    closed_now = True
                else:
                    accepted   = False
                    closed_now = False

            if accepted:
                print(f"{MAGENTA}[BID] {username} raised price ${old_price:.2f} -> ${bid_amount:.2f}{RESET}")
                broadcast(
                    f"\n  [NEW BID] {username} bid ${bid_amount:.2f} for {current_item}!\n"
                    f"  Current leader : {username} @ ${bid_amount:.2f}\n"
                )
                broadcast("  [UPDATE] Clock reset to 20 seconds!\n")
            elif closed_now:
                conn.send("  [CLOSED] Auction has ended. No more bids accepted.\n".encode())
            else:
                conn.send("[REJECTED] Bids must be whole numbers and at least $5 higher than the current price.\n".encode())

    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, ssl.SSLError, OSError):
        print(f"{RED}[DISCONNECT] {addr} lost connection abruptly.{RESET}")

    finally:
        with clients_lock:
            if conn in clients:
                clients.remove(conn)
        conn.close()
        print(f"{RED}[CLOSED] Connection to {addr} closed.{RESET}")


def start_server():
    """Bind, wrap with SSL if enabled, listen, and accept clients in a loop."""
    global current_item, current_price

    HOST = "0.0.0.0"
    PORT = 9999

    current_item, current_price = fetch_todays_item()

    raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw_socket.bind((HOST, PORT))
    raw_socket.listen(5)

    if ENABLE_SSL:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(certfile="server.pem", keyfile="server.key")

    print(f"{GREEN}[AUCTION SERVER STARTED]{RESET}")
    print(f"{GREEN}  Item     : {current_item}{RESET}")
    print(f"{GREEN}  Start    : ${current_price:.2f}{RESET}")
    print(f"{GREEN}  Duration : {AUCTION_DURATION}s{RESET}")
    print(f"{GREEN}  SSL/TLS  : {'Enabled (server.pem)' if ENABLE_SSL else 'DISABLED (plain TCP)'}{RESET}")
    print(f"{GREEN}  Listening on {HOST}:{PORT}\n{RESET}")

    preferred_ips, all_ips = pick_demo_ip_candidates()
    if preferred_ips:
        print(f"{CYAN}[CONNECT FROM OTHER DEVICES] Try this first:{RESET}")
        print(f"{CYAN}  python client.py {preferred_ips[0]} {PORT}{RESET}")
        if len(preferred_ips) > 1:
            print(f"{CYAN}  Other possible real-network IPs: {', '.join(preferred_ips[1:])}{RESET}")
        print()
    elif all_ips:
        fallback_ips = [ip for ip in all_ips if not ip.startswith("127.")]
        if fallback_ips:
            print(f"{YELLOW}[CONNECT FROM OTHER DEVICES] No clear primary adapter found. Try:{RESET}")
            print(f"{YELLOW}  python client.py {fallback_ips[0]} {PORT}{RESET}\n")
    else:
        print(f"{YELLOW}[CONNECT FROM OTHER DEVICES] No non-loopback IPv4 detected automatically.{RESET}")
        print(f"{YELLOW}  Share the server laptop's hotspot/LAN IPv4 and keep TCP {PORT} allowed in the firewall.{RESET}\n")

    timer_thread = threading.Thread(target=auction_timer)
    timer_thread.daemon = True
    timer_thread.start()

    # tried asyncio first but threading was easier to reason about for this
    while True:
        conn, addr = raw_socket.accept()
        if ENABLE_SSL:
            try:
                conn = ssl_context.wrap_socket(conn, server_side=True)
            except ssl.SSLError as exc:
                # Keep server alive even when a non-TLS/invalid client hits the port.
                print(f"{YELLOW}[TLS HANDSHAKE FAILED] {addr} -> {exc}{RESET}")
                conn.close()
                continue

        client_thread = threading.Thread(target=handle_client, args=(conn, addr))
        client_thread.daemon = True
        client_thread.start()
        print(f"{GREEN}[ACTIVE CONNECTIONS] {threading.active_count() - 1}{RESET}")


if __name__ == "__main__":
    start_server()
