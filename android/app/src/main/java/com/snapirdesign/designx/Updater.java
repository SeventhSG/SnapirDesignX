package com.snapirdesign.designx;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Checks GitHub for a newer build and installs it.
 *
 * <p>There is no Play listing, so the app has to look for its own updates. It
 * asks the same releases page a person would open, compares the tag with the
 * version it is running, and offers the APK hanging off that release.
 *
 * <p>Nothing happens without the operator agreeing to it: the check is silent
 * and only speaks up when there is something newer, and Android itself asks
 * again before the package is replaced. A surveyor in a stairwell with one bar
 * of signal should never have an update start on its own, so the download only
 * begins after they tap.
 */
final class Updater {

    /** The releases page for this app, which is public, so no token is needed. */
    private static final String LATEST =
            "https://api.github.com/repos/SeventhSG/SnapirDesignX/releases/latest";

    private static final int CONNECT_MS = 8000;
    private static final int READ_MS = 20000;

    private Updater() {
    }

    /** What the releases page is offering, or null when it is not newer. */
    static final class Release {
        final String version;
        final String url;
        final long bytes;

        Release(String version, String url, long bytes) {
            this.version = version;
            this.url = url;
            this.bytes = bytes;
        }
    }

    /**
     * Ask GitHub what the newest release is. Runs on the caller's thread, so
     * never call it from the UI one.
     */
    static Release check(String running) {
        try {
            final JSONObject release = new JSONObject(get(LATEST));
            final String tag = release.optString("tag_name", "").replaceFirst("^[vV]", "");
            if (tag.isEmpty() || !isNewer(tag, running)) return null;

            final JSONArray assets = release.optJSONArray("assets");
            if (assets == null) return null;
            for (int i = 0; i < assets.length(); i++) {
                final JSONObject a = assets.getJSONObject(i);
                final String name = a.optString("name", "");
                if (!name.endsWith(".apk")) continue;
                final String url = a.optString("browser_download_url", "");
                if (url.isEmpty()) continue;
                return new Release(tag, url, a.optLong("size", 0));
            }
        } catch (Throwable ignored) {
            // An update check is a convenience. If the network is not there,
            // or GitHub is rate limiting, the app carries on as it was.
        }
        return null;
    }

    /**
     * Compare two dotted versions numerically.
     *
     * <p>String comparison would call 1.3.10 older than 1.3.9, which is exactly
     * the kind of bug nobody notices until the tenth patch release.
     */
    static boolean isNewer(String remote, String local) {
        final int[] a = parts(remote);
        final int[] b = parts(local);
        for (int i = 0; i < Math.max(a.length, b.length); i++) {
            final int x = i < a.length ? a[i] : 0;
            final int y = i < b.length ? b[i] : 0;
            if (x != y) return x > y;
        }
        return false;
    }

    private static int[] parts(String v) {
        final String[] bits = v.trim().split("[.+-]");
        final int[] out = new int[bits.length];
        for (int i = 0; i < bits.length; i++) {
            try {
                out[i] = Integer.parseInt(bits[i].replaceAll("\\D", ""));
            } catch (NumberFormatException e) {
                out[i] = 0;
            }
        }
        return out;
    }

    private static String get(String url) throws Exception {
        final HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(CONNECT_MS);
            c.setReadTimeout(READ_MS);
            c.setRequestProperty("Accept", "application/vnd.github+json");
            c.setRequestProperty("User-Agent", "SnapirDesignX");
            if (c.getResponseCode() != 200) throw new IllegalStateException("HTTP " + c.getResponseCode());
            try (InputStream in = c.getInputStream()) {
                return new String(readAll(in, null, 0), StandardCharsets.UTF_8);
            }
        } finally {
            c.disconnect();
        }
    }

    /** Offer the update. Called on the UI thread. */
    static void offer(Activity activity, Release release) {
        final String size = release.bytes > 0
                ? String.format(" (%.0f MB)", release.bytes / 1048576.0)
                : "";
        new AlertDialog.Builder(activity)
                .setTitle("Version " + release.version + " is out")
                .setMessage("Download and install it now?" + size)
                .setPositiveButton("Update", (d, w) -> start(activity, release))
                .setNegativeButton("Later", null)
                .show();
    }

    private static void start(Activity activity, Release release) {
        // Android will not let an app install a package until the user has
        // allowed this particular app to do it, and that switch lives in
        // Settings where only they can reach it.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                && !activity.getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(activity)
                    .setTitle("One permission first")
                    .setMessage("Android needs you to allow Snapir to install apps. "
                            + "Turn it on, then tap Update again.")
                    .setPositiveButton("Open settings", (d, w) -> activity.startActivity(
                            new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + activity.getPackageName()))))
                    .setNegativeButton("Cancel", null)
                    .show();
            return;
        }

        final AlertDialog progress = new AlertDialog.Builder(activity)
                .setTitle("Downloading " + release.version)
                .setMessage("0%")
                .setCancelable(false)
                .show();

        new Thread(() -> {
            try {
                final File apk = download(activity, release, percent ->
                        activity.runOnUiThread(() -> progress.setMessage(percent + "%")));
                activity.runOnUiThread(() -> {
                    progress.dismiss();
                    install(activity, apk);
                });
            } catch (Throwable t) {
                final String message = String.valueOf(t.getMessage());
                activity.runOnUiThread(() -> {
                    progress.dismiss();
                    new AlertDialog.Builder(activity)
                            .setTitle("Update failed")
                            .setMessage(message)
                            .setPositiveButton("OK", null)
                            .show();
                });
            }
        }).start();
    }

    interface Progress {
        void at(int percent);
    }

    private static File download(Activity activity, Release release, Progress onProgress)
            throws Exception {
        final File dir = new File(activity.getExternalFilesDir(null), "updates");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IllegalStateException("No room to download to");
        // One file, replaced every time: a phone that has been updated a dozen
        // times should not be carrying a dozen installers around.
        for (File old : dir.listFiles() == null ? new File[0] : dir.listFiles()) old.delete();
        final File apk = new File(dir, "SnapirDesignX-" + release.version + ".apk");

        HttpURLConnection c = (HttpURLConnection) new URL(release.url).openConnection();
        try {
            c.setConnectTimeout(CONNECT_MS);
            c.setReadTimeout(READ_MS);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", "SnapirDesignX");
            if (c.getResponseCode() != 200) throw new IllegalStateException("HTTP " + c.getResponseCode());
            final long total = release.bytes > 0 ? release.bytes : c.getContentLength();
            try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(apk)) {
                readAll(in, out, total, onProgress);
            }
        } finally {
            c.disconnect();
        }
        return apk;
    }

    private static void install(Activity activity, File apk) {
        // A file:// URI would be refused outright since Android 7, so the APK is
        // handed over through this app's own provider.
        final Uri uri = new Uri.Builder()
                .scheme("content")
                .authority(activity.getPackageName() + ".updates")
                .appendPath(apk.getName())
                .build();
        final Intent intent = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(intent);
    }

    private static byte[] readAll(InputStream in, OutputStream out, long total) throws Exception {
        return readAll(in, out, total, null);
    }

    private static byte[] readAll(InputStream in, OutputStream out, long total,
                                  Progress onProgress) throws Exception {
        final java.io.ByteArrayOutputStream buffer =
                out == null ? new java.io.ByteArrayOutputStream() : null;
        final byte[] chunk = new byte[65536];
        long done = 0;
        int last = -1;
        int n;
        while ((n = in.read(chunk)) > 0) {
            if (out != null) out.write(chunk, 0, n);
            else buffer.write(chunk, 0, n);
            done += n;
            if (onProgress != null && total > 0) {
                final int percent = (int) (done * 100 / total);
                if (percent != last) {
                    last = percent;
                    onProgress.at(percent);
                }
            }
        }
        return buffer == null ? new byte[0] : buffer.toByteArray();
    }
}
