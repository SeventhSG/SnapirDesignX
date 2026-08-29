#import "AppDelegate.h"

#import "SnapirViewController.h"

@implementation SnapirAppDelegate

// One window, one view controller, no scene manifest. A scene-based lifecycle
// buys multi-window on iPad, and a second window onto a single local service
// with a single project store is not something this app has an answer for.
- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)options {
  self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
  self.window.rootViewController = [[SnapirViewController alloc] init];
  [self.window makeKeyAndVisible];
  return YES;
}

@end
