package br.aporte.app

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var page: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        status = TextView(this).apply {
            text = "Abrindo o Aporte Brasil…"
            val padding = (16 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        page = WebView(this)
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(status)
            addView(page, LinearLayout.LayoutParams(-1, 0, 1f))
        })
        Thread(::startApplication, "AporteBrasil").start()
    }

    private fun startApplication() {
        try {
            val port = synchronized(Python::class.java) {
                if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                val python = Python.getInstance()
                // The Android wheel uses the default OpenSSL provider for the vault.
                python.getModule("os").get("environ")!!
                    .callAttr("setdefault", "CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")
                python.getModule("android_entry").callAttr("serve", filesDir.absolutePath).toInt()
            }
            runOnUiThread {
                if (!isDestroyed) openPage(port)
            }
        } catch (error: Exception) {
            Log.e("AporteBrasil", "Falha ao iniciar o aplicativo", error)
            runOnUiThread {
                if (!isDestroyed) status.text = "Não foi possível abrir o Aporte Brasil. Feche o aplicativo e tente novamente."
            }
        }
    }

    private fun openPage(port: Int) {
        page.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            userAgentString = "$userAgentString AporteBrasilAndroid/1"
        }
        page.webViewClient = object : WebViewClient() {
            private var loadFailed = false

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                return url.scheme != "http" || url.host != "127.0.0.1" || url.port != port
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) {
                    loadFailed = true
                    status.text = "Não foi possível abrir o Aporte Brasil.\n${error.description}"
                    status.visibility = View.VISIBLE
                }
            }

            override fun onPageCommitVisible(view: WebView, url: String) {
                if (!loadFailed) status.visibility = View.GONE
            }
        }
        page.loadUrl("http://127.0.0.1:$port/")
    }

    override fun onDestroy() {
        page.destroy()
        super.onDestroy()
    }
}
