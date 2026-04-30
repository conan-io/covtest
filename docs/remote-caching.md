# Remote caching

In a CI/CD environment, every branch produces its own snapshot. Remote caching lets developers and CI agents download the right snapshot automatically on a fresh checkout — no manual `covtest process` needed before predictions work.

---

## How it works

1. **CI runs the full test suite** on a clean commit, runs `covtest process`, then `covtest upload`.
2. The snapshot is stored on a simple HTTP file server at `<server_url>/<commit-hash>.covtest`.
3. **Developers** run `covtest predict` (or `-p covtest.predict`). If no local snapshot is found, covtest queries the server for the nearest ancestor commit that has one, downloads it, and proceeds with prediction.
4. **Negative results are cached locally** for `server_cache_ttl` seconds so repeated invocations don't hit the server unnecessarily.

---

## Server setup

The protocol is plain HTTP GET (download) and PUT (upload). Any static file server that supports PUT works.

### nginx with WebDAV

```nginx
location /covtest/ {
    root /var/www;
    dav_methods PUT;
    create_full_put_path on;
    dav_access user:rw group:r all:r;
    autoindex on;
}
```

### AWS S3 with pre-signed URLs

Use a small proxy or Lambda function that accepts PUT requests, generates pre-signed S3 upload URLs, and forwards them. The GET side can be a public CloudFront distribution.

### Simple Python server (for local testing)

```python
# serve.py — development only, no auth
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

class Handler(BaseHTTPRequestHandler):
    ROOT = "snapshots"

    def do_PUT(self):
        path = os.path.join(self.ROOT, self.path.lstrip("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        length = int(self.headers["Content-Length"])
        with open(path, "wb") as f:
            f.write(self.rfile.read(length))
        self.send_response(201)
        self.end_headers()

    def do_GET(self):
        path = os.path.join(self.ROOT, self.path.lstrip("/"))
        if os.path.isfile(path):
            self.send_response(200)
            self.end_headers()
            with open(path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

HTTPServer(("", 8765), Handler).serve_forever()
```

---

## Configuration

```ini
# covtest.ini
[covtest]
server_url = https://covtest.example.com/myproject
server_cache_ttl = 3600
```

---

## CI workflow example

```yaml
# .github/workflows/ci.yml (relevant steps)

- name: Run test suite
  run: pytest --cov=mypackage --cov-context=test

- name: Build covtest snapshot
  run: covtest process

- name: Upload snapshot to server
  run: covtest upload
  env:
    # If your server requires auth, pass it via environment and read it
    # in a custom upload wrapper. Basic PUT needs no env by default.
```

The upload step only runs on the main branch (or release branches) where snapshots are authoritative. Feature branch CI can skip the upload and rely on the server serving the merge-base snapshot.

---

## Developer workflow with remote caching

On a fresh checkout:

```bash
git clone https://github.com/myorg/myrepo
cd myrepo
pip install -e ".[dev]"

# Edit some files, then:
covtest predict        # downloads the nearest snapshot automatically
pytest @.covtest/covtests.tests
```

No manual `covtest process` step. The snapshot is pulled from the server transparently.
