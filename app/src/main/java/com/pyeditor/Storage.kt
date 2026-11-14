package com.pyeditor

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Environment
import java.io.File

/** Where the user's own files live (public phone storage, not the private app folder). */
object Storage {
    fun granted(c: Context): Boolean = try {
        if (Build.VERSION.SDK_INT >= 30) Environment.isExternalStorageManager()
        else c.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    } catch (e: Throwable) { false }

    /** "root" = main phone storage itself (no folder), "app" = /Pyvora folder */
    fun mode(c: Context): String = c.getSharedPreferences("pv", 0).getString("dir", "root") ?: "root"
    fun setMode(c: Context, m: String) { c.getSharedPreferences("pv", 0).edit().putString("dir", m).apply() }

    fun dir(c: Context): File? {
        if (!granted(c)) return null
        val base = Environment.getExternalStorageDirectory()
        val d = if (mode(c) == "app") File(base, "Pyvora") else base
        return try { d.mkdirs(); if (d.canWrite()) d else null } catch (e: Throwable) { null }
    }

    fun path(c: Context): String = dir(c)?.absolutePath ?: ""
}
