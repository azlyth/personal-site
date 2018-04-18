---
title: "A React Native library to run commands over SSH"
date: 2016-12-06
draft: false
---
For my React Native app {{< link "Hooks" "/hooks/" >}}, I wrote some native Android code to enable
the running of arbitrary commands over SSH.

I've now added the iOS side, and after some refactoring, the SSH code for both platforms is now its
own library: {{< link "react-native-ssh" "https://github.com/azlyth/react-native-ssh" >}}.

There are no tests and it's very light on the error handling. But I figured I'd put it out there
for others to use and/or improve upon.

### Native dependency pains

Gradle (the Android build system) lets you specify dependencies from Maven (Java's package
repository). This meant that including the Android SSH library I needed was a single line. Nice and
easy.

Installing third-party dependencies on the iOS side of things is a pain, though. First, a
disclaimer: I'm by no means an iOS developer, and have only dealt with XCode and CocoaPods a
handful of times.

I first tried to make my library a pod to be installed via CocoaPods, which would allow it to have
its own dependencies. However, there are two problems with installing a React Native library as a
pod:

- it has to list React as one of its dependencies, which is deprecated
- it's incompatible with **react-native link** which links your iOS library for you, and would result
in duplicate libraries in XCode

After this didn't work, I decided to go with the manual installation methods listed by a few other
libraries (specifically {{< link "react-native-lock" "https://github.com/auth0/react-native-lock" >}}, thanks
auth0). So as it stands, after npm-installing **react-native-ssh**, you have to:

- run **react-native link** to include the library
- install **NMSSH** to your own app via CocoaPods
- update **RNSSH**'s Header Search Paths (react-native-ssh's name in XCode) to include your Pods
headers

Perhaps I missed something, but if I haven't, this is definitely something to be addressed for
React Native.

### Get it while it's hot

**react-native-ssh** is on {{< link "GitHub" "https://github.com/azlyth/react-native-ssh" >}} and
{{< link "npm" "https://www.npmjs.com/package/react-native-ssh" >}}.
