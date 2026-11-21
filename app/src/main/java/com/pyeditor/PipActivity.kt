package com.pyeditor

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.FrameLayout
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Pip screen: installed libraries, search, install, quick install (the page is assets/pip.html).
 * Python work (runner.pip_*) runs on one background thread; the page gets the answers through window.onXxx(...).
 */
class PipActivity : Activity() {
    private lateinit var web: WebView
    private val worker = Executors.newSingleThreadExecutor()
    @Volatile private var site: String = ""

    private fun js(code: String) {
        runOnUiThread { if (!isFinishing) web.evaluateJavascript(code, null) }
    }

    private fun call(fn: String, vararg args: String) {
        js("window.$fn&&window.$fn(" + args.joinToString(",") + ")")
    }

    /** print() of the Python side ends up here (runner._setup redirects stdout / stderr to this object) */
    inner class Io {
        fun write(s: String) { call("onLog", JSONObject.quote(s)) }
        fun readLine(): String = ""
        fun nextEvent(ms: Int): String = ""
        fun gui(json: String) { }
    }

    private val io = Io()

    private fun runner(): PyObject = Python.getInstance().getModule("runner")

    /** runs [block] on the worker; any failure is shown in the page */
    private fun background(block: () -> Unit) {
        worker.execute {
            try { block() } catch (e: Throwable) { call("onErr", JSONObject.quote(e.toString())) }
        }
    }

    inner class Bridge {
        @JavascriptInterface
        fun list() = background {
            call("onList", JSONObject.quote(runner().callAttr("pip_list_json", site).toString()))
        }

        @JavascriptInterface
        fun install(text: String, prebuilt: Boolean) = background {
            val rc = runner().callAttr("pip_install", text, site, prebuilt).toInt()
            call("onDone", "\"install\"", rc.toString())
        }

        @JavascriptInterface
        fun uninstall(name: String) = background {
            val rc = runner().callAttr("pip_uninstall", name, site).toInt()
            call("onDone", "\"uninstall\"", rc.toString())
        }

        @JavascriptInterface
        fun search(q: String) = background {
            val json = runner().callAttr("pip_search_json", q).toString()
            call("onSearch", JSONObject.quote(q), JSONObject.quote(json))
        }

        @JavascriptInterface
        fun close() { runOnUiThread { finish() } }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#172a3e"))
        web.settings.javaScriptEnabled = true
        web.addJavascriptInterface(Bridge(), "Android")
        val root = FrameLayout(this)
        root.setBackgroundColor(Color.parseColor("#172a3e"))
        root.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        Edge.install(root)
        web.loadUrl("file:///android_asset/pip.html")

        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                OnBackInvokedCallback { handleBack() }
            )
        }

        val wd = filesDir.absolutePath
        val pub = Storage.path(this)
        background {
            if (!Python.isStarted()) Python.start(AndroidPlatform(this@PipActivity))
            site = runner().callAttr("pip_init", io, wd, pub).toString()
            call("onReady")
        }
    }

    /** Back closes the dialog / log of the page first, then the screen */
    private fun handleBack() {
        web.evaluateJavascript("(function(){try{return window.pvBack?window.pvBack():false}catch(e){return false}})()") { r ->
            if (r != "true") finish()
        }
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() { handleBack() }

    override fun onDestroy() {
        worker.shutdown()
        (web.parent as? ViewGroup)?.removeView(web)
        web.destroy()
        super.onDestroy()
    }
}
