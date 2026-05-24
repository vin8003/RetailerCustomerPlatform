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
    Overrides makeSocket to wrap the connection in an SSL context.
    """
    def __init__(self, address, **kwargs):
        super().__init__(address=address, socktype=socket.SOCK_STREAM, **kwargs)

    def makeSocket(self, timeout=1):
        """
        Creates and returns a connected SSL socket.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(s, 'settimeout'):
            s.settimeout(timeout)
        
        try:
            s.connect(self.address)
            context = ssl.create_default_context()
            # Disable hostname checking for standard syslogs if needed, 
            # but usually it's fine. SolarWinds has a valid cert.
            ssl_sock = context.wrap_socket(s, server_hostname=self.address[0])
            return ssl_sock
        except Exception as e:
            s.close()
            raise


class RFC5424Formatter(logging.Formatter):
    """
    Formatter to output logs in RFC 5424 format suitable for SolarWinds Observability.
    Format: <PRIVAL>1 YYYY-MM-DDThh:mm:ss.sssZ HOSTNAME APPNAME PROCID MSGID [swc@32473 token="YOUR_TOKEN"] MESSAGE
    """
    def __init__(self, app_name='django', token=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app_name = app_name
        self.token = token or os.getenv('SOLARWINDS_TOKEN', '')
        self.hostname = platform.node()

    def format(self, record):
        # Calculate PRIVAL (Facility 16 (local0) * 8 + Severity)
        # severity mapping:
        syslog_severity = 6 # default info
        if record.levelno >= logging.CRITICAL:
            syslog_severity = 2
        elif record.levelno >= logging.ERROR:
            syslog_severity = 3
        elif record.levelno >= logging.WARNING:
            syslog_severity = 4
        elif record.levelno >= logging.DEBUG:
            syslog_severity = 7
            
        prival = (16 * 8) + syslog_severity
        
        # Format timestamp (RFC3339)
        t = time.gmtime(record.created)
        ms = int(record.msecs)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", t) + f".{ms:03d}Z"
        
        msg = super().format(record)
        
        proc_id = os.getpid()
        msg_id = "-"
        
        # The structured data part where SolarWinds expects the token
        structured_data = f'[swc@32473 token="{self.token}"]' if self.token else "-"
        
        return f"<{prival}>1 {timestamp} {self.hostname} {self.app_name} {proc_id} {msg_id} {structured_data} {msg}"
