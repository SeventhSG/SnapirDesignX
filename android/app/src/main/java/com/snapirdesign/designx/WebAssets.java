package com.snapirdesign.designx;

import android.content.Context;
import android.content.res.AssetManager;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Unpacks the built interface out of the APK so the native service can serve it.
 *
 * <p>The page has to come from the same origin as the API. Loading it from
 * {@code file://} instead would put the interface on a null origin and every
 * call to the backend would be a cross-origin request against a WebView that
 * blocks them. Serving both from {@code 127.0.0.1} sidesteps that entirely, and
 * costs one copy on first run.
 */
final class WebAssets {

    private static final String SOURCE = "web";
    private static final String SHIM = "snapir-android.js";

    /**
     * The same object {@code preload.cjs} exposes on the desktop, so not one
     * line of the interface has to know which one it is talking to.
     */
    private static final String SHIM_JS =
            "window.snapir = {\n"
            + "  api: location.origin,\n"
            + "  backendReady: function () { return Promise.resolve({ ok: true }); },\n"
            + "  setTheme: function (dark) { try { SnapirAndroid.setTheme(!!dark); } catch (e) {} },\n"
            + "  reveal: function (p) { try { SnapirAndroid.reveal(String(p)); } catch (e) {} },\n"
            + "  pickFolder: function () {\n"
            + "    return new Promise(function (resolve) {\n"
            + "      window.__snapirFolderChosen = function (path) {\n"
            + "        window.__snapirFolderChosen = null;\n"
            + "        resolve(path || null);\n"
            + "      };\n"
            + "      try { SnapirAndroid.pickFolder(); } catch (e) { resolve(null); }\n"
            + "    });\n"
            + "  },\n"
            + "  pickSdxp: function () {\n"
            + "    return new Promise(function (resolve) {\n"
            + "      window.__snapirSdxpChosen = function (path) {\n"
            + "        window.__snapirSdxpChosen = null;\n"
            + "        resolve(path || null);\n"
            + "      };\n"
            + "      try { SnapirAndroid.pickSdxp(); } catch (e) { resolve(null); }\n"
            + "    });\n"
            + "  }\n"
            + "};\n";

    private WebAssets() {}

    /** Returns the directory the service should serve, unpacking it if needed. */
    static File install(Context ctx, String versionName) throws IOException {
        File root = new File(ctx.getFilesDir(), "web");
        File stamp = new File(root, ".version");

        if (root.isDirectory() && versionName.equals(read(stamp))) {
            return root;
        }
        deleteTree(root);
        if (!root.mkdirs() && !root.isDirectory()) {
            throw new IOException("Could not create " + root);
        }

        copyTree(ctx.getAssets(), SOURCE, root);
        injectBridge(new File(root, "index.html"));
        write(stamp, versionName);
        return root;
    }

    /**
     * Puts the bridge in front of the interface.
     *
     * <p>It goes in as a file rather than an inline script on purpose: the built
     * page carries a Content-Security-Policy of {@code default-src 'self'},
     * which blocks inline script outright. A file served from the same origin
     * satisfies that policy, and leaving the policy alone is better than
     * widening it to get a few lines of glue in.
     */
    private static void injectBridge(File indexHtml) throws IOException {
        if (!indexHtml.isFile()) throw new IOException("No index.html in assets/web");
        String html = read(indexHtml);
        if (html == null) throw new IOException("Could not read " + indexHtml);
        if (html.contains(SHIM)) return;

        write(new File(indexHtml.getParentFile(), SHIM), SHIM_JS);

        // Ahead of the module script, so window.snapir exists by the time the
        // interface looks for it.
        String tag = "<script src=\"./" + SHIM + "\"></script>\n    ";
        int at = html.indexOf("<script type=\"module\"");
        if (at < 0) {
            at = html.indexOf("</head>");
            if (at < 0) throw new IOException("index.html has no <head>");
        }
        write(indexHtml, html.substring(0, at) + tag + html.substring(at));
    }

    private static void copyTree(AssetManager assets, String path, File dest)
            throws IOException {
        String[] children = assets.list(path);
        if (children == null || children.length == 0) {
            copyFile(assets, path, dest);
            return;
        }
        if (!dest.isDirectory() && !dest.mkdirs()) {
            throw new IOException("Could not create " + dest);
        }
        for (String child : children) {
            copyTree(assets, path + "/" + child, new File(dest, child));
        }
    }

    private static void copyFile(AssetManager assets, String path, File dest)
            throws IOException {
        File parent = dest.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("Could not create " + parent);
        }
        byte[] buf = new byte[16 * 1024];
        try (InputStream in = assets.open(path); OutputStream out = new FileOutputStream(dest)) {
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) deleteTree(k);
        }
        // Nothing useful to do if this fails; the write that follows will say so.
        f.delete();
    }

    private static String read(File f) {
        if (!f.isFile()) return null;
        try (InputStream in = new java.io.FileInputStream(f)) {
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        } catch (IOException e) {
            return null;
        }
    }

    private static void write(File f, String text) throws IOException {
        try (OutputStream out = new FileOutputStream(f)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
    }
}
