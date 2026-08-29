#import "SnapirViewController.h"

#import <WebKit/WebKit.h>

#import "NativeService.h"
#import "WebBridge.h"

@interface SnapirViewController ()
@property(nonatomic, strong) WKWebView *web;
@property(nonatomic, strong) UILabel *status;
@property(nonatomic, strong) SnapirWebBridge *bridge;
@property(nonatomic, assign) BOOL loaded;
@end

@implementation SnapirViewController

- (void)viewDidLoad {
  [super viewDidLoad];
  self.view.backgroundColor = UIColor.systemBackgroundColor;

  self.status = [[UILabel alloc] initWithFrame:CGRectZero];
  self.status.numberOfLines = 0;
  self.status.textAlignment = NSTextAlignmentCenter;
  self.status.textColor = UIColor.secondaryLabelColor;
  self.status.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
  self.status.text = @"Starting the geometry engine…";
  self.status.translatesAutoresizingMaskIntoConstraints = NO;
  [self.view addSubview:self.status];

  self.bridge = [[SnapirWebBridge alloc] initWithHost:self];

  WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
  [config.userContentController addUserScript:[SnapirWebBridge shim]];
  [config.userContentController addScriptMessageHandler:self.bridge
                                                   name:[SnapirWebBridge handlerName]];

  self.web = [[WKWebView alloc] initWithFrame:CGRectZero configuration:config];
  self.web.hidden = YES;
  self.web.allowsBackForwardNavigationGestures = YES;
  // The page owns the full window, including under the notch, the same way it
  // owns the Electron window and the Android activity.
  self.web.scrollView.contentInsetAdjustmentBehavior =
      UIScrollViewContentInsetAdjustmentNever;
  self.web.translatesAutoresizingMaskIntoConstraints = NO;
  [self.view addSubview:self.web];

  [NSLayoutConstraint activateConstraints:@[
    [self.status.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor],
    [self.status.centerYAnchor constraintEqualToAnchor:self.view.centerYAnchor],
    [self.status.leadingAnchor
        constraintEqualToAnchor:self.view.layoutMarginsGuide.leadingAnchor],
    [self.status.trailingAnchor
        constraintEqualToAnchor:self.view.layoutMarginsGuide.trailingAnchor],

    [self.web.topAnchor constraintEqualToAnchor:self.view.topAnchor],
    [self.web.bottomAnchor constraintEqualToAnchor:self.view.bottomAnchor],
    [self.web.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor],
    [self.web.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor],
  ]];

  self.bridge.webView = self.web;

  [NSNotificationCenter.defaultCenter
      addObserver:self
         selector:@selector(willEnterForeground)
             name:UIApplicationWillEnterForegroundNotification
           object:nil];

  [self startBackend];
}

- (void)startBackend {
  dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
    NSString *error = nil;
    if (![SnapirNativeService startReturningError:&error]) {
      dispatch_async(dispatch_get_main_queue(), ^{
        self.status.text = [NSString
            stringWithFormat:@"Could not start the geometry engine.\n\n%@", error];
      });
      return;
    }

    const BOOL up = [SnapirNativeService waitUntilReady:15.0];
    dispatch_async(dispatch_get_main_queue(), ^{
      if (!up) {
        self.status.text =
            [NSString stringWithFormat:@"The geometry engine did not answer on %@.",
                                       SnapirNativeService.origin];
        return;
      }
      self.status.hidden = YES;
      self.web.hidden = NO;
      self.loaded = YES;
      NSURL *url = [NSURL URLWithString:
                              [SnapirNativeService.origin stringByAppendingString:@"/"]];
      [self.web loadRequest:[NSURLRequest requestWithURL:url]];
    });
  });
}

/// iOS suspends a backgrounded process and the listening socket goes with it.
/// For a tool used while standing in a room that is an acceptable trade, but
/// coming back to a dead socket and a blank page is not, so the service is
/// re-checked and restarted on the way in.
- (void)willEnterForeground {
  if (!self.loaded) return;
  if ([SnapirNativeService isListening]) return;

  self.loaded = NO;
  self.web.hidden = YES;
  self.status.hidden = NO;
  self.status.text = @"Restarting the geometry engine…";
  [self startBackend];
}

- (void)dealloc {
  [NSNotificationCenter.defaultCenter removeObserver:self];
}

@end
