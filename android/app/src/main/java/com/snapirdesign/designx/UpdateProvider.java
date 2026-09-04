package com.snapirdesign.designx;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * Hands a downloaded APK to the system installer.
 *
 * <p>Since Android 7 a {@code file://} URI thrown at another app is refused
 * outright, so the installer has to be given a {@code content://} one from a
 * provider this app owns. AndroidX has a FileProvider that does this, but this
 * module deliberately carries no dependencies, and the whole of what is needed
 * here is one read-only file and the two columns the installer asks about.
 *
 * <p>It serves exactly one directory - the folder update downloads land in -
 * and nothing else in the app is reachable through it.
 */
public class UpdateProvider extends ContentProvider {

    private File root() {
        return new File(getContext().getExternalFilesDir(null), "updates");
    }

    /**
     * Resolve a request back to a real file, refusing anything that tries to
     * climb out of the updates folder.
     */
    private File resolve(Uri uri) throws FileNotFoundException {
        final String name = uri.getLastPathSegment();
        if (name == null || name.contains("/") || name.contains("\\") || name.contains("..")) {
            throw new FileNotFoundException("Bad update path");
        }
        final File f = new File(root(), name);
        if (!f.isFile()) throw new FileNotFoundException(name);
        return f;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        // Read-only, whatever the caller asked for. The installer only reads.
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    /**
     * The installer asks for the name and the size before it opens anything,
     * and shows a blank confirmation screen if it does not get them.
     */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        final File f;
        try {
            f = resolve(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        final String[] cols = {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        final MatrixCursor c = new MatrixCursor(cols, 1);
        c.addRow(new Object[]{f.getName(), f.length()});
        return c;
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("read-only");
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("read-only");
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("read-only");
    }
}
