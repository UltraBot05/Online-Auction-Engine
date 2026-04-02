"""
server.py -- Online Auction Engine
Skeleton: socket setup, item fetching, client accept loop.
Threading, broadcast, auction timer, and SSL added in next commit.
"""

import socket
import json
import random
import urllib.request

HOST = "127.0.0.1"
PORT = 9999
AUCTION_DURATION = 60

FALLBACK_ITEMS = [
    ("Nvidia RTX 5090", 1800),
    ("MacBook Neo", 2500),
    ("Rolex Submariner", 8000),
    ("iPhone 18 Pro Max 1TB", 1600),
]


def fetch_todays_item():
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
            raise ValueError("Empty product list")
        product = random.choice(products)
        return (str(product["title"]).strip(), int(product["price"]))
    except Exception as exc:
        print(f"[ERROR] API failed: {exc}. Using fallback.")
        return random.choice(FALLBACK_ITEMS)


def start_server():
    item, price = fetch_todays_item()
    print(f"[SERVER] Item: {item} | Start price: ${price}")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"[SERVER] Listening on {HOST}:{PORT}")

    while True:
        conn, addr = server_socket.accept()
        print(f"[CONNECTION] {addr}")
        conn.send(b"Connected. Auction coming soon.\n")
        conn.close()


if __name__ == "__main__":
    start_server()