import logging
import logging.handlers
import socket
import ssl
import time
import os
import platform

class TLSSysLogHandler(logging.handlers.SysLogHandler):
    """
    A SysLogHandler that supports TLS over TCP.
    Overrides createSocket to wrap the established TCP socket in an SSL context.
    """
    def __init__(self, address, **kwargs):
        super().__init__(address=address, socktype=socket.SOCK_STREAM, **kwargs)

    def createSocket(self):
        """
        Creates a socket, connects it, and wraps it in SSL if it is TCP.
        """
        super().createSocket()
        if self.socktype == socket.SOCK_STREAM and self.socket:
            try:
                context = ssl.create_default_context()
                # Wrap the existing socket with SSL
                ssl_sock = context.wrap_socket(self.socket, server_hostname=self.address[0])
                self.socket = ssl_sock
            except Exception:
                if self.socket:
                    self.socket.close()
                self.socket = None
                raise


class RFC5424Formatter(logging.Formatter):
    """
    Formatter to output logs in RFC 5424 format suitable for SolarWinds Observability.
    SysLogHandler.emit() automatically prepends the `<PRI>` part, so we format the rest:
    Format: 1 YYYY-MM-DDThh:mm:ss.sssZ HOSTNAME APPNAME PROCID MSGID [swc@32473 token="YOUR_TOKEN"] MESSAGE
    """
    def __init__(self, app_name='django', token=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app_name = app_name
        self.token = token or os.getenv('SOLARWINDS_TOKEN', '')
        self.hostname = platform.node()

    def format(self, record):
        # Format timestamp (RFC3339)
        t = time.gmtime(record.created)
        ms = int(record.msecs)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", t) + f".{ms:03d}Z"
        
        msg = super().format(record)
        
        proc_id = os.getpid()
        msg_id = "-"
        
        # The structured data part where SolarWinds expects the token
        structured_data = f'[swc@32473 token="{self.token}"]' if self.token else "-"
        
        return f"1 {timestamp} {self.hostname} {self.app_name} {proc_id} {msg_id} {structured_data} {msg}"
