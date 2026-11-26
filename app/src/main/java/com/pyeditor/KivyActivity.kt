package com.pyeditor

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.WindowInsets
import android.window.OnBackInvokedDispatcher
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.pyvora.kv.SDLActivity
import java.io.File

/**
 * REAL Kivy: Kivy 2.3.1 (native modules built in CI) on its own SDL2 2.28.5 (renamed org.pyvora.kv / libSDL2kv.so),
 * so it never clashes with the SDL that real tkinter uses. SDLActivity creates the OpenGL surface and calls SDL_main()
 * (libkvmain.so) on its own thread; SDL_main calls runPython() below, so the user's script (and Kivy's event loop)
 * run on that thread. Runs in its own process (:kivy).
 */
class KivyActivity : SDLActivity() {
    private var codePath = ""
    private var scriptName = "main.py"
    private lateinit var outFile: File

    // live output panel + top bar (✕ and Output) drawn over the Kivy screen
    private var topBarPx = 0
    private var panel: ScrollView? = null
    private var panelText: TextView? = null
    private var outBtn: TextView? = null
    private var panelOpen = false
    private val outBuf = StringBuilder()
    private val outLock = Any()
    private var outPending = false

    companion object {
        /** true only on 64-bit devices where the native Kivy libraries were packaged */
        fun supported(c: Context): Boolean {
            if (Build.SUPPORTED_64_BIT_ABIS.isEmpty()) return false
            val d = c.applicationInfo.nativeLibraryDir
            return File(d, "libSDL2kv.so").exists() && File(d, "libkvmain.so").exists() &&
                File(d, "libkvx_kivy_core_window__window_sdl2.so").exists()
        }
    }

    // our own renamed SDL2 + the entry point (libkvmain.so, last in the list, is the one SDL starts)
    override fun getLibraries(): Array<String> = arrayOf("SDL2kv", "kvmain")

    override fun onCreate(savedInstanceState: Bundle?) {
        scriptName = intent.getStringExtra("name") ?: "main.py"
        codePath = intent.getStringExtra("codePath") ?: ""
        outFile = File(cacheDir, "kv_out.txt")
        try { outFile.delete() } catch (e: Exception) { }
        try {
            prepareRuntime()
        } catch (e: Throwable) {
            try { outFile.appendText("setup failed: $e\n") } catch (x: Exception) { }
        }
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        super.onCreate(savedInstanceState)
        keepClearOfSystemBars()
        buildOverlay()
        // Back button / gesture closes the Kivy screen (a fullscreen window has no title bar to close it with)
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT) { finish() }
        }
    }

    /**
     * Android 15+ draws apps edge-to-edge, so the top of the screen ended up under the status bar / camera cut-out
     * (untouchable). This keeps the drawing surface inside the safe area (and above the keyboard when it is open).
     */
    private fun keepClearOfSystemBars() {
        if (Build.VERSION.SDK_INT < 30) return
        val content = findViewById<View>(android.R.id.content) ?: return
        content.setBackgroundColor(0xFF000000.toInt())
        content.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            v.setPadding(bars.left, maxOf(bars.top, topBarPx), bars.right, maxOf(bars.bottom, ime.bottom))
            // the keyboard was closed (its own button / the back gesture): Android does not tell Kivy, so the text field
            // stayed "focused" and tapping it again did nothing. Tell Kivy to let go of the keyboard.
            val imeShown = insets.isVisible(WindowInsets.Type.ime())
            if (imeWasShown && !imeShown) {
                Thread {
                    try {
                        Python.getInstance().getModule("kvrun").callAttr("ime_hidden")
                    } catch (e: Throwable) {
                    }
                }.start()
            }
            imeWasShown = imeShown
            WindowInsets.CONSUMED
        }
        content.requestApplyInsets()
    }

    private var imeWasShown = false

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun chip(label: String, color: Int, onClick: () -> Unit) = TextView(this).apply {
        text = label
        setTextColor(0xFFFFFFFF.toInt())
        setBackgroundColor(color)
        textSize = 15f
        gravity = Gravity.CENTER
        setPadding(dp(14), 0, dp(14), 0)
        setOnClickListener { onClick() }
    }

    /** a thin bar in the unused top margin: ✕ closes the Kivy screen, "Output" shows what the script printed */
    private fun buildOverlay() {
        try {
            topBarPx = dp(44)
            val decor = window.decorView as ViewGroup
            val close = chip("✕", 0xCCB71C1C.toInt()) { finish() }
            decor.addView(close, FrameLayout.LayoutParams(dp(56), dp(36), Gravity.TOP or Gravity.END).apply {
                topMargin = dp(4); rightMargin = dp(6)
            })
            val tv = TextView(this).apply {
                setTextColor(0xFF9EE6A8.toInt()); typeface = Typeface.MONOSPACE; textSize = 12f
                setPadding(dp(8), dp(6), dp(8), dp(6)); setTextIsSelectable(true)
            }
            val sv = ScrollView(this).apply {
                setBackgroundColor(0xEE0D1117.toInt()); visibility = View.GONE
                addView(tv)
            }
            val h = (resources.displayMetrics.heightPixels * 0.42).toInt()
            decor.addView(sv, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h, Gravity.BOTTOM))
            panel = sv; panelText = tv
            val ob = chip("Output", 0xCC1F6FEB.toInt()) {
                panelOpen = !panelOpen
                sv.visibility = if (panelOpen) View.VISIBLE else View.GONE
                outBtn?.text = "Output"
                if (panelOpen) sv.post { sv.fullScroll(View.FOCUS_DOWN) }
            }
            decor.addView(ob, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(36), Gravity.TOP or Gravity.START).apply {
                topMargin = dp(4); leftMargin = dp(6)
            })
            outBtn = ob
        } catch (e: Throwable) { }
    }

    /** called from Python for every print() while the script runs (any thread) */
    fun appendOut(s: String) {
        synchronized(outLock) {
            outBuf.append(s)
            if (outBuf.length > 60000) outBuf.delete(0, outBuf.length - 50000)
            if (outPending) return
            outPending = true
        }
        runOnUiThread { Handler(Looper.getMainLooper()).postDelayed({ flushOut() }, 80) }
    }

    private fun flushOut() {
        val t = synchronized(outLock) { outPending = false; outBuf.toString() }
        val tv = panelText ?: return
        tv.text = t
        panel?.post { panel?.fullScroll(View.FOCUS_DOWN) }
        if (!panelOpen) outBtn?.text = "Output ●"
    }

    private var keyboardKind = "text"

    /**
     * Kivy calls this when a TextInput gets focus (python-for-android's PythonActivity has the same method).
     * The type arrives as a number (or, in some Kivy versions, a text like "text" / "number").
     * SDL 2.28 always opens the normal text keyboard, so for now we only remember it.
     */
    @Suppress("unused")
    fun changeKeyboard(type: Int) {
        keyboardKind = type.toString()
    }

    @Suppress("unused")
    fun changeKeyboard(type: String?) {
        keyboardKind = type ?: "text"
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode == KeyEvent.KEYCODE_BACK) {
            if (event.action == KeyEvent.ACTION_UP) finish()
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    private fun runtimeDir() = File(filesDir, "kvrt")

    /** copies the Kivy python package (and its data) out of the APK (once per app update) */
    private fun prepareRuntime() {
        val root = runtimeDir()
        val stamp = File(root, ".stamp")
        val ver = packageManager.getPackageInfo(packageName, 0).lastUpdateTime.toString()
        if (stamp.exists() && stamp.readText() == ver) return
        root.deleteRecursively()
        root.mkdirs()
        copyAsset("kivy_rt", File(root, "kivy_rt"))
        // the same fonts real tkinter uses (Cairo, DejaVu...): app/src/main/assets/tkfonts/*.ttf
        copyAsset("tkfonts", File(root, "kvfonts"))
        stamp.writeText(ver)
    }

    private fun copyAsset(path: String, dest: File) {
        val list = assets.list(path)
        if (list == null || list.isEmpty()) {
            try {
                dest.parentFile?.mkdirs()
                assets.open(path).use { i -> dest.outputStream().use { o -> i.copyTo(o) } }
            } catch (e: java.io.FileNotFoundException) {
                dest.mkdirs()      // an empty folder
            }
        } else {
            dest.mkdirs()
            for (f in list) copyAsset("$path/$f", File(dest, f))
        }
    }

    /** called from native SDL_main() on the SDL thread */
    fun runPython(): Int {
        var rc = 1
        try {
            val root = runtimeDir()
            val m = Python.getInstance().getModule("kvrun")
            val r = m.callAttr(
                "main", codePath, scriptName, filesDir.absolutePath, Storage.path(this),
                applicationInfo.nativeLibraryDir,
                File(root, "kivy_rt").absolutePath, File(root, "kvfonts").absolutePath,
                outFile.absolutePath, this
            )
            rc = r.toInt()
        } catch (e: Throwable) {
            try { outFile.appendText("\n$e\n") } catch (x: Exception) { }
        }
        if (rc != 0) showOutput()      // errors are shown after the screen closes; normal output only via the Output button
        return rc
    }

    private fun showOutput() {
        val t = try { outFile.readText() } catch (e: Exception) { "" }
        if (t.isBlank()) return
        try {
            startActivity(
                Intent(this, TkOutputActivity::class.java)
                    .putExtra("path", outFile.absolutePath)
                    .putExtra("name", scriptName)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (e: Throwable) { }
    }

    // SDL keeps static state, so every run gets a fresh process
    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing) Process.killProcess(Process.myPid())
    }
}
