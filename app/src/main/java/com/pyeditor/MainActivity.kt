package com.pyeditor

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlin.concurrent.thread

class MainActivity : Activity() {
    private lateinit var web: WebView
    private var pendingSave: String = ""

    private fun js(code: String) = runOnUiThread { web.evaluateJavascript(code, null) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        web = WebView(this)
        web.setBackgroundColor(Color.BLACK)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.addJavascriptInterface(Bridge(), "Android")
        web.loadUrl("file:///android_asset/index.html")
        setContentView(web)
    }

    private fun callPy(fn: String, vararg a: Any): String = try {
        Python.getInstance().getModule("runner").callAttr(fn, *a).toString()
    } catch (e: Throwable) { e.toString() }

    inner class Bridge {
        @JavascriptInterface
        fun run(code: String, name: String) {
            thread { js("onOutput(${JSONObject.quote(callPy("run", code, name, filesDir.absolutePath))})") }
        }
        @JavascriptInterface
        fun pip(args: String) {
            thread { js("onTerm(${JSONObject.quote(callPy("pip", args, filesDir.absolutePath))})") }
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
