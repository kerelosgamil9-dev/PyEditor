package com.pyeditor

import android.app.Activity
import android.app.ActivityManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Process
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.util.concurrent.LinkedBlockingQueue
import kotlin.concurrent.thread

class ConsoleActivity : Activity() {
    private val q = LinkedBlockingQueue<String>()
    private val buf = StringBuilder()
    private var pending = false
    private lateinit var tv: TextView
    private lateinit var sv: ScrollView
    private lateinit var status: TextView
    private lateinit var input: EditText

    inner class Io {
        fun write(s: String) {
            synchronized(buf) {
                buf.append(s)
                if (pending) return
                pending = true
            }
            tv.postDelayed({ flush() }, 40)
        }
        fun readLine(): String = q.take()
    }
    private val io = Io()

    private fun flush() {
        val s = synchronized(buf) { val t = buf.toString(); buf.setLength(0); pending = false; t }
        val i = s.lastIndexOf('\u000c')
        if (i >= 0) { tv.text = ""; tv.append(s.substring(i + 1)) } else tv.append(s)
        if (tv.length() > 300000) tv.text = tv.text.subSequence(tv.length() - 200000, tv.length())
        sv.post { sv.fullScroll(View.FOCUS_DOWN) }
    }

    private fun submit() {
        val s = input.text.toString()
        input.setText("")
        io.write(s + "\n")
        q.put(s + "\n")
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        val term = intent.getBooleanExtra("term", false)
        val name = intent.getStringExtra("name") ?: "main.py"
        val title = if (term) "Terminal" else name
        setTaskDescription(ActivityManager.TaskDescription(title))
        val fg = Color.parseColor("#d4d4d4")

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#1e1e1e"))
        }
        val head = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#252526"))
            setPadding(32, 8, 16, 8)
        }
        status = TextView(this).apply { text = title; setTextColor(fg); textSize = 16f }
        val stop = Button(this).apply { text = "■"; setOnClickListener { finishAndRemoveTask() } }
        head.addView(status, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(stop)

        tv = TextView(this).apply {
            setTextColor(fg); typeface = Typeface.MONOSPACE; textSize = 14f
            setPadding(24, 16, 24, 16); setTextIsSelectable(true)
        }
        sv = ScrollView(this).apply { addView(tv) }

        input = EditText(this).apply {
            setTextColor(fg); setHintTextColor(Color.GRAY); hint = "input ›"
            typeface = Typeface.MONOSPACE; isSingleLine = true
            imeOptions = EditorInfo.IME_ACTION_SEND
            setOnEditorActionListener { _, _, _ -> submit(); true }
        }
        val send = Button(this).apply { text = "↵"; setOnClickListener { submit() } }
        val row = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#252526"))
            setPadding(16, 4, 8, 4)
        }
        row.addView(input, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(send)

        root.addView(head)
        root.addView(sv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(row)
        setContentView(root)

        intent.getStringExtra("prefill")?.let { input.setText(it); input.setSelection(it.length); input.requestFocus() }

        val wd = filesDir.absolutePath
        val code = intent.getStringExtra("code") ?: ""
        thread {
            try {
                val m = Python.getInstance().getModule("runner")
                if (term) m.callAttr("shell", io, wd) else m.callAttr("run", io, code, name, wd)
            } catch (e: Throwable) { io.write("\n$e\n") }
            io.write(if (term) "\n[Terminal closed]\n" else "\n[Finished ✔]\n")
            runOnUiThread { status.text = "$title ✔" }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing) Process.killProcess(Process.myPid())
    }
}
