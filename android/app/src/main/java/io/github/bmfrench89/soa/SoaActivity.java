package io.github.bmfrench89.soa;

import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.UriPermission;
import android.content.pm.ApplicationInfo;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.os.OperationCanceledException;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.libsdl.app.SDLActivity;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Collections;

/**
 * The APK's one activity (specs/android.md 3.6): SDL's, with the runtime's
 * library as the one that holds SDL_main (runtime/android.c), and the Java
 * half of the import (L12d), which runtime/android.c calls from SDL's thread
 * through JNI, by name (app/proguard-rules.pro keeps every one):
 *
 * <ul>
 *   <li>{@link #pick}: the system's file picker, its permission kept before
 *       anything is told of the pick, and the pick written to
 *       no_backup/pending_&lt;kind&gt; so that a process started after the
 *       one that asked still has it;</li>
 *   <li>{@link #openFd}, {@link #describe}, {@link #release},
 *       {@link #tidyGrants}: a picked file's descriptor, its name and size,
 *       and the permissions kept for it;</li>
 *   <li>{@link #status}: a copy's progress, with a Cancel, the screen kept on;</li>
 *   <li>the message boxes SDL asks for ({@link #messageboxShowMessageBox}),
 *       drawn here so a long refusal scrolls, a pad can answer, and nothing
 *       waits for a box that can no longer be answered.</li>
 * </ul>
 *
 * <p>Every one of them is called on SDL's thread and waits there: none may
 * wait on the UI thread, which has to draw what they wait for, and none waits
 * on the activity's own monitor, which SDL uses for itself. When the activity
 * is destroyed, {@link #onDestroy} wakes them all before SDL's own teardown,
 * and runtime/android.c, seeing {@code destroyed}, ends the run inside the
 * second SDL waits for it.
 *
 * <p>For the checks tools/android.py runs (3.14), the run's environment and
 * arguments come from the intent: {@code --es env "SOA_SELFTEST=1;SOA_SETTINGS=0"},
 * {@code --es args "--replay fifo/0100"} and {@code --es pick "content://..."},
 * the files the import's picks are answered with, in order, without the
 * picker. Only a debuggable build reads them, and any of them makes the run a
 * check run (SOA_CHECK_RUN): the activity is exported, and a release must not
 * let another app choose what the port loads or how it runs. Any build reads
 * the extra of the launcher's shortcut "Choose the game files again".
 */
public class SoaActivity extends SDLActivity {

    private static final String TAG = "soa";
    /** The launcher shortcut's extra: both files are picked again, with Keep offered. */
    static final String REIMPORT = "soa.reimport";
    private static final String SHORTCUT = "reimport";
    /** pick()'s kinds as runtime/android.c numbers them, and the pending files' names. */
    private static final String[] KINDS = {"library", "disc"};
    /** The picks' request codes: far above SDL's own, which count up from 0, one per file dialog of its. */
    private static final int[] PICK_CODES = {0x5A01, 0x5A02};
    /** Where the picker opens: the shared Download folder, where a player copies a file to. */
    private static final String START_AUTHORITY = "com.android.externalstorage.documents";
    private static final String START_DOCUMENT = "primary:Download";
    /** SDL_messagebox.h's button flags. */
    private static final int RETURNKEY_DEFAULT = 1, ESCAPEKEY_DEFAULT = 2;

    /** Set first thing in onDestroy: runtime/android.c reads it after every call. */
    private volatile boolean destroyed;
    private volatile String lastError = "";

    /** The pick extra's files, answered in order (check runs). */
    private final ArrayDeque<String> queue = new ArrayDeque<>();

    /** One pick at a time, waited for on this lock, never the activity. */
    private final Object pickLock = new Object();
    private int pickToken;
    private int pickKind = -1;
    private boolean pickStarted; // the picker was asked for: a result from now on answers the pick
    private boolean pickDone;
    private String pickAnswer;

    private final Object boxLock = new Object();
    private int boxToken;
    private boolean boxDone;
    private int boxAnswer;
    private AlertDialog boxDialog; // the UI thread's

    private final Object statusLock = new Object();
    private String statusWant;
    private int statusPermille;
    private boolean statusPosted;
    private volatile boolean statusCancel;
    private volatile CancellationSignal openSignal;
    private AlertDialog statusDialog; // the UI thread's, with the two below
    private TextView statusText;
    private ProgressBar statusBar;

    private boolean checks() {
        return (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
    }

    /** SDL3, then the runtime; SDL_main is in the last one loaded. */
    @Override
    protected String[] getLibraries() {
        return new String[] {"SDL3", "soa_runtime"};
    }

    @Override
    protected String[] getArguments() {
        String args = checks() ? getIntent().getStringExtra("args") : null;
        return args == null || args.trim().isEmpty() ? new String[0] : args.trim().split("\\s+");
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state); // loads the libraries; SDL_main starts later, on resume
        if (mBrokenLibraries) {
            return; // SDL is saying why, and there is no runtime to tell anything
        }
        // the library and the disc's copy: kept out of backups and out of a move to a new phone
        nativeSetenv("SOA_NOBACKUP", getNoBackupFilesDir().getAbsolutePath());
        Intent intent = getIntent();
        if (checks()) {
            String env = intent.getStringExtra("env");
            String pick = intent.getStringExtra("pick");
            if (env != null || pick != null || intent.getStringExtra("args") != null) {
                nativeSetenv("SOA_CHECK_RUN", "1");
            }
            if (env != null) {
                for (String pair : env.split(";")) {
                    int eq = pair.indexOf('=');
                    if (eq > 0) {
                        nativeSetenv(pair.substring(0, eq), pair.substring(eq + 1));
                    }
                }
            }
            if (pick != null) {
                synchronized (queue) {
                    for (String uri : pick.split(";")) {
                        if (!uri.trim().isEmpty()) {
                            queue.add(uri.trim());
                        }
                    }
                }
            }
        }
        if (intent.getBooleanExtra(REIMPORT, false)) {
            nativeSetenv("SOA_REIMPORT", "1");
        }
        publishShortcut();
    }

    /**
     * The launcher's long press, "Choose the game files again": the way back
     * to the first-run screen that specs/android.md section 1 promises, a cold
     * start with both picks forced. Dynamic, since the package name is still a
     * working one. Losing it costs only the shortcut.
     */
    private void publishShortcut() {
        try {
            ShortcutManager shortcuts = getSystemService(ShortcutManager.class);
            if (shortcuts == null) {
                return;
            }
            String label = "Choose the game files again";
            for (ShortcutInfo s : shortcuts.getDynamicShortcuts()) {
                if (SHORTCUT.equals(s.getId()) && s.getLongLabel() != null && label.contentEquals(s.getLongLabel())) {
                    return; // published already: asked again, the system may count it against the app
                }
            }
            Intent launch = new Intent(Intent.ACTION_MAIN, null, this, SoaActivity.class).putExtra(REIMPORT, true);
            ShortcutInfo info = new ShortcutInfo.Builder(this, SHORTCUT)
                    .setShortLabel("Game files")
                    .setLongLabel(label)
                    .setIntent(launch)
                    .build();
            shortcuts.setDynamicShortcuts(Collections.singletonList(info));
        } catch (RuntimeException e) {
            Log.w(TAG, "no launcher shortcut: " + e);
        }
    }

    /**
     * The shortcut, used while this activity exists. A dynamic shortcut's
     * intent carries no FLAG_ACTIVITY_CLEAR_TASK (a static one's always
     * would), so it comes here rather than making the activity again, which
     * SDL answers by ending the process. Until SDL's thread starts, it still
     * counts, since SDL_main is what reads SOA_REIMPORT: Android kills a
     * process in the background and keeps its activity, and the shortcut then
     * makes a new process whose onCreate has the launch the activity was
     * first made by, this intent arriving only after it, and before SDL's
     * thread starts (SDLActivity starts it once the surface is ready). Once
     * SDL_main runs, SDL ignores a new intent and the import may be done
     * with: closing the app is the way, said in a toast.
     */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent == null || !intent.getBooleanExtra(REIMPORT, false) || mBrokenLibraries) {
            return;
        }
        if (mSDLThread == null) {
            nativeSetenv("SOA_REIMPORT", "1");
            return;
        }
        Toast.makeText(this, "The app is running: close it (swipe it away in Recents), then choose the game files again.",
                Toast.LENGTH_LONG).show();
    }

    @Override
    protected void onDestroy() {
        // Before SDL's own onDestroy, which waits only a second for SDL's
        // thread and then tears down what a window would need: every waiter is
        // woken now, and runtime/android.c ends the run inside that second.
        destroyed = true;
        synchronized (pickLock) {
            pickLock.notifyAll();
        }
        synchronized (boxLock) {
            boxLock.notifyAll();
        }
        CancellationSignal open = openSignal;
        if (open != null) {
            open.cancel();
        }
        try {
            if (boxDialog != null) {
                boxDialog.dismiss();
            }
            hideStatus();
        } catch (RuntimeException e) {
            Log.w(TAG, "a dialog outlived the activity: " + e);
        }
        super.onDestroy();
    }

    // ---- the picker ---------------------------------------------------------

    /**
     * The game library (kind 0) or the disc (1), picked by the player: its
     * URI; "" when nothing was (Back, the launcher's icon, no picker, or a
     * check run with no picker allowed); null once the activity has gone.
     * Called on SDL's thread, which it blocks. A pick already received for
     * this kind, by a process started after the one that asked, answers at
     * once; then the pick extra's queue (check runs); then the picker, when
     * {@code picker} allows it.
     */
    public String pick(final int kind, boolean picker) {
        try {
            if (kind != 0 && kind != 1) {
                return "";
            }
            if (Looper.myLooper() == Looper.getMainLooper()) {
                lastError = "pick() was called on the UI thread, which it would wait for";
                return "";
            }
            lastError = "";
            String waiting = readPending(kind);
            if (waiting != null) {
                return waiting;
            }
            synchronized (queue) {
                if (!queue.isEmpty()) {
                    return queue.poll();
                }
            }
            if (!picker) {
                return "";
            }
            final int token;
            synchronized (pickLock) {
                if (destroyed) {
                    return null;
                }
                token = ++pickToken;
                pickKind = kind;
                pickStarted = false;
                pickDone = false;
                pickAnswer = "";
            }
            runOnUiThread(() -> startPick(token, kind));
            synchronized (pickLock) {
                while (!destroyed && !(pickDone && pickToken == token)) {
                    pickLock.wait();
                }
                pickKind = -1;
                return pickDone && pickToken == token ? pickAnswer : null;
            }
        } catch (InterruptedException e) {
            return null;
        } catch (RuntimeException e) {
            lastError = e.toString();
            return "";
        }
    }

    /** On the UI thread: the system's picker, any file, opening in Download; the disc from this phone only. */
    private void startPick(int token, int kind) {
        synchronized (pickLock) {
            if (destroyed || token != pickToken || pickDone) {
                return;
            }
            pickStarted = true;
        }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                // never narrowed: Android knows no type for .so, .soadisc or .gcm,
                // and the files' own checks say what each is
                .setType("*/*")
                .putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                        DocumentsContract.buildDocumentUri(START_AUTHORITY, START_DOCUMENT));
        if (kind == 1) {
            // a cloud's disc would be fetched again at every launch: download it to the phone first
            intent.putExtra(Intent.EXTRA_LOCAL_ONLY, true);
        }
        try {
            startActivityForResult(intent, PICK_CODES[kind]);
        } catch (ActivityNotFoundException | SecurityException e) {
            lastError = "the system's file picker could not be opened: " + e.getMessage();
            answerPick(kind, "");
        }
    }

    private void answerPick(int kind, String answer) {
        synchronized (pickLock) {
            if (pickKind != kind || !pickStarted || pickDone) {
                return;
            }
            pickDone = true;
            pickAnswer = answer;
            pickLock.notifyAll();
        }
    }

    /**
     * A pick's result, to this activity whether or not anything still waits
     * for it: the permission kept, then the pick written down, and only then
     * the waiter told. Nothing counts as imported before
     * takePersistableUriPermission has returned; a pick whose permission could
     * not be kept is still answered, and runtime/android.c copies it.
     */
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data); // SDL's own file dialogs, which this app never opens
        int kind = requestCode == PICK_CODES[0] ? 0 : requestCode == PICK_CODES[1] ? 1 : -1;
        if (kind < 0) {
            return;
        }
        Uri uri = resultCode == RESULT_OK && data != null ? data.getData() : null;
        String answer = "";
        if (uri != null) {
            keep(uri, data.getFlags());
            writePending(kind, uri.toString());
            answer = uri.toString();
        }
        answerPick(kind, answer);
    }

    private boolean keep(Uri uri, int flags) {
        if ((flags & Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION) == 0) {
            return false;
        }
        try {
            getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            return true;
        } catch (SecurityException e) {
            Log.w(TAG, "the permission to read " + uri + " could not be kept: " + e.getMessage());
            return false;
        }
    }

    private File pendingFile(int kind) {
        return new File(getNoBackupFilesDir(), "pending_" + KINDS[kind]);
    }

    /** no_backup/pending_&lt;kind&gt;, whole or not at all; runtime/android.c removes it once the pick is used. */
    private void writePending(int kind, String uri) {
        File to = pendingFile(kind);
        File tmp = new File(to.getPath() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write((uri + "\n").getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        } catch (IOException e) {
            Log.w(TAG, "the pick " + uri + " could not be written down: " + e);
            return;
        }
        if (!tmp.renameTo(to)) {
            Log.w(TAG, "the pick " + uri + " could not be put in " + to);
        }
    }

    private String readPending(int kind) {
        byte[] b = new byte[8192];
        int n;
        try (FileInputStream in = new FileInputStream(pendingFile(kind))) {
            n = in.read(b);
        } catch (IOException e) {
            return null;
        }
        if (n <= 0) {
            return null;
        }
        String line = new String(b, 0, n, StandardCharsets.UTF_8).split("\n", 2)[0].trim();
        return line.isEmpty() ? null : line;
    }

    // ---- a picked file --------------------------------------------------------

    /**
     * A descriptor of the file at uri, detached so runtime/android.c owns it:
     * -2 when the permission is gone, -3 when the file is not there, -5 when
     * the open was cancelled, -4 for anything else; lastError() says more. An
     * open a provider takes long over (a cloud fetching the file) shows the
     * progress dialog, whose Cancel cancels it.
     */
    public int openFd(String uri) {
        final CancellationSignal signal = new CancellationSignal();
        final Handler ui = new Handler(Looper.getMainLooper());
        final Runnable slow = () -> status("Waiting for the app that holds the file you picked", -1);
        lastError = "";
        statusCancel = false;
        openSignal = signal;
        ui.postDelayed(slow, 700);
        try {
            if (destroyed) {
                signal.cancel();
            }
            ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(Uri.parse(uri), "r", signal);
            if (pfd == null) {
                lastError = "its provider gave no file";
                return -4;
            }
            if (signal.isCanceled()) {
                // Cancel was pressed while a provider that does not listen
                // for it went on opening (ContentResolver does not ask again
                // once it answers): the player said stop all the same
                try {
                    pfd.close();
                } catch (IOException e) {
                    // closed or not, nothing reads it
                }
                lastError = "cancelled";
                return -5;
            }
            return pfd.detachFd();
        } catch (OperationCanceledException e) {
            lastError = "cancelled";
            return -5;
        } catch (SecurityException e) {
            lastError = String.valueOf(e.getMessage());
            return -2;
        } catch (FileNotFoundException e) {
            lastError = String.valueOf(e.getMessage());
            return -3;
        } catch (Exception e) { // an address that is no content URI, or a provider's own failure
            lastError = e.toString();
            return -4;
        } finally {
            ui.removeCallbacks(slow);
            openSignal = null;
            status(null, -1);
        }
    }

    /**
     * What a picked file is, a line each: the name the player knows it by
     * (never used as a path), its size or -1, its provider's authority, and 1
     * when the permission to read it is kept past this launch, else 0.
     */
    public String describe(String uri) {
        String name = null;
        long size = -1;
        String authority = "";
        boolean kept = false;
        try {
            Uri u = Uri.parse(uri);
            authority = u.getAuthority() != null ? u.getAuthority() : "";
            try (Cursor c = getContentResolver().query(u,
                    new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
                if (c != null && c.moveToFirst()) {
                    int n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    int s = c.getColumnIndex(OpenableColumns.SIZE);
                    if (n >= 0 && !c.isNull(n)) {
                        name = c.getString(n);
                    }
                    if (s >= 0 && !c.isNull(s)) {
                        size = c.getLong(s);
                    }
                }
            } catch (RuntimeException e) {
                lastError = e.toString();
            }
            for (UriPermission p : getContentResolver().getPersistedUriPermissions()) {
                if (p.isReadPermission() && p.getUri().equals(u)) {
                    kept = true;
                }
            }
            if (name == null) {
                name = u.getLastPathSegment();
            }
        } catch (RuntimeException e) {
            lastError = e.toString();
        }
        if (name == null || name.trim().isEmpty()) {
            name = "the file you picked";
        }
        // one line, and short: any installed app names its own files
        name = name.replaceAll("[\\r\\n\\t]+", " ").trim();
        if (name.length() > 120) {
            name = name.substring(0, 120) + "...";
        }
        return name + "\n" + size + "\n" + authority + "\n" + (kept ? "1" : "0");
    }

    /** The permission kept for uri given up; nothing when none is. */
    public void release(String uri) {
        try {
            getContentResolver().releasePersistableUriPermission(Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (RuntimeException e) {
            // not kept, or gone already
        }
    }

    /** Every permission kept but those keep names given up: how many. */
    public int tidyGrants(String[] keep) {
        int n = 0;
        try {
            for (UriPermission p : getContentResolver().getPersistedUriPermissions()) {
                String uri = p.getUri().toString();
                boolean wanted = false;
                for (String k : keep) {
                    wanted |= uri.equals(k);
                }
                if (!wanted) {
                    release(uri);
                    n++;
                }
            }
        } catch (RuntimeException e) {
            lastError = e.toString();
        }
        return n;
    }

    public String lastError() {
        return lastError;
    }

    // ---- a copy's progress --------------------------------------------------

    /**
     * The progress dialog: text, and how far in thousandths (-1 for not
     * known), shown or brought up to date; null hides it. True once its Cancel
     * was pressed. Back reaches no app that targets Android 16, so Cancel is
     * the only way to stop a copy; the screen stays on while it shows, since a
     * copy of 1.4 GB outlasts its timeout.
     */
    public boolean status(String text, int permille) {
        boolean post;
        if (text == null) {
            statusCancel = false; // the next copy starts uncancelled
        }
        // the latest wins: a copy asks once a MiB, and the UI thread draws only what is current
        synchronized (statusLock) {
            statusWant = text;
            statusPermille = permille;
            post = !statusPosted;
            statusPosted = true;
        }
        if (post) {
            runOnUiThread(this::applyStatus);
        }
        return statusCancel;
    }

    private void applyStatus() {
        String text;
        int permille;
        synchronized (statusLock) {
            text = statusWant;
            permille = statusPermille;
            statusPosted = false;
        }
        try {
            if (text == null || destroyed || isFinishing()) {
                hideStatus();
                return;
            }
            if (statusDialog == null) {
                if (statusCancel) {
                    return; // cancelled: the copy is stopping
                }
                AlertDialog.Builder b = new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert);
                LinearLayout column = new LinearLayout(b.getContext());
                column.setOrientation(LinearLayout.VERTICAL);
                column.setPadding(dp(24), dp(16), dp(24), dp(8));
                statusText = new TextView(b.getContext());
                statusText.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Medium);
                statusBar = new ProgressBar(b.getContext(), null, android.R.attr.progressBarStyleHorizontal);
                statusBar.setMax(1000);
                column.addView(statusText);
                column.addView(statusBar, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
                b.setView(column);
                b.setCancelable(false);
                b.setNegativeButton("Cancel", (d, w) -> {
                    statusCancel = true;
                    CancellationSignal open = openSignal;
                    if (open != null) {
                        open.cancel();
                    }
                });
                final AlertDialog dialog = b.create();
                dialog.setCanceledOnTouchOutside(false);
                dialog.setOnDismissListener(d -> {
                    if (statusDialog == dialog) {
                        statusDialog = null;
                    }
                });
                statusDialog = dialog;
                dialog.show();
                getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            }
            statusText.setText(text);
            statusBar.setIndeterminate(permille < 0);
            if (permille >= 0) {
                statusBar.setProgress(Math.min(permille, 1000));
            }
        } catch (RuntimeException e) {
            Log.w(TAG, "the progress could not be shown: " + e);
        }
    }

    private void hideStatus() {
        AlertDialog d = statusDialog;
        statusDialog = null;
        if (d != null) {
            d.dismiss();
        }
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    // ---- the message boxes ----------------------------------------------------

    /**
     * SDL_ShowMessageBox's dialog (SDL_android.c calls it on the object, so
     * this one is used): the message in a ScrollView, so a long refusal never
     * pushes the buttons off a short screen or a large font; up to three
     * buttons in the dialog's own bar, any more under the message; the
     * system's current dialog style; and a pad's A answering with the default
     * button, B with the Escape one. The calling thread waits on a lock of its
     * own until a button is pressed, and the answer is the button's id, or -1
     * at once when called on the UI thread (it would wait for the thread that
     * has to draw it) and once the activity has gone, which runtime/android.c
     * takes as the end of the run.
     */
    @Override
    public int messageboxShowMessageBox(final int flags, final String title, final String message,
            final int[] buttonFlags, final int[] buttonIds, final String[] buttonTexts, final int[] colors) {
        try {
            if (Looper.myLooper() == Looper.getMainLooper()) {
                return -1;
            }
            if (buttonFlags == null || buttonIds == null || buttonTexts == null || buttonIds.length == 0
                    || buttonFlags.length != buttonIds.length || buttonTexts.length != buttonIds.length) {
                return -1; // a box no button can close
            }
            final int token;
            synchronized (boxLock) {
                if (destroyed) {
                    return -1;
                }
                token = ++boxToken;
                boxDone = false;
                boxAnswer = -1;
            }
            runOnUiThread(() -> showBox(token, title, message, buttonFlags, buttonIds, buttonTexts));
            synchronized (boxLock) {
                while (!destroyed && !(boxDone && boxToken == token)) {
                    boxLock.wait();
                }
                return boxDone && boxToken == token ? boxAnswer : -1;
            }
        } catch (InterruptedException e) {
            return -1;
        } catch (RuntimeException e) { // SDL asks for no exception after this call: none may leave it
            Log.e(TAG, "the message box failed", e);
            return -1;
        }
    }

    private void answerBox(int token, int answer) {
        synchronized (boxLock) {
            if (token != boxToken || boxDone) {
                return;
            }
            boxDone = true;
            boxAnswer = answer;
            boxLock.notifyAll();
        }
    }

    private void showBox(final int token, String title, String message, int[] flags, final int[] ids, String[] texts) {
        try {
            synchronized (boxLock) {
                if (destroyed || token != boxToken || boxDone) {
                    return;
                }
            }
            if (isFinishing()) {
                answerBox(token, -1);
                return;
            }
            AlertDialog.Builder b = new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert);
            if (title != null && !title.isEmpty()) {
                b.setTitle(title);
            }
            ScrollView scroll = new ScrollView(b.getContext());
            LinearLayout column = new LinearLayout(b.getContext());
            column.setOrientation(LinearLayout.VERTICAL);
            column.setPadding(dp(24), dp(12), dp(24), dp(4));
            TextView text = new TextView(b.getContext());
            text.setTextAppearance(android.R.style.TextAppearance_DeviceDefault_Medium);
            text.setText(message);
            column.addView(text);
            scroll.addView(column);
            b.setView(scroll);
            b.setCancelable(false);
            final int[] which = {DialogInterface.BUTTON_POSITIVE, DialogInterface.BUTTON_NEGATIVE,
                DialogInterface.BUTTON_NEUTRAL};
            final AlertDialog[] made = new AlertDialog[1];
            int def = -1;
            int esc = -1;
            for (int i = 0; i < ids.length; i++) {
                final int id = ids[i];
                if ((flags[i] & RETURNKEY_DEFAULT) != 0 && def < 0) {
                    def = i;
                }
                if ((flags[i] & ESCAPEKEY_DEFAULT) != 0 && esc < 0) {
                    esc = i;
                }
                if (i < which.length) {
                    DialogInterface.OnClickListener chosen = (d, w) -> answerBox(token, id);
                    if (i == 0) {
                        b.setPositiveButton(texts[i], chosen);
                    } else if (i == 1) {
                        b.setNegativeButton(texts[i], chosen);
                    } else {
                        b.setNeutralButton(texts[i], chosen);
                    }
                } else {
                    Button more = new Button(b.getContext());
                    more.setText(texts[i]);
                    more.setOnClickListener(v -> {
                        answerBox(token, id);
                        if (made[0] != null) {
                            made[0].dismiss();
                        }
                    });
                    column.addView(more);
                }
            }
            final AlertDialog dialog = b.create();
            made[0] = dialog;
            dialog.setCanceledOnTouchOutside(false);
            // dismissed by anything but a button, the box still answers
            dialog.setOnDismissListener(d -> answerBox(token, -1));
            final int defIndex = def;
            final int escIndex = esc;
            dialog.setOnKeyListener((d, keyCode, event) -> {
                boolean a = keyCode == KeyEvent.KEYCODE_BUTTON_A;
                int i = a ? defIndex
                        : keyCode == KeyEvent.KEYCODE_BUTTON_B || keyCode == KeyEvent.KEYCODE_ESCAPE ? escIndex : -2;
                if (i == -2) {
                    return false; // the D-pad moves between the buttons, and its centre presses one
                }
                if (event.getAction() == KeyEvent.ACTION_UP) {
                    View focused = dialog.getCurrentFocus();
                    if (a && focused instanceof Button) {
                        focused.performClick(); // A presses the button the D-pad is on
                    } else if (i >= 0 && i < which.length && dialog.getButton(which[i]) != null) {
                        dialog.getButton(which[i]).performClick();
                    }
                }
                return true;
            });
            dialog.show();
            boxDialog = dialog;
            if (defIndex >= 0 && defIndex < which.length && dialog.getButton(which[defIndex]) != null) {
                // where a pad's first press lands, once it takes the dialog out of touch mode
                dialog.getButton(which[defIndex]).setFocusedByDefault(true);
            }
        } catch (RuntimeException e) {
            Log.e(TAG, "the message box could not be shown", e);
            answerBox(token, -1);
        }
    }

    private int dp(int n) {
        return Math.round(n * getResources().getDisplayMetrics().density);
    }
}
