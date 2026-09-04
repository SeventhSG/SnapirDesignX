package com.snapirdesign.designx;

import android.webkit.JavascriptInterface;

/**
 * The only bridge between the page and the device.
 *
 * <p>It mirrors what the Electron preload exposes, minus the parts that only
 * mean something on a desktop. Everything of substance goes over the HTTP API
 * instead, so this stays small on purpose.
 */
public class WebBridge {

    private final MainActivity activity;

    WebBridge(MainActivity activity) {
        this.activity = activity;
    }

    @JavascriptInterface
    public void pickFolder() {
        activity.runOnUiThread(activity::pickFolder);
    }

    @JavascriptInterface
    public void pickSdxp() {
        activity.runOnUiThread(activity::pickSdxp);
    }

    /** There is no file manager to jump to, so say where the file landed. */
    @JavascriptInterface
    public void reveal(String path) {
        activity.toast("Saved to\n" + path);
    }

    /** Check for a new version on demand, and say so either way. */
    @JavascriptInterface
    public void checkForUpdate() {
        activity.checkForUpdate(true);
    }

    @JavascriptInterface
    public void setTheme(boolean dark) {
        // The page paints itself; the shell has nothing of its own to re-colour.
    }
}
