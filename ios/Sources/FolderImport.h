#import <UIKit/UIKit.h>

/// Brings a survey folder inside the sandbox and hands back a real path.
///
/// The Android build reconstructs an absolute path from the `content://` tree
/// the picker returns, so the core reads the operator's files where they lie.
/// iOS has no equivalent: there are no real paths outside the container, and
/// teaching the parser about security-scoped URLs would put a platform seam
/// through the middle of the one piece of code that is supposed to be shared.
///
/// So the folder is copied in, once, and everything downstream -- the parser,
/// the exporter, the project list -- sees an ordinary directory.
@interface SnapirFolderImport : NSObject

/// Presents the system folder picker and copies the choice into
/// `Documents/surveys/`. The completion runs on the main thread and receives
/// the imported absolute path, or nil if the operator cancelled or the copy
/// failed.
+ (void)presentFrom:(nonnull UIViewController *)host
         completion:(void (^_Nonnull)(NSString *_Nullable path))completion;

@end
