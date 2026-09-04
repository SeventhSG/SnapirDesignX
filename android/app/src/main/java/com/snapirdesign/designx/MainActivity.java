package com.snapirdesign.designx;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;

/**
 * The whole Android shell.
 *
 * <p>It does three things: unpack the interface, start the geometry service,
 * and show a WebView pointed at it. Everything else the app does happens in the
 * same C++ and the same React the desktop runs, which is the reason this file
 * is as short as it is.
 */
public class MainActivity extends Activity {

    private static final int REQ_LEGACY_STORAGE = 41;
    private static final int REQ_PICK_TREE = 42;
    private static final int REQ_PICK_SDXP = 43;

    private WebView web;
    private TextView status;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        web = findViewById(R.id.web);
        status = findViewById(R.id.status);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // The interface and the API are both on 127.0.0.1, so nothing here needs
        // file access or cross-origin permission.
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setTextZoom(100);
        web.addJavascriptInterface(new WebBridge(this), "SnapirAndroid");

        requestStorage();
        new Thread(this::startBackend).start();
    }

    /**
     * The surveys live in ordinary folders the user copies off the instrument,
     * so the app needs to read them where they are rather than in its own
     * sandbox. On Android 11 and up that is All files access, which only the
     * user can grant, in Settings.
     */
    private void requestStorage() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (Environment.isExternalStorageManager()) return;
            new AlertDialog.Builder(this)
                    .setTitle("Storage access")
                    .setMessage("Snapir reads survey folders straight off the "
                            + "instrument's export, so it needs access to all files. "
                            + "Android only lets you grant that in Settings.")
                    .setPositiveButton("Open settings", (d, w) -> {
                        try {
                            startActivity(new Intent(
                                    Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                    Uri.parse("package:" + getPackageName())));
                        } catch (Exception e) {
                            startActivity(new Intent(
                                    Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
                        }
                    })
                    .setNegativeButton("Not now", null)
                    .show();
        } else if (checkSelfPermission(android.Manifest.permission.READ_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{
                    android.Manifest.permission.READ_EXTERNAL_STORAGE,
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE,
            }, REQ_LEGACY_STORAGE);
        }
    }

    private void startBackend() {
        try {
            String version = getPackageManager()
                    .getPackageInfo(getPackageName(), 0).versionName;
            File webRoot = WebAssets.install(this, version);
            NativeService.start(getFilesDir().getAbsolutePath(), webRoot.getAbsolutePath());
        } catch (Throwable t) {
            final String message = String.valueOf(t.getMessage());
            runOnUiThread(() -> status.setText("Could not start the geometry engine.\n\n"
                    + message));
            return;
        }

        final boolean up = NativeService.waitUntilReady(15000);
        runOnUiThread(() -> {
            if (!up) {
                status.setText("The geometry engine did not answer on "
                        + NativeService.ORIGIN + ".");
                return;
            }
            status.setVisibility(View.GONE);
            web.setVisibility(View.VISIBLE);
            web.loadUrl(NativeService.ORIGIN + "/");
        });

        // Only once the app is up and usable. An update prompt on top of a
        // splash screen, before the operator can even see their rooms, is a
        // dialog in the way rather than a service.
        checkForUpdate(false);
    }

    /**
     * Opens the system Files app to choose a survey folder.
     *
     * <p>The picker returns a {@code content://} tree, which the geometry core
     * cannot open, so the choice is mapped back to a real path. When that
     * mapping fails, which it can on an unusual storage provider, the built-in
     * directory browser takes over rather than leaving the operator stuck.
     */
    void pickFolder() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            startActivityForResult(i, REQ_PICK_TREE);
        } catch (Exception e) {
            browseForFolder();
        }
    }

    private void browseForFolder() {
        FolderPicker.show(this, new FolderPicker.Listener() {
            @Override
            public void onPicked(String absolutePath) {
                deliverFolder(absolutePath);
            }

            @Override
            public void onCancelled() {
                deliverFolder(null);
            }
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_PICK_SDXP) {
            if (resultCode != RESULT_OK || data == null || data.getData() == null) {
                deliverSdxp(null);
            } else {
                deliverSdxp(copySdxpToTemp(data.getData()));
            }
            return;
        }
        if (requestCode != REQ_PICK_TREE) return;

        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            deliverFolder(null);
            return;
        }

        final String path = StoragePaths.toFilePath(data.getData());
        if (path == null) {
            toast("That folder is not on internal storage. Pick it here instead.");
            browseForFolder();
            return;
        }
        deliverFolder(path);
    }

    /** Hands a chosen folder back to the promise the page is waiting on. */
    void deliverFolder(String path) {
        final String js = path == null
                ? "window.__snapirFolderChosen && window.__snapirFolderChosen(null)"
                : "window.__snapirFolderChosen && window.__snapirFolderChosen("
                        + jsString(path) + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    /**
     * Lets the operator pick a .sdxp from anywhere - another app, a cloud
     * drive, a shared folder - the same way the desktop's open-file dialog
     * does. Unlike a survey folder there is no directory to browse into, so
     * this is the one picker with no FolderPicker-style fallback.
     */
    void pickSdxp() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        try {
            startActivityForResult(i, REQ_PICK_SDXP);
        } catch (Exception e) {
            deliverSdxp(null);
        }
    }

    /**
     * The picker returns a {@code content://} URI, which the geometry core
     * cannot open, so the bytes are copied into a real file the core can read
     * - the manifest inside decides whether it was actually a .sdxp.
     */
    private String copySdxpToTemp(Uri uri) {
        File dir = new File(getFilesDir(), "tmp");
        if (!dir.isDirectory() && !dir.mkdirs()) return null;
        File dest = new File(dir, "import-" + System.currentTimeMillis() + ".sdxp");
        try (java.io.InputStream in = getContentResolver().openInputStream(uri);
             java.io.OutputStream out = new java.io.FileOutputStream(dest)) {
            if (in == null) return null;
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return dest.getAbsolutePath();
        } catch (IOException e) {
            return null;
        }
    }

    /** Hands a chosen .sdxp's real path back to the promise the page is waiting on. */
    void deliverSdxp(String path) {
        final String js = path == null
                ? "window.__snapirSdxpChosen && window.__snapirSdxpChosen(null)"
                : "window.__snapirSdxpChosen && window.__snapirSdxpChosen("
                        + jsString(path) + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    /**
     * Look for a newer release. Silent when there is nothing to report unless
     * the operator asked, in which case saying "you are up to date" is the
     * whole answer they wanted.
     */
    void checkForUpdate(boolean announceWhenCurrent) {
        new Thread(() -> {
            String running = "0";
            try {
                running = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            } catch (PackageManager.NameNotFoundException ignored) {
                // Cannot happen for our own package, and if it somehow does the
                // comparison below simply finds everything newer.
            }
            final Updater.Release release = Updater.check(running);
            runOnUiThread(() -> {
                if (release != null) Updater.offer(this, release);
                else if (announceWhenCurrent) toast("Snapir is up to date.");
            });
        }).start();
    }

    void toast(String text) {
        runOnUiThread(() -> Toast.makeText(this, text, Toast.LENGTH_LONG).show());
    }

    WebView webView() {
        return web;
    }

    private static String jsString(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c == '\n') b.append("\\n");
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
            else b.append(c);
        }
        return b.append('"').toString();
    }

    @Override
    public void onBackPressed() {
        if (web.getVisibility() == View.VISIBLE && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
