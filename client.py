"""
client.py - Online Auction Engine
Tkinter GUI client with a background receive thread,
thread-safe queue bridge, color-coded auction log, and SSL/TLS.
"""

import socket
import ssl
import threading
import queue
import os
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999

# Toggle SSL/TLS on or off - set to False for plain TCP (no cert needed)
ENABLE_SSL = True


def resolve_server_target(root):
    """Resolve the server host/port from CLI args, env vars, or a GUI prompt."""
    host = ""
    port_value = ""

    if len(sys.argv) > 1:
        host = sys.argv[1].strip()
    elif os.getenv("AUCTION_HOST"):
        host = os.getenv("AUCTION_HOST", "").strip()

    if len(sys.argv) > 2:
        port_value = sys.argv[2].strip()
    elif os.getenv("AUCTION_PORT"):
        port_value = os.getenv("AUCTION_PORT", "").strip()

    if not host:
        host = simpledialog.askstring(
            "Server Address",
            "Enter the server IPv4 address or hostname:",
            initialvalue=DEFAULT_HOST,
            parent=root
        )
        if host is None:
            return None, None
        host = host.strip() or DEFAULT_HOST

    port = DEFAULT_PORT
    if port_value:
        try:
            port = int(port_value)
        except ValueError:
            messagebox.showerror(
                "Invalid Port",
                f"Port must be a whole number.\nReceived: {port_value}",
                parent=root
            )
            return None, None
        if not (1 <= port <= 65535):
            messagebox.showerror(
                "Invalid Port",
                f"Port must be between 1 and 65535.\nReceived: {port}",
                parent=root
            )
            return None, None

    return host, port


def receive_messages(sock, msg_queue, stop_event):
    """Continuously read from the socket and enqueue messages for the GUI."""
    while not stop_event.is_set():
        try:
            data = sock.recv(4096).decode()
            if not data:
                msg_queue.put("\n[INFO] Server has closed the connection.\n")
                stop_event.set()
                break
            msg_queue.put(data)
        except socket.timeout:
            # The socket is used in blocking mode after connect, but tolerate
            # stray timeouts so a quiet auction does not look like a disconnect.
            continue
        except (ConnectionResetError, OSError):
            if not stop_event.is_set():
                msg_queue.put("\n[DISCONNECT] Lost connection to server.\n")
                stop_event.set()
            break


class AuctionApp:
    """Tkinter GUI for placing bids and viewing the live auction log."""

    def __init__(self, root, sock, username, msg_queue, stop_event):
        self.root       = root
        self.sock       = sock
        self.username   = username
        self.msg_queue  = msg_queue
        self.stop_event = stop_event

        self.root.title(f"Online Auction Engine - {username}")
        self.root.geometry("620x480")
        self.root.resizable(False, False)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._process_queue)

    def _build_ui(self):
        title_lbl = tk.Label(
            self.root,
            text="Online Auction Engine",
            font=("Helvetica", 14, "bold"),
            pady=6
        )
        title_lbl.pack(fill=tk.X)

        log_frame = tk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log = tk.Text(
            log_frame,
            state=tk.DISABLED,
            wrap=tk.WORD,
            font=("Courier", 10),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            yscrollcommand=scrollbar.set
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log.yview)

        self.log.tag_config("yellow",  foreground="#ffd166")
        self.log.tag_config("red",     foreground="#ff6b6b")
        self.log.tag_config("green",   foreground="#80ed99")
        self.log.tag_config("cyan",    foreground="#72efdd")
        self.log.tag_config("magenta", foreground="#f284ff")

        bid_frame = tk.Frame(self.root, pady=8)
        bid_frame.pack(fill=tk.X, padx=10)

        tk.Label(bid_frame, text="Bid Amount: $", font=("Helvetica", 11)).pack(side=tk.LEFT)

        self.bid_entry = tk.Entry(bid_frame, font=("Helvetica", 11), width=14)
        self.bid_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.bid_entry.focus()
        self.bid_entry.bind("<Return>", lambda event: self._place_bid())

        place_btn = tk.Button(
            bid_frame,
            text="Place Bid",
            font=("Helvetica", 11, "bold"),
            bg="#0078d4",
            fg="white",
            activebackground="#005a9e",
            activeforeground="white",
            relief=tk.FLAT,
            padx=12,
            command=self._place_bid
        )
        place_btn.pack(side=tk.LEFT)

        quit_btn = tk.Button(
            bid_frame,
            text="Quit",
            font=("Helvetica", 11),
            fg="#cc0000",
            relief=tk.FLAT,
            padx=8,
            command=self._on_close
        )
        quit_btn.pack(side=tk.RIGHT)

    def _append_log(self, text, tag=None):
        """Insert text into the read-only log and auto-scroll."""
        self.log.config(state=tk.NORMAL)
        if tag:
            self.log.insert(tk.END, text, tag)
        else:
            self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _pick_tag(self, text):
        """Map a message prefix to a color tag."""
        normalized = text.lstrip()
        if normalized.startswith("[TIMER]"):
            return "yellow"
        if normalized.startswith("[REJECTED]"):
            return "red"
        if normalized.startswith("[NEW BID]"):
            return "green"
        if normalized.startswith("[UPDATE]"):
            return "cyan"
        if normalized.startswith("[JOIN]") or normalized.startswith("[LEAVE]"):
            return "magenta"
        return None

    def _process_queue(self):
        """Drain the message queue into the log widget (runs on GUI thread)."""
        try:
            while True:
                message = self.msg_queue.get_nowait()
                self._append_log(message, self._pick_tag(message))
        except queue.Empty:
            pass

        if not self.stop_event.is_set():
            self.root.after(100, self._process_queue)
        else:
            self._append_log("\n[SESSION ENDED] Bidding is no longer available.\n")
            self.bid_entry.config(state=tk.DISABLED)

    def _place_bid(self):
        """Send the current entry value to the server."""
        bid_text = self.bid_entry.get().strip()
        if not bid_text:
            return
        try:
            self.sock.send(bid_text.encode())
        except OSError:
            self._append_log("[ERROR] Could not send bid - connection lost.\n")
            return
        self.bid_entry.delete(0, tk.END)
        if bid_text.lower() == "quit":
            self._append_log("[YOU] Sent quit - waiting for server...\n")

    def _on_close(self):
        """Graceful shutdown on window close or Quit button."""
        self.stop_event.set()
        try:
            self.sock.send("quit".encode())
        except OSError:
            pass
        self.sock.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    root.withdraw()

    host, port = resolve_server_target(root)
    if not host:
        root.destroy()
        return

    username = simpledialog.askstring(
        "Auction Login",
        "Enter your bidder name:",
        parent=root
    )

    if not username or not username.strip():
        root.destroy()
        return

    username = username.strip()

    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_sock.settimeout(8)

    if ENABLE_SSL:
        # SSL - verify server identity using the shared certificate
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_verify_locations("server.pem")
        sock = ssl_context.wrap_socket(raw_sock, server_hostname=host)
    else:
        # plain TCP mode - no cert needed
        sock = raw_sock

    try:
        sock.connect((host, port))
        sock.settimeout(None)
    except ConnectionRefusedError:
        sock.close()
        messagebox.showerror(
            "Connection Failed",
            f"Could not connect to {host}:{port}\nMake sure server.py is running.",
            parent=root
        )
        root.destroy()
        return
    except TimeoutError:
        sock.close()
        messagebox.showerror(
            "Connection Timed Out",
            (
                f"Timed out connecting to {host}:{port}.\n"
                "Check LAN/hotspot reachability, host IP, and firewall rule for TCP 9999."
            ),
            parent=root
        )
        root.destroy()
        return
    except ssl.SSLCertVerificationError as exc:
        sock.close()
        messagebox.showerror(
            "TLS Certificate Verification Failed",
            (
                "This client does not trust the certificate presented by the server.\n"
                "Make sure every client has the same shared server.pem file from the server machine.\n\n"
                f"Details: {exc}"
            ),
            parent=root
        )
        root.destroy()
        return
    except ssl.SSLError as exc:
        sock.close()
        messagebox.showerror(
            "TLS Handshake Failed",
            f"Secure connection could not be established.\n\nDetails: {exc}",
            parent=root
        )
        root.destroy()
        return

    # consume the name prompt and welcome banner before starting
    # recv_thread so they don't leak into the GUI log
    sock.recv(1024)           # "Enter your name: " prompt
    sock.send(username.encode())
    sock.recv(4096)           # auction welcome banner

    msg_queue  = queue.Queue()
    stop_event = threading.Event()

    recv_thread = threading.Thread(
        target=receive_messages,
        args=(sock, msg_queue, stop_event)
    )
    recv_thread.daemon = True
    recv_thread.start()

    # reuse the same root window instead of creating a second tk.Tk()
    root.deiconify()
    app = AuctionApp(root, sock, username, msg_queue, stop_event)
    root.mainloop()


if __name__ == "__main__":
    main()
