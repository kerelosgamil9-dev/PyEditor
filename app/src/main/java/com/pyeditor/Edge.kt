package com.pyeditor

import android.os.Build
import android.view.View
import android.view.WindowInsets

object Edge {
    /**
     * Android 15+ always draws apps edge-to-edge (under the status bar, the navigation bar and the keyboard).
     * This pads [root] by exactly those insets so nothing is hidden. On older Android the system already
     * does this, so nothing is changed there.
     */
    fun install(root: View) {
        if (Build.VERSION.SDK_INT < 35) return
        root.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            WindowInsets.CONSUMED
        }
        root.requestApplyInsets()
    }
}
