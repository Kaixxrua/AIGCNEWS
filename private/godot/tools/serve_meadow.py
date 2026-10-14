"""Loopback-only Web preview. Serve versioned exports, not source/snapshot trees."""
import argparse
from email.utils import parsedate_to_datetime
from functools import lru_cache, partial
import gzip
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import zlib
from urllib.parse import parse_qs, unquote, urlsplit

CHUNK = 1024 * 1024
HASH_NAME = re.compile(r"^(.+)\.([0-9a-f]{64})(\.[^.]+)$")


def fingerprint(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=256)
def file_hash(path, stamp):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    if fingerprint(path) != stamp:
        raise OSError("File changed while hashing")
    return digest.hexdigest()


@lru_cache(maxsize=32)
def manifest(path, stamp):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or fingerprint(path) != stamp:
        raise ValueError("Invalid/changing manifest")
    return data


@lru_cache(maxsize=128)
def legacy_gzip_matches(path, stamp, raw_hash):
    """Old exports have no encoded hashes. Validate once, not just by mtime."""
    digest = hashlib.sha256()
    try:
        with gzip.open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(CHUNK), b""):
                digest.update(chunk)
        return fingerprint(path) == stamp and digest.hexdigest() == raw_hash
    except (OSError, EOFError, zlib.error):
        return False


def encoding_preferences(header):
    """Explicit exclusions override '*'; implicit identity is a fallback."""
    values = {}
    for item in (header or "").lower().split(","):
        parts = [part.strip() for part in item.split(";")]
        if not parts[0]:
            continue
        quality = 1.0
        if len(parts) > 1:
            match = re.fullmatch(r"q\s*=\s*(0(?:\.\d{0,3})?|1(?:\.0{0,3})?)", parts[1])
            quality = float(match[1]) if match and len(parts) == 2 else 0.0
        values[parts[0]] = min(values.get(parts[0], 1.0), quality)
    return values


class MeadowHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm",
                      ".pck": "application/octet-stream", ".js": "text/javascript; charset=utf-8",
                      ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8"}

    def send_head(self):
        route = unquote(urlsplit(self.path).path)
        if not re.fullmatch(r"/v\d+/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(html|js|css|wasm|pck|png|ico)", route):
            self.send_error(404)
            return None
        root = Path(self.directory).resolve()
        source = (root / route.lstrip("/")).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            self.send_error(404)
            return None
        try:
            return self._asset_head(root, source)
        except (OSError, ValueError):
            self.send_error(503, "Asset publication in progress; retry")
            return None

    def _asset_head(self, root, source):
        source_stamp = fingerprint(source)
        raw_hash = file_hash(source, source_stamp)
        named_hash = HASH_NAME.fullmatch(source.name)
        query_hashes = parse_qs(urlsplit(self.path).query).get("v", [])
        if ((named_hash and named_hash[2] != raw_hash) or
                any(re.fullmatch(r"[0-9a-fA-F]{16,64}", token) and
                    not raw_hash.startswith(token.lower()) for token in query_hashes)):
            # Do not return new bytes under an old content-addressed URL.
            self.send_response(404)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        record = {}
        manifest_path = source.parent / "web-payload.json"
        if manifest_path.resolve().is_relative_to(root) and manifest_path.is_file():
            try:
                canonical = named_hash[1] + named_hash[3] if named_hash else source.name
                record = manifest(manifest_path, fingerprint(manifest_path)).get(canonical, {})
                if not isinstance(record, dict) or record.get("sha256") != raw_hash:
                    record = {}
            except (OSError, ValueError):
                record = {}
        preferences = encoding_preferences(self.headers.get("Accept-Encoding"))
        choices = []
        for coding, suffix, tie in (("br", ".br", 2), ("gzip", ".gz", 1)):
            quality = preferences.get(coding, preferences.get("*", 0))
            if quality > 0:
                choices.append((quality, tie, coding, suffix))
        identity_q = preferences.get("identity", 0 if preferences.get("*") == 0 else 1)
        if identity_q > 0:
            # Explicit identity competes by q; otherwise it is the final fallback.
            choices.append((identity_q if "identity" in preferences else -1, 0, "identity", ""))
        selected = None
        for _, _, coding, suffix in sorted(choices, reverse=True):
            if coding == "identity":
                selected, stamp, digest = source, source_stamp, raw_hash
                break
            path = source.with_name(source.name + suffix).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                continue
            stamp = fingerprint(path)
            encoded_hash = file_hash(path, stamp)
            encoded = record.get("encodings", {})
            info = encoded.get(coding, {}) if isinstance(encoded, dict) else {}
            valid = (isinstance(info, dict) and info.get("sha256") == encoded_hash and
                     info.get("bytes") == stamp[2])
            # gzip remains usable for pre-manifest exports and retained older URLs.
            # Unverified Brotli is ignored: serving static .br requires no codec here.
            if not valid and coding == "gzip":
                valid = legacy_gzip_matches(path, stamp, raw_hash)
            if valid:
                selected, digest = path, encoded_hash
                break
        if selected is None:
            self.send_response(406)
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        etag = f'"{coding}-{digest}"'
        modified = max(source_stamp[3], stamp[3]) // 1_000_000_000
        inm = self.headers.get("If-None-Match")
        unchanged = False
        if inm is not None:
            tags = [tag.strip() for tag in inm.split(",")]
            unchanged = any(tag == "*" or tag.removeprefix("W/") == etag for tag in tags)
        elif self.headers.get("If-Modified-Since"):
            try:
                date = parsedate_to_datetime(self.headers["If-Modified-Since"])
                unchanged = date.tzinfo is not None and modified <= date.timestamp()
            except (ValueError, TypeError, OverflowError):
                pass
        # Open before headers, and reject a concurrently replaced publication.
        stream = selected.open("rb")
        if fingerprint(selected) != stamp or fingerprint(source) != source_stamp:
            stream.close()
            raise OSError("Asset changed before response")
        status = 304 if unchanged else 200
        self.send_response(status)
        self.send_header("ETag", etag)
        self.send_header("Vary", "Accept-Encoding")
        immutable = named_hash and source.suffix != ".html"
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable
                         else "public, max-age=0, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Last-Modified", self.date_time_string(modified))
        if coding != "identity":
            self.send_header("Content-Encoding", coding)
        if status == 304:
            self.end_headers()
            stream.close()
            return None
        self.send_header("Content-type", self.guess_type(str(source)))
        self.send_header("Content-Length", str(stamp[2]))
        self.end_headers()
        return stream


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--bind", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4231)
    args = parser.parse_args()
    root = args.directory.resolve(strict=True)
    handler = partial(MeadowHandler, directory=str(root))
    with ThreadingHTTPServer((args.bind, args.port), handler) as server:
        print(f"Meadow preview on http://{args.bind}:{args.port}/; root={root}", flush=True)
        server.serve_forever()
