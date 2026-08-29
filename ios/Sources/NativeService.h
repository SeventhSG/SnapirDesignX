#import <Foundation/Foundation.h>

/// The geometry backend, running inside this process.
///
/// On the desktop this same service is a sidecar process the Electron shell
/// spawns; on Android it is a thread behind JNI; here it is a thread called
/// straight from Objective-C++. Either way it is the same C++ and the same
/// HTTP routes, which is what makes the interface identical on all three.
@interface SnapirNativeService : NSObject

/// Loopback only. Nothing about this service is meant to leave the device.
///
/// The port is not a free choice: the built page pins 8765 in its
/// Content-Security-Policy, so moving it silently breaks every API call.
@property(class, readonly) NSInteger port;
@property(class, readonly, nonnull) NSString *origin;

/// The directory the survey folders are imported into, created on first use.
@property(class, readonly, nonnull) NSString *surveysDirectory;

/// Starts the service if it is not already running. Returns immediately; the
/// server runs on its own thread. Call `waitUntilReady:` before pointing a web
/// view at it. Returns NO if the interface is missing from the bundle.
+ (BOOL)startReturningError:(NSString *_Nullable *_Nullable)error;

/// Polls the port. NO if it never came up.
+ (BOOL)waitUntilReady:(NSTimeInterval)timeout;

/// One connect attempt, for the foreground re-check.
+ (BOOL)isListening;

@end
