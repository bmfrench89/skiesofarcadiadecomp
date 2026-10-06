plugins {
    id("com.android.application")
}

// specs/android.md 3.6: compile and target 36 (installed here), Android 13 or
// newer (Q-A3, D-32), arm64-v8a for phones and x86_64 for the emulator. The
// package name is a working one until the owner chooses (Q-A4, D-33); an
// uninstall replaces it. SDL3 is SDL's own build of the pinned release, its
// AAR fetched by tools/fetch_sdl.py --android into vendor/, never committed.
android {
    namespace = "io.github.bmfrench89.soa"
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "io.github.bmfrench89.soa.dev"
        minSdk = 33
        targetSdk = 36
        versionCode = 1
        versionName = "0.1-dev"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildFeatures {
        prefab = true
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
}

dependencies {
    implementation(files("../../vendor/sdl3/android/SDL3-3.4.18.aar"))
}
