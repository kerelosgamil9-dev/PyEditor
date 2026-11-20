package com.pyeditor

import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextUtils
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.webkit.ConsoleMessage
import android.webkit.GeolocationPermissions
import android.webkit.JsPromptResult
import android.webkit.JsResult
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FilterInputStream
import java.io.InputStream

/**
 * Preview screen for HTML / CSS / JavaScript.
 *
 * The page is served from the virtual address https://appassets.androidplatform.net/ :
 *   1) files of the editor tabs (written to cache/preview by MainActivity)  2) files of the working folder.
 * That gives the page a real origin (fetch, localStorage, ES modules, video seeking ... work) while no
 * file:// access is needed. The page gets NO access to the app (no JavascriptInterface).
 */
class HtmlActivity : Activity() {
    companion object {
        const val HOST = "appassets.androidplatform.net"
        const val ORIGIN = "https://appassets.androidplatform.net"
        private const val REQ_FILE = 11
    }

    private lateinit var web: WebView
    private lateinit var status: TextView
    private lateinit var consBtn: Button
    private lateinit var consPanel: LinearLayout
    private lateinit var consText: TextView
    private lateinit var consScroll: ScrollView
    private lateinit var consInput: EditText
    private lateinit var previewDir: File
    private var wsDir: File? = null
    private var main = "index.html"
    private var errors = 0
    private var fileCb: ValueCallback<Array<Uri>>? = null

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    private fun btn(t: String, f: () -> Unit) = Button(this).apply {
        text = t; minWidth = 0; minimumWidth = 0
        setOnClickListener { f() }
    }

    // ------------------------------------------------------------------ console panel
    /** level: 0 log, 1 warning, 2 error, 3 info */
    private fun logLine(level: Int, text: String) {
        runOnUiThread {
            if (isFinishing) return@runOnUiThread
            val color = when (level) {
                2 -> Color.parseColor("#f48771")
                1 -> Color.parseColor("#e5c07b")
                3 -> Color.parseColor("#7f848e")
                else -> Color.parseColor("#d4d4d4")
            }
            val sb = SpannableStringBuilder(text + "\n")
            sb.setSpan(ForegroundColorSpan(color), 0, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            consText.append(sb)
            if (consText.length() > 120000) consText.text = consText.text.subSequence(consText.length() - 80000, consText.length())
            if (level == 2) { errors++; updateConsBtn() }
            consScroll.post { consScroll.fullScroll(View.FOCUS_DOWN) }
        }
    }

    private fun updateConsBtn() {
        consBtn.text = if (errors > 0) "⌨ $errors" else "⌨"
        consBtn.setTextColor(if (errors > 0) Color.parseColor("#f48771") else Color.WHITE)
    }

    private fun toggleConsole() {
        val show = consPanel.visibility != View.VISIBLE
        consPanel.visibility = if (show) View.VISIBLE else View.GONE
        if (show) consScroll.post { consScroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun evalInput() {
        val code = consInput.text.toString().trim()
        if (code.isEmpty()) return
        consInput.setText("")
        logLine(3, "› $code")
        web.evaluateJavascript(code) { r -> logLine(0, "← " + (r ?: "undefined")) }
    }

    private fun load() {
        errors = 0
        updateConsBtn()
        consText.text = ""
        web.loadUrl(ORIGIN + "/" + Uri.encode(main, "/"))
    }

    // ------------------------------------------------------------------ the virtual web server
    private fun findFile(rel: String): File? {
        val roots = arrayOf<File?>(previewDir, wsDir)
        for (root in roots) {
            if (root == null) continue
            val f = Storage.resolve(root, rel) ?: continue
            if (f.exists()) return f
        }
        return null
    }

    private fun resp(code: Int, reason: String, mime: String, body: ByteArray): WebResourceResponse {
        val h = HashMap<String, String>()
        h["Cache-Control"] = "no-cache"
        h["Access-Control-Allow-Origin"] = "*"
        return WebResourceResponse(mime, "utf-8", code, reason, h, ByteArrayInputStream(body))
    }

    private fun serve(req: WebResourceRequest?): WebResourceResponse? {
        val r: WebResourceRequest = req ?: return null
        val u: Uri = r.url ?: return null
        if (u.host != HOST) return null
        val method: String = r.method ?: "GET"
        if (method != "GET" && method != "HEAD") return resp(405, "Method Not Allowed", "text/plain", "405".toByteArray())

        var rel = Uri.decode(u.encodedPath ?: "/").trimStart('/')
        if (rel.isEmpty()) rel = main
        var f = findFile(rel)
        if (f != null && f.isDirectory) f = findFile(rel.trimEnd('/') + "/index.html")
        if (f == null || !f.isFile) {
            logLine(2, "404 Not Found: /$rel")
            val safe = rel.replace("&", "&amp;").replace("<", "&lt;")
            return resp(404, "Not Found", "text/html", ("<h3>404 – Not Found</h3><p>/$safe</p>").toByteArray())
        }

        val mime = Storage.mime(f.name)
        val enc: String? = if (Storage.isText(mime)) "utf-8" else null
        val len = f.length()
        val h = HashMap<String, String>()
        h["Cache-Control"] = "no-cache"
        h["Access-Control-Allow-Origin"] = "*"
        h["Accept-Ranges"] = "bytes"

        // byte ranges: needed for <video>/<audio> seeking
        val range = r.requestHeaders?.get("Range") ?: r.requestHeaders?.get("range")
        if (range != null && range.startsWith("bytes=") && len > 0) {
            val spec = range.substring(6).substringBefore(',')
            val a = spec.substringBefore('-').trim()
            val b = spec.substringAfter('-', "").trim()
            var start: Long
            var end: Long
            if (a.isEmpty()) {
                val n = b.toLongOrNull() ?: 0L
                start = maxOf(0L, len - n)
                end = len - 1
            } else {
                start = a.toLongOrNull() ?: 0L
                end = if (b.isEmpty()) len - 1 else minOf(b.toLongOrNull() ?: (len - 1), len - 1)
            }
            if (start > end || start >= len) {
                h["Content-Range"] = "bytes */$len"
                return WebResourceResponse(mime, enc, 416, "Range Not Satisfiable", h, ByteArrayInputStream(ByteArray(0)))
            }
            return try {
                val ins = FileInputStream(f)
                ins.channel.position(start)
                h["Content-Range"] = "bytes $start-$end/$len"
                h["Content-Length"] = (end - start + 1).toString()
                WebResourceResponse(mime, enc, 206, "Partial Content", h, Bounded(ins, end - start + 1))
            } catch (e: Exception) {
                resp(500, "Error", "text/plain", "500".toByteArray())
            }
        }
        return try {
            h["Content-Length"] = len.toString()
            WebResourceResponse(mime, enc, 200, "OK", h, FileInputStream(f))
        } catch (e: Exception) {
            resp(500, "Error", "text/plain", "500".toByteArray())
        }
    }

    /** an InputStream that stops after [left] bytes */
    private class Bounded(input: InputStream, private var left: Long) : FilterInputStream(input) {
        override fun read(): Int {
            if (left <= 0) return -1
            val r = super.read()
            if (r >= 0) left--
            return r
        }

        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (left <= 0) return -1
            val r = super.read(b, off, minOf(len.toLong(), left).toInt())
            if (r > 0) left -= r
            return r
        }
    }

    // ------------------------------------------------------------------ screen
    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        previewDir = File(cacheDir, "preview")
        // With "All files access" in root mode the whole phone storage would be readable by the page: do not serve it.
        wsDir = if (Storage.granted(this) && Storage.mode(this) == "root") null else Storage.dir(this)
        main = intent.getStringExtra("main") ?: "index.html"

        val fg = Color.parseColor("#d4d4d4")
        val bar = Color.parseColor("#252526")

        status = TextView(this).apply {
            text = main; setTextColor(fg); textSize = 15f; maxLines = 1; ellipsize = TextUtils.TruncateAt.END
        }
        consBtn = btn("⌨") { toggleConsole() }
        val head = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL; setBackgroundColor(bar); setPadding(dp(14), dp(4), dp(8), dp(4))
        }
        head.addView(status, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(btn("⟳") { load() })
        head.addView(consBtn)
        head.addView(btn("✕") { finish() })

        // ---- web view
        web = WebView(this)
        web.setBackgroundColor(Color.WHITE)
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        }
        web.setDownloadListener { url, _, _, _, _ ->
            try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            catch (e: Exception) { logLine(1, "Download is not supported: $url") }
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? = serve(request)

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val u = request?.url ?: return false
                when (u.scheme) {
                    "http", "https", "about", "blob", "data" -> return false
                    "mailto", "tel", "sms", "geo" -> {
                        try { startActivity(Intent(Intent.ACTION_VIEW, u)) } catch (e: Exception) { }
                        return true
                    }
                    else -> { logLine(1, "Blocked: $u"); return true }
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                val t = view?.title
                if (!t.isNullOrBlank() && !t.startsWith(HOST)) status.text = t
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                val u = request?.url ?: return
                if (u.host == HOST) return
                logLine(2, "Failed to load $u  (${error?.description})")
            }

            override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?) {
                val u = request?.url ?: return
                if (u.host == HOST) return
                logLine(2, "HTTP ${errorResponse?.statusCode} $u")
            }

            @TargetApi(Build.VERSION_CODES.O)
            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                logLine(2, "The page crashed (out of memory?). Press ⟳ to reload.")
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(m: ConsoleMessage?): Boolean {
                if (m == null) return true
                val src = (m.sourceId() ?: "").substringAfterLast('/')
                val loc = if (src.isNotEmpty()) "  ($src:${m.lineNumber()})" else ""
                val lvl = when (m.messageLevel()) {
                    ConsoleMessage.MessageLevel.ERROR -> 2
                    ConsoleMessage.MessageLevel.WARNING -> 1
                    ConsoleMessage.MessageLevel.TIP -> 3
                    else -> 0
                }
                logLine(lvl, m.message() + loc)
                return true
            }

            override fun onReceivedTitle(view: WebView?, title: String?) {
                if (!title.isNullOrBlank() && !title.startsWith(HOST)) status.text = title
            }

            override fun onJsAlert(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                if (result == null) return true
                if (isFinishing) { result.cancel(); return true }
                AlertDialog.Builder(this@HtmlActivity).setMessage(message)
                    .setPositiveButton(android.R.string.ok) { _, _ -> result.confirm() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }

            override fun onJsConfirm(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                if (result == null) return true
                if (isFinishing) { result.cancel(); return true }
                AlertDialog.Builder(this@HtmlActivity).setMessage(message)
                    .setPositiveButton(android.R.string.ok) { _, _ -> result.confirm() }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }

            override fun onJsPrompt(view: WebView?, url: String?, message: String?, defaultValue: String?, result: JsPromptResult?): Boolean {
                if (result == null) return true
                if (isFinishing) { result.cancel(); return true }
                val input = EditText(this@HtmlActivity)
                input.setText(defaultValue ?: "")
                AlertDialog.Builder(this@HtmlActivity).setMessage(message).setView(input)
                    .setPositiveButton(android.R.string.ok) { _, _ -> result.confirm(input.text.toString()) }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }

            override fun onShowFileChooser(webView: WebView?, filePathCallback: ValueCallback<Array<Uri>>?, fileChooserParams: FileChooserParams?): Boolean {
                fileCb?.onReceiveValue(null)
                fileCb = filePathCallback
                return try {
                    val i = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).setType("*/*")
                    @Suppress("DEPRECATION")
                    startActivityForResult(i, REQ_FILE)
                    true
                } catch (e: Exception) {
                    fileCb?.onReceiveValue(null)
                    fileCb = null
                    false
                }
            }

            // camera / microphone / location are not supported in the preview
            override fun onPermissionRequest(request: PermissionRequest?) { request?.deny() }
            override fun onGeolocationPermissionsShowPrompt(origin: String?, callback: GeolocationPermissions.Callback?) {
                callback?.invoke(origin, false, false)
            }
        }

        // ---- console panel (hidden until the ⌨ button is pressed)
        consText = TextView(this).apply {
            setTextColor(fg); typeface = Typeface.MONOSPACE; textSize = 12f
            setPadding(dp(10), dp(6), dp(10), dp(6)); setTextIsSelectable(true)
        }
        consScroll = ScrollView(this).apply { addView(consText) }
        consInput = EditText(this).apply {
            setTextColor(fg); setHintTextColor(Color.GRAY); hint = "JavaScript ›"
            typeface = Typeface.MONOSPACE; isSingleLine = true; textSize = 14f
            imeOptions = EditorInfo.IME_ACTION_SEND
            setOnEditorActionListener { _, _, _ -> evalInput(); true }
        }
        val inputRow = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL; setPadding(dp(8), 0, dp(4), 0) }
        inputRow.addView(consInput, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        inputRow.addView(btn("▶") { evalInput() })
        val consHead = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL; setBackgroundColor(bar); setPadding(dp(12), 0, dp(4), 0) }
        consHead.addView(TextView(this).apply { text = "Console"; setTextColor(fg); textSize = 13f },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        consHead.addView(btn("🗑") { consText.text = ""; errors = 0; updateConsBtn() })
        consPanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; visibility = View.GONE; setBackgroundColor(Color.parseColor("#1e1e1e"))
        }
        consPanel.addView(consHead)
        consPanel.addView(consScroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        consPanel.addView(inputRow)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bar)
        }
        root.addView(head)
        root.addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(consPanel, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(230)))
        setContentView(root)
        Edge.install(root)
        updateConsBtn()

        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                OnBackInvokedCallback { handleBack() }
            )
        }
        load()
    }

    private fun handleBack() {
        if (consPanel.visibility == View.VISIBLE) { consPanel.visibility = View.GONE; return }
        if (web.canGoBack()) web.goBack() else finish()
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() { handleBack() }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == REQ_FILE) {
            fileCb?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data))
            fileCb = null
        }
    }

    override fun onPause() { super.onPause(); web.onPause() }
    override fun onResume() { super.onResume(); web.onResume() }

    override fun onDestroy() {
        fileCb?.onReceiveValue(null)
        fileCb = null
        (web.parent as? ViewGroup)?.removeView(web)
        web.destroy()
        super.onDestroy()
    }
}
