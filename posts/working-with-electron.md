---
title: "Working with Electron"
date: '2017-11-12'
draft: false
---

Working with [Electron](https://electron.atom.io/) is a pleasure. I just built an
app called [Redub](http://redub.audio) with it. For the uninitiated, here is how the
creators describe Electron:

> Electron is a framework for creating native applications with web technologies like JavaScript,
  HTML, and CSS.

Most programmers know how to build web apps. Now, with that same knowledge, you can build
cross-platform desktop apps.

Electron gets a
[lot](https://josephg.com/blog/electron-is-flash-for-the-desktop/)
[of](https://medium.com/@caspervonb/electron-is-cancer-b066108e6c32)
[crap](http://sircmpwn.github.io/2016/11/24/Electron-considered-harmful.html)
for being too resource intensive and for enabling lazy developers. The haters say that better
frameworks for desktop apps already exist and that you should use those instead.

They're right, Electron apps are more intensive than I'd like. For those unaware, it's because
every app has a full browser baked into it. That's how you're able to use Javascript, HTML, and CSS.

But let me be the first to say: the haters are missing the point, as usual. The real value of
Electron is that it lets you move from **random idea** to **cross-platform app** fast, using the
web dev knowledge you probably already have (which also means you have a huge community to draw
from).

Also, it's not like you the performance problems can't be addressed. Solutions are already being
proposed. For example, there's talks of an ["Electron runtime"](https://github.com/electron/electron/issues/673).
Basically, every Electron app on your system would share a single copy of chromium.

Finally, let's be real. Most people don't have the time to learn a new language and cross-platform
framework. So if there wasn't a way to use web tech to build desktop apps, some ideas wouldn't ever
get created.

So, I ask you, dear reader: would you rather live in a world with apps that are memory hogs but
fulfill unique needs, or not have those apps exist at all? I'm definitely with the first.
