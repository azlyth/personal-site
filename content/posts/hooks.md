+++
title = "A mobile app to run scripts on servers"
date = 2016-11-24
draft = false
+++
Over the years, whether I was working with a Raspberry Pi or running a server, there would often be
one-off scripts that I would want to run. The usual pattern would be:

- SSH into the server
- Run a single command
- Logout

I always thought it would be nice to have a phone app that could easily run those scripts.

I'd try some mobile SSH client but those felt clunky; a full-blown terminal was overkill. I just
wanted to quickly run a single script.

Other times I'd write a quick Flask app to listen on obscure ports and URLs to trigger a script.
This also felt like overkill, though, because I really didn't want to have to expose some HTTP
server on some port just to run a script on occasion.

So I decided to bite the bullet and write the app that I wanted.

## Hooks

The app is simple. It works as follows:

- Add a server's SSH credentials
- You'll see a list of the executable files in **~/.hooks-app/hooks**
- Tap one of them and it will run

I myself have started to use this for a few things, including making sure all the containers are
running properly on this server.

<p align="center">
<img src="/content/images/2016/11/demo.gif" alt="How it works" style="width:250px;">
</p>

## What I learned

This was the first time I used React and it's libraries. I have to say that using it, particularly
together with Redux, felt elegant and safe. The fact that a global state defines the UI really
makes things simpler.

Working with React Native was also a treat. **Hot Loading** is a wonderful feature that will update
your app when you save a file, while maintaining your app's state. This makes UI work so much
easier.

I also got to write some native Android code. I used the JSch Java library to do the SSH
communication, so I had to write a bridge between that library and the app's JavaScript. Basically,
you write a new Java class that implements method (annotated with **@ReactMethod**) where certain
Java types map to the JS types.

Finally, I learned that ES6 is the bomb. Special shoutouts to the feature listed below.

Shorthand property names:

```js
return { foo, bar, baz }
```

Object destructuring:
```js
let { width: screenWidth } = Dimensions.get('window')
```

Arrow functions:
```js
[1, 2, 3].map(x => x + 5)
```

Object spread operator:
```js
{ ...currentState, ...newState }
```

Async / await:
```js
let x = await somePromiseReturningMethod()
```

## Get the app

I haven't written an iOS version of the native SSH bridge, so for now, the app only works on
Android.

- [Google Play store](https://play.google.com/store/apps/details?id=com.hooks)
- [GitHub](https://github.com/azlyth/hooks)
