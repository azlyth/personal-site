#!/usr/bin/env python3
"""Process an image for a blog post and upload it to img.cloudy.nyc.

Strips EXIF (re-encoding drops it; also drops GPS data from phone photos),
caps the longest edge at 1600px, and re-encodes as JPEG. Uploads to
s3://$PERSONAL_SITE_IMAGES_BUCKET/<post-slug>/<name>.jpg with a far-future
Cache-Control, since Cloudflare (img.cloudy.nyc, via Caddy) edge-caches by
that header and the key is unique per post.

Usage: scripts/upload-image.py <post-slug> <name> <source-image>
Prints the final https://img.cloudy.nyc/... URL on success.

Credentials: ../personal-cloud-infra `make sync-personal-site-images` writes
.aws.env here (gitignored) with PERSONAL_SITE_IMAGES_*.
"""
import os
import subprocess
import sys

from PIL import Image, ImageOps

MAX_EDGE = 1600
JPEG_QUALITY = 85


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


def process(src_path, out_path):
    img = Image.open(src_path)
    img = ImageOps.exif_transpose(img)  # apply rotation before dropping EXIF
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_EDGE:
        scale = MAX_EDGE / longest
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)


def main():
    if len(sys.argv) != 4:
        sys.exit(f"usage: {sys.argv[0]} <post-slug> <name> <source-image>")
    post_slug, name, src_path = sys.argv[1:4]
    if not os.path.exists(src_path):
        sys.exit(f"no such file: {src_path}")

    env = load_env()
    bucket = env["PERSONAL_SITE_IMAGES_BUCKET"]
    key = f"{post_slug}/{name}.jpg"
    out_path = f"/tmp/{name}.upload.jpg"

    process(src_path, out_path)

    aws_env = dict(env)
    aws_env["AWS_ACCESS_KEY_ID"] = env["PERSONAL_SITE_IMAGES_ACCESS_KEY_ID"]
    aws_env["AWS_SECRET_ACCESS_KEY"] = env["PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY"]
    aws_env["AWS_DEFAULT_REGION"] = env.get("AWS_REGION", "us-east-1")

    subprocess.run(
        [
            "aws", "s3", "cp", out_path, f"s3://{bucket}/{key}",
            "--content-type", "image/jpeg",
            "--cache-control", "public, max-age=31536000, immutable",
            "--no-progress",
        ],
        env=aws_env,
        check=True,
    )
    os.remove(out_path)
    print(f"https://img.cloudy.nyc/{key}")


if __name__ == "__main__":
    main()
