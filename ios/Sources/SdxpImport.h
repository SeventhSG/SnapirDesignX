#import <UIKit/UIKit.h>

/// Brings a picked .sdxp inside the sandbox and hands back a real path.
///
/// Mirrors SnapirFolderImport: the picker returns a security-scoped URL, so
/// the file is copied into a real, ordinary path the geometry core can open.
/// Unlike a survey folder there is no directory to browse into, so this is
/// the one picker with no fallback -- the system document picker is the only
/// way in.
@interface SnapirSdxpImport : NSObject

/// Presents the system file picker and copies the choice into a temporary
/// location. The completion runs on the main thread and receives the
/// imported absolute path, or nil if the operator cancelled or the copy
/// failed.
+ (void)presentFrom:(nonnull UIViewController *)host
         completion:(void (^_Nonnull)(NSString *_Nullable path))completion;

@end
