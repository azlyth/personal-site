"""One definition of how a blog clip gets encoded.

Both upload paths feed the same bucket and the same page -- the tablet
editor (`editor/videos.py`) and the CLI (`scripts/upload-video.py`) -- so
the ffmpeg flags live here rather than being hand-copied into each. Import
only stdlib: upload-video.py runs standalone and must not drag in the
editor's dependencies.
"""
from __future__ import annotations

import subprocess

WIDTH = 640
CRF = 28
# ~1s at 30fps. The loop-sync script corrects drift by assigning
# currentTime, and a seek must decode from the previous keyframe -- at one
# keyframe per clip that meant re-decoding from frame 0 every time.
GOP_FRAMES = 30
# Caps the peak a phone has to chew through when several clips autoplay at
# once. CRF alone let detailed handheld footage reach ~3.8 Mbps each.
MAXRATE = "1500k"
BUFSIZE = "3000k"

# Transfer functions that mean "this is HDR". Phone video is usually HLG;
# smpte2084 is HDR10/PQ.
_HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}

# HLG/PQ BT.2020 -> BT.709 SDR. Tone-mapping has to happen in linear light,
# hence the round trip through gbrpf32le. Without this the pixels get
# squeezed to 8 bit but keep their HDR tags, and an HDR phone screen renders
# them brighter than the rest of the page.
_TONEMAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


def is_hdr(path: str) -> bool:
    """True when the source carries an HDR transfer function.

    Parsed as `key=value` rather than bare CSV on purpose: a real phone clip
    has display-matrix side data on its video stream, and `-of csv=p=0` emits
    a trailing empty field for it, so the value comes back as
    "arib-std-b67," and no longer matches. Synthetic test clips have no
    rotation and hid that.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=color_transfer", "-of", "default=nw=1", str(path)],
        capture_output=True,
    )
    if probe.returncode != 0:
        return False
    for line in probe.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "color_transfer":
            return value.strip() in _HDR_TRANSFERS
    return False


def video_filter(hdr: bool, extra: str = "") -> str:
    """The -vf chain: scale first (tone-mapping full-resolution frames is far
    slower and these are 640px loops), then tone-map when the source is HDR."""
    chain = f"scale={WIDTH}:-2"
    if extra:
        chain += f",{extra}"
    if hdr:
        chain += f",{_TONEMAP}"
    return chain


def encode_args(hdr: bool) -> list[str]:
    """Everything after -vf. Colour is only re-tagged when we actually
    tone-mapped -- forcing bt709 onto an untouched SDR clip would mislabel a
    bt601 source rather than convert it."""
    args = [
        "-an", "-c:v", "libx264", "-crf", str(CRF),
        "-preset", "medium", "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-g", str(GOP_FRAMES), "-keyint_min", str(GOP_FRAMES), "-sc_threshold", "0",
        "-maxrate", MAXRATE, "-bufsize", BUFSIZE,
        "-movflags", "+faststart",
    ]
    if hdr:
        args += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    return args


# -map_metadata -1 drops container/global metadata. Phone clips carry GPS
# (TAG:location/location-eng) and device info (TAG:com.android.model/
# manufacturer) at the format level, and ffmpeg copies it across a re-encode
# by default -- this is the video equivalent of the EXIF strip in images.py,
# and it is why a 2026-09-20 upload published the owner's home coordinates.
# Verified with ffprobe on real Pixel clips: these tags live only in
# format_tags, never stream_tags, so -map_metadata -1 alone is sufficient.
STRIP_METADATA = ["-map_metadata", "-1"]
