"""The encode settings that make a clip play properly on a phone.

Two real defects on the published guerilla-gardening clips motivated these:

1. Phone video is HDR (BT.2020 primaries, HLG transfer). `-pix_fmt yuv420p`
   drops it to 8 bit but does NOT tone-map, and the HDR tags survive into
   the output -- so the file is SDR-ish data still *labelled* HDR. An HDR
   phone screen then routes it through the HDR path and it renders visibly
   brighter than the page around it, with BT.2020 primaries read as
   BT.709 desaturating it on top.

2. Every published clip had exactly ONE keyframe, at t=0. The loop-sync
   script in templates/base.html corrects drift by assigning `currentTime`,
   and with a single keyframe every one of those seeks has to decode the
   whole clip from frame 0. On a phone that is slow enough to cause more
   drift, which causes more seeks -- a feedback loop that lands at a few
   frames per second.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from editor import config
from editor.ffmpeg_args import GOP_FRAMES
from editor.videos import process_video


def _probe(data: bytes, entries: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.mp4"
        p.write_bytes(data)
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", entries, "-of", "csv=p=0", str(p)],
            capture_output=True, check=True,
        )
        return out.stdout.decode().strip()


def _keyframe_count(data: bytes) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.mp4"
        p.write_bytes(data)
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "frame=key_frame", "-of", "csv=p=0", str(p)],
            capture_output=True, check=True,
        )
        return sum(1 for line in out.stdout.decode().splitlines() if line.strip() == "1")


def _clip(seconds: float = 2.0, hdr: bool = False, rotated: bool = False) -> bytes:
    """A real clip from ffmpeg -- HLG/BT.2020 tagged when `hdr`, matching what
    a phone actually records.

    `rotated` adds the display-matrix side data every handheld phone clip
    carries. It is not cosmetic: its presence changes ffprobe's CSV output
    shape, which is what broke HDR detection against real footage while
    synthetic clips passed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "src.mp4"
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=s=256x144:d={seconds}:r=30",
            "-c:v", "libx264",
        ]
        if hdr:
            cmd += [
                "-pix_fmt", "yuv420p10le", "-profile:v", "high10",
                "-x264-params",
                "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
            ]
        else:
            cmd += ["-pix_fmt", "yuv420p"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True)
        if rotated:
            # -display_rotation is an input option, so the matrix gets added
            # by re-muxing rather than at encode time.
            spun = Path(tmp) / "rotated.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-display_rotation", "90",
                 "-i", str(out), "-c", "copy", str(spun)],
                check=True,
            )
            return spun.read_bytes()
        return out.read_bytes()


def test_hdr_source_is_tone_mapped_to_bt709():
    """An HLG/BT.2020 phone clip must come out tagged plain BT.709 SDR.

    Without this the browser hands it to the HDR pipeline and it looks
    brighter than everything around it.
    """
    out = process_video(_clip(hdr=True))
    transfer = _probe(out, "stream=color_transfer")
    primaries = _probe(out, "stream=color_primaries")
    space = _probe(out, "stream=color_space")

    assert transfer == "bt709", f"transfer still {transfer!r} -- HDR tag survived"
    assert primaries == "bt709", f"primaries still {primaries!r}"
    assert space == "bt709", f"matrix still {space!r}"


def test_hdr_is_detected_on_a_rotated_clip():
    """Regression: handheld phone clips carry display-matrix side data, which
    padded ffprobe's CSV output with a trailing field so the transfer value
    read as "arib-std-b67," and never matched. Real footage silently skipped
    the tone-map while synthetic clips passed."""
    out = process_video(_clip(hdr=True, rotated=True))
    assert _probe(out, "stream=color_transfer") == "bt709"


def test_hdr_source_is_downconverted_to_8_bit():
    out = process_video(_clip(hdr=True))
    assert _probe(out, "stream=pix_fmt") == "yuv420p"


def test_output_is_seekable_without_decoding_the_whole_clip():
    """A seek costs a decode back to the previous keyframe, and the loop-sync
    script seeks. One keyframe per clip makes every correction maximally
    expensive; this pins the interval so a seek stays cheap."""
    seconds = 4
    out = process_video(_clip(seconds=seconds))

    keyframes = _keyframe_count(out)
    expected = (seconds * 30) / GOP_FRAMES
    assert keyframes > 1, "single-keyframe clip: every seek re-decodes from frame 0"
    assert keyframes >= expected - 1, f"only {keyframes} keyframes in {seconds}s"


def test_sdr_source_is_left_in_its_own_colour_space():
    """The tone-map curve is only correct for HDR input -- running it over an
    already-SDR clip would crush it. SDR must take the plain path."""
    out = process_video(_clip(hdr=False))
    assert _probe(out, "stream=pix_fmt") == "yuv420p"
    assert _probe(out, "stream=color_transfer") != "arib-std-b67"


def test_both_upload_paths_share_one_encoder_definition():
    """scripts/upload-video.py and editor/videos.py produce files for the same
    bucket and the same page. They used to hand-duplicate the ffmpeg flags,
    so a fix applied to one silently missed the other."""
    script = (config.REPO / "scripts" / "upload-video.py").read_text(encoding="utf-8")

    assert "ffmpeg_args" in script, "upload-video.py must use the shared encoder args"
    assert "libx264" not in script, "upload-video.py still hardcodes encoder flags"
    assert "-crf" not in script, "upload-video.py still hardcodes a CRF"
