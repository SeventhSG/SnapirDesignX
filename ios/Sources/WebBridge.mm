#import "WebBridge.h"

#import "FolderImport.h"

@interface SnapirWebBridge ()
@property(nonatomic, weak) UIViewController *host;
@end

@implementation SnapirWebBridge

+ (NSString *)handlerName {
  return @"snapir";
}

+ (WKUserScript *)shim {
  // The same object preload.cjs exposes on the desktop, so not one line of the
  // interface has to know which shell it is talking to.
  NSString *source =
      @"(function () {\n"
      @"  function post(name, arg) {\n"
      @"    try {\n"
      @"      window.webkit.messageHandlers.snapir.postMessage({ name: name, arg: arg });\n"
      @"      return true;\n"
      @"    } catch (e) { return false; }\n"
      @"  }\n"
      @"  window.snapir = {\n"
      @"    api: location.origin,\n"
      @"    backendReady: function () { return Promise.resolve({ ok: true }); },\n"
      @"    setTheme: function (dark) { post('setTheme', !!dark); },\n"
      @"    reveal: function (p) { post('reveal', String(p)); },\n"
      @"    pickFolder: function () {\n"
      @"      return new Promise(function (resolve) {\n"
      @"        window.__snapirFolderChosen = function (path) {\n"
      @"          window.__snapirFolderChosen = null;\n"
      @"          resolve(path || null);\n"
      @"        };\n"
      @"        if (!post('pickFolder', null)) {\n"
      @"          window.__snapirFolderChosen = null;\n"
      @"          resolve(null);\n"
      @"        }\n"
      @"      });\n"
      @"    }\n"
      @"  };\n"
      @"})();\n";

  // At document start, so window.snapir exists by the time the interface looks
  // for it. Main frame only: there is nothing else on this origin.
  return [[WKUserScript alloc] initWithSource:source
                                injectionTime:WKUserScriptInjectionTimeAtDocumentStart
                             forMainFrameOnly:YES];
}

- (instancetype)initWithHost:(UIViewController *)host {
  if ((self = [super init])) {
    _host = host;
  }
  return self;
}

- (void)userContentController:(WKUserContentController *)controller
      didReceiveScriptMessage:(WKScriptMessage *)message {
  NSDictionary *body = [message.body isKindOfClass:NSDictionary.class]
                           ? (NSDictionary *)message.body
                           : nil;
  NSString *name = body[@"name"];
  if (![name isKindOfClass:NSString.class]) return;

  if ([name isEqualToString:@"pickFolder"]) {
    [self pickFolder];
  } else if ([name isEqualToString:@"reveal"]) {
    [self reveal:body[@"arg"]];
  } else if ([name isEqualToString:@"setTheme"]) {
    // The page paints itself; the shell has nothing of its own to re-colour.
  }
}

- (void)pickFolder {
  UIViewController *host = self.host;
  if (!host) {
    [self deliverFolder:nil];
    return;
  }
  [SnapirFolderImport presentFrom:host
                       completion:^(NSString *path) {
                         [self deliverFolder:path];
                       }];
}

/// Hands a chosen folder back to the promise the page is waiting on.
- (void)deliverFolder:(NSString *)path {
  NSString *js =
      path ? [NSString stringWithFormat:
                           @"window.__snapirFolderChosen && window.__snapirFolderChosen(%@)",
                           [self jsString:path]]
           : @"window.__snapirFolderChosen && window.__snapirFolderChosen(null)";
  dispatch_async(dispatch_get_main_queue(), ^{
    [self.webView evaluateJavaScript:js completionHandler:nil];
  });
}

/// There is no file manager to jump to, so offer the file itself. Everything
/// written also shows up in Files.app, which is what UIFileSharingEnabled is
/// for; this is the shorter route for one export.
- (void)reveal:(id)path {
  if (![path isKindOfClass:NSString.class]) return;
  UIViewController *host = self.host;
  if (!host) return;

  NSURL *url = [NSURL fileURLWithPath:(NSString *)path];
  if (![NSFileManager.defaultManager fileExistsAtPath:url.path]) return;

  dispatch_async(dispatch_get_main_queue(), ^{
    UIActivityViewController *sheet =
        [[UIActivityViewController alloc] initWithActivityItems:@[ url ]
                                          applicationActivities:nil];
    // An activity sheet with no anchor is a crash on iPad, and iPad is the
    // device this is built for.
    sheet.popoverPresentationController.sourceView = host.view;
    sheet.popoverPresentationController.sourceRect =
        CGRectMake(CGRectGetMidX(host.view.bounds),
                   CGRectGetMaxY(host.view.bounds) - 1, 1, 1);
    [host presentViewController:sheet animated:YES completion:nil];
  });
}

- (NSString *)jsString:(NSString *)s {
  NSData *json = [NSJSONSerialization dataWithJSONObject:@[ s ]
                                                 options:0
                                                   error:nil];
  NSString *wrapped = [[NSString alloc] initWithData:json
                                            encoding:NSUTF8StringEncoding];
  // ["..."] -> "..."
  return [wrapped substringWithRange:NSMakeRange(1, wrapped.length - 2)];
}

@end
