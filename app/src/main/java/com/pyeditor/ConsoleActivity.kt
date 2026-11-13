package com.pyeditor

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.content.Context
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.inputmethod.InputMethodManager
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

open class ConsoleActivity : Activity() {
    private val q = LinkedBlockingQueue<String>()
    private val events = LinkedBlockingQueue<String>()
    private val buf = StringBuilder()
    private var pending = false
    private lateinit var tv: TextView
    private lateinit var sv: ScrollView
    private lateinit var status: TextView
    private lateinit var input: EditText
    private lateinit var row: LinearLayout
    private lateinit var body: FrameLayout
    private lateinit var tog: Button
    private var web: WebView? = null
    private var webReady = false
    private var guiFailed = false
    private var mode = "run"
    private var wantInput = false
    private var inErr = false
    private val webPending = ArrayList<String>()

    // الجسر اللي بايثون بيكلمه
    inner class Io {
        fun write(s: String) {
            synchronized(buf) {
                buf.append(s)
                if (pending) return
                pending = true
            }
            tv.postDelayed({ flush() }, 40)
        }
        fun readLine(): String {
            runOnUiThread {
                wantInput = true
                if (web?.visibility == View.VISIBLE) showGui(false)
                updateRow()
                input.requestFocus()
                (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(input, InputMethodManager.SHOW_IMPLICIT)
            }
            val s = q.take()
            runOnUiThread { wantInput = false; updateRow() }
            return s
        }
        fun nextEvent(ms: Int): String = events.poll(ms.toLong(), TimeUnit.MILLISECONDS) ?: ""
        fun gui(json: String) { runOnUiThread { guiSend(json) } }
    }
    private val io = Io()

    inner class TkBridge {
        @JavascriptInterface
        fun ev(s: String) { events.put(s) }
    }

    private fun flush() {
        val s = synchronized(buf) { val t = buf.toString(); buf.setLength(0); pending = false; t }
        val i = s.lastIndexOf('\u000c')
        if (i >= 0) { tv.text = ""; inErr = false; appendMarked(s.substring(i + 1)) } else appendMarked(s)
        if (tv.length() > 300000) tv.text = tv.text.subSequence(tv.length() - 200000, tv.length())
        sv.post { sv.fullScroll(View.FOCUS_DOWN) }
    }

    /** text between \u0001 and \u0002 comes from stderr and is painted red */
    private fun appendMarked(s: String) {
        val sb = SpannableStringBuilder()
        var start = 0
        var errStart = if (inErr) 0 else -1
        val red = Color.parseColor("#f48771")
        for (i in s.indices) {
            val c = s[i]
            if (c == '\u0001') { sb.append(s, start, i); start = i + 1; errStart = sb.length; inErr = true }
            else if (c == '\u0002') {
                sb.append(s, start, i); start = i + 1
                if (errStart >= 0 && sb.length > errStart) sb.setSpan(ForegroundColorSpan(red), errStart, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                errStart = -1; inErr = false
            }
        }
        sb.append(s, start, s.length)
        if (errStart >= 0 && sb.length > errStart) sb.setSpan(ForegroundColorSpan(red), errStart, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        tv.append(sb)
    }

    /** the input box exists only while the program is waiting for input() (always shown in terminal / pip) */
    private fun updateRow() {
        val gui = web?.visibility == View.VISIBLE
        row.visibility = if (wantInput || (mode != "run" && !gui)) View.VISIBLE else View.GONE
    }

    private fun showGui(on: Boolean) {
        web?.visibility = if (on) View.VISIBLE else View.GONE
        sv.visibility = if (on) View.GONE else View.VISIBLE
        updateRow()
    }

    private fun run(w: WebView, json: String) = w.evaluateJavascript("tkApply(${JSONObject.quote(json)})", null)

    private fun guiSend(json: String) {
        if (guiFailed) return
        if (web == null) {
          try {
            val w = WebView(this)
            w.settings.javaScriptEnabled = true
            w.setBackgroundColor(Color.parseColor("#d9d9d9"))
            w.addJavascriptInterface(TkBridge(), "Native")
            w.webViewClient = object : WebViewClient() {
                override fun onPageFinished(v: WebView?, u: String?) {
                    webReady = true
                    for (j in webPending) run(w, j)
                    webPending.clear()
                }
            }
            w.loadUrl("file:///android_asset/tk.html")
            body.addView(w, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            web = w
            tog.visibility = View.VISIBLE
            showGui(true)
          } catch (e: Throwable) {
            guiFailed = true
            io.write("\n[GUI error] $e\n")
            return
          }
        }
        if (webReady) run(web!!, json) else webPending.add(json)
    }

    private fun submit(prefix: String = "") {
        val s = input.text.toString()
        if (prefix.isNotEmpty() && s.isBlank()) return
        input.setText("")
        val line = if (prefix.isEmpty()) s else "$prefix ${s.trim()}"
        io.write((if (prefix.isEmpty()) s else "\n$ pip $line") + "\n")
        q.put(line + "\n")
    }

    private fun btn(t: String, f: () -> Unit) = Button(this).apply {
        text = t; minWidth = 0; minimumWidth = 0
        setOnClickListener { f() }
    }

    override fun onCreate(b: Bundle?) {
        if (Build.VERSION.SDK_INT >= 28) {
            try { WebView.setDataDirectorySuffix("run") } catch (e: Exception) {}
        }
        super.onCreate(b)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        mode = intent.getStringExtra("mode") ?: "run"
        val name = intent.getStringExtra("name") ?: "main.py"
        val title = when (mode) { "term" -> "Terminal"; "pip" -> "Pip"; else -> name }
        val fg = Color.parseColor("#d4d4d4")
        val bar = Color.parseColor("#252526")

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#1e1e1e"))
        }
        status = TextView(this).apply { text = title; setTextColor(fg); textSize = 16f }
        tog = btn("▣") { showGui(web?.visibility != View.VISIBLE) }.apply { visibility = View.GONE }
        val head = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL; setBackgroundColor(bar); setPadding(32, 8, 16, 8)
        }
        head.addView(status, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(tog)
        head.addView(btn("■") { finish() })

        tv = TextView(this).apply {
            setTextColor(fg); typeface = Typeface.MONOSPACE; textSize = 14f
            setPadding(24, 16, 24, 16); setTextIsSelectable(true)
        }
        sv = ScrollView(this).apply { addView(tv) }
        body = FrameLayout(this).apply { addView(sv) }

        input = EditText(this).apply {
            setTextColor(fg); setHintTextColor(Color.GRAY)
            hint = if (mode == "pip") "اسم المكتبة / package name" else "input ›"
            typeface = Typeface.MONOSPACE; isSingleLine = true
            imeOptions = EditorInfo.IME_ACTION_SEND
            setOnEditorActionListener { _, _, _ -> submit(if (mode == "pip") "install" else ""); true }
        }
        row = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL; setBackgroundColor(bar); setPadding(16, 4, 8, 4)
        }
        row.addView(input, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (mode == "pip") {
            row.addView(btn("⬇ Install") { submit("install") })
            row.addView(btn("🗑") { submit("uninstall") })
        } else row.addView(btn("↵") { submit() })

        root.addView(head)
        root.addView(body, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(row)
        setContentView(root)
        updateRow()

        val wd = filesDir.absolutePath
        val pub = Storage.path(this)
        val code = intent.getStringExtra("code") ?: ""
        thread {
            try {
                val m = Python.getInstance().getModule("runner")
                when (mode) {
                    "term" -> m.callAttr("shell", io, wd, pub)
                    "pip" -> m.callAttr("pip_page", io, wd, pub)
                    else -> m.callAttr("run", io, code, name, wd, pub)
                }
            } catch (e: Throwable) { io.write("\n$e\n") }
            io.write(if (mode == "run") "\n[Finished ✔]\n" else "\n[Closed]\n")
            runOnUiThread { wantInput = false; status.text = "$title ✔"; showGui(false) }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing) Process.killProcess(Process.myPid())
    }
}

class ToolActivity : ConsoleActivity()
