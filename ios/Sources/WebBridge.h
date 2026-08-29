#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>

/// The only bridge between the page and the device.
///
/// It mirrors what `preload.cjs` exposes on the desktop and what
/// `WebBridge.java` exposes on Android, minus the parts that only mean
/// something with a mouse. Everything of substance goes over the HTTP API
/// instead, so this stays small on purpose.
@interface SnapirWebBridge : NSObject <WKScriptMessageHandler>

/// The name the page posts to: `window.webkit.messageHandlers.snapir`.
@property(class, readonly, nonnull) NSString *handlerName;

/// Defines `window.snapir` before the interface's own scripts run.
///
/// Android has to write this out as a file and splice a `<script>` tag into
/// index.html, because the built page carries `default-src 'self'` and that
/// blocks inline script. A WKUserScript is injected by the host rather than
/// loaded by the document, so the page's policy does not apply to it and the
/// bundle can stay read-only and untouched.
+ (nonnull WKUserScript *)shim;

- (nonnull instancetype)initWithHost:(nonnull UIViewController *)host
    NS_DESIGNATED_INITIALIZER;
- (nonnull instancetype)init NS_UNAVAILABLE;

@property(nonatomic, weak, nullable) WKWebView *webView;

@end
