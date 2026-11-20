package com.pyeditor

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Environment
import android.webkit.MimeTypeMap
import java.io.File

/**
 * Where the user's own files live.
 *
 *  - "play" build : always the app's own folder (needs no permission, allowed on Google Play).
 *  - "full" build : the main phone storage when "All files access" was granted, else the app folder.
 */
object Storage {
    /** true only in the sideload ("full") build, which declares the All-files-access permission */
    val allFilesBuild: Boolean get() = BuildConfig.ALL_FILES

    fun granted(c: Context): Boolean {
        if (!allFilesBuild) return false
        return try {
            if (Build.VERSION.SDK_INT >= 30) Environment.isExternalStorageManager()
            else c.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        } catch (e: Throwable) { false }
    }

    /** "root" = main phone storage itself (no folder), "app" = /Pyvora folder (full build only) */
    fun mode(c: Context): String = c.getSharedPreferences("pv", 0).getString("dir", "root") ?: "root"
    fun setMode(c: Context, m: String) { c.getSharedPreferences("pv", 0).edit().putString("dir", m).apply() }

    /** The app's own folder: no permission needed, works on every Android version. */
    fun appDir(c: Context): File {
        val d = c.getExternalFilesDir(null) ?: File(c.filesDir, "workspace")
        d.mkdirs()
        return d
    }

    /** The working folder. Never null: falls back to the app folder. */
    fun dir(c: Context): File {
        if (granted(c)) {
            try {
                val base = Environment.getExternalStorageDirectory()
                val d = if (mode(c) == "app") File(base, "Pyvora") else base
                d.mkdirs()
                if (d.canWrite()) return d
            } catch (e: Throwable) { }
        }
        return appDir(c)
    }

    fun path(c: Context): String = dir(c).absolutePath

    /** true when the working folder is the app's own (private-ish) folder, so the in-app file manager is needed */
    fun isAppDir(c: Context): Boolean = dir(c).absolutePath == appDir(c).absolutePath

    // ------------------------------------------------------------------ helpers

    /** Normalises a relative file name. Returns null when it is empty or tries to leave the folder (..). */
    fun safeRel(path: String): String? {
        val parts = ArrayList<String>()
        for (raw in path.replace('\\', '/').split('/')) {
            val p = raw.replace(Regex("[:*?\"<>|\\u0000-\\u001f]"), "_").trim()
            if (p.isEmpty() || p == ".") continue
            if (p == "..") return null
            parts.add(p)
        }
        return if (parts.isEmpty()) null else parts.joinToString("/")
    }

    /** root + relative name, guaranteed to stay inside root. */
    fun resolve(root: File, rel: String): File? {
        val clean = safeRel(rel) ?: return null
        return try {
            val f = File(root, clean)
            val rc = root.canonicalPath
            val fc = f.canonicalPath
            if (fc == rc || fc.startsWith(rc + File.separator)) f else null
        } catch (e: Exception) { null }
    }

    /** a file name that does not exist yet: name, name(1).ext, name(2).ext ... */
    fun unique(dir: File, name: String): File {
        var f = File(dir, name)
        if (!f.exists()) return f
        val base = f.nameWithoutExtension
        val ext = f.extension
        var n = 1
        while (f.exists()) {
            f = File(f.parentFile ?: dir, base + "(" + n + ")" + (if (ext.isEmpty()) "" else ".$ext"))
            n++
        }
        return f
    }

    fun mime(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        return when (ext) {
            "html", "htm", "xhtml" -> "text/html"
            "css" -> "text/css"
            "js", "mjs", "cjs" -> "text/javascript"
            "json", "map" -> "application/json"
            "svg" -> "image/svg+xml"
            "wasm" -> "application/wasm"
            "py", "pyw" -> "text/x-python"
            "txt", "log" -> "text/plain"
            "md" -> "text/markdown"
            "csv" -> "text/csv"
            "xml" -> "application/xml"
            "webmanifest" -> "application/manifest+json"
            "ico" -> "image/x-icon"
            "woff2" -> "font/woff2"
            "woff" -> "font/woff"
            "ttf" -> "font/ttf"
            "otf" -> "font/otf"
            "mp3" -> "audio/mpeg"
            "ogg" -> "audio/ogg"
            "wav" -> "audio/wav"
            "mp4" -> "video/mp4"
            "webm" -> "video/webm"
            else -> MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
        }
    }

    /** text-like responses get a charset so Arabic and emoji show correctly */
    fun isText(mime: String): Boolean =
        mime.startsWith("text/") || mime == "application/json" || mime == "application/xml" ||
            mime == "image/svg+xml" || mime == "application/manifest+json"
}
