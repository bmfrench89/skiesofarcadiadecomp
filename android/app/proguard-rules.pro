# What runtime/android.c reaches in SoaActivity by name, through JNI, from
# SDL's thread (specs/android.md L12d): no Java code calls these, so a
# shrinker would remove or rename them, and the first pick would fail in a
# release alone. SDL's AAR keeps its own (its proguard.txt); the override of
# its message box is ours to keep. Minify is off today (app/build.gradle.kts).
-keep class io.github.bmfrench89.soa.SoaActivity {
    public java.lang.String pick(int, boolean);
    public int openFd(java.lang.String);
    public java.lang.String describe(java.lang.String);
    public void release(java.lang.String);
    public int tidyGrants(java.lang.String[]);
    public boolean status(java.lang.String, int);
    public java.lang.String lastError();
    public int messageboxShowMessageBox(int, java.lang.String, java.lang.String, int[], int[], java.lang.String[], int[]);
    boolean destroyed;
}
