package com.snapirdesign.designx;

/**
 * The geometry backend, running inside this process.
 *
 * <p>On the desktop this same service is a sidecar process the Electron shell
 * spawns. Here it is a thread. Either way it is the same C++ and the same HTTP
 * routes, which is what makes the interface identical on both.
 */
final class NativeService {

    /** Loopback only. Nothing about this service is meant to leave the device. */
    static final int PORT = 8765;
    static final String ORIGIN = "http://127.0.0.1:" + PORT;

    private static boolean loaded = false;

    private NativeService() {}

    /**
     * Starts the service if it is not already running. Returns immediately; the
     * server runs on its own thread. Call {@link #waitUntilReady} before
     * pointing a WebView at it.
     */
    static synchronized void start(String filesDir, String webRoot) {
        if (!loaded) {
            System.loadLibrary("snapir");
            loaded = true;
        }
        nativeStart(filesDir, webRoot, PORT);
    }

    /** Polls the health endpoint. Returns false if it never came up. */
    static boolean waitUntilReady(long timeoutMs) {
        final long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            try {
                java.net.Socket s = new java.net.Socket();
                s.connect(new java.net.InetSocketAddress("127.0.0.1", PORT), 300);
                s.close();
                return true;
            } catch (Exception ignored) {
                try {
                    Thread.sleep(100);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return false;
                }
            }
        }
        return false;
    }

    private static native void nativeStart(String filesDir, String webRoot, int port);
}
