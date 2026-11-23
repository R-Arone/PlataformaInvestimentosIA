package br.aporte.app

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ContentResolver
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.DocumentsContract
import android.util.Log
import android.view.View
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import android.window.OnBackInvokedDispatcher
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var page: WebView
    private var documentCallback: ValueCallback<Array<Uri>>? = null

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
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT, ::handleBack
            )
        }
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
                return !isLocalPage(request.url, port)
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
        page.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {
                val url = webView.url
                if (url == null || !isLocalPage(Uri.parse(url), port) ||
                    fileChooserParams.mode != FileChooserParams.MODE_OPEN ||
                    fileChooserParams.isCaptureEnabled || documentCallback != null
                ) {
                    filePathCallback.onReceiveValue(null)
                    return true
                }
                openDocument(filePathCallback)
                return true
            }
        }
        page.loadUrl("http://127.0.0.1:$port/")
    }

    @Deprecated("Uses the back callback from Activity without AndroidX")
    override fun onBackPressed() = handleBack()

    @Suppress("DEPRECATION")
    private fun handleBack() {
        page.evaluateJavascript("window.AporteMobile?.closeOverlay() === true") { closed ->
            if (isFinishing || isDestroyed || closed == "true") return@evaluateJavascript
            if (page.canGoBack()) page.goBack() else super.onBackPressed()
        }
    }

    private fun isLocalPage(uri: Uri, port: Int): Boolean =
        uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port == port

    @Suppress("DEPRECATION")
    private fun openDocument(callback: ValueCallback<Array<Uri>>) {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            // Drive and other providers can expose .aporteb under different MIME types.
            type = "*/*"
        }
        documentCallback = callback
        try {
            startActivityForResult(intent, OPEN_DOCUMENT_REQUEST)
        } catch (error: ActivityNotFoundException) {
            finishDocumentSelection(null)
            Toast.makeText(this, "Nenhum seletor de arquivos disponível.", Toast.LENGTH_LONG).show()
        }
    }

    @Deprecated("Uses the platform Activity result callback without AndroidX")
    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != OPEN_DOCUMENT_REQUEST) return

        val uri = data?.data?.takeIf {
            resultCode == RESULT_OK && it.scheme == ContentResolver.SCHEME_CONTENT &&
                DocumentsContract.isDocumentUri(this, it)
        }
        finishDocumentSelection(uri)
    }

    private fun finishDocumentSelection(uri: Uri?) {
        val callback = documentCallback
        documentCallback = null
        callback?.onReceiveValue(uri?.let { arrayOf(it) })
    }

    override fun onDestroy() {
        finishDocumentSelection(null)
        page.destroy()
        super.onDestroy()
    }

    private companion object {
        const val OPEN_DOCUMENT_REQUEST = 1
    }
}
