#!/usr/bin/env python3
"""Process an image for a blog post and upload it to img.cloudy.nyc.

Strips EXIF (re-encoding drops it; also drops GPS data from phone photos),
caps the longest edge at 1600px, and re-encodes as JPEG. Uploads to
s3://$PERSONAL_SITE_IMAGES_BUCKET/<key> with a far-future, immutable
Cache-Control -- safe only because `image_key` (shared with the tablet
editor's upload path, see editor/images.py) content-hashes the bytes into
the key. Re-running this with a corrected photo under the same <name> still
gets a *different* key, so the old bytes don't stay stuck behind Cloudflare's
edge cache and a browser's "immutable" forever. A plain `<post-slug>/<name>`
key -- what this script used before -- can't make that promise: the same
name re-uploaded reuses the URL, and an immutable Cache-Control means caches
never even re-check.

Usage: scripts/upload-image.py <post-slug> <name> <source-image>
Prints the final https://img.cloudy.nyc/... URL on success.

Credentials: ../personal-cloud-infra `make sync-personal-site-images` writes
.aws.env here (gitignored) with PERSONAL_SITE_IMAGES_*.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Shared with the tablet editor's upload path so a fix (or the key scheme)
# reaches both instead of drifting -- see editor/images.py.
from editor.images import CACHE_CONTROL, image_key, process_image  # noqa: E402


def load_env():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".aws.env")
    if not os.path.exists(env_path):
        sys.exit(f"missing {env_path} — run 'make sync-personal-site-images' in personal-cloud-infra first")
    env = dict(os.environ)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    required = ["PERSONAL_SITE_IMAGES_BUCKET", "PERSONAL_SITE_IMAGES_ACCESS_KEY_ID", "PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        sys.exit(f"{env_path} is missing: {', '.join(missing)}")
    return env


def main():
    if len(sys.argv) != 4:
        sys.exit(f"usage: {sys.argv[0]} <post-slug> <name> <source-image>")
    post_slug, name, src_path = sys.argv[1:4]
    if not os.path.exists(src_path):
        sys.exit(f"no such file: {src_path}")

    env = load_env()
    bucket = env["PERSONAL_SITE_IMAGES_BUCKET"]

    with open(src_path, "rb") as fh:
        processed = process_image(fh.read())
    key = image_key(post_slug, name, processed)
    out_path = f"/tmp/{os.path.basename(key).replace('/', '_')}.upload.jpg"
    with open(out_path, "wb") as fh:
        fh.write(processed)

    aws_env = dict(env)
    aws_env["AWS_ACCESS_KEY_ID"] = env["PERSONAL_SITE_IMAGES_ACCESS_KEY_ID"]
    aws_env["AWS_SECRET_ACCESS_KEY"] = env["PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY"]
    aws_env["AWS_DEFAULT_REGION"] = env.get("AWS_REGION", "us-east-1")

    subprocess.run(
        [
            "aws", "s3", "cp", out_path, f"s3://{bucket}/{key}",
            "--content-type", "image/jpeg",
            "--cache-control", CACHE_CONTROL,
            "--no-progress",
        ],
        env=aws_env,
        check=True,
    )
    os.remove(out_path)
    print(f"https://img.cloudy.nyc/{key}")


if __name__ == "__main__":
    main()
