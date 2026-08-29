# Snapir Design X 1.2.0

A third shell: iOS. The geometry is untouched.

## iOS

The same move as Android, and for the same reason. The geometry core is C++
behind a narrow loopback HTTP API, and the interface is a React page that does
not care what is on the other end of it, so iOS is a `WKWebView` pointed at the
same service running on a thread in the same process. Not one line under
`native/`, `app/` or `snapir/` changed to make it work.

Universal, iPad first — this is a survey tool, not a phone tool — and free to
rotate in all four orientations rather than the phone build's portrait lock.

**There is no iOS download in this release, and that is the point to read
carefully.** iOS cannot be built on the machine this project is developed on,
so the app is built by a macOS runner on GitHub Actions instead. There is no
Apple Developer account, which means nothing is signed and there is no `.ipa`,
no TestFlight and no App Store build. What CI produces is a simulator build
that runs and a device build that only proves it compiles and links.

It has also never run on an iPhone or an iPad. It stands exactly where the
Android APK stood before the first phone: written, checked as far as it can be
checked without hardware, and unproven until someone installs it.

### What is different from Android, and why

- **Survey folders are copied in.** Android reads them where they lie, by
  reconstructing a real path out of the picker's `content://` tree. iOS has no
  equivalent and no real paths outside the app container, so the chosen folder
  is imported into `Documents/surveys/` once and everything downstream sees an
  ordinary directory. Reading in place instead would have put a platform seam
  through the middle of the parser, which is the one file that most needs to
  stay identical on every platform.
- **Exports show up in Files.app.** They land beside the input, and the whole
  tree is visible under On My iPad → Snapir. Revealing an export opens a share
  sheet rather than the Android toast.
- **The app is foreground-only.** iOS suspends a backgrounded process and the
  local service goes with it, so coming back re-checks it and restarts rather
  than showing a blank page.

## Verified

`Daire 53 - Salon` is now a fixture in the repository, so every CI run builds a
real room and checks the answer rather than checking that the app launched:

```
1 solid · 123 faces · 20.922131 m3
```

A simulator shares the host's network stack, which means CI can drive the same
HTTP API that the desktop comparison tools drive. A room whose volume moved is
a failed build.

## Unchanged

The geometry, and the desktop and Android apps. Same C++ core, same Open
CASCADE 7.9.3, same numbers everywhere.

Both downloads are unsigned, so each will ask once before installing.
