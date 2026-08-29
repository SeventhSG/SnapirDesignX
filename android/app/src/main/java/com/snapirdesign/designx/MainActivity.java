package com.snapirdesign.designx;

import android.annotation.SuppressLint;
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

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import java.io.File;

/**
 * The whole Android shell.
 *
 * <p>It does three things: unpack the interface, start the geometry service,
 * and show a WebView pointed at it. Everything else the app does happens in the
 * same C++ and the same React the desktop runs, which is the reason this file
 * is as short as it is.
 */
public class MainActivity extends AppCompatActivity {

    private static final int REQ_LEGACY_STORAGE = 41;

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
        } else if (ContextCompat.checkSelfPermission(this,
                android.Manifest.permission.READ_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{
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
    }

    /** Hands a chosen folder back to the promise the page is waiting on. */
    void deliverFolder(String path) {
        final String js = path == null
                ? "window.__snapirFolderChosen && window.__snapirFolderChosen(null)"
                : "window.__snapirFolderChosen && window.__snapirFolderChosen("
                        + jsString(path) + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
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
