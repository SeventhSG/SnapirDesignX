#import <UIKit/UIKit.h>

/// The whole iOS shell.
///
/// It does two things: start the geometry service and show a web view pointed
/// at it. Android needs a third -- unpacking the interface out of the APK --
/// which is why that file is longer than this one. Everything else the app
/// does happens in the same C++ and the same React the desktop runs.
@interface SnapirViewController : UIViewController
@end
