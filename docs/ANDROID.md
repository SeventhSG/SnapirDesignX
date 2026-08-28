# Android

## The short version

A native Android port is possible. I said otherwise when I raised the question
and that was wrong: **OpenCASCADE is officially certified on Android arm64**,
with an official CMake toolchain and two shipped sample apps. The kernel is not
the obstacle.

The obstacle is the language the current app is written in.

## What actually blocks it

Snapir's geometry runs on Python talking to OCCT through the `cadquery-ocp`
bindings. Those bindings ship as prebuilt wheels for Windows, macOS and Linux,
including ARM64 for macOS and Linux. **There is no Android wheel, and no
documented way to produce one.** Building it would mean cross-compiling the
pywrap-generated binding layer with the Android NDK, then getting a Python
runtime onto the device to load it. Two undocumented problems stacked on each
other, either of which could turn out to be a dead end after weeks of work.

So the port is not "make the kernel run on a phone". The kernel already does.
It is "stop going through Python to reach it".

## What a real port looks like

| Layer | Today | On Android |
|---|---|---|
| Kernel | OCCT 7.x via `cadquery-ocp` | OCCT built for `arm64-v8a` with the official NDK toolchain |
| Geometry service | `snapir/` in Python, ~1500 lines | The same logic in C++, calling OCCT directly |
| Bridge | FastAPI over loopback | JNI, following OCCT's own `JniViewer` sample |
| Interface | React + three.js in Electron | The same React code in a WebView |
| Viewport | three.js reading tessellated faces | Unchanged; it already consumes plain triangle buffers |

The interface survives almost untouched, which is the good news. It is already
a web app that talks to a service over a narrow, typed boundary. Swapping
FastAPI for a JNI bridge changes the transport, not the screens.

The geometry layer is the work. Parsing, plane fitting, topology and the solid
construction are about 1500 lines of Python, and the OCCT calls inside them are
the same C++ API they would be calling on Android. It is a rewrite in a
different language, not a redesign.

## Honest estimate

Several weeks, most of it in the C++ rewrite and the NDK build. The risk is
concentrated at the start: OCCT's Android build is well trodden, but a 358 MB
kernel on a phone needs measuring for size and startup before committing.

## The cheaper thing, if the goal is site access

If the point is looking at rooms on a phone while standing in the flat, none of
the above is needed. The interface is a web app; serving it over the network
would let an Android browser open it with the PC doing the geometry. It works
over a hotspot, needs no port, and is roughly a day of work. It stops working
when the PC is not reachable.

That is a different product to a native app, and worth being clear about:
one is Snapir on a phone, the other is a window onto Snapir running elsewhere.
