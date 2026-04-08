"""Simple performance check for the auction server."""

import socket
import ssl
import threading
import time
import statistics
import os
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999
ENABLE_SSL = True

# Test parameters
LATENCY_SAMPLES    = 10   # connections for latency test
CONCURRENT_CLIENTS = 10   # simultaneous clients for concurrency test
BIDS_PER_CLIENT    = 5    # bids each concurrent client sends

results_lock = threading.Lock()
all_bid_rtts = []
connect_times = []
errors = 0


def resolve_target():
    """Resolve host/port from CLI args or env vars for flexible local/LAN testing."""
    host = DEFAULT_HOST
    port = DEFAULT_PORT

    if len(sys.argv) > 1 and sys.argv[1].strip():
        host = sys.argv[1].strip()
    elif os.getenv("AUCTION_HOST"):
        host = os.getenv("AUCTION_HOST", "").strip() or DEFAULT_HOST

    port_value = ""
    if len(sys.argv) > 2:
        port_value = sys.argv[2].strip()
    elif os.getenv("AUCTION_PORT"):
        port_value = os.getenv("AUCTION_PORT", "").strip()

    if port_value:
        port = int(port_value)

    return host, port


HOST, PORT = resolve_target()


def make_socket():
    """Create a plain or SSL-wrapped socket depending on ENABLE_SSL."""
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(10)
    if ENABLE_SSL:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations("server.pem")
        return ctx.wrap_socket(raw, server_hostname=HOST)
    return raw


def measure_connection_latency(sample_num):
    """Connect, send a name, receive banner, then disconnect. Records connect time."""
    global errors
    try:
        t0 = time.perf_counter()
        sock = make_socket()
        sock.connect((HOST, PORT))
        t1 = time.perf_counter()

        sock.recv(1024)                          # "Enter your name: "
        sock.send(f"LatencyBot{sample_num}".encode())
        sock.recv(4096)                          # welcome banner

        connect_ms = (t1 - t0) * 1000
        with results_lock:
            connect_times.append(connect_ms)

        sock.send("quit".encode())
        try:
            sock.recv(1024)                      # goodbye message
        except Exception:
            pass
        sock.close()
    except Exception as e:
        with results_lock:
            errors += 1
        print(f"  [ERROR] Latency sample {sample_num} failed: {e}")


def concurrent_bidder(client_id, start_price):
    """
    Simulates a bidder: connects, places BIDS_PER_CLIENT bids,
    records round-trip time for each bid, then quits.
    """
    global errors
    try:
        sock = make_socket()
        sock.connect((HOST, PORT))

        sock.recv(1024)                              # "Enter your name: "
        sock.send(f"Bot{client_id}".encode())
        sock.recv(4096)                              # welcome banner

        bid = start_price + (client_id * 100)
        for _ in range(BIDS_PER_CLIENT):
            bid += 10
            t0 = time.perf_counter()
            sock.send(str(bid).encode())
            sock.recv(4096)                          # server response
            t1 = time.perf_counter()
            rtt_ms = (t1 - t0) * 1000
            with results_lock:
                all_bid_rtts.append(rtt_ms)

        sock.send("quit".encode())
        try:
            sock.recv(1024)                      # goodbye message
        except Exception:
            pass
        sock.close()
    except Exception as e:
        with results_lock:
            errors += 1
        # not all bids will be accepted when concurrent - that's expected
        # print(f"  [DEBUG] Bot{client_id} exception: {e}")


def run_latency_test():
    print(f"\n{'='*55}")
    print(f"  TEST 1: Connection Latency ({LATENCY_SAMPLES} sequential connections)")
    print(f"{'='*55}")
    for i in range(LATENCY_SAMPLES):
        measure_connection_latency(i)
        time.sleep(0.1)   # small gap so server doesn't throttle

    if connect_times:
        print(f"  Samples     : {len(connect_times)}")
        print(f"  Min latency : {min(connect_times):.2f} ms")
        print(f"  Max latency : {max(connect_times):.2f} ms")
        print(f"  Avg latency : {statistics.mean(connect_times):.2f} ms")
        print(f"  Std dev     : {statistics.stdev(connect_times):.2f} ms" if len(connect_times) > 1 else "")
    else:
        print("  No samples collected - is server running?")


def run_concurrent_test(start_price):
    print(f"\n{'='*55}")
    print(f"  TEST 2: Concurrent Clients ({CONCURRENT_CLIENTS} clients, {BIDS_PER_CLIENT} bids each)")
    print(f"{'='*55}")

    threads = []
    t0 = time.perf_counter()
    for i in range(CONCURRENT_CLIENTS):
        t = threading.Thread(target=concurrent_bidder, args=(i, start_price))
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    elapsed = time.perf_counter() - t0
    total_bids = CONCURRENT_CLIENTS * BIDS_PER_CLIENT

    print(f"  Clients     : {CONCURRENT_CLIENTS}")
    print(f"  Total bids  : {total_bids}")
    print(f"  Errors      : {errors}")
    print(f"  Total time  : {elapsed:.2f} s")
    print(f"  Throughput  : {total_bids / elapsed:.1f} bids/sec")

    if all_bid_rtts:
        print(f"\n  Bid Round-Trip Time (RTT):")
        print(f"  Min RTT     : {min(all_bid_rtts):.2f} ms")
        print(f"  Max RTT     : {max(all_bid_rtts):.2f} ms")
        print(f"  Avg RTT     : {statistics.mean(all_bid_rtts):.2f} ms")
        print(f"  Median RTT  : {statistics.median(all_bid_rtts):.2f} ms")
        if len(all_bid_rtts) > 1:
            print(f"  Std dev     : {statistics.stdev(all_bid_rtts):.2f} ms")

    return total_bids, elapsed


def fmt_stat(values, fn, suffix=" ms"):
    """Format a numeric stat consistently for README copy-paste."""
    if not values:
        return "N/A"
    return f"{fn(values):.2f}{suffix}"


def print_summary(total_bids, elapsed):
    """Print a short summary that can be copied into the README."""
    throughput = total_bids / elapsed if elapsed > 0 else 0.0
    connect_std = f"{statistics.stdev(connect_times):.2f} ms" if len(connect_times) > 1 else "N/A"
    bid_std = f"{statistics.stdev(all_bid_rtts):.2f} ms" if len(all_bid_rtts) > 1 else "N/A"

    print(f"\n{'='*55}")
    print("  SUMMARY")
    print(f"{'='*55}")
    print(f"Host: {HOST}:{PORT} | SSL: {'On' if ENABLE_SSL else 'Off'}")
    print(f"Latency samples: {LATENCY_SAMPLES} | Concurrent clients: {CONCURRENT_CLIENTS} | Bids/client: {BIDS_PER_CLIENT}")
    print(f"Connection latency -> min {fmt_stat(connect_times, min)}, max {fmt_stat(connect_times, max)}, avg {fmt_stat(connect_times, statistics.mean)}, std {connect_std}")
    print(f"Bid RTT -> min {fmt_stat(all_bid_rtts, min)}, max {fmt_stat(all_bid_rtts, max)}, avg {fmt_stat(all_bid_rtts, statistics.mean)}, median {fmt_stat(all_bid_rtts, statistics.median)}, std {bid_std}")
    print(f"Total bids: {total_bids} | Total time: {elapsed:.2f} s | Throughput: {throughput:.1f} bids/sec | Errors: {errors}")


def main():
    print("\nAuction performance check")
    print(f"Target: {HOST}:{PORT}")
    print(f"SSL: {'Enabled' if ENABLE_SSL else 'Disabled'}")
    print("Keep server.py running and use a long auction duration for this test.")

    run_latency_test()

    # Use a high starting price so bids don't clash with active auction price
    total_bids, elapsed = run_concurrent_test(start_price=50000)

    print(f"\n{'='*55}")
    print("  Done")
    print(f"{'='*55}\n")
    print_summary(total_bids, elapsed)


if __name__ == "__main__":
    main()
