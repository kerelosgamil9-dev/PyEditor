package com.pyeditor

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.provider.Settings
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.FrameLayout
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var rootView: FrameLayout
    private var pendingSave: String = ""
    private var pendingExport: File? = null

    private fun js(code: String) = runOnUiThread { web.evaluateJavascript(code, null) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(Color.BLACK)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.addJavascriptInterface(Bridge(), "Android")
        rootView = FrameLayout(this)
        rootView.setBackgroundColor(Color.BLACK)
        rootView.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(rootView)
        Edge.install(rootView)
        web.loadUrl("file:///android_asset/index.html")

        // Android 16 (target 36) uses the predictive-back system: the old onBackPressed() is not called any more
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                OnBackInvokedCallback { handleBack() }
            )
        }
    }

    override fun onResume() {
        super.onResume()
        if (Storage.granted(this)) Storage.dir(this)
        js("window.pvResume&&window.pvResume()")
    }

    /** Back closes the drawer / dialogs inside the page first, otherwise the app goes to the background. */
    private fun handleBack() {
        web.evaluateJavascript("(function(){try{return window.pvBack?window.pvBack():false}catch(e){return false}})()") { r ->
            if (r != "true") moveTaskToBack(true)
        }
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() { handleBack() }

    private fun askStorage() {
        if (!Storage.allFilesBuild) return
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                try {
                    startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")))
                } catch (e: Exception) {
                    startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                }
            } else {
                requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE), 7)
            }
        } catch (e: Throwable) { }
    }

    private fun displayName(uri: Uri): String {
        try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val n = c.getString(0)
                    if (!n.isNullOrBlank()) return n
                }
            }
        } catch (e: Exception) { }
        return uri.lastPathSegment?.substringAfterLast('/') ?: "file"
    }

    private fun importUri(uri: Uri) {
        val name = Storage.safeRel(displayName(uri))?.substringAfterLast('/') ?: "file"
        val f = Storage.unique(Storage.dir(this), name)
        contentResolver.openInputStream(uri)?.use { input ->
            f.outputStream().use { out -> input.copyTo(out) }
        }
    }

    inner class Bridge {
        // ---------------------------------------------------------------- Python
        @JavascriptInterface
        fun run(code: String, name: String) {
            val i = Intent(this@MainActivity, ConsoleActivity::class.java).putExtra("name", name)
            // the code goes through a file, an Intent can only carry about 1 MB
            try {
                val f = File(cacheDir, "run_" + System.currentTimeMillis() + ".py")
                f.writeText(code, Charsets.UTF_8)
                i.putExtra("codePath", f.absolutePath)
            } catch (e: Exception) {
                i.putExtra("code", code.take(200000))
            }
            runOnUiThread { startActivity(i) }
        }

        @JavascriptInterface
        fun terminal() {
            runOnUiThread { startActivity(Intent(this@MainActivity, ToolActivity::class.java).putExtra("mode", "term")) }
        }

        @JavascriptInterface
        fun pip() {
            runOnUiThread { startActivity(Intent(this@MainActivity, ToolActivity::class.java).putExtra("mode", "pip")) }
        }

        // ---------------------------------------------------------------- HTML preview
        /** Writes every open web file (html / css / js ...) to a temp folder and opens the preview screen. */
        @JavascriptInterface
        fun preview(main: String, filesJson: String, mainPath: String) {
            try {
                val dir = File(cacheDir, "preview")
                dir.deleteRecursively()
                dir.mkdirs()
                val o = JSONObject(filesJson)
                val keys = o.keys()
                while (keys.hasNext()) {
                    val name = keys.next()
                    val f = Storage.resolve(dir, name) ?: continue
                    f.parentFile?.mkdirs()
                    f.writeText(o.optString(name, ""), Charsets.UTF_8)
                }
                val m = Storage.safeRel(main) ?: return
                val i = Intent(this@MainActivity, HtmlActivity::class.java).putExtra("main", m)
                // the folder of the saved page: its images / data.json / other files are served to the preview too
                if (mainPath.isNotEmpty()) {
                    val pd = File(mainPath).parentFile
                    if (pd != null && pd.isDirectory) i.putExtra("dir", pd.absolutePath)
                }
                runOnUiThread { startActivity(i) }
            } catch (e: Throwable) {
                js("toast(${JSONObject.quote(e.toString())})")
            }
        }

        // ---------------------------------------------------------------- opening / saving
        @JavascriptInterface
        fun openFile() {
            runOnUiThread {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), 1)
            }
        }

        @JavascriptInterface
        fun saveAs(name: String, content: String) {
            pendingSave = content
            runOnUiThread {
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE).setType(Storage.mime(name))
                    .putExtra(Intent.EXTRA_TITLE, name), 2)
            }
        }

        /** Save straight into the working folder. Returns the full path, or "" on failure. */
        @JavascriptInterface
        fun quickSave(name: String, content: String, path: String): String {
            return try {
                var f: File? = null
                if (path.isNotEmpty()) {
                    val p = File(path)
                    if (p.parentFile?.canWrite() == true) f = p
                }
                if (f == null) {
                    val rel = Storage.safeRel(name) ?: "file.txt"
                    val t = Storage.unique(Storage.dir(this@MainActivity), rel)
                    t.parentFile?.mkdirs()
                    f = t
                }
                f.writeText(content, Charsets.UTF_8)
                f.absolutePath
            } catch (e: Throwable) { "" }
        }

        // ---------------------------------------------------------------- storage / permission
        @JavascriptInterface
        fun allFilesBuild(): Boolean = Storage.allFilesBuild

        @JavascriptInterface
        fun hasStorage(): Boolean = Storage.granted(this@MainActivity)

        @JavascriptInterface
        fun grantStorage() { runOnUiThread { askStorage() } }

        @JavascriptInterface
        fun setDirMode(m: String) { Storage.setMode(this@MainActivity, m) }

        @JavascriptInterface
        fun dirPath(): String = Storage.path(this@MainActivity)

        /** true when the files live in the app's own folder (so the in-app Files screen is useful) */
        @JavascriptInterface
        fun usesAppDir(): Boolean = Storage.isAppDir(this@MainActivity)

        // ---------------------------------------------------------------- in-app file manager
        @JavascriptInterface
        fun listFiles(): String {
            val root = Storage.dir(this@MainActivity)
            val arr = JSONArray()
            fun walk(d: File, depth: Int) {
                val kids = d.listFiles() ?: return
                val sorted = kids.sortedWith(compareBy<File>({ !it.isDirectory }, { it.name.lowercase() }))
                for (f in sorted) {
                    if (arr.length() >= 400) return
                    if (f.name.startsWith(".")) continue
                    val rel = f.relativeTo(root).path.replace(File.separatorChar, '/')
                    arr.put(JSONObject().put("p", rel).put("s", if (f.isDirectory) -1L else f.length()))
                    if (f.isDirectory && depth < 3) walk(f, depth + 1)
                }
            }
            try { walk(root, 0) } catch (e: Throwable) { }
            return arr.toString()
        }

        /** Opens a text file of the working folder in the editor. Returns false for binary / huge files. */
        @JavascriptInterface
        fun openWorkspaceFile(rel: String): Boolean {
            return try {
                val f = Storage.resolve(Storage.dir(this@MainActivity), rel) ?: return false
                if (!f.isFile || f.length() > 3_000_000L) return false
                val bytes = f.readBytes()
                val n = minOf(bytes.size, 4096)
                for (i in 0 until n) if (bytes[i].toInt() == 0) return false
                val text = String(bytes, Charsets.UTF_8)
                js("onFile(${JSONObject.quote(rel)}, ${JSONObject.quote(text)}, ${JSONObject.quote(f.absolutePath)})")
                true
            } catch (e: Throwable) { false }
        }

        @JavascriptInterface
        fun deleteWorkspaceFile(rel: String): Boolean {
            return try {
                val f = Storage.resolve(Storage.dir(this@MainActivity), rel) ?: return false
                f.deleteRecursively()
            } catch (e: Throwable) { false }
        }

        /** Copies a file out of the app folder to a place the user picks (Downloads, Drive ...). */
        @JavascriptInterface
        fun exportFile(rel: String) {
            val f = Storage.resolve(Storage.dir(this@MainActivity), rel) ?: return
            if (!f.isFile) return
            pendingExport = f
            runOnUiThread {
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE).setType(Storage.mime(f.name))
                    .putExtra(Intent.EXTRA_TITLE, f.name), 3)
            }
        }

        /** Copies files picked by the user into the working folder. */
        @JavascriptInterface
        fun importFiles() {
            runOnUiThread {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                    .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true), 4)
            }
        }

        // ---------------------------------------------------------------- system bars (Android 15+)
        @JavascriptInterface
        fun setBars(color: String, light: Boolean) {
            runOnUiThread {
                try {
                    rootView.setBackgroundColor(Color.parseColor(color))
                    if (Build.VERSION.SDK_INT >= 35) {
                        val mask = android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                            android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
                        window.insetsController?.setSystemBarsAppearance(if (light) mask else 0, mask)
                    }
                } catch (e: Throwable) { }
            }
        }
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (res != RESULT_OK || data == null) return
        try {
            when (req) {
                1 -> {
                    val uri = data.data ?: return
                    val text = contentResolver.openInputStream(uri)!!.bufferedReader(Charsets.UTF_8).use { it.readText() }
                    js("onFile(${JSONObject.quote(displayName(uri))}, ${JSONObject.quote(text)}, \"\")")
                }
                2 -> {
                    val uri = data.data ?: return
                    contentResolver.openOutputStream(uri, "wt")!!.use { it.write(pendingSave.toByteArray(Charsets.UTF_8)) }
                    js("toast('✔')")
                }
                3 -> {
                    val uri = data.data ?: return
                    val f = pendingExport ?: return
                    contentResolver.openOutputStream(uri, "wt")!!.use { out -> f.inputStream().use { it.copyTo(out) } }
                    js("toast('✔')")
                }
                4 -> {
                    val clip = data.clipData
                    if (clip != null) {
                        for (i in 0 until clip.itemCount) importUri(clip.getItemAt(i).uri)
                    } else {
                        val uri = data.data ?: return
                        importUri(uri)
                    }
                    js("window.pvFilesChanged&&window.pvFilesChanged()")
                }
            }
        } catch (e: Exception) {
            js("toast(${JSONObject.quote(e.toString())})")
        }
    }
}
