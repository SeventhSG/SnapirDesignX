package com.snapirdesign.designx;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Environment;

import java.io.File;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Picks a survey folder and hands back a real filesystem path.
 *
 * <p>The system document picker would be the conventional choice, but it
 * returns {@code content://} URIs, and the geometry core opens files with the
 * standard library. Rather than teach the core about Android's storage
 * abstraction, this walks actual directories, which is also what lets the same
 * parser read the same CSVs on both platforms.
 *
 * <p>Directories that hold Leica room exports are marked with a count, so the
 * folder the surveyor wants is easy to spot among dozens.
 */
final class FolderPicker {

    interface Listener {
        void onPicked(String absolutePath);

        void onCancelled();
    }

    private FolderPicker() {}

    static void show(Activity activity, Listener listener) {
        File start = Environment.getExternalStorageDirectory();
        if (start == null || !start.isDirectory()) start = new File("/storage/emulated/0");
        browse(activity, start, listener);
    }

    private static void browse(Activity activity, File dir, Listener listener) {
        List<File> dirs = new ArrayList<>();
        File[] kids = dir.listFiles();
        if (kids != null) {
            for (File f : kids) {
                if (f.isDirectory() && !f.getName().startsWith(".")) dirs.add(f);
            }
        }
        dirs.sort(Comparator.comparing(f -> f.getName().toLowerCase()));

        List<String> labels = new ArrayList<>();
        final List<File> targets = new ArrayList<>();

        File parent = dir.getParentFile();
        if (parent != null && parent.canRead()) {
            labels.add("↑  ..");
            targets.add(parent);
        }
        for (File f : dirs) {
            int n = countRoomCsvs(f);
            labels.add(n > 0 ? f.getName() + "   · " + n + " rooms" : f.getName());
            targets.add(f);
        }

        final File here = dir;
        int rooms = countRoomCsvs(dir);
        String useLabel = rooms > 0 ? "Use this folder (" + rooms + " rooms)" : "Use this folder";

        new AlertDialog.Builder(activity)
                .setTitle(dir.getAbsolutePath())
                .setItems(labels.toArray(new String[0]),
                        (d, which) -> browse(activity, targets.get(which), listener))
                .setPositiveButton(useLabel,
                        (d, which) -> listener.onPicked(here.getAbsolutePath()))
                .setNegativeButton("Cancel", (d, which) -> listener.onCancelled())
                .setOnCancelListener(d -> listener.onCancelled())
                .show();
    }

    /** How many Leica room CSVs sit directly in this folder, ignoring reports. */
    private static int countRoomCsvs(File dir) {
        File[] kids = dir.listFiles();
        if (kids == null) return 0;
        int n = 0;
        for (File f : kids) {
            String name = f.getName();
            if (!f.isFile() || !name.toLowerCase().endsWith(".csv")) continue;
            if (name.toUpperCase().contains("FUKOKU")) continue;
            n++;
        }
        return n;
    }
}
