// The APK shell (specs/android.md 3.6, L12c): SDL3 and the runtime, and no
// game code. tools/android.py builds it with the Gradle it fetches, pinned.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "soa"
include(":app")
