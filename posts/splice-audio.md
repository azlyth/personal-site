---
title: "Insert an audio clip to a video file with FFMPEG"
date: '2017-10-26'
draft: false
---
### The goal

For a [hobby project of mine](https://github.com/azlyth/redub), I wanted to be able
to merge an audio clip into the existing audio track of a video file.

### The command

After struggling for an hour or two, I finally came up with the correct incantation of the command
`ffmpeg` to overlay an audio clip to a video file:

```bash
ffmpeg \
  -i movie.mkv \
  -i new-audio-clip.mp3 \
  -filter_complex "[1:0] adelay=2728000|2728000 [delayed];[0:1][delayed] amix=inputs=2" \
  -map 0:0 \
  -c:a aac -strict -2 \
  -c:v copy \
  output.mp4
```

### The explanation

Line by line:

- **-i movie.mkv**: set the video/audio file as an input
- **-i new-audio-clip.mp3**: set the audio clip as an input
- **-filter_complex "..."**: specify the two following filters:
  - **"[1:0] adelay=2728000|2728000 [delayed]**: the adelay filter, specifically:
     - **[1:0]**: using the second input file's first stream
     - **adelay=2728000|2728000**: add a delay of 2,728,000 milliseconds to both channels of the audio (the left and right channels, because the audio is stereo)
     - **[delayed]**: assign the name "delayed" to the new stream
  - **[0:1][delayed] amix=inputs=2**: the amix filter, specifically:
     - **[0:1][delayed]**: using the first input's second stream and the "delayed" stream
     - **amix=inputs=2**: mix the two audio streams (NOTE: I'm not 100% on the meaning of **inputs=2** here)
- **-map 0:0**: add the first input's first stream to the output (which is the video)
- **-c:a aac -strict -2**: use AAC for audio encoding
- **-c:v copy**: don't re-encode the video (in other words, copy the original encoding)
- **output.mp4**: specify the output file

### JS version

And for any of you interested in doing this in JavaScript, here's the same command translated to
[node-fluent-ffmpeg](https://github.com/fluent-ffmpeg/node-fluent-ffmpeg):

```js
ffmpeg()
  .input('movie.mkv')
  .input('new-audio-clip.mp3')
  .complexFilter([
    '[1:0] adelay=2728000|2728000 [delayed]',
    '[0:1][delayed] amix=inputs=2',
  ])
  .outputOption('-map 0:0')
  .audioCodec('aac')
  .videoCodec('copy')
  .save('output.mp4')
```
### Realization

After writing all of this, I now realize that I actually need to silence the video's audio track
for the duration of the new audio clip. Not merge them.

Back to work.