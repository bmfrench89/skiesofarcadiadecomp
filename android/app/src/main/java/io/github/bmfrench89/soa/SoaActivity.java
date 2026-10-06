package io.github.bmfrench89.soa;

import android.content.pm.ApplicationInfo;
import android.os.Bundle;

import org.libsdl.app.SDLActivity;

/**
 * The APK's one activity (specs/android.md 3.6): SDL's, with the runtime's
 * library as the one that holds SDL_main (runtime/android.c), and, for the
 * checks tools/android.py runs, the run's environment and arguments from the
 * intent (3.14): {@code --es env "SOA_SELFTEST=1;SOA_SETTINGS=0"} and
 * {@code --es args "--replay fifo/0100"}. Only a debuggable build reads them:
 * the activity is exported, and a release must not let another app choose
 * what the port loads or how it runs.
 */
public class SoaActivity extends SDLActivity {

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
        String env = checks() ? getIntent().getStringExtra("env") : null;
        if (env != null) {
            for (String pair : env.split(";")) {
                int eq = pair.indexOf('=');
                if (eq > 0) {
                    nativeSetenv(pair.substring(0, eq), pair.substring(eq + 1));
                }
            }
        }
    }
}
