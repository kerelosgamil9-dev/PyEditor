package com.pyeditor

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var web: WebView
    private var pendingSave: String = ""

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

    private fun console(i: Intent) {
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_DOCUMENT or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)
        startActivity(i)
    }

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
