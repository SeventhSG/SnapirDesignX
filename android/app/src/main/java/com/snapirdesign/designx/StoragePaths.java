package com.snapirdesign.designx;

import android.net.Uri;
import android.os.Environment;
import android.provider.DocumentsContract;

import java.io.File;

/**
 * Turns a folder chosen in the system Files app back into a real path.
 *
 * <p>The picker hands back a {@code content://} tree URI, and the geometry core
 * opens files with the standard library, so the two have to be reconciled
 * somewhere. Doing it here means the picker is the familiar system one while
 * the parser stays identical to the desktop's.
 *
 * <p>A tree id looks like {@code primary:Download/PB Mustafa}, or
 * {@code 1A2B-3C4D:Surveys} on a card. Anything that does not resolve to a
 * readable directory returns null, and the caller falls back to browsing.
 */
final class StoragePaths {

    private StoragePaths() {}

    static String toFilePath(Uri treeUri) {
        if (treeUri == null) return null;

        String docId;
        try {
            docId = DocumentsContract.getTreeDocumentId(treeUri);
        } catch (Exception e) {
            return null;
        }
        if (docId == null) return null;

        final int colon = docId.indexOf(':');
        final String volume = colon < 0 ? docId : docId.substring(0, colon);
        final String relative = colon < 0 ? "" : docId.substring(colon + 1);

        File base;
        if ("primary".equalsIgnoreCase(volume) || "home".equalsIgnoreCase(volume)) {
            base = Environment.getExternalStorageDirectory();
        } else {
            // A removable volume is mounted under its own id.
            base = new File("/storage/" + volume);
            if (!base.isDirectory()) base = null;
        }
        if (base == null) return null;

        final File dir = relative.isEmpty() ? base : new File(base, relative);
        if (!dir.isDirectory() || !dir.canRead()) return null;
        return dir.getAbsolutePath();
    }
}
