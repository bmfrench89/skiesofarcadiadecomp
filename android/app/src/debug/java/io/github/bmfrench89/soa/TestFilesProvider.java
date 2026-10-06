package io.github.bmfrench89.soa;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.List;

/**
 * The debug build's own document source, for the import's checks on the
 * emulator (specs/android.md L12d); src/debug never reaches a release. It
 * serves what tools/android.py put in the app's files/provider/:
 *
 * <ul>
 *   <li>{@code content://<package>.testfiles/file/NAME}: a regular
 *       descriptor on the file, as the phone's own storage gives one;</li>
 *   <li>{@code .../pipe/NAME}: the same bytes through a pipe and a writer
 *       thread, as a cloud's provider may hand a file over, which the import
 *       must copy rather than read in place;</li>
 *   <li>{@code ?truncate=N} on either: only the first N bytes, while
 *       {@link #query} still says the whole size, as a provider that dies
 *       mid-stream looks once its descriptor is detached.</li>
 * </ul>
 *
 * Not exported: only the app opens it, through SoaActivity's pick extra, so
 * no grant from it is ever another app's. It serves reads only.
 */
public class TestFilesProvider extends ContentProvider {

    private static final String TAG = "soa";

    @Override
    public boolean onCreate() {
        return true;
    }

    /** The file a file/NAME or pipe/NAME address names, in files/provider/ and nowhere else. */
    private File file(Uri uri) throws FileNotFoundException {
        List<String> parts = uri.getPathSegments();
        if (parts.size() != 2 || !("file".equals(parts.get(0)) || "pipe".equals(parts.get(0)))) {
            throw new FileNotFoundException(uri + " is not file/NAME or pipe/NAME");
        }
        String name = parts.get(1);
        if (name.isEmpty() || name.equals(".") || name.equals("..") || name.contains("/")) {
            throw new FileNotFoundException(uri + " names no file");
        }
        File f = new File(new File(getContext().getFilesDir(), "provider"), name);
        if (!f.isFile()) {
            throw new FileNotFoundException("no " + f);
        }
        return f;
    }

    /** ?truncate=N's N, or -1 for the whole file. */
    private static long truncate(Uri uri) {
        String n = uri.getQueryParameter("truncate");
        try {
            return n == null ? -1 : Math.max(0, Long.parseLong(n));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /** DISPLAY_NAME and SIZE, the whole file's even when it is served truncated. */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        File f;
        try {
            f = file(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        String[] columns = projection != null ? projection
                : new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        Object[] row = new Object[columns.length];
        for (int i = 0; i < columns.length; i++) {
            row[i] = OpenableColumns.DISPLAY_NAME.equals(columns[i]) ? f.getName()
                    : OpenableColumns.SIZE.equals(columns[i]) ? (Object) f.length() : null;
        }
        MatrixCursor c = new MatrixCursor(columns, 1);
        c.addRow(row);
        return c;
    }

    @Override
    public String getType(Uri uri) {
        return "application/octet-stream";
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) {
            throw new FileNotFoundException(uri + " is served to read only, not '" + mode + "'");
        }
        File f = file(uri);
        long n = truncate(uri);
        if ("pipe".equals(uri.getPathSegments().get(0))) {
            return pipe(f, n);
        }
        return n < 0 ? ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY) : cut(f, n);
    }

    /** f's first n bytes as a regular file of their own: a copy in the cache, opened, then unlinked, so the descriptor alone holds it. */
    private ParcelFileDescriptor cut(File f, long n) throws FileNotFoundException {
        File part = new File(getContext().getCacheDir(), "truncated-" + f.getName());
        try (InputStream in = new FileInputStream(f); OutputStream out = new FileOutputStream(part)) {
            copy(in, out, n);
        } catch (IOException e) {
            part.delete();
            throw new FileNotFoundException("cannot cut " + f + " short: " + e);
        }
        ParcelFileDescriptor pfd = ParcelFileDescriptor.open(part, ParcelFileDescriptor.MODE_READ_ONLY);
        part.delete();
        return pfd;
    }

    /** f's bytes, the first n of them when n >= 0, through a pipe a thread writes. */
    private ParcelFileDescriptor pipe(final File f, final long n) throws FileNotFoundException {
        final ParcelFileDescriptor[] ends;
        try {
            ends = ParcelFileDescriptor.createReliablePipe();
        } catch (IOException e) {
            throw new FileNotFoundException("no pipe for " + f + ": " + e);
        }
        new Thread(() -> {
            try (InputStream in = new FileInputStream(f);
                    OutputStream out = new ParcelFileDescriptor.AutoCloseOutputStream(ends[1])) {
                copy(in, out, n);
            } catch (IOException e) {
                // the reader stopped reading (a copy refused after its first bytes closes its end)
                Log.i(TAG, "testfiles: the pipe of " + f.getName() + " ended early: " + e);
            }
        }, "testfiles-pipe").start();
        return ends[0];
    }

    private static void copy(InputStream in, OutputStream out, long n) throws IOException {
        byte[] b = new byte[1 << 16];
        long left = n < 0 ? Long.MAX_VALUE : n;
        while (left > 0) {
            int got = in.read(b, 0, (int) Math.min(b.length, left));
            if (got < 0) {
                break;
            }
            out.write(b, 0, got);
            left -= got;
        }
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("the test files are read only");
    }

    @Override
    public int delete(Uri uri, String selection, String[] args) {
        throw new UnsupportedOperationException("the test files are read only");
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] args) {
        throw new UnsupportedOperationException("the test files are read only");
    }
}
