package com.pyeditor

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import java.io.File

class MainActivity : Activity() {
    private lateinit var web: WebView
    private var pendingSave: String = ""
    private var asked = false

    private fun js(code: String) = runOnUiThread { web.evaluateJavascript(code, null) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(Color.BLACK)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.addJavascriptInterface(Bridge(), "Android")
        web.loadUrl("file:///android_asset/index.html")
        setContentView(web)
    }

    override fun onResume() {
        super.onResume()
        if (Storage.granted(this)) Storage.dir(this)
    }

    private fun askStorage() {
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

    private fun console(i: Intent) = startActivity(i)

    inner class Bridge {
        @JavascriptInterface
        fun run(code: String, name: String) {
            console(Intent(this@MainActivity, ConsoleActivity::class.java)
                .putExtra("code", code).putExtra("name", name))
        }
        @JavascriptInterface
        fun terminal() {
            startActivity(Intent(this@MainActivity, ToolActivity::class.java).putExtra("mode", "term"))
        }
        @JavascriptInterface
        fun pip() {
            startActivity(Intent(this@MainActivity, ToolActivity::class.java).putExtra("mode", "pip"))
        }
        @JavascriptInterface
        fun openFile() {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), 1)
        }
        @JavascriptInterface
        fun saveAs(name: String, content: String) {
            pendingSave = content
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("text/x-python")
                .putExtra(Intent.EXTRA_TITLE, name), 2)
        }
        /** Save straight into the phone storage. Returns the full path, or "" when there is no permission. */
        @JavascriptInterface
        fun quickSave(name: String, content: String, path: String): String {
            return try {
                val dir = Storage.dir(this@MainActivity) ?: return ""
                var f: File
                if (path.isNotEmpty() && File(path).parentFile?.canWrite() == true) {
                    f = File(path)
                } else {
                    val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_").ifBlank { "file.py" }
                    f = File(dir, safe)
                    var n = 1
                    val base = f.nameWithoutExtension
                    val ext = f.extension
                    while (f.exists()) {
                        f = File(dir, base + "(" + n + ")" + (if (ext.isEmpty()) "" else ".$ext"))
                        n++
                    }
                }
                f.writeText(content, Charsets.UTF_8)
                f.absolutePath
            } catch (e: Throwable) { "" }
        }
        @JavascriptInterface
        fun hasStorage(): Boolean = Storage.granted(this@MainActivity)
        @JavascriptInterface
        fun grantStorage() { runOnUiThread { askStorage() } }
        @JavascriptInterface
        fun setDirMode(m: String) { Storage.setMode(this@MainActivity, m) }
        @JavascriptInterface
        fun dirPath(): String = Storage.path(this@MainActivity)
    }

    @Deprecated("simple")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        val uri = data?.data ?: return
        if (res != RESULT_OK) return
        try {
            if (req == 1) {
                val text = contentResolver.openInputStream(uri)!!.bufferedReader(Charsets.UTF_8).readText()
                val name = uri.lastPathSegment?.substringAfterLast('/') ?: "file.py"
                js("onFile(${JSONObject.quote(name)}, ${JSONObject.quote(text)})")
            } else if (req == 2) {
                contentResolver.openOutputStream(uri, "wt")!!.use { it.write(pendingSave.toByteArray(Charsets.UTF_8)) }
                js("toast('✔')")
            }
        } catch (e: Exception) { js("toast(${JSONObject.quote(e.toString())})") }
    }

    @Deprecated("simple")
    override fun onBackPressed() { moveTaskToBack(true) }
}
