import java.util.Properties

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "br.aporte.app"
    compileSdk = 37

    defaultConfig {
        applicationId = "br.aporte.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 2
        versionName = "0.1.0"
        manifestPlaceholders["appLabel"] = "Aporte Brasil"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    buildTypes.getByName("debug") {
        // Keep the package identity of the APK already installed by prototype testers.
        applicationIdSuffix = ".spike"
        manifestPlaceholders["appLabel"] = "Aporte Brasil (teste)"
    }
}

val localProperties = providers.fileContents(rootProject.layout.projectDirectory.file("local.properties"))
    .asText.orElse("").map { contents -> Properties().apply { load(contents.reader()) } }
val hostPython = providers.gradleProperty("aporteBuildPython")
    .orElse(providers.environmentVariable("APORTE_BUILD_PYTHON"))
    .orElse(localProperties.map { it.getProperty("aporte.buildPython", "") }.filter { it.isNotBlank() })

val sharedPythonDir = layout.buildDirectory.dir("generated/sharedPython")
val syncSharedPython = tasks.register<Sync>("syncSharedPython") {
    // Keep the build input scoped to app code and web resources, outside user data.
    from(rootProject.projectDir.parentFile) {
        include("app.py", "aporte_brasil/**/*.py", "tools/check_git_safety.py")
        include("static/*.html", "static/*.css", "static/*.js", "static/*.svg")
    }
    into(sharedPythonDir)
}

tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncSharedPython)
}

chaquopy {
    sourceSets.getByName("main").srcDir(sharedPythonDir)
    defaultConfig {
        version = "3.12"
        hostPython.orNull?.let { buildPython(it) }
        extractPackages("aporte_brasil")
        pip {
            options("--extra-index-url", "https://pypi.flet.dev")
            install("cryptography==43.0.1")
            install("cffi==2.1.1")
            install("tzdata==2026.6")
        }
    }
}
