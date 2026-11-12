plugins {
    id("com.android.application")
}

android {
    namespace = "com.blowai.demo"
    compileSdk = 36
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.blowai.demo"
        minSdk = 23
        targetSdk = 35
        versionCode = 2
        versionName = "1.2"
    }
}
