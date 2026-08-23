import base64
import gzip
from pathlib import Path

_payload = Path(__file__).with_name("_views_kan63.py.gz.b64").read_text()
exec(gzip.decompress(base64.b64decode("".join(_payload.split()))), globals())
