"""Fetch only the matching Web templates from the official Godot ZIP via HTTP ranges.

The all-platform archive is >1 GB. zipfile reads its directory remotely, then
downloads only the two single-thread Web templates into the portable editor.
"""
import io
import pathlib
import shutil
import urllib.request
import zipfile

VERSION = "4.7.2"
URL = (
    "https://github.com/godotengine/godot-builds/releases/download/"
    f"{VERSION}-stable/Godot_v{VERSION}-stable_export_templates.tpz"
)


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=45) as response:
            self.url = response.url
            self.size = int(response.headers["Content-Length"])
        self.position = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        self.position = offset + (self.position if whence == io.SEEK_CUR else self.size if whence == io.SEEK_END else 0)
        return self.position

    def read(self, size=-1):
        size = min(self.size - self.position, size if size >= 0 else self.size)
        if size <= 0:
            return b""
        start = self.position
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{start + size - 1}"})
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status != 206:
                raise RuntimeError("Server ignored the range; refusing to fetch the all-platform archive")
            data = response.read()
        if len(data) != size:
            raise RuntimeError(f"Incomplete range at {start}: {len(data)} != {size}")
        self.position += size
        return data


def main():
    root = pathlib.Path(__file__).resolve().parents[2]
    destination = root / ".tools" / f"godot-{VERSION}" / "editor_data" / "export_templates" / f"{VERSION}.stable"
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RemoteZip(URL)) as archive:
        web = [entry for entry in archive.infolist() if "web" in entry.filename and entry.filename.endswith(".zip")]
        print("Available Web templates:", [entry.filename for entry in web], flush=True)
        for entry in web:
            if "nothreads" not in entry.filename or "dlink" in entry.filename:
                continue
            target = destination / pathlib.PurePosixPath(entry.filename).name
            if target.exists() and target.stat().st_size == entry.file_size:
                print("Already present:", target.name, flush=True)
                continue
            print("Fetching:", entry.filename, "compressed bytes", entry.compress_size, flush=True)
            partial = target.with_suffix(".partial")
            with archive.open(entry) as source, partial.open("wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            partial.replace(target)
            print("Saved:", target, flush=True)


if __name__ == "__main__":
    main()
