#!/usr/bin/env python3
"""Process a short video clip for a blog post and upload it to img.cloudy.nyc.

Re-encodes as muted H.264 (no audio track, since these are silent looping
clips), scaled to 640px wide — much smaller than an equivalent animated
WebP/GIF for photographic content, and hardware-decoded by the browser.
Uploads to s3://$PERSONAL_SITE_IMAGES_BUCKET/<key> with a far-future,
immutable Cache-Control -- safe only because `video_key` (shared with the
tablet editor's upload path, see editor/videos.py) content-hashes the
*encoded* bytes into the key, same reasoning as upload-image.py. A plain
`<post-slug>/<name>` key -- what this script used before -- lets a
re-uploaded fix reuse the old URL, and an immutable Cache-Control means nothing
ever re-checks it.

Usage: scripts/upload-video.py <post-slug> <name> <source-video> [loop-seconds]
Prints the final https://img.cloudy.nyc/... URL on success.

If loop-seconds is given, the source is looped (via -stream_loop) and cut to
exactly that many seconds at a fixed frame rate, so several clips of
different native lengths come out with identical, frame-accurate durations —
needed for multiple <video> elements on a page to stay loop-synchronized
(see data-sync-loop in base.html).

Credentials: ../personal-cloud-infra `make sync-personal-site-images` writes
.aws.env here (gitignored) with PERSONAL_SITE_IMAGES_*.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Shared with the tablet editor's upload path so a fix to one reaches both.
from editor.ffmpeg_args import STRIP_METADATA, encode_args, is_hdr, video_filter  # noqa: E402
from editor.videos import CACHE_CONTROL, video_key  # noqa: E402

FPS = 30


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


def process(src_path, out_path, loop_seconds=None):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if loop_seconds:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", src_path]
    hdr = is_hdr(src_path)
    extra = f"fps={FPS}" if loop_seconds else ""
    cmd += [*STRIP_METADATA, "-vf", video_filter(hdr, extra), *encode_args(hdr)]
    if loop_seconds:
        cmd += ["-t", str(loop_seconds), "-frames:v", str(round(loop_seconds * FPS))]
    cmd += [out_path]
    subprocess.run(cmd, check=True)


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(f"usage: {sys.argv[0]} <post-slug> <name> <source-video> [loop-seconds]")
    post_slug, name, src_path = sys.argv[1:4]
    loop_seconds = float(sys.argv[4]) if len(sys.argv) == 5 else None
    if not os.path.exists(src_path):
        sys.exit(f"no such file: {src_path}")

    env = load_env()
    bucket = env["PERSONAL_SITE_IMAGES_BUCKET"]
    out_path = f"/tmp/{name}.upload.mp4"

    process(src_path, out_path, loop_seconds)
    with open(out_path, "rb") as fh:
        encoded = fh.read()
    key = video_key(post_slug, name, encoded)

    aws_env = dict(env)
    aws_env["AWS_ACCESS_KEY_ID"] = env["PERSONAL_SITE_IMAGES_ACCESS_KEY_ID"]
    aws_env["AWS_SECRET_ACCESS_KEY"] = env["PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY"]
    aws_env["AWS_DEFAULT_REGION"] = env.get("AWS_REGION", "us-east-1")

    subprocess.run(
        [
            "aws", "s3", "cp", out_path, f"s3://{bucket}/{key}",
            "--content-type", "video/mp4",
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
